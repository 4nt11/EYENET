package engine

import (
	"math"
	"sort"
)

// RunRules evaluates the full ruleset against a victim folder.
// Container rules (L1) determine the family winner; content rules (L3)
// extract and merge fields. Mirrors the Python and JS engines exactly.
func RunRules(rules []Rule, folder VictimFolder) RunResult {
	evaluations := make([]EvalResult, 0, len(rules))
	ci := ContainerInput{Paths: make([]string, 0, len(folder.Files))}
	for _, f := range folder.Files {
		ci.Paths = append(ci.Paths, f.Path)
	}

	// L1: container winner = highest priority matched container rule.
	var winner *EvalResult
	for _, r := range rules {
		if r.Layer != "container" {
			continue
		}
		ev := evalContainer(r, ci)
		evaluations = append(evaluations, ev)
		if ev.Matched && (winner == nil || r.Priority > winner.Priority) {
			w := ev
			winner = &w
		}
	}
	var family any // nil when no container matched; mirrors Python None / JS null
	if winner != nil {
		family = winner.Family
	}

	// L3: content rules by ascending priority so later wins on key collision.
	contentRules := filterContent(rules)
	sort.SliceStable(contentRules, func(i, j int) bool {
		return contentRules[i].Priority < contentRules[j].Priority
	})

	merged := map[string]any{}
	familyStr, _ := family.(string)
	for _, r := range contentRules {
		if r.RequiresContainerFamily != "" && r.RequiresContainerFamily != familyStr {
			continue
		}
		glob := r.PathGlob
		if glob == "" {
			glob = "**/*"
		}
		for _, file := range folder.Files {
			if !MatchGlob(glob, file.Path) {
				continue
			}
			ev := evalContent(r, file)
			ev.FilePath = file.Path
			evaluations = append(evaluations, ev)
			if ev.Matched {
				for k, v := range ev.Fields {
					merged[k] = v
				}
			}
		}
	}

	return RunResult{Family: family, Fields: merged, Evaluations: evaluations}
}

// BulkParse walks every record a matcher would emit for a (rule, file)
// pair and yields each one SYNCHRONOUSLY to the caller via the yield
// callback. Returns BulkMeta{Total, Truncated} where Total is every
// record the matcher saw (including rejects and truncation overflow)
// and Truncated is true when yield did not receive every record.
//
// yield returns false => stop iterating, early-exit cleanly. Mirrors
// the iter.Seq convention used by IterDelimiter / IterJSON / IterXML.
// NO GOROUTINES, NO CHANNELS. A channel-based generator previously
// caused a 150k-goroutine leak + 22 GiB RSS before the iter.Seq
// rewrite; the lesson stuck.
//
// limit caps the number of records actually yielded. Rejected records
// count toward Total but not toward yielded count (semantic preserved
// from the previous accumulator-based BulkParse). A limit <= 0 means
// "no caller cap"; math.MaxInt is the only ceiling.
func BulkParse(
	rule Rule, file ContentInput, limit int,
	yield func(map[string]any) bool,
) BulkMeta {
	if limit <= 0 {
		limit = math.MaxInt
	}
	var total, yielded int
	stop := false

	push := func(raw map[string]any) {
		total++
		if stop || yielded >= limit {
			return
		}
		mapped := applyMap(raw, rule.Map)
		if hit := ruleRejects(rule.RejectPatterns, mapped); hit != "" {
			return
		}
		normed := mapped
		if len(rule.Normalize) > 0 {
			normed = applyNormalize(mapped, rule.Normalize)
		}
		yielded++
		if !yield(escapeNulls(normed)) {
			stop = true
		}
	}

	switch typeOf(rule.Match) {
	case "delimiter":
		for row := range IterDelimiter(rule.Match, rule.Extract, file.Text) {
			push(row)
			if stop {
				break
			}
		}
	case "vdf":
		for row := range IterVDF(rule.Match, rule.Extract, file.Text) {
			push(row)
			if stop {
				break
			}
		}
	case "xml":
		for row := range IterXML(rule.Match, rule.Extract, file.Text) {
			push(row)
			if stop {
				break
			}
		}
	case "json":
		for row := range IterJSON(rule.Match, rule.Extract, file.Text) {
			push(row)
			if stop {
				break
			}
		}
	case "regex":
		rest := file.Text
		// v1.3.11: was `safety := 10000` since the initial Go port
		// (commit 77580e0). That silently capped BulkParse to 10k matches
		// per file per rule regardless of the configured limit; invisible
		// on stealer-archive files but on raw ULP drops (~2M lines per
		// 131 MB file) dropped 99.4% of the data. push() caps via limit,
		// the no-progress fallback either advances past \n or clears rest
		// to "" (terminating the loop). No runaway path.
		for rest != "" && !stop {
			hit := MatchRegex(rule.Match, rule.Extract, ContentInput{Path: file.Path, Text: rest})
			if hit == nil || len(hit) == 0 {
				break
			}
			push(hit)
			// Advance past the first captured value to make progress.
			advanced := false
			for _, v := range hit {
				if s, ok := v.(string); ok && s != "" {
					if idx := indexOf(rest, s); idx >= 0 {
						rest = rest[idx+len(s):]
						advanced = true
						break
					}
				}
			}
			if !advanced {
				if nl := indexOf(rest, "\n"); nl >= 0 {
					rest = rest[nl+1:]
				} else {
					rest = ""
				}
			}
		}
	default:
		var fields map[string]any
		switch typeOf(rule.Match) {
		case "template":
			fields = MatchTemplate(rule.Match, rule.Extract, file)
		case "json":
			fields = MatchJSON(rule.Match, rule.Extract, file)
		case "yaml":
			fields = MatchYAML(rule.Match, rule.Extract, file)
		case "keyvalue":
			fields = MatchKeyvalue(rule.Match, rule.Extract, file)
		case "keyvalue_ini":
			fields = MatchKeyvalueIni(rule.Match, rule.Extract, file)
		}
		if fields != nil {
			push(fields)
		}
	}

	return BulkMeta{Total: total, Truncated: total > yielded}
}

