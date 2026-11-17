package engine

import (
	"fmt"
	"regexp"
)

// ruleRejects returns the first reject_pattern that matches any
// extracted value, or "" if nothing rejects. Applied after map and
// before normalize, same as Python / JS.
func ruleRejects(patterns []string, fields map[string]any) string {
	if len(patterns) == 0 {
		return ""
	}
	compiled := make([]*regexp.Regexp, 0, len(patterns))
	for _, p := range patterns {
		re, err := regexp.Compile(p)
		if err != nil {
			// Bad pattern = fail-open, same as the other engines.
			return ""
		}
		compiled = append(compiled, re)
	}
	for _, v := range fields {
		s := toString(v)
		for i, re := range compiled {
			if re.MatchString(s) {
				return patterns[i]
			}
		}
	}
	return ""
}

func toString(v any) string {
	switch x := v.(type) {
	case string:
		return x
	case []byte:
		return string(x)
	case nil:
		return ""
	default:
		return fmt.Sprintf("%v", x)
	}
}
