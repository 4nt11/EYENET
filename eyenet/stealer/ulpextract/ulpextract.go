// ulpextract - production port of ulp_extract.py parse_line.
// Go's stdlib regexp IS RE2 (linear time, no ReDoS) -> satisfies the untrusted-
// input rule with ZERO dependencies. Stateless streaming: constant low RSS.
//
// Format model (frozen; discovered in the Python prototype, see its --profile):
//   Anchor 1  URL [<delim>] [login] : password   (reset capture = empty login)
//   Anchor 2  email : password                   (combolist, no URL)
// Emits:  host<TAB>url<TAB>login<TAB>password   (control chars stripped).
// Dedup is ClickHouse's job (ReplacingMergeTree), NOT ours.
//
//   go build -o ulpextract ulpextract.go
//   ./ulpextract FILE...                         # paths as args
//   find DATA -name '*.txt' -print0 | ./ulpextract   # NUL paths on stdin
//   ./ulpextract -selftest
package main

import (
	"bufio"
	"bytes"
	"fmt"
	"io"
	"net/netip"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"time"
	"unicode/utf16"
)

var (
	scheme       = regexp.MustCompile(`(?i)[a-z][a-z0-9+-]*://`) // ANY scheme:// (no dots); android handled first
	leadingURL   = regexp.MustCompile(`(?i)^(?:\d{1,3}(?:\.\d{1,3}){3}|(?:[a-z0-9-]+\.)+[a-z]{2,})(?:/[^\s:;|,]*)?`) // IPv4 or dotted host + opt path
	leadingEmail = regexp.MustCompile(`(?i)^[^@\s:;|,]+@[^@\s:;|,]+\.[a-z]{2,}`)
	leadingSchm  = regexp.MustCompile(`(?i)^([a-z][a-z0-9+-]*)://`) // captures the scheme token (no dots: a host fragment is not a scheme)
	corrupt      = regexp.MustCompile(`(?i)ht[0-9]ps://`)           // byte-corrupted https -> whole line is garbage, drop
	cleaner      = strings.NewReplacer("\t", "", "\r", "", "\n", "") // TSV-safe (concurrent-safe)
)

const trim = " \t:;|,"

func host(url string) string {
	if url == "" {
		return ""
	}
	if i := strings.IndexByte(url, '/'); i >= 0 {
		url = url[:i]
	}
	if i := strings.IndexByte(url, ':'); i >= 0 { // drop :PORT so host groups/matches cleanly
		url = url[:i]
	}
	return strings.ToLower(url)
}

// ipClass tags a special-use IP host to its RFC (ordered most-specific first);
// "" for a normal public IP or a non-IP host. Private ranges are evidence-only,
// never a global join key.
var ipClasses = []struct {
	p   netip.Prefix
	tag string
}{
	{netip.MustParsePrefix("10.0.0.0/8"), "rfc1918"},
	{netip.MustParsePrefix("172.16.0.0/12"), "rfc1918"},
	{netip.MustParsePrefix("192.168.0.0/16"), "rfc1918"},
	{netip.MustParsePrefix("192.0.2.0/24"), "rfc5737"},
	{netip.MustParsePrefix("198.51.100.0/24"), "rfc5737"},
	{netip.MustParsePrefix("203.0.113.0/24"), "rfc5737"},
	{netip.MustParsePrefix("fc00::/7"), "rfc4193"},
	{netip.MustParsePrefix("0.0.0.0/8"), "rfc5735"},
	{netip.MustParsePrefix("127.0.0.0/8"), "rfc5735"},
	{netip.MustParsePrefix("169.254.0.0/16"), "rfc5735"},
	{netip.MustParsePrefix("192.0.0.0/24"), "rfc5735"},
	{netip.MustParsePrefix("192.88.99.0/24"), "rfc5735"},
	{netip.MustParsePrefix("198.18.0.0/15"), "rfc5735"},
	{netip.MustParsePrefix("224.0.0.0/4"), "rfc5735"},
	{netip.MustParsePrefix("240.0.0.0/4"), "rfc5735"},
}

func ipClass(h string) string {
	a, err := netip.ParseAddr(h)
	if err != nil {
		return "" // not an IP (domain host)
	}
	for _, e := range ipClasses {
		if e.p.Contains(a) {
			return e.tag
		}
	}
	return "" // global/public IP
}

