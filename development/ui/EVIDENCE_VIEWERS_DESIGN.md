# Evidence Viewers - design pass

Design for the three "Evidence" cluster screens: **documents**, **attachments**,
**reclassify**. These are the deep ones because evidence exists to be *observed*:
they need real viewers (text, code, images, PDF, bytes) and they sit on the most
safety-critical backend surface (clearance-gated, signed, journaled, promote-only).

All backend facts below are code-grounded (file:line). Frontend stack for this
layer: **Bits UI** (accessible Dialog/Tabs/Tooltip/Popover, styled with our tokens),
**@lucide/svelte** (icons, 1.5px), **highlight.js** (leak-dump code/JSON, custom
theme in our 3 tokens), **pdf.js** and **docx-preview** staged (lazy-loaded, only
when we wire real bytes).

No em dashes anywhere. Three colors on black. Red stays reserved for the top tier,
tamper, and destructive actions.

---

## 0. Backend readiness (this drives what the UI can do NOW)

| Capability | Route | Method | Scope / gate | Status |
|---|---|---|---|---|
| Upload document | `/v1/documents` | POST (raw body) | `write:documents` | **LIVE** (202 provisional) |
| Get document content | `/v1/documents/{id}` | GET | (read + tier) | **MISSING - not built** |
| Attachment manifest | `/v1/attachments/{blob_id}/manifest` | GET | tier gate | **LIVE for NORMAL only** |
| Attachment bytes | `/v1/attachments/{blob_id}/access` | POST | signed + tier gate | **LIVE for NORMAL only** |
| Reclassify observation | `/v1/observations/{observation_id}/reclassify` | POST | `admin:reclassify` | **STUB (501)** |
| Reclassify attachment | `/v1/attachments/{blob_id}/reclassify` | POST | `admin:reclassify` | **STUB (501)** |
| File-access exoneration (by hash) | `/v1/audit/file-access?content_hash=` | GET | `read:audit` | **STUB (501)** |
| File-access log (by user) | `/v1/audit/file-access/by-user` | GET | `read:audit` | **STUB (501)** |

Stub citations (for the worktree work):
- Reclassify observation: `eyenet/api/v1/reclassify/api_reclassify_observation.py:14-24` (`NotImplementedError`, M9.0 skeleton).
- Reclassify attachment: `eyenet/api/v1/reclassify/api_reclassify_attachment.py:14-24`.
- Exoneration by hash: `eyenet/api/v1/audit/api_list_file_access.py:18-21`.
- File-access by user: `eyenet/api/v1/audit/api_list_file_access_by_user.py:21-26`.
- Clearance gate (manifest): `eyenet/api/v1/attachments/api_get_manifest.py:51-55` (non-NORMAL fails closed 403, PHASE-6 stub).
- Clearance gate (access): `eyenet/api/v1/attachments/api_access_file.py:96-98`.
- No document-content GET exists: only `eyenet/api/v1/documents/api_upload_document.py` is present.

**Consequence for the UI:** every viewer ships as a faithful mock now, with each
blocked capability marked by a small `stub` chip (accent, never red) that names the
exact route it is waiting on. When you implement a route on your worktree, we flip
that chip off and wire it. Nothing in the UI pretends a stub is live.

---

## 1. The sensitivity model (shared across all three)

`SensitivityTier` (`eyenet/contracts/enums.py:176-187`), exactly 3, low to high:

- `normal` - default at ingest
- `restricted`
- `classified`

Rules the UI must reflect:
- **Promote-only, never demote.** `effective_tier = COALESCE(operator_tier_override, classifier_tier)`, and both the endpoint and a DB CHECK reject anything not strictly higher (`observation.py:34-37`, `document.py:44`, `message.py:53`).
- The classifier owns `classifier_tier` (immutable lower bound). The operator can only raise via `operator_tier_override`.
- `ClearanceScope` (`enums.py:189-203`): `read:restricted`, `read:classified`, `admin:reclassify`, `admin:case`. Grant-only, <=90 day expiry, mandatory reason. These never sit in a role baseline.

**Tier rendering convention (locks the palette):**
- `normal` -> neutral badge, calm.
- `restricted` -> accent (purple) badge.
- `classified` -> red badge. This is the one place red signals tier.
- Effective vs classifier: when an override is present, show `classifier -> effective` with the override called out (mirrors the reclassify story).

---

## 2. Shared components to build (Evidence cluster)

Built once, reused by all three viewers:

