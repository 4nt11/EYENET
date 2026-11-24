package engine

import (
	"regexp"
	"strings"
	"sync"
)

// MatchGlob is byte-parity with the Python and JS matchGlob impls.
// Algorithm, mirrored line for line:
//   - escape regex meta first
//   - '**' becomes the sentinel GLOBSTAR so '*' substitution doesn't eat it
//   - '*'  becomes '[^/]*'
//   - '?'  becomes '[^/]'
//   - GLOBSTAR becomes '.*'
//
// Compiled regex is anchored start/end.
//
// Hot path: RunRules calls this for every rule x every file per archive.
// With the vendored catalog that is 74 rules x ~50 files x N archives
// per batch, so a soak drove regexp.Compile to 43% of total allocation
// before the cache. Globs come from the catalog (bounded cardinality),
// so an unbounded sync.Map is safe and amortises to one compile per
// unique glob string.
var globCache sync.Map // map[string]*regexp.Regexp

func MatchGlob(glob, path string) bool {
	if v, ok := globCache.Load(glob); ok {
		if re := v.(*regexp.Regexp); re != nil {
			return re.MatchString(path)
		}
		return false // cached compile-fail
	}
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
	// A glob with no '/' is a FILENAME pattern and matches at ANY depth (root
	// or nested), the gitignore semantic. Without this, "pc_info.json" compiles
	// to ^pc_info\.json$ and only matches a root-level file -- silently dropping
	// every nested victim-folder copy (this is what left the whole json_v2
	// pc_info.json / log_info.json fingerprint lane dark). Globs that contain a
	// '/' stay path-anchored as written; use '**' for explicit any-depth there.
	anchored := "^" + pattern + "$"
	if !strings.Contains(glob, "/") {
		anchored = "^(?:.*/)?" + pattern + "$"
	}
	re, err := regexp.Compile(anchored)
	if err != nil {
		globCache.LoadOrStore(glob, (*regexp.Regexp)(nil))
		return false
	}
	actual, _ := globCache.LoadOrStore(glob, re)
	return actual.(*regexp.Regexp).MatchString(path)
}