// tldOf returns the last dot-label of the host = ccTLD for country domains (an
// imperfect location signal). Falls back to the email domain for host-less combo
// rows; empty for android packages (reverse-DNS, no geographic TLD).
func tldOf(sch, h, login string) string {
	if sch == "android" {
		return ""
	}
	d := h
	if d == "" {
		if i := strings.LastIndexByte(login, '@'); i >= 0 {
			d = login[i+1:]
		}
	}
	if i := strings.LastIndexByte(d, '.'); i >= 0 {
		t := strings.ToLower(d[i+1:])
		allDigit := t != ""
		for _, c := range t {
			if c < '0' || c > '9' {
				allDigit = false
				break
			}
		}
		if allDigit { // last label is all digits -> IP octet, not a TLD
			return ""
		}
		return t
	}
	return ""
}

// stripPort peels a genuine :PORT (optionally with a trailing /path) off the text
// right after the host: all-digits, 1-5 long, ending AT a delimiter, with a
// login+pass still to follow. Returns ("", tail) when it is not a port, e.g.
// host:123abc (alphanumeric login) or host:12345:pass (numeric login, one field).
func stripPort(tail string) (string, string) {
	if len(tail) == 0 || tail[0] != ':' {
		return "", tail
	}
	j := 1
	for j < len(tail) && tail[j] >= '0' && tail[j] <= '9' {
		j++
	}
	if j == 1 || j-1 > 5 || j >= len(tail) { // no digits / >5 digits / nothing follows
		return "", tail
	}
	nxt, after := tail[j], tail[j+1:]
	isPort := nxt == '/' || nxt == ' ' || nxt == '\t' ||
		(nxt == ':' && (strings.IndexByte(after, ':') >= 0 || strings.ContainsAny(after, " \t")))
	if !isPort {
		return "", tail
	}
	if nxt == '/' { // absorb the path that follows the port into the URL too
		k := j
		for k < len(tail) && strings.IndexByte(" \t:;|,", tail[k]) < 0 {
			k++
		}
		return tail[:k], tail[k:]
	}
	return tail[:j], tail[j:]
}

// parseAndroid handles  android://<hash>@<package>/<delim>login<delim>pass .
// The credential identity is the PACKAGE (reverse-DNS), not the hash; fields are
// usually pipe-delimited. Must run before the generic scheme strip + email anchor,
// or the base64 hash gets mistaken for a login.
func parseAndroid(ln string) (url, login, password string, ok bool) {
	m := leadingSchm.FindStringSubmatch(ln) // app creds can ride android:// OR https://
	if m == nil {
		return "", "", "", false
	}
	body := ln[len(m[0]):]
	at := strings.IndexByte(body, '@')
	if at < 1 {
		return "", "", "", false
	}
	hashpart := body[:at]
	if strings.IndexByte(hashpart, '.') >= 0 {
		return "", "", "", false // a dotted thing before @ is a host/email, not an app hash
	}
	// android:// trusts any hash; other schemes need a long opaque base64 hash so we
	// don't misread https://longuser@host.com/... as an app.
	if !strings.EqualFold(m[1], "android") && len(hashpart) < 40 {
		return "", "", "", false
	}
	after := body[at+1:] // com.pkg.name/<delim>login<delim>pass
	k := strings.IndexAny(after, "/|: \t")
	if k <= 0 {
		return "", "", "", false
	}
	pkg := after[:k]
	if strings.IndexByte(pkg, '.') < 0 { // must look like a reverse-DNS package
		return "", "", "", false
	}
	rest := strings.TrimLeft(after[k:], "/|: \t")
	di := strings.IndexAny(rest, "|:")
	if di < 0 {
		return "", "", "", false
	}
	lg, pw := strings.TrimSpace(rest[:di]), rest[di+1:]
	if lg == "" || pw == "" {
		return "", "", "", false
	}
	return pkg, lg, pw, true
}

