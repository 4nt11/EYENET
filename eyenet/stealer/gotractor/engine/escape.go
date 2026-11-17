package engine

import "strings"

// escapeNulls replaces raw NUL bytes (U+0000) in string values with the
// literal 4-char escape '\x00'. Lossless, round-trippable, forensic-
// visible. Mirrors the Python and JS impls.
func escapeNulls(fields map[string]any) map[string]any {
	out := make(map[string]any, len(fields))
	for k, v := range fields {
		if s, ok := v.(string); ok && strings.ContainsRune(s, 0) {
			out[k] = strings.ReplaceAll(s, "\x00", `\x00`)
		} else {
			out[k] = v
		}
	}
	return out
}
