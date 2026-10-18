// Undo/redo for the exploration graph. In-memory session history (NOT localStorage: the
// draft already handles reload survival; undo/redo is a within-session "revert that").
// Snapshot-based: each entry is a shallow copy of the {nodes, edges} arrays. Capped so a
// long session can't grow unbounded. recordHistory() is called on every structural change
// (add/remove node or edge); undo/redo swap snapshots and set a suppress flag so applying
// one does not record itself.
import { explorer } from './explorer.svelte.js';

const MAX = 50;

export const history = $state({ past: [], future: [] });

let suppress = false;
let last = null; // { sig, state } of the currently-recorded graph

const snap = () => ({ nodes: [...explorer.nodes], edges: [...explorer.edges] });
const sig = () =>
  explorer.nodes.map((n) => n.id).join(',') +
  '|' +
  explorer.edges.map((e) => e.edgeId ?? `${e.srcId}:${e.dstId}:${e.kind}`).join(',');

// Record the PRIOR state when the graph structurally changes. No-op during undo/redo and
// when nothing structural changed (positions/labels don't count).
export function recordHistory() {
  if (suppress) return;
  const s = sig();
  if (last && last.sig === s) return;
  if (last) {
    history.past.push(last.state);
    if (history.past.length > MAX) history.past.shift();
    history.future = []; // a fresh action invalidates the redo branch
  }
  last = { sig: s, state: snap() };
}

function apply(state) {
  suppress = true;
  explorer.nodes = state.nodes;
  explorer.edges = state.edges;
  last = { sig: sig(), state: snap() };
  // release after the reactive effects for this change have flushed
  queueMicrotask(() => {
    suppress = false;
  });
}

export function undoGraph() {
  if (!history.past.length) return;
  history.future.push(snap());
  apply(history.past.pop());
}

export function redoGraph() {
  if (!history.future.length) return;
  history.past.push(snap());
  apply(history.future.pop());
}

// Drop history (e.g. on loading a different graph).
export function resetHistory() {
  history.past = [];
  history.future = [];
  last = null;
}
