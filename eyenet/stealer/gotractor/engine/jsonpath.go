package engine

import (
	"bytes"
	"encoding/json"
	"math"
	"regexp"
	"strconv"
)

// orderedMap is a map that remembers insertion order. We use it as the
// value type when parsing JSON input for the matcher, so nested-object
// stringification preserves the source order (matches Python's
// json.dumps(dict) and JS's JSON.stringify(obj)). Plain map[string]any
// loses this ordering through encoding/json.
type orderedMap struct {
	Keys   []string
	Values map[string]any
}

// parseOrderedJSON streams the input through encoding/json.Decoder.Token
// and builds an *orderedMap tree instead of flat map[string]any. Uses
// UseNumber so numeric scalars survive as json.Number (prevents the
// 1.0 -> "1" float-to-string lossy path we see in map[string]any).
func parseOrderedJSON(data []byte) (any, error) {
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	return parseOrderedValue(dec)
}

func parseOrderedValue(dec *json.Decoder) (any, error) {
	tok, err := dec.Token()
	if err != nil {
		return nil, err
	}
	if d, ok := tok.(json.Delim); ok {
		switch d {
		case '{':
			om := &orderedMap{Values: map[string]any{}}
			for dec.More() {
				keyTok, err := dec.Token()
				if err != nil {
					return nil, err
				}
				key, _ := keyTok.(string)
				val, err := parseOrderedValue(dec)
				if err != nil {
					return nil, err
				}
				om.Keys = append(om.Keys, key)
				om.Values[key] = val
			}
			_, err := dec.Token() // consume '}'
			return om, err
		case '[':
			var out []any
			for dec.More() {
				v, err := parseOrderedValue(dec)
				if err != nil {
					return nil, err
				}
				out = append(out, v)
			}
			_, err := dec.Token() // consume ']'
			return out, err
		}
	}
	// Convert json.Number to int64/float64 the same way json.Unmarshal
	// to interface{} would, so downstream type switches keep working.
	if n, ok := tok.(json.Number); ok {
		if i, err := n.Int64(); err == nil {
			return i, nil
		}
		if f, err := n.Float64(); err == nil {
			return f, nil
		}
		return n.String(), nil
	}
	return tok, nil
}

// marshalOrdered serialises an orderedMap tree back to JSON preserving
// key order. Falls through to encoding/json.Marshal for anything else.
func marshalOrdered(v any) ([]byte, error) {
	switch x := v.(type) {
	case *orderedMap:
		var buf bytes.Buffer
		buf.WriteByte('{')
		for i, k := range x.Keys {
			if i > 0 {
				buf.WriteByte(',')
			}
			kbytes, err := json.Marshal(k)
			if err != nil {
				return nil, err
			}
			buf.Write(kbytes)
			buf.WriteByte(':')
			vbytes, err := marshalOrdered(x.Values[k])
			if err != nil {
				return nil, err
			}
			buf.Write(vbytes)
		}
		buf.WriteByte('}')
		return buf.Bytes(), nil
	case []any:
		var buf bytes.Buffer
		buf.WriteByte('[')
		for i, elem := range x {
			if i > 0 {
				buf.WriteByte(',')
			}
			eb, err := marshalOrdered(elem)
			if err != nil {
				return nil, err
			}
			buf.Write(eb)
		}
		buf.WriteByte(']')
		return buf.Bytes(), nil
	default:
		return json.Marshal(v)
	}
}

// JSONPath-lite: '$.a.b[0].c' walk. Byte-parity with the Python and
// JS impls. Returns nil when any step in the path is missing or the
// current node has the wrong shape (map vs list). Numeric indices only.
var pathToken = regexp.MustCompile(`\.([\w-]+)|\[(\d+)\]`)

func evalPath(doc any, expr string) any {
	if len(expr) == 0 || expr[0] != '$' {
		return nil
	}
	cur := doc
	for _, m := range pathToken.FindAllStringSubmatch(expr[1:], -1) {
		if cur == nil {
			return nil
		}
		if m[1] != "" {
			switch asMap := cur.(type) {
			case *orderedMap:
				cur = asMap.Values[m[1]]
			case map[string]any:
				cur = asMap[m[1]]
			default:
				return nil
			}
		} else {
			asList, ok := cur.([]any)
			if !ok {
				return nil
			}
			i, err := strconv.Atoi(m[2])
			if err != nil || i < 0 || i >= len(asList) {
				return nil
			}
			cur = asList[i]
		}
	}
	return cur
}


// extractPaths walks the paths map and populates the output dict,
// honoring all the parity rules we accumulated: drop null, drop
// non-finite floats, coerce whole-number floats to int, stringify
// bools via "true"/"false", stringify nested objects/arrays as
// compact JSON.
func extractPaths(doc any, paths map[string]any) map[string]any {
	out := map[string]any{}
	for field, exprAny := range paths {
		expr, _ := exprAny.(string)
		v := evalPath(doc, expr)
		if v == nil {
			continue
		}
		switch vv := v.(type) {
		case float64:
			if math.IsNaN(vv) || math.IsInf(vv, 0) {
				continue
			}
			if vv == math.Trunc(vv) && !math.IsInf(vv, 0) {
				out[field] = int64(vv)
			} else {
				out[field] = vv
			}
		case bool:
			if vv {
				out[field] = "true"
			} else {
				out[field] = "false"
			}
		case string:
			out[field] = vv
		case int, int64:
			out[field] = vv
		case *orderedMap, []any, map[string]any:
			// Go's json.Marshal sorts map keys alphabetically; Python
			// and JS preserve insertion order. For nested composites
			// extracted via JSONPath we serialise through marshalOrdered
			// which keeps the orderedMap key ordering intact.
			b, err := marshalOrdered(vv)
			if err == nil {
				out[field] = string(b)
			}
		default:
			b, err := json.Marshal(vv)
			if err == nil {
				out[field] = string(b)
			}
		}
	}
	return out
}
