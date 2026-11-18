package engine

import (
	"net/mail"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"golang.org/x/net/publicsuffix"
)

// applyNormalize applies the normalize verbs in order, matching the
// Python / JS semantics: a verb that fails (parse error, no match)
// DROPS the field silently. The derive_url_parts verb is a special
// case: it writes SIBLING fields instead of replacing the source
// field, so URL-structured emits (host, scheme, tld) can be produced
// from a single raw URL capture.
func applyNormalize(fields map[string]any, steps []map[string]any) map[string]any {
	out := make(map[string]any, len(fields))
	for k, v := range fields {
		out[k] = v
	}
	for _, step := range steps {
		verb, _ := step["verb"].(string)
		if verb == "derive_url_parts" {
			applyDeriveURL(out, step)
			continue
		}
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

// applyDeriveURL derives the structured parts (registrable host,
// scheme, TLD) from a raw URL captured in `step.field` and writes them
// into the sibling field names declared by `host_to`, `scheme_to`, and
// `tld_to`. Replaces the Python-side URL post-processing that
// ulpextract used to do; keeping it as a built-in means every rule
// that captures a URL gets the same canonical shape without a per-
// rule derivation helper.
//
// Behaviour:
//   - A URL without a scheme is tolerated for parsing (we prepend a
//     stub) but scheme_to is left unwritten so the operator sees
//     "no scheme" rather than a fake http://.
//   - registrable domain comes from EffectiveTLDPlusOne on the public
//     suffix list; falls back to the raw hostname when the PSL does
//     not match (unusual, but keeps pathological inputs flowing).
//   - TLD is the public-suffix segment (e.g. "co.uk", "com", "club").
//   - Empty source field or parse failure writes nothing silently.
func applyDeriveURL(fields map[string]any, step map[string]any) {
	srcField, _ := step["field"].(string)
	if srcField == "" {
		return
	}
	raw := toString(fields[srcField])
	if raw == "" {
		return
	}
	toParse := raw
	hadScheme := strings.Contains(raw, "://")
	if !hadScheme {
		toParse = "http://" + raw
	}
	u, err := url.Parse(toParse)
	if err != nil || u.Host == "" {
		return
	}
	host := strings.ToLower(u.Hostname())
	registrable, errReg := publicsuffix.EffectiveTLDPlusOne(host)
	if errReg != nil || registrable == "" {
		registrable = host
	}
	tld, _ := publicsuffix.PublicSuffix(host)
	if hostTo, _ := step["host_to"].(string); hostTo != "" {
		fields[hostTo] = registrable
	}
	if schemeTo, _ := step["scheme_to"].(string); schemeTo != "" && hadScheme {
		fields[schemeTo] = strings.ToLower(u.Scheme)
	}
	if tldTo, _ := step["tld_to"].(string); tldTo != "" {
		fields[tldTo] = tld
	}
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
