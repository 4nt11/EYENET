package engine

import (
	"fmt"
	"sort"
)

// Hit is one (rule, file) emission summary from StreamRunRules, fired
// AFTER every record for that (rule, file) pair has been pushed through
// the per-record onRecord callback. Carries metadata only (counts +
// panic marker); the records themselves stream out via onRecord so no
// slice accumulation happens at the engine level.
//
// v1.3.11: Records was a []map[string]any; held 1.93 GiB on a 131 MB
// ULP drop because every (rule, file) pair materialised ~1.92M records
// before the caller saw any of them. Dropped for streaming semantics.
//
// PanicMsg is non-empty when BulkParse panicked on this (rule, file)
// pair; in that case TotalSeen is 0 and the caller surfaces the error
// without rolling back the whole stream.
type Hit struct {
	Rule      Rule
	FilePath  string
	Truncated bool
	TotalSeen int
	PanicMsg  string
}

// PathLoader streams a file's content to the engine in one or more
// chunks. The loader opens the file, reads a window (default 16 MiB)
// at a time with a trailing overlap (default 64 KiB) prepended to the
// next window, and invokes yield once per chunk. isLast is true on the
// final chunk so the engine can drop any cross-chunk state.
//
// Small files (smaller than the window size) are delivered as a single
// chunk with isLast=true; behaviour is identical to the pre-v1.3.12
// single-string loader. Only very large files (ULP drops, raw memory
// dumps) materialise multiple chunks.
//
// v1.3.12: was `func(rel string) (string, error)`. Reading whole files
// pinned 1.65 GiB of heap on a single prod ULP (daemon.listArchive.func3
// pprof trace). The streaming API lets the daemon's loader keep peak
// RSS flat regardless of input size; the CH sink's ReplacingMergeTree
// key `(archive_sha256, rule_id, file_path, cityHash64(fields))` dedupes
// any over-emission from the overlap region, so the engine does not
// need to track byte offsets.
//
// Returning a non-nil error from the loader (or from yield) aborts the
// per-path stream. The archive stream continues with the next path.
type PathLoader func(relPath string, yield func(chunk string, isLast bool) error) error