// parseLine mirrors parse_line() in ulp_extract.py, case-for-case.
// Returns the URL scheme token ("" when schemeless) alongside the credential.
func parseLine(ln string) (sch, url, login, password string, ok bool) {
	if corrupt.MatchString(ln) { // ht?ps:// = byte-corrupted line, drop before a scheme masks it
		return "", "", "", "", false
	}
	if u, l, p, ok := parseAndroid(ln); ok { // android app creds (hash@pkg, pipe-delimited)
		return "android", u, l, p, ok
	}
	if m := leadingSchm.FindStringSubmatch(ln); m != nil { // capture the scheme before stripping
		sch = strings.ToLower(m[1])
	}
	ln = strings.TrimSpace(scheme.ReplaceAllString(ln, ""))

	if loc := leadingURL.FindStringIndex(ln); loc != nil {
		url = ln[:loc[1]]
		tail := ln[loc[1]:]
		if p, rest := stripPort(tail); p != "" { // fold :PORT[/path] into the URL
			url += p
			tail = rest
		}
		if len(tail) > 0 && (tail[0] == ' ' || tail[0] == '\t') {
			// space-delimited: a following ':' marks an EMPTY login (reset capture)
			rest := strings.TrimLeft(tail, " \t")
			if strings.HasPrefix(rest, ":") {
				if pw := strings.TrimSpace(rest[1:]); pw != "" {
					return sch, url, "", pw, true
				}
				return "", "", "", "", false
			}
			if i := strings.IndexByte(rest, ':'); i >= 0 {
				lg := strings.TrimSpace(rest[:i])
				if pw := rest[i+1:]; lg != "" && pw != "" {
					return sch, url, lg, pw, true
				}
			}
			return "", "", "", "", false
		}
		// colon/sep-delimited: tail opens with the delimiter itself
		rest := strings.TrimLeft(tail, trim)
		if i := strings.IndexByte(rest, ':'); i >= 0 {
			lg := strings.TrimSpace(rest[:i])
			if pw := rest[i+1:]; lg != "" && pw != "" {
				return sch, url, lg, pw, true
			}
		}
		return "", "", "", "", false
	}

	if loc := leadingEmail.FindStringIndex(ln); loc != nil { // email combos have no scheme
		email := ln[:loc[1]]
		rest := strings.TrimSpace(strings.TrimLeft(ln[loc[1]:], trim))
		if rest != "" {
			return "", "", email, rest, true
		}
	}
	return "", "", "", "", false
}

// detectEncoding sniffs a file's leading bytes: BOM first, then a NUL-density +
// parity heuristic for BOM-less UTF-16 (Windows stealer logs love it).
func detectEncoding(p []byte) string {
	if len(p) >= 2 {
		if p[0] == 0xFF && p[1] == 0xFE {
			return "utf16le"
		}
		if p[0] == 0xFE && p[1] == 0xFF {
			return "utf16be"
		}
	}
	if len(p) >= 16 {
		zeros, odd := 0, 0
		for i, b := range p {
			if b == 0 {
				zeros++
				if i%2 == 1 {
					odd++
				}
			}
		}
		if zeros*4 > len(p) { // >25% NUL -> UTF-16; parity picks endianness
			if odd*2 >= zeros {
				return "utf16le"
			}
			return "utf16be"
		}
	}
	return "utf8"
}

func decodeUTF16(raw []byte, bigEndian bool) string {
	if len(raw) >= 2 && ((raw[0] == 0xFF && raw[1] == 0xFE) || (raw[0] == 0xFE && raw[1] == 0xFF)) {
		raw = raw[2:] // strip BOM
	}
	n := len(raw) / 2
	u := make([]uint16, n)
	for i := 0; i < n; i++ {
		if bigEndian {
			u[i] = uint16(raw[2*i])<<8 | uint16(raw[2*i+1])
		} else {
			u[i] = uint16(raw[2*i+1])<<8 | uint16(raw[2*i])
		}
	}
	return string(utf16.Decode(u))
}

// --- multi-line labeled records (Host:/Username:/Password:, ftp:/port:/pass:) ---
// A label line is <word>:<whitespace><value> (or empty value). The whitespace
// after the colon is what distinguishes a label from `ftp://...` or `d.com:u:p`.
var mlLabel = regexp.MustCompile(`(?i)^([a-z]{2,12})[ \t]*:(?:[ \t]+(.*))?$`)

func mlRole(label string) string {
	switch strings.ToLower(label) {
	case "host", "hostname", "url", "urls", "uri", "server", "soft", "application":
		return "host"
	case "ftp": // host slot + implies the ftp scheme
		return "ftp"
	case "port":
		return "port"
	case "username", "user", "login", "email", "mail", "account":
		return "login"
	case "password", "pass", "pwd", "passwd":
		return "pass"
	}
	return ""
}

type mlAcc struct{ scheme, host, port, login, pass string }

func (a *mlAcc) hasRole(role string) bool {
	switch role {
	case "host", "ftp":
		return a.host != ""
	case "port":
		return a.port != ""
	case "login":
		return a.login != ""
	case "pass":
		return a.pass != ""
	}
	return false
}