// BulkParseCollect is the pre-v1.3.11 BulkParse shape: accumulate every
// record into a slice, return BulkResult. KEPT ONLY FOR TESTS and the
// Workbench which materialises the full result for display. Production
// callers (daemon, CLI emit, stream) use the streaming BulkParse above
// so they never hold more than one record in flight.
//
// On a 131 MB ULP drop this holds ~1.93 GiB of RSS. Do not call from the
// hot path.
func BulkParseCollect(rule Rule, file ContentInput, limit int) BulkResult {
	records := make([]map[string]any, 0, 64)
	meta := BulkParse(rule, file, limit, func(rec map[string]any) bool {
		records = append(records, rec)
		return true
	})
	return BulkResult{Records: records, Total: meta.Total, Truncated: meta.Truncated}
}

func filterContent(rules []Rule) []Rule {
	out := make([]Rule, 0, len(rules))
	for _, r := range rules {
		if r.Layer == "content" {
			out = append(out, r)
		}
	}
	return out
}

func typeOf(m map[string]any) string {
	s, _ := m["type"].(string)
	return s
}

func indexOf(s, sub string) int {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}

func evalContainer(r Rule, inp ContainerInput) EvalResult {
	base := EvalResult{RuleID: r.ID, Layer: r.Layer, Family: r.Family, Priority: r.Priority}
	if typeOf(r.Match) != "folder" {
		base.Reason = "container rule requires folder match"
		return base
	}
	fields := MatchFolder(r.Match, inp)
	if fields == nil {
		base.Reason = "no match"
		return base
	}
	mapped := applyMap(fields, r.Map)
	if hit := ruleRejects(r.RejectPatterns, mapped); hit != "" {
		base.Reason = "reject: " + hit
		return base
	}
	normed := mapped
	if len(r.Normalize) > 0 {
		normed = applyNormalize(mapped, r.Normalize)
	}
	base.Matched = true
	base.Fields = escapeNulls(normed)
	return base
}

func evalContent(r Rule, file ContentInput) EvalResult {
	base := EvalResult{RuleID: r.ID, Layer: r.Layer, Family: r.Family, Priority: r.Priority}
	var fields map[string]any
	switch typeOf(r.Match) {
	case "regex":
		fields = MatchRegex(r.Match, r.Extract, file)
	case "template":
		fields = MatchTemplate(r.Match, r.Extract, file)
	case "delimiter":
		fields = MatchDelimiter(r.Match, r.Extract, file)
	case "json":
		fields = MatchJSON(r.Match, r.Extract, file)
	case "yaml":
		fields = MatchYAML(r.Match, r.Extract, file)
	case "vdf":
		fields = MatchVDF(r.Match, r.Extract, file)
	case "xml":
		fields = MatchXML(r.Match, r.Extract, file)
	case "keyvalue":
		fields = MatchKeyvalue(r.Match, r.Extract, file)
	case "keyvalue_ini":
		fields = MatchKeyvalueIni(r.Match, r.Extract, file)
	case "folder":
		base.Reason = "folder match only valid in container layer"
		return base
	default:
		base.Reason = "unknown match type: " + typeOf(r.Match)
		return base
	}
	if fields == nil {
		base.Reason = "no match"
		return base
	}
	mapped := applyMap(fields, r.Map)
	if hit := ruleRejects(r.RejectPatterns, mapped); hit != "" {
		base.Reason = "reject: " + hit
		return base
	}
	normed := mapped
	if len(r.Normalize) > 0 {
		normed = applyNormalize(mapped, r.Normalize)
	}
	base.Matched = true
	base.Fields = escapeNulls(normed)
	return base
}

func applyMap(fields map[string]any, m map[string]any) map[string]any {
	if m == nil {
		return fields
	}
	drop := map[string]bool{}
	for _, d := range asStringList(m["_drop"]) {
		drop[d] = true
	}
	rename, _ := m["rename"].(map[string]any)
	out := make(map[string]any, len(fields))
	for k, v := range fields {
		if drop[k] {
			continue
		}
		if r, has := rename[k].(string); has {
			out[r] = v
		} else {
			out[k] = v
		}
	}
	return out
}
