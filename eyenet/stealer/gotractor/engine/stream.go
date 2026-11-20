package engine

import (
	"fmt"
	"sort"
)

// Hit is one (rule, file, BulkParse result) emission from StreamRules.
// Records may be empty when the rule's regex didn't actually match
// anything in the file; emit callers use that to decide whether to
// forward the hit downstream. PanicMsg is non-empty when BulkParse
// panicked on this (rule, file) pair; in that case Records is nil
// and the caller should surface the error without rolling back the
// whole stream.
type Hit struct {
	Rule      Rule
	FilePath  string
	Records   []map[string]any
	Truncated bool
	TotalSeen int
	PanicMsg  string
}

// PathLoader reads a file's content on demand. Paths are relative to
// the folder root; the loader implementation is responsible for the
// actual I/O. Returning a non-nil error causes the engine to skip the
// file; the stream continues with the next path.
type PathLoader func(relPath string) (string, error)

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
// bulkLimit bounds records per (rule, file) pair; same semantics as the
// non-streaming BulkParse.
//
// Returns the container-rule family (nil when no container rule matched,
// mirrors the RunRules behaviour) and a map of rule_id -> total record
// count so the daemon can bill rules_fired in run_done.
func StreamRunRules(
	rules []Rule,
	paths []string,
	loader PathLoader,
	bulkLimit int,
	verdict func(family any),
	emit func(Hit) error,
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
		text, rerr := loader(path)
		if rerr != nil {
			// Unreadable file is a data concern, not a fatal engine
			// concern. Skip and continue.
			continue
		}
		file := ContentInput{Path: path, Text: text}
		for _, r := range toRun {
			bulk, panicMsg := safeBulkParseStream(r, file, bulkLimit)
			if panicMsg != "" {
				// A single rule panicking on a single file is a data
				// concern, not a stream-level failure. Surface it so
				// the caller can log/emit the error, then continue.
				if eerr := emit(Hit{
					Rule:     r,
					FilePath: path,
					PanicMsg: panicMsg,
				}); eerr != nil {
					return family, rulesFired, eerr
				}
				continue
			}
			if len(bulk.Records) == 0 && !bulk.Truncated {
				continue
			}
			if eerr := emit(Hit{
				Rule:      r,
				FilePath:  path,
				Records:   bulk.Records,
				Truncated: bulk.Truncated,
				TotalSeen: bulk.Total,
			}); eerr != nil {
				return family, rulesFired, eerr
			}
			rulesFired[r.ID] += len(bulk.Records)
		}
		// text falls out of scope after this iteration; GC reclaims
		// the file content before the next path is loaded.
	}
	return family, rulesFired, nil
}

// safeBulkParseStream wraps BulkParse in a per-(rule,file) recover so a
// malformed file taking down one rule's parser does not abort the entire
// archive stream. Mirrors the daemon's historical safeBulkParse but lives
// in the engine package so StreamRunRules can own its own resilience.
func safeBulkParseStream(r Rule, file ContentInput, limit int) (result BulkResult, panicMsg string) {
	defer func() {
		if p := recover(); p != nil {
			panicMsg = fmt.Sprintf("%v", p)
		}
	}()
	return BulkParse(r, file, limit), ""
}
