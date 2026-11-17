package engine

import (
	"fmt"
	"regexp"
	"strings"
	"unicode"
)

// Hardened hand-rolled XML parser. No DOCTYPE (fatal), no entity
// expansion beyond the five standard XML entities plus &#NN; / &#xHH;
// numeric refs, no PI handling beyond skip, no namespace resolution,
// no external I/O (the parser is pure string indexing; there is no
// network code path to subvert). Depth cap 256. Byte-parity with the
// Python / JS ports.

const xmlMaxDepth = 256

var xmlEntities = map[string]string{
	"lt": "<", "gt": ">", "amp": "&", "quot": `"`, "apos": "'",
}

type xmlElement struct {
	Name     string
	Attrs    map[string]string
	Children []*xmlElement
	Text     string
}

type xmlParser struct {
	t     string
	i, n  int
	depth int
}

func parseXML(text string) (*xmlElement, error) {
	p := &xmlParser{t: text, n: len(text)}
	if err := p.skipProlog(); err != nil {
		return nil, err
	}
	if p.i >= p.n || p.t[p.i] != '<' {
		return nil, fmt.Errorf("no root element")
	}
	return p.parseElement()
}

func (p *xmlParser) skipProlog() error {
	for {
		p.skipWS()
		if strings.HasPrefix(p.t[p.i:], "<?") {
			end := strings.Index(p.t[p.i+2:], "?>")
			if end < 0 {
				return fmt.Errorf("unterminated PI")
			}
			p.i += 2 + end + 2
			continue
		}
		if strings.HasPrefix(p.t[p.i:], "<!--") {
			end := strings.Index(p.t[p.i+4:], "-->")
			if end < 0 {
				return fmt.Errorf("unterminated comment")
			}
			p.i += 4 + end + 3
			continue
		}
		if strings.HasPrefix(p.t[p.i:], "<!DOCTYPE") {
			return fmt.Errorf("DOCTYPE not supported")
		}
		return nil
	}
}

func (p *xmlParser) parseElement() (*xmlElement, error) {
	p.depth++
	if p.depth > xmlMaxDepth {
		return nil, fmt.Errorf("depth > %d", xmlMaxDepth)
	}
	if p.i >= p.n || p.t[p.i] != '<' {
		return nil, fmt.Errorf("expected '<' at %d", p.i)
	}
	p.i++
	name, err := p.readName()
	if err != nil {
		return nil, err
	}
	el := &xmlElement{Name: name, Attrs: map[string]string{}}
	for {
		p.skipWS()
		if p.i >= p.n {
			return nil, fmt.Errorf("unterminated start tag <%s>", name)
		}
		if strings.HasPrefix(p.t[p.i:], "/>") {
			p.i += 2
			p.depth--
			return el, nil
		}
		if p.t[p.i] == '>' {
			p.i++
			break
		}
		attrName, err := p.readName()
		if err != nil {
			return nil, err
		}
		p.skipWS()
		if p.i >= p.n || p.t[p.i] != '=' {
			return nil, fmt.Errorf("missing '=' after attr %q", attrName)
		}
		p.i++
		p.skipWS()
		val, err := p.readAttrValue()
		if err != nil {
			return nil, err
		}
		el.Attrs[attrName] = val
	}
	var buf strings.Builder
	for {
		if p.i >= p.n {
			return nil, fmt.Errorf("unterminated <%s>", name)
		}
		if strings.HasPrefix(p.t[p.i:], "</") {
			p.i += 2
			closing, err := p.readName()
			if err != nil {
				return nil, err
			}
			p.skipWS()
			if p.i >= p.n || p.t[p.i] != '>' {
				return nil, fmt.Errorf("malformed close </%s>", closing)
			}
			p.i++
			if closing != name {
				return nil, fmt.Errorf("close </%s> != open <%s>", closing, name)
			}
			el.Text = buf.String()
			p.depth--
			return el, nil
		}
		if strings.HasPrefix(p.t[p.i:], "<!--") {
			end := strings.Index(p.t[p.i+4:], "-->")
			if end < 0 {
				return nil, fmt.Errorf("unterminated comment")
			}
			p.i += 4 + end + 3
			continue
		}
		if strings.HasPrefix(p.t[p.i:], "<![CDATA[") {
			end := strings.Index(p.t[p.i+9:], "]]>")
			if end < 0 {
				return nil, fmt.Errorf("unterminated CDATA")
			}
			buf.WriteString(p.t[p.i+9 : p.i+9+end])
			p.i += 9 + end + 3
			continue
		}
		if strings.HasPrefix(p.t[p.i:], "<?") {
			end := strings.Index(p.t[p.i+2:], "?>")
			if end < 0 {
				return nil, fmt.Errorf("unterminated PI")
			}
			p.i += 2 + end + 2
			continue
		}
		if p.t[p.i] == '<' {
			child, err := p.parseElement()
			if err != nil {
				return nil, err
			}
			el.Children = append(el.Children, child)
			continue
		}
		end := strings.IndexByte(p.t[p.i:], '<')
		if end < 0 {
			return nil, fmt.Errorf("unterminated <%s>", name)
		}
		buf.WriteString(xmlUnescape(p.t[p.i : p.i+end]))
		p.i += end
	}
}