func (a *mlAcc) set(role, val string) {
	switch role {
	case "host":
		a.host = val
	case "ftp":
		a.host, a.scheme = val, "ftp"
	case "port":
		a.port = val
	case "login":
		a.login = val
	case "pass":
		a.pass = val
	}
}

// row assembles a completed record: host-value gets the same scheme/host treatment
// as a single-line URL; needs (host or login) + password.
func (a *mlAcc) row() (sch, h, url, login, pass string, ok bool) {
	hv, sch := a.host, a.scheme
	if m := leadingSchm.FindStringSubmatch(hv); m != nil {
		sch = strings.ToLower(m[1])
	}
	hv = strings.TrimSpace(scheme.ReplaceAllString(hv, ""))
	if a.port != "" {
		hv += ":" + strings.TrimSpace(a.port)
	}
	if (hv == "" && a.login == "") || a.pass == "" {
		return "", "", "", "", "", false
	}
	return sch, host(hv), hv, a.login, a.pass, true
}

func processFile(path string, out *bufio.Writer, mu *sync.Mutex) (kept, dropped int64) {
	f, err := os.Open(path)
	if err != nil {
		fmt.Fprintf(os.Stderr, "skip %s: %v\n", path, err)
		return
	}
	defer f.Close()
	br := bufio.NewReaderSize(f, 1<<20)
	peek, _ := br.Peek(256)
	enc := detectEncoding(peek)

	src := cleaner.Replace(filepath.Base(path)) // provenance: the source dump (later: channel id -> actor)
	buf := bytes.Buffer{}
	flush := func() {
		if buf.Len() == 0 {
			return
		}
		mu.Lock()
		out.Write(buf.Bytes())
		mu.Unlock()
		buf.Reset()
	}
	emitRow := func(sch, h, url, login, pw string) {
		buf.WriteString(cleaner.Replace(h))
		buf.WriteByte('\t')
		buf.WriteString(cleaner.Replace(url))
		buf.WriteByte('\t')
		buf.WriteString(cleaner.Replace(login))
		buf.WriteByte('\t')
		buf.WriteString(cleaner.Replace(pw))
		buf.WriteByte('\t')
		buf.WriteString(cleaner.Replace(sch))
		buf.WriteByte('\t')
		buf.WriteString(cleaner.Replace(tldOf(sch, h, login)))
		buf.WriteByte('\t')
		buf.WriteString(src)
		buf.WriteByte('\t')
		buf.WriteString(ipClass(h))
		buf.WriteByte('\n')
		kept++
		if buf.Len() > 1<<20 {
			flush()
		}
	}
	var acc mlAcc
	flushAcc := func() {
		if sch, h, url, login, pw, ok := acc.row(); ok {
			emitRow(sch, h, url, login, pw)
		}
		acc = mlAcc{}
	}
	feed := func(line string) {
		if strings.TrimSpace(line) == "" { // blank -> record boundary
			flushAcc()
			return
		}
		if m := mlLabel.FindStringSubmatch(line); m != nil {
			if role := mlRole(m[1]); role != "" {
				if acc.hasRole(role) { // a repeated role starts a new record
					flushAcc()
				}
				acc.set(role, strings.TrimSpace(m[2]))
				return
			}
		}
		// non-label (or unknown-label) line: interleaving safety -> flush any pending
		// partial record, then parse the line as a single-line credential.
		flushAcc()
		if sch, url, login, pw, ok := parseLine(line); ok {
			emitRow(sch, host(url), url, login, pw)
		} else {
			dropped++
		}
	}

	if enc == "utf16le" || enc == "utf16be" {
		// ponytail: whole-file decode for UTF-16 (a small minority); UTF-8 still
		// streams. A pathologically huge UTF-16 file would spike RAM -> switch to
		// a streaming x/text decoder if one ever shows up.
		raw, _ := io.ReadAll(br)
		for _, line := range strings.Split(decodeUTF16(raw, enc == "utf16be"), "\n") {
			feed(strings.TrimRight(line, "\r"))
		}
	} else {
		if len(peek) >= 3 && peek[0] == 0xEF && peek[1] == 0xBB && peek[2] == 0xBF {
			br.Discard(3) // UTF-8 BOM
		}
		for {
			line, err := br.ReadString('\n') // no 64K line cap, unlike Scanner
			if len(line) > 0 {
				feed(strings.TrimRight(line, "\r\n"))
			}
			if err != nil {
				break
			}
		}
	}
	flushAcc()
	flush()
	return
}