1. **`TierBadge`** - wraps our `Badge` with the tier->tone map above; optional `classifier -> effective` promoted form.
2. **`EvidenceViewer`** (Bits UI `Tabs`) - the content pane with tabs: `Extracted text` | `Findings` | `Metadata` | `Raw`. Which tabs appear depends on subject kind (documents get all four; attachments get Metadata + Raw only, see below).
3. **`CodeBlock`** (highlight.js) - detects language (`highlightAuto`) for unlabeled leak dumps; pretty-prints JSON first; custom theme using only `--accent-text` + text shades, red reserved. Lazy-imports `highlight.js`.
4. **`FindingsList`** - renders `classification.regex_matches` / `presidio_matches` / `review_flags` with masked spans (the backend already masks `matched_text`).
5. **`AccessDialog`** (Bits UI `Dialog`, focus-trapped) - the signed byte-access acknowledgment flow (reason, viewing context, case refs, signature status). Governs the attachment viewer.
6. **`StubChip`** - small accent chip, `stub · POST /v1/...`, tooltip (Bits UI `Tooltip`) explaining what is blocked.
7. Lucide icons: `file-text`, `paperclip`, `lock`, `shield`, `download`, `maximize-2`, `arrow-up` (promote). 1.5px stroke.

pdf.js and docx-preview are **not** components yet; they mount inside `EvidenceViewer`'s `Raw` tab only once byte access is wired.

---

## 3. Documents viewer (`/documents`)

**Data:** `DocumentTable` (`eyenet/models/document.py:36-62`): `id`, `sha256` (host hash of raw bytes), `mime`, `size_bytes`, `doc_kind`, `filename`, `storage_uri`, `extracted_text` (retained, tier-gated), `embedded_meta` (JSON, attacker-controlled, sanitized), `classification` (redacted JSON), `review_required`, `uploaded_by_user_id`, `uploaded_at`, `ingested_at`, `classifier_tier`, `operator_tier_override`.

**Layout:** master-detail.
- Left: documents table (filename, mime, tier badge, `review_required` flag, uploaded_at).
- Right: `EvidenceViewer` for the selected doc:
  - **Extracted text** tab: `extracted_text` in a mono reading pane. If the doc is JSON/code (common in leaks), route through `CodeBlock`. This is the authoritative evidence, not a rendered Word/PDF page.
  - **Findings** tab: the classifier story from `classification` JSON. Per-stage provenance rows (`extraction` / `regex` / `presidio` / `metadata`) each with `tier_floor`; regex + presidio matches with masked spans and offsets; review flags (`possible_over_classification`, `llm_higher_tier`, `llm_unavailable`) with `corroborated`. A small pipeline strip showing the MAX aggregation: `extraction | regex | presidio -> effective tier`, and a "never auto-lowered" note.
  - **Metadata** tab: `embedded_meta` (clearly labeled "document-claimed, untrusted") + forensic facts (sha256, size, mime, doc_kind, uploaded_by, timestamps).
  - **Raw** tab: staged. Shows a placeholder until a document-content/bytes route exists; pdf.js mounts here for PDFs.
- Header: `TierBadge` (classifier vs effective), Upload action (POST /v1/documents), and a **Reclassify** action that opens the promote dialog (see 5).

**Classifier "why this tier" is the star.** The Findings tab is what makes this forensic and not a file browser. Everything it renders comes from the already-redacted `classification` payload (`classification_audit_payload`, `eyenet/classifier/aggregate/_audit.py:21-86`); the UI never sees raw spans.

**Blocked now:** no `GET /v1/documents/{id}` exists. Mock shows full behavior; the doc list + content are mock data. `StubChip: GET /v1/documents/{id} (to build)`. Upload is live (202 provisional -> settles off-path); the UI can show the provisional `classified` state and a "settling" hint.

---

## 4. Attachments viewer (`/attachments`)

The byte-level evidence surface. This is the two-step, signed, journaled flow, and it is the most security-shaped screen.

**Data:** `AttachmentTable` (`eyenet/models/message.py:45-65`): `id`, `message_id`, `kind`, `mime`, `size_bytes`, `sha256`, `filename`, `storage_uri`, `classifier_tier`, `operator_tier_override`. Note: attachments have **no** `extracted_text` / `classification` (unlike documents), so the viewer has fewer tabs.