func (p *xmlParser) readName() (string, error) {
	if p.i >= p.n {
		return "", fmt.Errorf("expected name at eof")
	}
	start := p.i
	r := rune(p.t[p.i])
	if !unicode.IsLetter(r) && r != '_' && r != ':' {
		return "", fmt.Errorf("expected name at %d", p.i)
	}
	p.i++
	for p.i < p.n {
		c := rune(p.t[p.i])
		if unicode.IsLetter(c) || unicode.IsDigit(c) || c == '_' || c == '-' || c == '.' || c == ':' {
			p.i++
		} else {
			break
		}
	}
	return p.t[start:p.i], nil
}

func (p *xmlParser) readAttrValue() (string, error) {
	if p.i >= p.n || (p.t[p.i] != '"' && p.t[p.i] != '\'') {
		return "", fmt.Errorf("attr value not quoted")
	}
	q := p.t[p.i]
	p.i++
	start := p.i
	for p.i < p.n && p.t[p.i] != q {
		p.i++
	}
	if p.i >= p.n {
		return "", fmt.Errorf("unterminated attr value")
	}
	v := xmlUnescape(p.t[start:p.i])
	p.i++
	return v, nil
}

func (p *xmlParser) skipWS() {
	for p.i < p.n && (p.t[p.i] == ' ' || p.t[p.i] == '\t' || p.t[p.i] == '\r' || p.t[p.i] == '\n') {
		p.i++
	}
}

func xmlUnescape(s string) string {
	if !strings.ContainsRune(s, '&') {
		return s
	}
	var out strings.Builder
	i, n := 0, len(s)
	for i < n {
		if s[i] != '&' {
			out.WriteByte(s[i])
			i++
			continue
		}
		end := strings.IndexByte(s[i+1:], ';')
		if end < 0 {
			out.WriteByte('&')
			i++
			continue
		}
		end += i + 1
		name := s[i+1 : end]
		if rep, ok := xmlEntities[name]; ok {
			out.WriteString(rep)
		} else if strings.HasPrefix(name, "#x") || strings.HasPrefix(name, "#X") {
			var cp int
			_, err := fmt.Sscanf(name[2:], "%x", &cp)
			if err == nil {
				out.WriteRune(rune(cp))
			} else {
				out.WriteString(s[i : end+1])
			}
		} else if strings.HasPrefix(name, "#") {
			var cp int
			_, err := fmt.Sscanf(name[1:], "%d", &cp)
			if err == nil {
				out.WriteRune(rune(cp))
			} else {
				out.WriteString(s[i : end+1])
			}
		} else {
			// Unknown named entity: preserve literally; do NOT resolve.
			out.WriteString(s[i : end+1])
		}
		i = end + 1
	}
	return out.String()
}