func filesFromStdin() []string {
	data, _ := io.ReadAll(os.Stdin)
	sep := byte('\n')
	if bytes.IndexByte(data, 0) >= 0 { // find -print0
		sep = 0
	}
	var out []string
	for _, p := range bytes.Split(data, []byte{sep}) {
		if s := strings.TrimSpace(string(p)); s != "" {
			out = append(out, s)
		}
	}
	return out
}

func main() {
	args := os.Args[1:]
	var files []string
	manifestPath := ""
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "-selftest":
			selftest()
			return
		case "-manifest":
			if i+1 < len(args) {
				i++
				manifestPath = args[i]
			}
		default:
			files = append(files, args[i])
		}
	}
	if len(files) == 0 {
		files = filesFromStdin()
	}
	if len(files) == 0 {
		fmt.Fprintln(os.Stderr, "usage: ulpextract [-manifest FILE] FILE...  |  find ... -print0 | ulpextract [-manifest FILE]")
		os.Exit(2)
	}

	// Optional per-file ledger: timestamp<TAB>path<TAB>kept<TAB>dropped<TAB>kept_pct
	// O_APPEND so batched load.sh invocations accumulate ONE cumulative manifest.
	// A file appears here only AFTER it finished extracting (so a crash mid-file
	// leaves no false "done" row); note it does NOT prove the downstream INSERT landed.
	var man *bufio.Writer
	var manMu sync.Mutex
	if manifestPath != "" {
		mf, err := os.OpenFile(manifestPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
		if err != nil {
			fmt.Fprintf(os.Stderr, "manifest: %v\n", err)
			os.Exit(1)
		}
		defer mf.Close()
		man = bufio.NewWriter(mf)
	}

	out := bufio.NewWriterSize(os.Stdout, 1<<20)
	var mu sync.Mutex
	jobs := make(chan string, 256)
	var kept, dropped int64
	var wg sync.WaitGroup
	for i := 0; i < runtime.NumCPU(); i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for path := range jobs {
				k, d := processFile(path, out, &mu)
				atomic.AddInt64(&kept, k)
				atomic.AddInt64(&dropped, d)
				if man != nil {
					pct := 0.0
					if t := k + d; t > 0 {
						pct = 100 * float64(k) / float64(t)
					}
					manMu.Lock()
					fmt.Fprintf(man, "%s\t%s\t%d\t%d\t%.1f\n", time.Now().Format(time.RFC3339), path, k, d, pct)
					manMu.Unlock()
				}
			}
		}()
	}
	for _, f := range files {
		jobs <- f
	}
	close(jobs)
	wg.Wait()
	out.Flush()
	if man != nil {
		man.Flush()
	}
	total := kept + dropped
	pct := 0.0
	if total > 0 {
		pct = 100 * float64(kept) / float64(total)
	}
	fmt.Fprintf(os.Stderr, "files=%d kept=%d dropped=%d kept_pct=%.1f%%\n", len(files), kept, dropped, pct)
}

