// DevTools "Copy as cURL" -> Netscape cookies.txt, in the browser.
//
// Why this beats hand-building a jar: the browser sends EVERY cookie — HttpOnly
// (sid, mybbuser) AND in-memory session cookies — in each request's Cookie
// header. `document.cookie` can't see HttpOnly; the request header has them all.
// One Copy-as-cURL, no per-cookie work. Ported from poc-browser/cookies_from_curl.py.
//
// Run the self-check: `bun src/lib/curl-cookies.js`

/** Pull the cookie string out of a cURL blob / "Cookie:" header / raw "k=v; k=v". */
export function extractCookieString(blob) {
  let m = blob.match(/(?:-b|--cookie)\s+(['"])(.*?)\1/s); // curl -b '...' / --cookie '...'
  if (m) return m[2];
  m = blob.match(/-H\s+(['"])\s*cookie:\s*(.*?)\1/is); // -H 'cookie: ...' (name case-insensitive)
  if (m) return m[2];
  m = blob.match(/^\s*cookie:\s*(.+)$/im); // a bare "Cookie: ..." header line
  if (m) return m[1].trim();
  if (blob.includes('=') && blob.includes(';')) return blob.trim(); // already "k=v; k=v"
  return '';
}

/** Strip scheme + path from a URL, leaving the bare host (the cookie domain). */
export function hostFromUrl(url) {
  return (url || '').replace(/^https?:\/\//, '').split('/')[0].trim();
}

/** Emit Netscape cookies.txt lines for a "k=v; k=v" string scoped to `host`. */
export function toNetscape(cookieString, host, ttlDays = 365) {
  host = hostFromUrl(host);
  if (!host) throw new Error('set the Forum base URL first (it is the cookie host)');
  const expiry = Math.floor(Date.now() / 1000) + 86400 * ttlDays; // keep the warmed session alive
  const lines = ['# Netscape HTTP Cookie File', '# generated from Copy-as-cURL by eyenet-fe'];
  let n = 0;
  for (let part of cookieString.split(';')) {
    part = part.trim();
    const i = part.indexOf('='); // split on FIRST = — cookie values may contain =
    if (i < 0) continue;
    const name = part.slice(0, i).trim();
    const val = part.slice(i + 1).trim();
    if (!name) continue;
    // host-only cookie (col2 FALSE), path /, secure FALSE (onion is plain http).
    lines.push(`${host}\tFALSE\t/\tFALSE\t${expiry}\t${name}\t${val}`);
    n++;
  }
  if (n === 0) throw new Error('parsed 0 cookies — is the Cookie header in the blob?');
  return lines.join('\n');
}

/** cURL blob + host -> { text: Netscape jar, count }. Throws with a usable message. */
export function curlToNetscape(blob, host, ttlDays = 365) {
  const cs = extractCookieString(blob);
  if (!cs) throw new Error("no Cookie found — paste a 'Copy as cURL', a 'Cookie:' header, or 'k=v; k=v'");
  const text = toNetscape(cs, host, ttlDays);
  const count = text.split('\n').filter((l) => l && !l.startsWith('#')).length;
  return { text, count };
}

if (import.meta.main) {
  const curl =
    "curl 'http://x.onion/index.php' -X GET -H 'User-Agent: Mozilla/5.0' " +
    "-H 'cookie: mybb[lastvisit]=1790; sid=139d23; mybbuser=768203_qGqIb' --compressed";
  const expect = (got, want, msg) => {
    if (got !== want) throw new Error(`${msg}: got ${JSON.stringify(got)}`);
  };
  expect(extractCookieString(curl), 'mybb[lastvisit]=1790; sid=139d23; mybbuser=768203_qGqIb', 'curl -H');
  expect(extractCookieString('Cookie: a=1; b=2'), 'a=1; b=2', 'bare header');
  expect(extractCookieString('a=1; b=2'), 'a=1; b=2', 'raw pairs');
  expect(extractCookieString("curl 'http://x' -b 'z=9; q=8'"), 'z=9; q=8', '-b flag');
  const { text, count } = curlToNetscape('sid=139d23; mybbuser=768203', 'pwnfrm7rbf.onion');
  expect(count, 2, 'cookie count');
  const row = text.split('\n').find((l) => l.includes('\tsid\t')).split('\t');
  if (!(row[0] === 'pwnfrm7rbf.onion' && row[5] === 'sid' && row[6] === '139d23')) {
    throw new Error('row shape: ' + JSON.stringify(row));
  }
  expect(hostFromUrl('http://pwnfrm7rbf.onion/Forum-Databases'), 'pwnfrm7rbf.onion', 'hostFromUrl');
  console.log('OK  curl-cookies: cURL/header/raw extraction + Netscape emit');
}
