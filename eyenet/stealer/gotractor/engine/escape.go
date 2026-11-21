package engine

import "strings"

// escapeNulls replaces raw NUL bytes (U+0000) in string values with the
// literal 4-char escape '\x00'. Lossless, round-trippable, forensic-
// visible. Mirrors the Python and JS impls.
//
// v1.3.11: every string value is cloned via strings.Clone before it
// leaves the engine. The matchers return substrings of the file's Text
// (FindStringSubmatch gives slice-views, same with delimiter/json
// captures), and Go's string type shares backing memory with the source.
// A 130 MB file producing 1.92M records retained ~1.93 GiB of RSS because
// every string field pinned the whole file.Text. Cloning at this
// chokepoint (one allocation per field, bounded by output size) lets the
// source file's backing array GC as soon as the parse loop advances past
// it. Downstream never sees a pinned string.
//
// ReplaceAll already allocates (returns a new string), so NUL-carrying
// values are naturally unpinned; the explicit Clone covers the common
// 99%+ path where the field has no NUL.
func escapeNulls(fields map[string]any) map[string]any {
	out := make(map[string]any, len(fields))
	for k, v := range fields {
		s, ok := v.(string)
		if !ok {
			out[k] = v
			continue
		}
		if strings.ContainsRune(s, 0) {
			out[k] = strings.ReplaceAll(s, "\x00", `\x00`)
			continue
		}
		out[k] = strings.Clone(s)
	}
	return out
}
