package engine

import (
	"regexp"
	"strconv"
	"strings"

	"gopkg.in/yaml.v3"
)

// MatchFolder is byte-parity with Python / JS match_folder.
//
// Semantics:
//   - every 'requires' path must be present (literal, or '/'-suffix prefix)
//   - no 'forbids' path may be present
//   - 'optional' paths each boost the score by 1 when present
//   - result matches when (#requires + #optional_hit) >= min_score
//   - min_score defaults to len(requires)
func MatchFolder(m map[string]any, inp ContainerInput) map[string]any {
	set := make(map[string]struct{}, len(inp.Paths))
	for _, p := range inp.Paths {
		set[p] = struct{}{}
	}
	requires := asStringList(m["requires"])
	forbids := asStringList(m["forbids"])
	optional := asStringList(m["optional"])
	minScore, _ := asInt(m["min_score"])

	for _, r := range requires {
		if !hasPath(set, inp.Paths, r) {
			return nil
		}
	}
	for _, f := range forbids {
		if hasPath(set, inp.Paths, f) {
			return nil
		}
	}
	opt := 0
	for _, o := range optional {
		if hasPath(set, inp.Paths, o) {
			opt++
		}
	}
	if m["min_score"] == nil {
		minScore = len(requires)
	}
	if len(requires)+opt >= minScore {
		return map[string]any{}
	}
	return nil
}

func hasPath(set map[string]struct{}, paths []string, p string) bool {
	if strings.HasSuffix(p, "/") {
		for _, x := range paths {
			if strings.HasPrefix(x, p) {
				return true
			}
		}
		return false
	}
	_, ok := set[p]
	return ok
}

// MatchRegex uses Go's RE2-syntax stdlib regexp. Named captures survive
// to the returned fields dict; 'fields' in the extract spec filters
// which captures to keep (default: all).
func MatchRegex(m map[string]any, ex map[string]any, inp ContentInput) map[string]any {
	pattern, _ := m["pattern"].(string)
	re, err := compileRE(pattern, boolOf(m["multiline"]), boolOf(m["dotall"]))
	if err != nil {
		return nil
	}
	hit := re.FindStringSubmatch(inp.Text)
	if hit == nil {
		return nil
	}
	names := re.SubexpNames()
	groups := map[string]string{}
	for i, name := range names {
		if i == 0 || name == "" {
			continue
		}
		groups[name] = hit[i]
	}
	if len(groups) == 0 {
		return map[string]any{}
	}
	want := asStringList(ex["fields"])
	if len(want) == 0 {
		for k := range groups {
			want = append(want, k)
		}
	}
	out := map[string]any{}
	for _, k := range want {
		if v, ok := groups[k]; ok {
			out[k] = v
		}
	}
	return out
}

// MatchTemplate compiles fixed literals interleaved with '{field}' holes
// into a RE2 pattern with `(?P<field>.*?)` groups, then delegates to
// MatchRegex. Same algorithm as JS and Python ports.
func MatchTemplate(m map[string]any, ex map[string]any, inp ContentInput) map[string]any {
	tpl, _ := m["template"].(string)
	var out strings.Builder
	var holes []string
	i := 0
	for i < len(tpl) {
		if tpl[i] == '{' {
			j := strings.Index(tpl[i:], "}")
			if j < 0 {
				break
			}
			name := tpl[i+1 : i+j]
			holes = append(holes, name)
			out.WriteString("(?P<")
			out.WriteString(name)
			out.WriteString(">.*?)")
			i += j + 1
		} else {
			j := strings.Index(tpl[i:], "{")
			end := len(tpl)
			if j >= 0 {
				end = i + j
			}
			out.WriteString(regexp.QuoteMeta(tpl[i:end]))
			i = end
		}
	}
	pattern := "^" + out.String() + "$"
	subEx := ex
	if subEx == nil {
		subEx = map[string]any{"fields": stringsToAny(holes)}
	}
	return MatchRegex(
		map[string]any{"type": "regex", "pattern": pattern, "multiline": boolOf(m["multiline"]), "dotall": true},
		subEx, inp,
	)
}

