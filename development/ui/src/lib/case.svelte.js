// Active-case context. Cases behave like tenants: entering a case scopes the
// whole Cases workspace to it. Universal reactive state (Svelte 5 runes in a module).
import { CASES } from './data.js';

export const caseCtx = $state({ active: null }); // active = a CASES entry, or null

export function enterCase(caseId) {
  caseCtx.active = CASES.find((c) => c.caseId === caseId) ?? null;
}
export function exitCase() {
  caseCtx.active = null;
}
