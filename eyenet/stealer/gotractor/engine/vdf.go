package engine

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
)

// MatchVDF parses Valve Data Format (Steam's .vdf) and extracts fields.
// Byte-parity with the Python / JS impls. When `pivot` is set, returns
// the first child under the pivot as a record; IterVDF walks every
// child (used by bulk parse).
func MatchVDF(m map[string]any, ex map[string]any, inp ContentInput) map[string]any {
	doc, err := parseVDF(inp.Text)
	if err != nil {
		return nil
	}
	for _, k := range asStringList(m["requires_keys"]) {
		if _, ok := doc[k]; !ok {
			return nil
		}
	}
	pivot, _ := m["pivot"].(string)
	paths, _ := ex["paths"].(map[string]any)
	if pivot == "" {
		return extractPathsVDF(doc, paths)
	}
	for key, value := range pivotChildren(doc, pivot) {
		return extractVDFRecord(value, key, paths)
	}
	return nil
}

// IterVDF yields every pivot child as its own record. When pivot is
// absent the single-doc extraction is yielded once.
func IterVDF(m map[string]any, ex map[string]any, text string) <-chan map[string]any {
	ch := make(chan map[string]any)
	go func() {
		defer close(ch)
		doc, err := parseVDF(text)
		if err != nil {
			return
		}
		for _, k := range asStringList(m["requires_keys"]) {
			if _, ok := doc[k]; !ok {
				return
			}
		}
		paths, _ := ex["paths"].(map[string]any)
		pivot, _ := m["pivot"].(string)
		if pivot == "" {
			ch <- extractPathsVDF(doc, paths)
			return
		}
		for key, value := range pivotChildren(doc, pivot) {
			ch <- extractVDFRecord(value, key, paths)
		}
	}()
	return ch
}

var vdfPathToken = regexp.MustCompile(`\.(\w+)|\[(\d+)\]`)

// pivotChildren walks the pivot path and yields a map of (key, value)
// pairs when the resolved node is a VDF object (map[string]any). Returns
// an empty map on non-object pivots or missing path steps.
func pivotChildren(doc map[string]any, pivotExpr string) map[string]any {
	if len(pivotExpr) == 0 || pivotExpr[0] != '$' {
		return nil
	}
	var cur any = doc
	for _, m := range vdfPathToken.FindAllStringSubmatch(pivotExpr[1:], -1) {
		mp, ok := cur.(map[string]any)
		if !ok || m[1] == "" {
			return nil
		}
		cur = mp[m[1]]
		if cur == nil {
			return nil
		}
	}
	mp, _ := cur.(map[string]any)
	return mp
}

func extractVDFRecord(value any, keyName string, paths map[string]any) map[string]any {
	out := map[string]any{}
	for field, exprAny := range paths {
		expr, _ := exprAny.(string)
		if expr == "$key" {
			out[field] = keyName
			continue
		}
		v := evalVDFPath(value, expr)
		if v == nil {
			continue
		}
		switch vv := v.(type) {
		case string:
			out[field] = vv
		case map[string]any, []any:
			b, err := json.Marshal(vv)
			if err == nil {
				out[field] = string(b)
			}
		default:
			out[field] = fmt.Sprintf("%v", vv)
		}
	}
	return out
}

func extractPathsVDF(doc map[string]any, paths map[string]any) map[string]any {
	out := map[string]any{}
	for field, exprAny := range paths {
		expr, _ := exprAny.(string)
		v := evalVDFPath(doc, expr)
		if v == nil {
			continue
		}
		if s, ok := v.(string); ok {
			out[field] = s
		} else {
			b, _ := json.Marshal(v)
			out[field] = string(b)
		}
	}
	return out
}

func evalVDFPath(doc any, expr string) any {
	if len(expr) == 0 || expr[0] != '$' {
		return nil
	}
	cur := doc
	for _, m := range vdfPathToken.FindAllStringSubmatch(expr[1:], -1) {
		if cur == nil {
			return nil
		}
		mp, ok := cur.(map[string]any)
		if !ok || m[1] == "" {
			return nil
		}
		cur = mp[m[1]]
	}
	return cur
}

// --- VDF parser --- //
// KeyValues: alternating "key" + ("value" | { nested }) pairs. Quoted
// strings with \" \\ \n \t escapes. '//' line comments. Duplicate keys
// are last-wins (matches Steam's own flattening).

type vdfParser struct {
	t string
	i int
	n int
}

func parseVDF(text string) (map[string]any, error) {
	p := &vdfParser{t: text, n: len(text)}
	out := map[string]any{}
	for {
		p.skipWS()
		if p.i >= p.n {
			break
		}
		key, err := p.readStr()
		if err != nil {
			return nil, err
		}
		p.skipWS()
		if p.i >= p.n {
			return nil, fmt.Errorf("dangling key %q at eof", key)
		}
		if p.t[p.i] == '{' {
			p.i++
			obj, err := p.readObj()
			if err != nil {
				return nil, err
			}
			out[key] = obj
		} else {
			v, err := p.readStr()
			if err != nil {
				return nil, err
			}
			out[key] = v
		}
	}
	return out, nil
}

func (p *vdfParser) readObj() (map[string]any, error) {
	obj := map[string]any{}
	for {
		p.skipWS()
		if p.i >= p.n {
			return nil, fmt.Errorf("unterminated object")
		}
		if p.t[p.i] == '}' {
			p.i++
			return obj, nil
		}
		key, err := p.readStr()
		if err != nil {
			return nil, err
		}
		p.skipWS()
		if p.i >= p.n {
			return nil, fmt.Errorf("dangling key %q inside object", key)
		}
		if p.t[p.i] == '{' {
			p.i++
			nested, err := p.readObj()
			if err != nil {
				return nil, err
			}
			obj[key] = nested
		} else {
			v, err := p.readStr()
			if err != nil {
				return nil, err
			}
			obj[key] = v
		}
	}
}

func (p *vdfParser) readStr() (string, error) {
	if p.i >= p.n {
		return "", fmt.Errorf("expected string at eof")
	}
	if p.t[p.i] == '"' {
		p.i++
		var sb strings.Builder
		for p.i < p.n {
			ch := p.t[p.i]
			if ch == '\\' && p.i+1 < p.n {
				nxt := p.t[p.i+1]
				switch nxt {
				case 'n':
					sb.WriteByte('\n')
				case 't':
					sb.WriteByte('\t')
				case 'r':
					sb.WriteByte('\r')
				default:
					sb.WriteByte(nxt)
				}
				p.i += 2
				continue
			}
			if ch == '"' {
				p.i++
				return sb.String(), nil
			}
			sb.WriteByte(ch)
			p.i++
		}
		return "", fmt.Errorf("unterminated quoted string")
	}
	start := p.i
	for p.i < p.n && !strings.ContainsRune(" \t\r\n{}\"", rune(p.t[p.i])) {
		p.i++
	}
	if p.i == start {
		return "", fmt.Errorf("expected string at offset %d", p.i)
	}
	return p.t[start:p.i], nil
}

func (p *vdfParser) skipWS() {
	for p.i < p.n {
		ch := p.t[p.i]
		if ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n' {
			p.i++
			continue
		}
		if ch == '/' && p.i+1 < p.n && p.t[p.i+1] == '/' {
			for p.i < p.n && p.t[p.i] != '\n' {
				p.i++
			}
			continue
		}
		return
	}
}