func selftest() {
	type want struct {
		url, login, pw string
		ok             bool
	}
	cases := map[string]want{
		"https://accounts.google.com/SignUp alice@mail.com:Pa$$w0rd": {"accounts.google.com/SignUp", "alice@mail.com", "Pa$$w0rd", true},
		"site.com user:pass":              {"site.com", "user", "pass", true},
		"domain.com:bob@x.com:pw":         {"domain.com", "bob@x.com", "pw", true},
		"example.org:carol:qwerty":        {"example.org", "carol", "qwerty", true},
		"com.android.chrome:dave:hunter2": {"com.android.chrome", "dave", "hunter2", true},
		"login.live.com eve:p:a:ss":       {"login.live.com", "eve", "p:a:ss", true},
		// :PORT folds into the URL, does not become the login
		"host.cl:8043:user:pass":          {"host.cl:8043", "user", "pass", true},
		"host.cl:8080 alice@x.com:pw":     {"host.cl:8080", "alice@x.com", "pw", true},
		"api.site.org:9000/login.php joe:secret": {"api.site.org:9000/login.php", "joe", "secret", true},
		// NOT a port: numeric login (one field after) and alphanumeric login are preserved
		"num.site.net:12345:pw":           {"num.site.net", "12345", "pw", true},
		"alpha.site.io:123abc:pw":         {"alpha.site.io", "123abc", "pw", true},
		// android app creds: package is the host, pipe-delimited, hash ignored
		"android://zQxb6==@com.facebook.orca/|user|pass":        {"com.facebook.orca", "user", "pass", true},
		"android://eJfC_-==@com.mercadolibre/|email@gmail.com|pass": {"com.mercadolibre", "email@gmail.com", "pass", true},
		// generic non-http scheme now stripped too
		"ftp://ftp.example.com:ftpuser:ftppw": {"ftp.example.com", "ftpuser", "ftppw", true},
		// v5: app creds behind https:// (long opaque hash @ reverse-DNS package)
		"https://RqosACteuEtSp_uD4UgRzxIIXLQSnPa1y0FUNYbIw3g==@com.sandboxol.blockymods/:user:pass": {"com.sandboxol.blockymods", "user", "pass", true},
		// v5: IPv4 host (private/public) now accepted
		"https://192.168.50.239:5000/:user:pass": {"192.168.50.239:5000/", "user", "pass", true},
		"192.168.250.84/doc/page/login.asp:user:pass": {"192.168.250.84/doc/page/login.asp", "user", "pass", true},
		// v5: byte-corrupted (ht?ps://) line is dropped, not laundered into https
		"https://ht4ps://m0.account.s1ny92om/x:email@gmail.1om:pass": {ok: false},
		"ht3ps://m0.inter.com:email@gmail.com:pass":                  {ok: false},
		"https://www.bancociudad.com.ar/autogestion/x%3D%3D :s3cret": {"www.bancociudad.com.ar/autogestion/x%3D%3D", "", "s3cret", true},
		"alice@mail.com:hunter2": {"", "alice@mail.com", "hunter2", true},
		"bob@x.com:p:a:ss":       {"", "bob@x.com", "p:a:ss", true},
		"░▒▓█ BANNER": {ok: false},
		"":                                {ok: false},
		"just some prose here":            {ok: false},
		"random:token:here":               {ok: false},
		"https://site.com nopassword":     {ok: false},
		"site.com:onlyonevalue":           {ok: false},
	}
	for line, w := range cases {
		_, u, l, p, ok := parseLine(line)
		if ok != w.ok || (ok && (u != w.url || l != w.login || p != w.pw)) {
			panic(fmt.Sprintf("FAIL %q -> (%q,%q,%q,%v) want (%q,%q,%q,%v)", line, u, l, p, ok, w.url, w.login, w.pw, w.ok))
		}
	}
	// scheme capture
	schemeOf := func(ln string) string { s, _, _, _, _ := parseLine(ln); return s }
	if schemeOf("https://x.com:u:p") != "https" || schemeOf("ftp://x.com:u:p") != "ftp" ||
		schemeOf("android://h@com.x.y/|u|p") != "android" || schemeOf("x.com:u:p") != "" ||
		schemeOf("u@x.com:p") != "" || schemeOf("www.foo.comhttps://x.com:u:p") != "" {
		panic("scheme capture broken")
	}
	if tldOf("https", "www.hites.cl", "u") != "cl" || tldOf("", "site.com.ar", "u") != "ar" ||
		tldOf("", "", "u@foo.cl") != "cl" || tldOf("android", "com.facebook.orca", "u") != "" ||
		tldOf("ftp", "1.2.3.4", "u") != "" {
		panic("tld derivation broken")
	}
	if ipClass("192.168.1.1") != "rfc1918" || ipClass("10.1.2.3") != "rfc1918" ||
		ipClass("192.0.2.5") != "rfc5737" || ipClass("127.0.0.1") != "rfc5735" ||
		ipClass("fd00::1") != "rfc4193" || ipClass("172.32.0.1") != "" ||
		ipClass("8.8.8.8") != "" || ipClass("example.com") != "" {
		panic("ipClass detection broken")
	}
	if host("WWW.Site.com/a") != "www.site.com" || host("host.cl:8043") != "host.cl" {
		panic("host() lower/path/port-strip broken")
	}
	if cleaner.Replace("pa\tss\r\nword") != "password" {
		panic("cleaner broken")
	}
	// UTF-16 LE of "a.com:u:p" with BOM -> decoded + detected
	le := []byte{0xFF, 0xFE}
	for _, c := range "a.com:u:p" {
		le = append(le, byte(c), 0)
	}
	if decodeUTF16(le, false) != "a.com:u:p" || detectEncoding(le) != "utf16le" {
		panic("utf16 decode/detect broken")
	}
	fmt.Println("OK  go parseLine matches python parse_line v3 spec (15 cases) + host + cleaner")
}
