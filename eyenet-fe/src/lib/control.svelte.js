// Control-plane workspace state. The panic kill-switch is a single fire-and-
// forget write (POST /v1/panic, write:panic — grant-only, never in a baseline);
// its durable record is the server's hash-chained audit log, which we READ back
// via GET /v1/audit filtered to the panic subject. Nothing is logged client-side.
import { apiGet, apiPost } from './api.js';

const shortTs = (ts) => (ts ? ts.replace('T', ' ').replace(/\..*$/, 'Z') : '·');
const stripSubject = (s) => (s ? s.replace(/^eyenet\.(audit\.)?/, '') : '');
const shortId = (id) => (id ? id.slice(0, 8) : 'system');

// Static descriptive copy — what tripping panic sets in motion downstream (every
// service reacts to the bus event). Not an API-backed posture; just operator docs.
export const PANIC_EFFECTS = [
  'Stop every collector in the fleet immediately',
  'Freeze the entire identity pool',
  'Halt ingest and seal open evidence',
  'Emit a signed control-plane panic event to the audit chain'
];

export const controlLog = $state({ rows: [], loaded: false, error: null });

// The panic subject is the reliable filter — panic audit rows carry
// subject_id=None (system-wide action), so we cannot filter by subject_id.
export async function loadControlLog() {
  try {
    const page = await apiGet('/v1/audit?subject=eyenet.control.panic&limit=50', { auth: true });
    controlLog.rows = page.items.map((r) => ({
      time: shortTs(r.ts),
      actor: shortId(r.user_id),
      verb: stripSubject(r.subject),
      target: r.payload?.reason ?? '',
      detail: r.payload?.action ?? ''
    }));
    controlLog.error = null;
  } catch (e) {
    controlLog.error = e.message ?? String(e);
    controlLog.rows = [];
  } finally {
    controlLog.loaded = true;
  }
}

export const panicView = $state({ submitting: false, submitMsg: null });

// Trip the kill-switch. 202 fire-and-forget: services react to the bus event, so
// there's no durable state to reload — instead we refetch the audit log to show
// the row the write just chained. A 403 (missing write:panic grant) surfaces the
// problem+json detail honestly.
export async function tripPanic(reason) {
  panicView.submitting = true;
  panicView.submitMsg = null;
  try {
    await apiPost(
      '/v1/panic',
      { reason, confirm: 'I_UNDERSTAND' },
      { auth: true, headers: { 'Idempotency-Key': crypto.randomUUID() } }
    );
    panicView.submitMsg = 'Panic declared — control event chained to the audit log.';
    await loadControlLog();
    return true;
  } catch (e) {
    panicView.submitMsg = `Failed: ${e.message ?? e}`;
    return false;
  } finally {
    panicView.submitting = false;
  }
}
