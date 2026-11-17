package engine

import (
	"net/mail"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// applyNormalize applies the normalize verbs in order, matching the
// Python / JS semantics: a verb that fails (parse error, no match)
// DROPS the field silently.
func applyNormalize(fields map[string]any, steps []map[string]any) map[string]any {
	out := make(map[string]any, len(fields))
	for k, v := range fields {
		out[k] = v
	}
	for _, step := range steps {
		verb, _ := step["verb"].(string)
		field, _ := step["field"].(string)
		cur, has := out[field]
		if !has || cur == nil {
			continue
		}
		raw := toString(cur)
		next, ok := runVerb(verb, step, raw)
		if !ok {
			delete(out, field)
		} else {
			out[field] = next
		}
	}
	return out
}

func runVerb(verb string, step map[string]any, raw string) (any, bool) {
	switch verb {
	case "strip_whitespace":
		return strings.TrimSpace(raw), true
	case "lowercase":
		return strings.ToLower(raw), true
	case "uppercase":
		return strings.ToUpper(raw), true
	case "truncate":
		n, _ := asInt(step["max_len"])
		if n <= 0 {
			return raw, true
		}
		// JS and Python both slice by code-unit / char count; we slice
		// by rune to approximate what js-yaml does via UTF-16 units.
		// For the typical ASCII + BMP case these all agree.
		runes := []rune(raw)
		if len(runes) > n {
			return string(runes[:n]), true
		}
		return raw, true
	case "int_from_string":
		re := regexp.MustCompile(`-?\d+`)
		m := re.FindString(raw)
		if m == "" {
			return nil, false
		}
		n, err := strconv.ParseInt(m, 10, 64)
		if err != nil {
			return nil, false
		}
		return n, true
	case "replace_re2":
		pattern, _ := step["pattern"].(string)
		if pattern == "" {
			return raw, true
		}
		re, err := regexp.Compile(pattern)
		if err != nil {
			return nil, false
		}
		repl, _ := step["replacement"].(string)
		return re.ReplaceAllString(raw, repl), true
	case "date_parse":
		format, _ := step["format"].(string)
		if format == "" {
			format = "iso8601"
		}
		return parseDate(raw, format)
	}
	return nil, false
}

func parseDate(raw, format string) (any, bool) {
	if format == "epoch_seconds" {
		n, err := strconv.ParseInt(raw, 10, 64)
		if err != nil {
			return nil, false
		}
		return time.Unix(n, 0).UTC().Format("2006-01-02T15:04:05Z"), true
	}
	// iso8601 / rfc2822: try both, emit canonical second-precision UTC
	// (parity with Python's microsecond-strip + JS's .000Z strip).
	layouts := []string{
		time.RFC3339,
		"2006-01-02T15:04:05Z",
		"2006-01-02T15:04:05",
		"2006-01-02 15:04:05",
		"2006-01-02",
	}
	for _, layout := range layouts {
		if t, err := time.Parse(layout, raw); err == nil {
			return t.UTC().Format("2006-01-02T15:04:05Z"), true
		}
	}
	if t, err := mail.ParseDate(raw); err == nil {
		return t.UTC().Format("2006-01-02T15:04:05Z"), true
	}
	return nil, false
}