// StreamRunRules is the memory-bounded counterpart to RunRules. L1
// container pass runs on paths only (no I/O for container rules). L3
// content pass walks each path, computes the set of content rules whose
// glob matches that path, and ONLY THEN calls the loader to pull the
// file content. BulkParse runs per matching rule; emit is invoked once
// per (rule, file) hit. The file string drops out of scope between
// paths, so Go's GC can reclaim it before the next file is loaded.
//
// Peak heap under this function: one file's text at a time, regardless
// of archive size. Files no content rule globs match are never read;
// binary cookie DBs and other non-rule assets cost zero I/O + zero RAM.
//
// v1.3.12: bulkLimit parameter removed. The pre-streaming engine capped
// records per (rule, file) to protect the daemon's heap. With the file
// loader now streaming chunks AND the CH sink streaming inserts, the
// only valid backpressure signal is CH refusing the next AsyncInsert;
// a Go-side counter dropping rows on the floor to spare CH's feelings
// is exactly what v1.3.11.1 did wrong (6.6 M records lost on the first
// prod archive).
//
// Returns the container-rule family (nil when no container rule matched,
// mirrors the RunRules behaviour) and a map of rule_id -> total record
// count so the daemon can bill rules_fired in run_done.
// onRecord fires once per record, in the same goroutine as StreamRunRules;
// return a non-nil error to abort the stream. onHit fires once per
// (rule, file) summary after all records for that pair have been pushed.
func StreamRunRules(
	rules []Rule,
	paths []string,
	loader PathLoader,
	verdict func(family any),
	onRecord func(rule Rule, filePath string, record map[string]any) error,
	onHit func(Hit) error,
) (family any, rulesFired map[string]int, err error) {
	// L1: container winner = highest priority matched container rule.
	// Uses path strings only; zero I/O.
	ci := ContainerInput{Paths: paths}
	var winner *EvalResult
	for _, r := range rules {
		if r.Layer != "container" {
			continue
		}
		ev := evalContainer(r, ci)
		if ev.Matched && (winner == nil || r.Priority > winner.Priority) {
			w := ev
			winner = &w
		}
	}
	if winner != nil {
		family = winner.Family
	}
	// Fire the verdict callback once the family is known. The caller
	// uses this to emit the archive-wide metadata line before any
	// records start flowing, so downstream (Python pipeline, CH sink)
	// can tag the record batch with the right family upfront.
	if verdict != nil {
		verdict(family)
	}
	familyStr, _ := family.(string)

	// L3 preparation: sort content rules by ascending priority to match
	// RunRules' key-collision tiebreaker, then filter out rules whose
	// RequiresContainerFamily gate rejects this archive's family. Done
	// once BEFORE the per-path loop so we pay sort+filter cost once,
	// not per file.
	contentRules := filterContent(rules)
	sort.SliceStable(contentRules, func(i, j int) bool {
		return contentRules[i].Priority < contentRules[j].Priority
	})
	applicable := contentRules[:0]
	for _, r := range contentRules {
		if r.RequiresContainerFamily != "" && r.RequiresContainerFamily != familyStr {
			continue
		}
		applicable = append(applicable, r)
	}

	rulesFired = map[string]int{}
	// Per-path streaming loop. The file string lives for the duration
	// of its iteration and drops out of scope before the next path is
	// handled; Go's GC collects the text between files.
	toRun := make([]Rule, 0, 8)
	for _, path := range paths {
		// First decide which rules want this path. Globs are cheap
		// string matches; no file read yet.
		toRun = toRun[:0]
		for _, r := range applicable {
			glob := r.PathGlob
			if glob == "" {
				glob = "**/*"
			}
			if MatchGlob(glob, path) {
				toRun = append(toRun, r)
			}
		}
		if len(toRun) == 0 {
			// No content rule cares about this path. Skip load entirely.
			continue
		}
		// Per-rule accumulators for the HIT summary. Chunked loaders may
		// invoke the yield closure many times; we tally emitted and
		// TotalSeen across all chunks and fire onHit once per (rule,
		// file) after the loader returns.
		emittedByRule := make(map[string]int, len(toRun))
		totalByRule := make(map[string]int, len(toRun))
		truncByRule := make(map[string]bool, len(toRun))
		panicByRule := make(map[string]string, len(toRun))
		var emitErr error
		loaderErr := loader(path, func(chunk string, isLast bool) error {
			file := ContentInput{Path: path, Text: chunk}
			for _, r := range toRun {
				if panicByRule[r.ID] != "" {
					// A prior chunk panicked this rule; skip it on the
					// remaining chunks so one bad chunk does not keep
					// re-tripping the same recover.
					continue
				}
				var emitted int
				yield := func(rec map[string]any) bool {
					if eerr := onRecord(r, path, rec); eerr != nil {
						emitErr = eerr
						return false
					}
					emitted++
					return true
				}
				meta, panicMsg := safeBulkParseStream(r, file, yield)
				emittedByRule[r.ID] += emitted
				totalByRule[r.ID] += meta.Total
				if meta.Truncated {
					truncByRule[r.ID] = true
				}
				if panicMsg != "" {
					panicByRule[r.ID] = panicMsg
				}
				if emitErr != nil {
					return emitErr
				}
			}
			_ = isLast
			return nil
		})
		if emitErr != nil {
			return family, rulesFired, emitErr
		}
		if loaderErr != nil {
			// Unreadable file is a data concern, not a fatal engine
			// concern. Skip and continue with the next path.
			continue
		}
		for _, r := range toRun {
			if panicMsg := panicByRule[r.ID]; panicMsg != "" {
				if eerr := onHit(Hit{Rule: r, FilePath: path, PanicMsg: panicMsg}); eerr != nil {
					return family, rulesFired, eerr
				}
				continue
			}
			emitted := emittedByRule[r.ID]
			if emitted == 0 && !truncByRule[r.ID] {
				continue
			}
			if eerr := onHit(Hit{
				Rule:      r,
				FilePath:  path,
				Truncated: truncByRule[r.ID],
				TotalSeen: totalByRule[r.ID],
			}); eerr != nil {
				return family, rulesFired, eerr
			}
			rulesFired[r.ID] += emitted
		}
		// chunk strings from the loader go out of scope as the loader's
		// yield returns; the loader is expected to reuse its read buffer
		// so peak RSS stays flat.
	}
	return family, rulesFired, nil
}

// safeBulkParseStream wraps BulkParse in a per-(rule,file) recover so a
// malformed file taking down one rule's parser does not abort the entire
// archive stream. Mirrors the daemon's historical safeBulkParse but lives
// in the engine package so StreamRunRules can own its own resilience.
func safeBulkParseStream(
	r Rule, file ContentInput,
	yield func(map[string]any) bool,
) (meta BulkMeta, panicMsg string) {
	defer func() {
		if p := recover(); p != nil {
			panicMsg = fmt.Sprintf("%v", p)
		}
	}()
	// v1.3.12: limit=0 (unbounded) always. BulkParse treats <=0 as
	// "no cap" and the chunked loader bounds working memory per chunk,
	// so a 1 GiB input cannot blow the heap the way the single-string
	// loader used to.
	return BulkParse(r, file, 0, yield), ""
}