// MatchDelimiter returns the first matching row; IterDelimiter walks
// every matching row (used by bulkParse).
func MatchDelimiter(m map[string]any, ex map[string]any, inp ContentInput) map[string]any {
	for row := range IterDelimiter(m, ex, inp.Text) {
		return row
	}
	return nil
}

// IterDelimiter yields every matching row as a map[string]any. Receiver
// uses a channel so the engine shares the same code path as Python's
// generator / JS's generator.
func IterDelimiter(m map[string]any, ex map[string]any, text string) <-chan map[string]any {
	ch := make(chan map[string]any)
	go func() {
		defer close(ch)
		sep, _ := m["separator"].(string)
		skipBlank := true
		if v, ok := m["skip_blank"].(bool); ok {
			skipBlank = v
		}
		skipComment, _ := m["skip_comment_prefix"].(string)
		minCols, _ := asInt(m["min_columns"])
		cols := asIntKeyMap(ex["columns"])

		for _, line := range splitLines(text) {
			if skipBlank && strings.TrimSpace(line) == "" {
				continue
			}
			if skipComment != "" && strings.HasPrefix(line, skipComment) {
				continue
			}
			parts := strings.Split(line, sep)
			if minCols > 0 && len(parts) < minCols {
				continue
			}
			row := map[string]any{}
			for idx, field := range cols {
				if idx < len(parts) {
					row[field] = parts[idx]
				}
			}
			ch <- row
		}
	}()
	return ch
}

// MatchJSON parses the input as JSON through the ordered decoder so
// nested-object stringification preserves source key order (parity
// with Python json.dumps(dict) + JS JSON.stringify(obj); Go's default
// json.Marshal of map[string]any sorts keys alphabetically).
func MatchJSON(m map[string]any, ex map[string]any, inp ContentInput) map[string]any {
	doc, err := parseOrderedJSON([]byte(inp.Text))
	if err != nil {
		return nil
	}
	om, ok := doc.(*orderedMap)
	if !ok {
		return nil
	}
	for _, k := range asStringList(m["requires_keys"]) {
		if _, has := om.Values[k]; !has {
			return nil
		}
	}
	paths, _ := ex["paths"].(map[string]any)
	return extractPaths(doc, paths)
}

// MatchYAML parses the input as YAML 1.2 (yaml.v3 default), with the
// same parity contract as the Python / JS sides: null, inf, nan dropped;
// whole-number floats coerced to int; bools stringified.
//
// Note on Norway problem: yaml.v3 follows YAML 1.2 Core schema by
// default, so `Country: NO` stays the string "NO" (parity with js-yaml
// after the fix). No special loader needed.
func MatchYAML(m map[string]any, ex map[string]any, inp ContentInput) map[string]any {
	var doc any
	if err := yaml.Unmarshal([]byte(inp.Text), &doc); err != nil {
		return nil
	}
	asMap, ok := doc.(map[string]any)
	if !ok {
		return nil
	}
	for _, k := range asStringList(m["requires_keys"]) {
		if _, has := asMap[k]; !has {
			return nil
		}
	}
	paths, _ := ex["paths"].(map[string]any)
	return extractPaths(doc, paths)
}

// MatchKeyvalue parses each line as "<key><sep><value>", case-insensitive
// key lookups. Parity with JS / Python.
func MatchKeyvalue(m map[string]any, ex map[string]any, inp ContentInput) map[string]any {
	sep, _ := m["separator"].(string)
	strip := true
	if v, ok := m["strip_whitespace"].(bool); ok {
		strip = v
	}
	kv := map[string]string{}
	for _, line := range splitLines(inp.Text) {
		i := strings.Index(line, sep)
		if i <= 0 {
			continue
		}
		k := line[:i]
		v := line[i+len(sep):]
		if strip {
			k = strings.TrimSpace(k)
			v = strings.TrimSpace(v)
		}
		if k != "" {
			kv[strings.ToLower(k)] = v
		}
	}
	for _, k := range asStringList(m["requires_keys"]) {
		if _, has := kv[strings.ToLower(k)]; !has {
			return nil
		}
	}
	out := map[string]any{}
	keys, _ := ex["keys"].(map[string]any)
	for src, dst := range keys {
		dstStr, _ := dst.(string)
		if hit, has := kv[strings.ToLower(src)]; has {
			out[dstStr] = hit
		}
	}
	return out
}

