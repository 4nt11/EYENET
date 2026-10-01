// Link defanging + triple-click-to-open guard for reader message bodies.
//
// Reader content is threat-actor material: a raw {@html} link would let a stray
// click send the operator's console straight to hostile infrastructure. So
// every link is DEFANGED at render (href removed, target stashed in data-url)
// and only fires on a deliberate triple-click: 1st click reveals the URL, 2nd
// arms, 3rd opens in a new tab with no referrer. Auto-resets after 6s.
//
// Shared by the full reader (reader/group) and the category reader
// (reader/category) so the two never diverge on how they neutralize links.
import DOMPurify from 'dompurify';

// A `forum:BOARD/...` evidence ref carries the board host, so relative links in
// the body can be resolved to absolute (otherwise they would point at us).
export const boardOf = (ref) => (ref && ref.startsWith('forum:') ? ref.split(':')[1] : '');

// Sanitize (XSS), then defang: resolve relative hrefs against the board, move
// the target to data-url, drop href/target so a stray click does nothing.
export function prepare(html, board) {
  const cleaned = DOMPurify.sanitize(html ?? '');
  if (typeof DOMParser === 'undefined') return cleaned; // SSR/prerender guard
  const doc = new DOMParser().parseFromString(cleaned, 'text/html');
  for (const a of doc.querySelectorAll('a')) {
    let href = a.getAttribute('href') || '';
    if (href && !/^https?:\/\//i.test(href) && !/^mailto:/i.test(href) && board) {
      href = `https://${board}/${href.replace(/^\//, '')}`;
    }
    a.removeAttribute('href');
    a.removeAttribute('target');
    if (href) {
      a.setAttribute('data-url', href);
      a.classList.add('guarded');
    }
  }
  return doc.body.innerHTML;
}

export function resetLink(a) {
  clearTimeout(a._t);
  if (a.dataset.orig != null) a.textContent = a.dataset.orig;
  a.dataset.arm = '0';
  a.classList.remove('armed1', 'armed2');
}

// Delegated click handler: bind on the post-list container. 1st reveals, 2nd
// arms, 3rd opens. Never navigates the board from the console by accident.
export function onGuardedClick(e) {
  const a = e.target.closest('a.guarded');
  if (!a) return;
  e.preventDefault();
  const url = a.getAttribute('data-url');
  if (!url) return;
  const step = Number(a.dataset.arm || '0') + 1;
  if (step === 1) {
    a.dataset.arm = '1';
    a.dataset.orig = a.textContent;
    a.textContent = `→ ${url}`;
    a.classList.add('armed1');
    clearTimeout(a._t);
    a._t = setTimeout(() => resetLink(a), 6000);
  } else if (step === 2) {
    a.dataset.arm = '2';
    a.textContent = `⚠ open? click once more · ${url}`;
    a.classList.remove('armed1');
    a.classList.add('armed2');
    clearTimeout(a._t);
    a._t = setTimeout(() => resetLink(a), 6000);
  } else {
    window.open(url, '_blank', 'noopener,noreferrer');
    resetLink(a);
  }
}
