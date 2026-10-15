// Tuning / Indicator rules — the operator-tunable indicator-extraction ruleset.
// Wraps /v1/indicators/rules (list/create/patch/delete). Vendored defaults ship
// seeded and can be disabled but not deleted; operator-custom rules are full CRUD.
import { apiDelete, apiGet, apiPatch, apiPost } from './api.js';

// Suggested kinds for the Kind combobox (datalist). Kinds are OPEN: the server
// accepts any lowercase slug [a-z][a-z0-9_]{1,63}, so an operator can type a
// custom kind too. These are the vendored InfrastructureKind values an operator
// usually wants; ipv4/ipv6 are omitted on purpose (coded extractors, not rules).
export const INDICATOR_KINDS = [
  'handle_other_platform',
  'wallet_btc',
  'wallet_xmr',
  'wallet_eth',
  'wallet_tron',
  'pgp_key',
  'email',
  'session',
  'tox',
  'domain',
  'onion',
  'phone',
  'paste_url'
];

export const indicatorRuleCtx = $state({
  list: [],
  loaded: false,
  error: null, // list-load failure (status-aware render)
  status: 0,
  busy: false,
  error_msg: null // mutation failure (inline banner)
});

export async function loadIndicatorRules() {
  try {
    // GET returns a plain array (list[IndicatorRuleOut]), not a cursor page.
    indicatorRuleCtx.list = await apiGet('/v1/indicators/rules', { auth: true });
    indicatorRuleCtx.loaded = true;
    indicatorRuleCtx.error = null;
    indicatorRuleCtx.status = 0;
  } catch (e) {
    indicatorRuleCtx.error = e.message ?? String(e);
    indicatorRuleCtx.status = e.status ?? 0;
    indicatorRuleCtx.loaded = true;
  }
}

// Create a custom rule. A bad RE2 pattern / unknown kind is a 422 and a duplicate
// (kind, pattern) a 409 — both throw with the problem `detail` in the message.
export async function createIndicatorRule({ kind, pattern, fold_case = true, description = '', enabled = true }) {
  indicatorRuleCtx.busy = true;
  indicatorRuleCtx.error_msg = null;
  try {
    await apiPost('/v1/indicators/rules', { kind, pattern, fold_case, description, enabled }, { auth: true });
    await loadIndicatorRules();
    return true;
  } catch (e) {
    indicatorRuleCtx.error_msg = `Create failed: ${e.message ?? e}`;
    return false;
  } finally {
    indicatorRuleCtx.busy = false;
  }
}

export async function setIndicatorRuleEnabled(ruleId, enabled) {
  indicatorRuleCtx.busy = true;
  indicatorRuleCtx.error_msg = null;
  try {
    await apiPatch(`/v1/indicators/rules/${ruleId}`, { enabled }, { auth: true });
    await loadIndicatorRules();
    return true;
  } catch (e) {
    indicatorRuleCtx.error_msg = `Update failed: ${e.message ?? e}`;
    return false;
  } finally {
    indicatorRuleCtx.busy = false;
  }
}

// Delete a custom rule. Vendored rules reject with 409 (disable instead).
export async function deleteIndicatorRule(ruleId) {
  indicatorRuleCtx.busy = true;
  indicatorRuleCtx.error_msg = null;
  try {
    await apiDelete(`/v1/indicators/rules/${ruleId}`, { auth: true });
    await loadIndicatorRules();
    return true;
  } catch (e) {
    indicatorRuleCtx.error_msg = `Delete failed: ${e.message ?? e}`;
    return false;
  } finally {
    indicatorRuleCtx.busy = false;
  }
}