// MatchKeyvalueIni parses `[Section]` + `key=value` lines. Sections
// before any explicit `[Section]` header go into the "" (empty)
// section, matching Python / JS semantics. Extract uses dotted
// `Section.Key` lookup.
func MatchKeyvalueIni(m map[string]any, ex map[string]any, inp ContentInput) map[string]any {
	sections := map[string]map[string]string{}
	cur := ""
	for _, raw := range splitLines(inp.Text) {
		line := strings.TrimSpace(raw)
		if line == "" || strings.HasPrefix(line, ";") || strings.HasPrefix(line, "#") {
			continue
		}
		if strings.HasPrefix(line, "[") && strings.HasSuffix(line, "]") {
			cur = line[1 : len(line)-1]
			if _, ok := sections[cur]; !ok {
				sections[cur] = map[string]string{}
			}
			continue
		}
		i := strings.Index(line, "=")
		if i <= 0 {
			continue
		}
		k := strings.TrimSpace(line[:i])
		v := strings.TrimSpace(line[i+1:])
		if _, ok := sections[cur]; !ok {
			sections[cur] = map[string]string{}
		}
		sections[cur][k] = v
	}
	for _, s := range asStringList(m["requires_sections"]) {
		if _, has := sections[s]; !has {
			return nil
		}
	}
	out := map[string]any{}
	keys, _ := ex["keys"].(map[string]any)
	for dotted, dst := range keys {
		dot := strings.Index(dotted, ".")
		if dot <= 0 {
			continue
		}
		sec := dotted[:dot]
		key := dotted[dot+1:]
		if v, has := sections[sec][key]; has {
			dstStr, _ := dst.(string)
			out[dstStr] = v
		}
	}
	return out
}

// Helpers below handle the generic YAML-decoded shapes (map[string]any
// with values that may be string, int, float64, []any).

func asStringList(v any) []string {
	switch x := v.(type) {
	case []string:
		return x
	case []any:
		out := make([]string, 0, len(x))
		for _, e := range x {
			if s, ok := e.(string); ok {
				out = append(out, s)
			}
		}
		return out
	}
	return nil
}

func asInt(v any) (int, bool) {
	switch x := v.(type) {
	case int:
		return x, true
	case int64:
		return int(x), true
	case float64:
		return int(x), true
	case string:
		n, err := strconv.Atoi(x)
		return n, err == nil
	}
	return 0, false
}

// asIntKeyMap turns a {"0": "host", "1": "user"} or {0: "host", 1: "user"}
// shape into a map[int]string so the delimiter matcher can key by
// column index.
func asIntKeyMap(v any) map[int]string {
	out := map[int]string{}
	asMap, ok := v.(map[string]any)
	if !ok {
		return out
	}
	for k, val := range asMap {
		idx, err := strconv.Atoi(k)
		if err != nil {
			continue
		}
		s, _ := val.(string)
		out[idx] = s
	}
	return out
}

func boolOf(v any) bool {
	b, _ := v.(bool)
	return b
}

func stringsToAny(xs []string) []any {
	out := make([]any, len(xs))
	for i, s := range xs {
		out[i] = s
	}
	return out
}

func splitLines(s string) []string {
	// Mirror JS text.split(/\r?\n/) and Python text.splitlines() by
	// stripping any trailing \r on each \n-split line.
	parts := strings.Split(s, "\n")
	for i, p := range parts {
		parts[i] = strings.TrimSuffix(p, "\r")
	}
	return parts
}

func compileRE(pattern string, multiline, dotall bool) (*regexp.Regexp, error) {
	var flags string
	if multiline {
		flags += "m"
	}
	if dotall {
		flags += "s"
	}
	if flags != "" {
		pattern = "(?" + flags + ")" + pattern
	}
	return regexp.Compile(pattern)
}

