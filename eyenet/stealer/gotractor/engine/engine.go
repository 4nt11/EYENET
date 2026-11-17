package engine

import "sort"

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
// pair. Used by the pipeline to extract credentials from a single file
// in one shot; also by the Workbench to show all parsed rows. Bounded
// at limit; returns Truncated=true when total > limit.
func BulkParse(rule Rule, file ContentInput, limit int) BulkResult {
	if limit <= 0 {
		limit = 1000
	}
	records := make([]map[string]any, 0, 64)
	total := 0

	push := func(raw map[string]any) {
		total++
		if len(records) >= limit {
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
		records = append(records, escapeNulls(normed))
	}

	switch typeOf(rule.Match) {
	case "delimiter":
		for row := range IterDelimiter(rule.Match, rule.Extract, file.Text) {
			push(row)
		}
	case "regex":
		rest := file.Text
		safety := 10000
		for rest != "" && safety > 0 {
			safety--
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

	return BulkResult{Records: records, Total: total, Truncated: total > len(records)}
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
