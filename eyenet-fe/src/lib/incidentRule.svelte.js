// Tuning / Incident rules — operator RE2 rules layered on the incident classifier.
// Wraps /v1/incident-rules (list/create/patch/delete). A rule maps a compiled-RE2
// pattern match to an incident-taxonomy label with a weight; the classifier fires
// them alongside the ML heads. `label` must be a taxonomy head (server validates).
import { apiDelete, apiGet, apiPatch, apiPost } from './api.js';

export const incidentRuleCtx = $state({
  list: [],
  loaded: false,
  error: null,
  status: 0,
  busy: false,
  error_msg: null
});

export async function loadIncidentRules() {
  try {
    incidentRuleCtx.list = await apiGet('/v1/incident-rules', { auth: true });
    incidentRuleCtx.loaded = true;
    incidentRuleCtx.error = null;
    incidentRuleCtx.status = 0;
  } catch (e) {
    incidentRuleCtx.error = e.message ?? String(e);
    incidentRuleCtx.status = e.status ?? 0;
    incidentRuleCtx.loaded = true;
  }
}

// A bad RE2 pattern or a non-taxonomy label is a 422; the problem `detail` rides
// the thrown error message.
export async function createIncidentRule({ name, pattern, label, weight = 2, description = '', enabled = true }) {
  incidentRuleCtx.busy = true;
  incidentRuleCtx.error_msg = null;
  try {
    const body = { name, pattern, label, weight, enabled };
    if (description) body.description = description;
    await apiPost('/v1/incident-rules', body, { auth: true });
    await loadIncidentRules();
    return true;
  } catch (e) {
    incidentRuleCtx.error_msg = `Create failed: ${e.message ?? e}`;
    return false;
  } finally {
    incidentRuleCtx.busy = false;
  }
}

export async function setIncidentRuleEnabled(ruleId, enabled) {
  incidentRuleCtx.busy = true;
  incidentRuleCtx.error_msg = null;
  try {
    await apiPatch(`/v1/incident-rules/${ruleId}`, { enabled }, { auth: true });
    await loadIncidentRules();
    return true;
  } catch (e) {
    incidentRuleCtx.error_msg = `Update failed: ${e.message ?? e}`;
    return false;
  } finally {
    incidentRuleCtx.busy = false;
  }
}

export async function deleteIncidentRule(ruleId) {
  incidentRuleCtx.busy = true;
  incidentRuleCtx.error_msg = null;
  try {
    await apiDelete(`/v1/incident-rules/${ruleId}`, { auth: true });
    await loadIncidentRules();
    return true;
  } catch (e) {
    incidentRuleCtx.error_msg = `Delete failed: ${e.message ?? e}`;
    return false;
  } finally {
    incidentRuleCtx.busy = false;
  }
}
