// Documents workspace state. List from GET /v1/documents (metadata only);
// selecting one fetches GET /v1/documents/{id}/manifest for the redacted
// classification (FindingsList) + full metadata. The manifest is clearance-gated
// (403 if the caller can't read the effective tier) and appends NO journal row.
//
// Field-name note: the LIST rows use sha256/mime/size_bytes; the MANIFEST uses
// content_hash/content_mime/content_size. Both are mapped here.
//
// The signed byte/extracted-text access + reclassify flows need client-side
// Ed25519 operator signing (M9.B2) which is not wired yet — the page renders
// those as disabled affordances.
import { apiGet } from './api.js';

const short = (id) => (id ? id.slice(0, 8) : '');
const shortTs = (ts) => (ts ? ts.replace('T', ' ').replace(/\..*$/, 'Z') : '·');

// Sensitivity tier → badge tone. normal→neutral, restricted→purple, classified→red.
export const tierTone = (t) =>
  t === 'classified' ? 'critical' : t === 'restricted' ? 'high' : 'neutral';

function mapDocument(d) {
  return {
    id: d.document_id,
    idShort: short(d.document_id),
    filename: d.filename || '(unnamed)',
    docKind: d.doc_kind ?? '',
    mime: d.mime,
    sizeBytes: d.size_bytes,
    sha256: d.sha256,
    classifierTier: d.classifier_tier,
    tier: d.tier,
    reviewRequired: d.review_required,
    uploaded: shortTs(d.uploaded_at),
    ingested: shortTs(d.ingested_at)
  };
}

export const documentCtx = $state({ list: [], loaded: false, error: null });

export async function loadDocuments() {
  try {
    const page = await apiGet('/v1/documents?limit=200', { auth: true });
    documentCtx.list = page.items.map(mapDocument);
    documentCtx.error = null;
  } catch (e) {
    documentCtx.error = e.message ?? String(e);
    documentCtx.list = [];
  } finally {
    documentCtx.loaded = true;
  }
}

export const documentView = $state({ id: null, manifest: null, loading: false, error: null });

let detailSeq = 0;

export async function loadDocumentManifest(id) {
  const mine = ++detailSeq;
  documentView.loading = true;
  documentView.id = id;
  // Clear stale manifest immediately so a fast row switch never shows the prior
  // document's findings/metadata while the new fetch is in flight.
  documentView.manifest = null;
  documentView.error = null;
  try {
    const m = await apiGet(`/v1/documents/${id}/manifest`, { auth: true });
    if (mine !== detailSeq) return;
    documentView.manifest = m;
    documentView.error = null;
  } catch (e) {
    if (mine !== detailSeq) return;
    documentView.error =
      e.status === 403
        ? 'Clearance required to view this document’s metadata.'
        : (e.message ?? String(e));
  } finally {
    if (mine === detailSeq) documentView.loading = false;
  }
}