**The access flow (the core UX):**
1. **Manifest** (`GET .../manifest`, `FileManifest`): `blob_id`, `content_hash`, `content_size`, `content_mime`, `tier`, `source_subject_id`, `source_subject_kind` (`observation` | `message`), `collected_at`, `access_nonce` (single-use, 60s TTL), `nonce_expires_at`. No journal row is written by the manifest. The UI shows the manifest immediately (metadata, no bytes).
2. **Access** (`POST .../access`, `FileAccessAcknowledgment`): the `AccessDialog` collects `reason` (min 16 chars), `viewing_context`, `case_refs` (>=1 required for classified rows), and drives the `operator_signature` (`ed25519:<b64>`) over the canonical body. Returns **raw bytes** (StreamingResponse) but only after the journal row is durably written. Failures the UI must handle: 409 hash mismatch, 401 signature/freshness/chain, 404 if `storage_uri` is null, 403 clearance stub.
3. Only after bytes arrive does `EvidenceViewer` render them: image (`<img>`), PDF (pdf.js, staged), or the **hex/byte view** for arbitrary blobs. `FileServedVia` (`inline_json` | `attachment_stream` | `thumbnail_only`) picks the render path.

**Journal awareness:** every access writes a signed, hash-chained `FileAccessJournalTable` row (in `audit.db`). The viewer shows an "access is logged and signed" affordance before serving, and links to the access history for that `content_hash`.

**Blocked now:**
- Non-NORMAL tiers fail closed 403 (clearance gating is PHASE-6). So today the viewer only truly serves `normal` blobs; restricted/classified show the gate with `StubChip: clearance gating (PHASE-6)`.
- Exoneration / access-history endpoints are stubs (`GET /v1/audit/file-access`, `.../by-user`). The "who accessed this byte-range" panel renders against mock data with a `StubChip` until those land. Wire shape `FileAccessExoneration` (`content_hash`, `query_time`, `journal_head_at_query`, `accesses[]`, `exoneration_signature`; empty `accesses` = signed non-access assertion) is defined and ready to render.

---

## 5. Reclassify (`/reclassify`)

Promote-only tier changes for observations and attachments. Both endpoints are
**stubs today**, but the wire contract is fixed, so we can build the whole UX now
and wire on flip.

**Contract:**
- `ReclassificationRequest` (`eyenet/api/v1/schemas/reclassify.py:25-57`): `new_tier` (server rejects `normal` and anything not strictly higher than current effective tier), `reason` (min 32 chars), `viewing_context?`, `operator_signature` (ed25519; a JWT alone is 403, a signed body is mandatory), `case_refs[]`.
- `ReclassificationResult` (:60-86): `subject_id`, `subject_kind` (`observation` | `attachment`), `classifier_tier` (immutable lower bound), `operator_tier_override`, `effective_tier`, `prior_effective_tier`, `audit_event_id`, `reclassified_at`, `grant_id` (the `admin:reclassify` grant used).

**Layout:** a focused promote form, reachable both as its own screen and as the Reclassify action inside the document/attachment viewers.
- Subject block: what is being promoted (id, kind), current `classifier_tier` and `effective_tier`.
- Tier selector: only tiers **strictly above** the current effective tier are selectable (UI mirrors the server CHECK). `normal` never offered.
- Required: `reason` (min 32, enforced client-side), optional `viewing_context`, `case_refs`, and a clear signature step (the promote button stays disabled until a signed body exists, same pattern as the panic trigger).
- Result: show `prior -> new` effective tier, `audit_event_id`, `grant_id`.
- A permanent note: "Promote-only. This cannot be undone from the console. The classifier floor never moves."

**Blocked now:** `StubChip: POST /v1/observations/{id}/reclassify (501)` and the attachment variant. The form validates and previews the result against the known contract; submit is disabled with the stub tooltip until the route is live.

---

## 6. What you (backend, on your worktree) unblock, in priority order

1. **`GET /v1/documents/{id}`** (and probably a list) returning the redacted `classification` + `extracted_text` gated by effective tier. Nothing about the Documents viewer is real without a read path.
2. **Reclassify** endpoints (`observations` + `attachments`) - contract is done, just the handler + audit emit + grant check.
3. **Clearance gating** (PHASE-6) on manifest + access, so restricted/classified bytes can actually be served to cleared operators.
4. **Exoneration queries** (`file-access` by hash + by user) - `FileAccessExoneration` is defined; these make the journal legible in the UI.

As each lands, ping me the route and I flip its `StubChip` and wire the fetch. I stay
on main; you keep your worktree.

---

## 7. Build order on the frontend (main)

1. Shared components (`TierBadge`, `CodeBlock` + hljs theme, `EvidenceViewer` tabs via Bits UI, `StubChip`, `AccessDialog`, `FindingsList`, hex view).
2. Documents viewer (richest, exercises Findings + CodeBlock).
3. Reclassify (form + promote dialog, reused by the viewers).
4. Attachments viewer (access flow + journal, most stubs).
5. pdf.js + docx-preview only when byte access is wired.
