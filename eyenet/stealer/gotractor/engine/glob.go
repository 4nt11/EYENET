package engine

import (
	"regexp"
	"strings"
)

// MatchGlob is byte-parity with the Python and JS matchGlob impls.
// Algorithm, mirrored line for line:
//   - escape regex meta first
//   - '**' becomes the sentinel GLOBSTAR so '*' substitution doesn't eat it
//   - '*'  becomes '[^/]*'
//   - '?'  becomes '[^/]'
//   - GLOBSTAR becomes '.*'
// Compiled regex is anchored start/end.
func MatchGlob(glob, path string) bool {
	var sb strings.Builder
	for _, r := range glob {
		switch r {
		case '.', '+', '^', '$', '{', '}', '(', ')', '|', '[', ']', '\\':
			sb.WriteRune('\\')
			sb.WriteRune(r)
		default:
			sb.WriteRune(r)
		}
	}
	pattern := sb.String()
	pattern = strings.ReplaceAll(pattern, "**", "\x00GLOBSTAR\x00")
	pattern = strings.ReplaceAll(pattern, "*", "[^/]*")
	pattern = strings.ReplaceAll(pattern, "?", "[^/]")
	pattern = strings.ReplaceAll(pattern, "\x00GLOBSTAR\x00", ".*")
	re, err := regexp.Compile("^" + pattern + "$")
	if err != nil {
		return false
	}
	return re.MatchString(path)
}
