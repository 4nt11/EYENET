// Cross-cutting UI shell state (Svelte 5 runes in a module, same shape as the
// other *.svelte.js stores). Right now this is just the NavRail collapse toggle,
// persisted per-browser. localStorage throws in some privacy modes, so every
// access is guarded.
const NAV_KEY = 'eyenet_nav_collapsed';
const PAL_KEY = 'eyenet_palette_collapsed';

function loadFlag(key) {
  try {
    return localStorage.getItem(key) === '1';
  } catch {
    return false;
  }
}

function saveFlag(key, on) {
  try {
    localStorage.setItem(key, on ? '1' : '0');
  } catch {
    // best-effort persistence only; the in-memory toggle still works
  }
}

export const ui = $state({
  navCollapsed: loadFlag(NAV_KEY),
  paletteCollapsed: loadFlag(PAL_KEY)
});

export function toggleNav() {
  ui.navCollapsed = !ui.navCollapsed;
  saveFlag(NAV_KEY, ui.navCollapsed);
}

export function togglePalette() {
  ui.paletteCollapsed = !ui.paletteCollapsed;
  saveFlag(PAL_KEY, ui.paletteCollapsed);
}
