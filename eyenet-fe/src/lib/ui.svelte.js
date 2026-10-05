// Cross-cutting UI shell state (Svelte 5 runes in a module, same shape as the
// other *.svelte.js stores). Right now this is just the NavRail collapse toggle,
// persisted per-browser. localStorage throws in some privacy modes, so every
// access is guarded.
const NAV_KEY = 'eyenet_nav_collapsed';

function loadNavCollapsed() {
  try {
    return localStorage.getItem(NAV_KEY) === '1';
  } catch {
    return false;
  }
}

export const ui = $state({
  navCollapsed: loadNavCollapsed()
});

export function toggleNav() {
  ui.navCollapsed = !ui.navCollapsed;
  try {
    localStorage.setItem(NAV_KEY, ui.navCollapsed ? '1' : '0');
  } catch {
    // best-effort persistence only; the in-memory toggle still works
  }
}