// MatchXML + IterXML mirror the VDF implementations in shape: when
// pivot is set, iterate child elements that match the LAST path
// segment's element name. $key resolves to the pivot child's element
// name. Paths support '@attr' for attribute access.
func MatchXML(m map[string]any, ex map[string]any, inp ContentInput) map[string]any {
	root, err := parseXML(inp.Text)
	if err != nil {
		return nil
	}
	if !xmlCheckRequires(root, asStringList(m["requires_keys"])) {
		return nil
	}
	paths, _ := ex["paths"].(map[string]any)
	pivot, _ := m["pivot"].(string)
	if pivot != "" {
		for _, kv := range xmlPivotChildren(root, pivot) {
			return xmlExtractRecord(kv.el, kv.key, paths)
		}
		return nil
	}
	return xmlExtractRecord(root, root.Name, paths)
}

func IterXML(m map[string]any, ex map[string]any, text string) <-chan map[string]any {
	ch := make(chan map[string]any)
	go func() {
		defer close(ch)
		root, err := parseXML(text)
		if err != nil {
			return
		}
		if !xmlCheckRequires(root, asStringList(m["requires_keys"])) {
			return
		}
		paths, _ := ex["paths"].(map[string]any)
		pivot, _ := m["pivot"].(string)
		if pivot == "" {
			ch <- xmlExtractRecord(root, root.Name, paths)
			return
		}
		for _, kv := range xmlPivotChildren(root, pivot) {
			ch <- xmlExtractRecord(kv.el, kv.key, paths)
		}
	}()
	return ch
}

func xmlCheckRequires(root *xmlElement, required []string) bool {
	if len(required) == 0 {
		return true
	}
	top := map[string]bool{root.Name: true}
	for _, c := range root.Children {
		top[c.Name] = true
	}
	for _, k := range required {
		if !top[k] {
			return false
		}
	}
	return true
}

type xmlKV struct {
	key string
	el  *xmlElement
}

var xmlPathSeg = regexp.MustCompile(`\.([\w-]+)`)

func xmlPivotChildren(root *xmlElement, pivotExpr string) []xmlKV {
	if !strings.HasPrefix(pivotExpr, "$") {
		return nil
	}
	var steps []string
	for _, m := range xmlPathSeg.FindAllStringSubmatch(pivotExpr[1:], -1) {
		steps = append(steps, m[1])
	}
	if len(steps) == 0 {
		return nil
	}
	cur := root
	rest := steps
	if steps[0] == root.Name {
		rest = steps[1:]
	}
	if len(rest) == 0 {
		return nil
	}
	target := rest[len(rest)-1]
	middle := rest[:len(rest)-1]
	for _, step := range middle {
		found := xmlFindChild(cur, step)
		if found == nil {
			return nil
		}
		cur = found
	}
	var out []xmlKV
	for _, c := range cur.Children {
		if c.Name == target {
			out = append(out, xmlKV{key: c.Name, el: c})
		}
	}
	return out
}

func xmlFindChild(el *xmlElement, name string) *xmlElement {
	for _, c := range el.Children {
		if c.Name == name {
			return c
		}
	}
	return nil
}

func xmlExtractRecord(el *xmlElement, keyName string, paths map[string]any) map[string]any {
	out := map[string]any{}
	for field, exprAny := range paths {
		expr, _ := exprAny.(string)
		if expr == "$key" {
			out[field] = keyName
			continue
		}
		if v, ok := xmlEvalPath(el, expr); ok {
			out[field] = v
		}
	}
	return out
}

func xmlEvalPath(el *xmlElement, expr string) (string, bool) {
	if !strings.HasPrefix(expr, "$") {
		return "", false
	}
	var attr string
	if idx := strings.LastIndexByte(expr, '@'); idx >= 0 {
		attr = expr[idx+1:]
		expr = expr[:idx]
	}
	cur := el
	for _, m := range xmlPathSeg.FindAllStringSubmatch(expr[1:], -1) {
		next := xmlFindChild(cur, m[1])
		if next == nil {
			return "", false
		}
		cur = next
	}
	if attr != "" {
		v, ok := cur.Attrs[attr]
		return v, ok
	}
	return cur.Text, true
}
