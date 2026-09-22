// Attachments workspace state. List from GET /v1/attachments (metadata only);
// selecting one fetches GET /v1/attachments/{id}/manifest for source-subject +
// collected-at (the list row can't carry those — they need the parent-message
// join). Manifest is clearance-gated and appends NO journal row.
//
// Signed byte access + reclassify need client-side Ed25519 operator signing
// (M9.B2, not wired) — the page renders those as disabled affordances.
import { apiGet } from './api.js';

const short = (id) => (id ? id.slice(0, 8) : '');
const shortTs = (ts) => (ts ? ts.replace('T', ' ').replace(/\..*$/, 'Z') : '·');

export const tierTone = (t) =>
  t === 'classified' ? 'critical' : t === 'restricted' ? 'high' : 'neutral';

function mapAttachment(a) {
  return {
    id: a.blob_id,
    idShort: short(a.blob_id),
    messageId: a.message_id,
    kind: a.kind,
    mime: a.mime,
    sizeBytes: a.size_bytes,
    sha256: a.sha256,
    filename: a.filename || '(unnamed)',
    classifierTier: a.classifier_tier,
    tier: a.tier
  };
}

export const attachmentCtx = $state({ list: [], loaded: false, error: null });

export async function loadAttachments() {
  try {
    const page = await apiGet('/v1/attachments?limit=200', { auth: true });
    attachmentCtx.list = page.items.map(mapAttachment);
    attachmentCtx.error = null;
  } catch (e) {
    attachmentCtx.error = e.message ?? String(e);
    attachmentCtx.list = [];
  } finally {
    attachmentCtx.loaded = true;
  }
}

// Detail = manifest (source_subject_* + collected_at + the clearance-gated
// nonce). Base metadata is already on the row; the manifest just adds provenance.
export const attachmentView = $state({ id: null, manifest: null, loading: false, error: null });

let detailSeq = 0;

export async function loadAttachmentManifest(id) {
  const mine = ++detailSeq;
  attachmentView.loading = true;
  attachmentView.id = id;
  attachmentView.manifest = null;
  attachmentView.error = null;
  try {
    const m = await apiGet(`/v1/attachments/${id}/manifest`, { auth: true });
    if (mine !== detailSeq) return;
    attachmentView.manifest = m;
    attachmentView.error = null;
  } catch (e) {
    if (mine !== detailSeq) return;
    attachmentView.error =
      e.status === 403
        ? 'Clearance required to view this attachment’s provenance.'
        : (e.message ?? String(e));
  } finally {
    if (mine === detailSeq) attachmentView.loading = false;
  }
}
