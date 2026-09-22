"""EYENET v1 HTTP API — explicit registration surface.

Per API_PLAN §9.1, this file is the canonical map of every endpoint:
- Each `api_<verb>_<noun>.py` exports `router: APIRouter` with exactly one operation.
- This file imports them, then mounts them on `v1_router` with shared `/v1` prefix.
- Shared error envelopes are declared once on the parent so they propagate into
  every operation's generated OpenAPI for free.

Adding an endpoint = two new lines here. Locator function: a bug citing
`/v1/linkages/{id}/confirm` maps to `eyenet/api/v1/linkages/api_confirm_linkage.py`.
"""

from __future__ import annotations

from fastapi import APIRouter

# === actors ===
from eyenet.api.v1.actors.api_get_actor import router as actors_get_router
from eyenet.api.v1.actors.api_get_neighbors import router as actors_neighbors_router
from eyenet.api.v1.actors.api_get_timeline import router as actors_timeline_router
from eyenet.api.v1.actors.api_list_observations import router as actors_observations_router

# === attachments ===
from eyenet.api.v1.attachments.api_access_file import router as attachments_access_router
from eyenet.api.v1.attachments.api_get_manifest import router as attachments_manifest_router

# === audit ===
from eyenet.api.v1.audit.api_list_anchors import router as audit_list_anchors_router
from eyenet.api.v1.audit.api_list_audit import router as audit_list_router
from eyenet.api.v1.audit.api_list_file_access import router as audit_file_access_by_hash_router
from eyenet.api.v1.audit.api_list_file_access_by_user import (
    router as audit_file_access_by_user_router,
)
from eyenet.api.v1.audit.api_verify_audit import router as audit_verify_router

# === auth ===
from eyenet.api.v1.auth.api_get_me import router as auth_me_router
from eyenet.api.v1.auth.api_list_tokens import router as auth_list_tokens_router
from eyenet.api.v1.auth.api_login import router as auth_login_router
from eyenet.api.v1.auth.api_login_verify import router as auth_login_verify_router
from eyenet.api.v1.auth.api_logout import router as auth_logout_router
from eyenet.api.v1.auth.api_mfa_disable import router as auth_mfa_disable_router
from eyenet.api.v1.auth.api_mfa_enroll import router as auth_mfa_enroll_router
from eyenet.api.v1.auth.api_mfa_verify_enroll import router as auth_mfa_verify_enroll_router
from eyenet.api.v1.auth.api_mint_token import router as auth_mint_token_router
from eyenet.api.v1.auth.api_refresh import router as auth_refresh_router
from eyenet.api.v1.auth.api_register_signing_key import router as auth_register_signing_key_router
from eyenet.api.v1.auth.api_revoke_token import router as auth_revoke_token_router
from eyenet.api.v1.auth.api_signing_key_challenge import (
    router as auth_signing_key_challenge_router,
)
from eyenet.api.v1.auth.api_stream_token import router as auth_stream_token_router

# === candidates (M9.D3 discovery triage) ===
from eyenet.api.v1.candidates.api_approve_candidate import router as candidates_approve_router
from eyenet.api.v1.candidates.api_get_candidate import router as candidates_get_router
from eyenet.api.v1.candidates.api_list_candidates import router as candidates_list_router
from eyenet.api.v1.candidates.api_park_candidate import router as candidates_park_router
from eyenet.api.v1.candidates.api_reject_candidate import router as candidates_reject_router
from eyenet.api.v1.candidates.api_retry_candidate import router as candidates_retry_router

# === cases ===
from eyenet.api.v1.cases.api_add_collaborator import router as cases_add_collaborator_router
from eyenet.api.v1.cases.api_add_member import router as cases_add_member_router
from eyenet.api.v1.cases.api_archive_case import router as cases_archive_router
from eyenet.api.v1.cases.api_bulk_add_members import router as cases_bulk_add_members_router
from eyenet.api.v1.cases.api_bulk_remove_members import router as cases_bulk_remove_members_router
from eyenet.api.v1.cases.api_close_case import router as cases_close_router
from eyenet.api.v1.cases.api_create_case import router as cases_create_router
from eyenet.api.v1.cases.api_get_case import router as cases_get_router
from eyenet.api.v1.cases.api_get_seed_roots import router as cases_get_seed_roots_router
from eyenet.api.v1.cases.api_list_cases import router as cases_list_router
from eyenet.api.v1.cases.api_list_collaborators import router as cases_list_collaborators_router
from eyenet.api.v1.cases.api_list_members import router as cases_list_members_router
from eyenet.api.v1.cases.api_promote_seed_root import router as cases_promote_seed_root_router
from eyenet.api.v1.cases.api_remove_member import router as cases_remove_member_router
from eyenet.api.v1.cases.api_reopen_case import router as cases_reopen_router
from eyenet.api.v1.cases.api_replace_seed_roots import router as cases_replace_seed_roots_router
from eyenet.api.v1.cases.api_revoke_collaborator import (
    router as cases_revoke_collaborator_router,
)
from eyenet.api.v1.cases.api_update_case import router as cases_update_router

# === clearance ===
from eyenet.api.v1.clearance.api_get_grant import router as clearance_get_grant_router
from eyenet.api.v1.clearance.api_grant_clearance import router as clearance_grant_router
from eyenet.api.v1.clearance.api_list_grants import router as clearance_list_grants_router
from eyenet.api.v1.clearance.api_revoke_grant import router as clearance_revoke_grant_router

# === collectors (M9.D2 discovery) ===
from eyenet.api.v1.collectors.api_collector_health import router as collectors_health_router
from eyenet.api.v1.collectors.api_create_collector import router as collectors_create_router
from eyenet.api.v1.collectors.api_delete_collector import router as collectors_delete_router
from eyenet.api.v1.collectors.api_get_collector import router as collectors_get_router
from eyenet.api.v1.collectors.api_list_collectors import router as collectors_list_router
from eyenet.api.v1.collectors.api_list_memberships import router as collectors_memberships_router
from eyenet.api.v1.collectors.api_start_collector import router as collectors_start_router
from eyenet.api.v1.collectors.api_stop_collector import router as collectors_stop_router
from eyenet.api.v1.collectors.api_update_collector import router as collectors_update_router

# === documents (M10 classifier) ===
from eyenet.api.v1.documents.api_access_document import router as documents_access_router
from eyenet.api.v1.documents.api_get_document_manifest import (
    router as documents_manifest_router,
)
from eyenet.api.v1.documents.api_upload_document import router as documents_upload_router

# === graph ===
from eyenet.api.v1.graph.api_get_stats import router as graph_stats_router
from eyenet.api.v1.graph.api_search import router as graph_search_router

# === health / metrics ===
from eyenet.api.v1.health.api_healthz import router as health_live_router
from eyenet.api.v1.health.api_readyz import router as health_ready_router

# === identities ===
from eyenet.api.v1.identities.api_burn_identity import router as identities_burn_router
from eyenet.api.v1.identities.api_claim_identity import router as identities_claim_router
from eyenet.api.v1.identities.api_freeze_all import router as identities_freeze_all_router
from eyenet.api.v1.identities.api_freeze_identity import router as identities_freeze_router
from eyenet.api.v1.identities.api_release_identity import router as identities_release_router

# === linkages ===
from eyenet.api.v1.linkages.api_confirm_linkage import router as linkages_confirm_router
from eyenet.api.v1.linkages.api_get_linkage import router as linkages_get_router
from eyenet.api.v1.linkages.api_list_linkages import router as linkages_list_router
from eyenet.api.v1.linkages.api_reject_linkage import router as linkages_reject_router
from eyenet.api.v1.linkages.api_suspect_linkage import router as linkages_suspect_router

# === meta (gated OpenAPI schema, §12.5) ===
from eyenet.api.v1.meta.api_openapi import router as meta_openapi_router
from eyenet.api.v1.metrics.api_metrics import router as health_metrics_router

# === panic ===
from eyenet.api.v1.panic.api_panic import router as control_panic_router

# === personas ===
from eyenet.api.v1.personas.api_get_persona import router as personas_get_router
from eyenet.api.v1.personas.api_list_members import router as personas_members_router
from eyenet.api.v1.personas.api_merge_persona import router as personas_merge_router
from eyenet.api.v1.personas.api_split_persona import router as personas_split_router

# === reclassify ===
from eyenet.api.v1.reclassify.api_reclassify_attachment import (
    router as reclassify_attachment_router,
)
from eyenet.api.v1.reclassify.api_reclassify_document import (
    router as reclassify_document_router,
)
from eyenet.api.v1.reclassify.api_reclassify_observation import (
    router as reclassify_observation_router,
)
from eyenet.api.v1.schemas.errors import ProblemDetail

# === sources (M9.D1 discovery) ===
from eyenet.api.v1.sources.api_add_source_domain import router as sources_add_domain_router
from eyenet.api.v1.sources.api_create_source import router as sources_create_router
from eyenet.api.v1.sources.api_get_bridge_summary import router as sources_bridge_summary_router
from eyenet.api.v1.sources.api_get_source import router as sources_get_router
from eyenet.api.v1.sources.api_list_source_domains import router as sources_list_domains_router
from eyenet.api.v1.sources.api_list_sources import router as sources_list_router
from eyenet.api.v1.sources.api_remove_source_domain import router as sources_remove_domain_router
from eyenet.api.v1.sources.api_update_source import router as sources_update_router
from eyenet.api.v1.sources.api_update_source_domain import router as sources_update_domain_router

# === stream ===
from eyenet.api.v1.stream.api_stream_all import router as stream_all_router
from eyenet.api.v1.stream.api_stream_audit import router as stream_audit_router
from eyenet.api.v1.stream.api_stream_control import router as stream_control_router
from eyenet.api.v1.stream.api_stream_linkages import router as stream_linkages_router
from eyenet.api.v1.stream.api_stream_personas import router as stream_personas_router
from eyenet.api.v1.system.api_get_system import router as system_stats_router

# Shared error envelopes — propagate into every operation's OpenAPI.
# Per §7, every 4xx/5xx returns application/problem+json → ProblemDetail.
_PROBLEM = {"model": ProblemDetail}
SHARED_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {**_PROBLEM, "description": "Missing or invalid credentials"},
    403: {**_PROBLEM, "description": "Insufficient scope"},
    404: {**_PROBLEM, "description": "Resource not found"},
    409: {**_PROBLEM, "description": "Conflict (idempotency replay mismatch)"},
    422: {**_PROBLEM, "description": "Request payload failed validation"},
    429: {**_PROBLEM, "description": "Rate limited"},
    503: {**_PROBLEM, "description": "Audit / storage / bus unavailable"},
}

v1_router = APIRouter(prefix="/v1", responses=SHARED_RESPONSES)

# --- mount order mirrors the API_PLAN §9.1 tree ---

# auth
v1_router.include_router(auth_login_router)
v1_router.include_router(auth_login_verify_router)
v1_router.include_router(auth_refresh_router)
v1_router.include_router(auth_logout_router)
v1_router.include_router(auth_me_router)
v1_router.include_router(auth_mfa_enroll_router)
v1_router.include_router(auth_mfa_verify_enroll_router)
v1_router.include_router(auth_mfa_disable_router)
v1_router.include_router(auth_list_tokens_router)
v1_router.include_router(auth_mint_token_router)
v1_router.include_router(auth_revoke_token_router)
v1_router.include_router(auth_stream_token_router)
v1_router.include_router(auth_signing_key_challenge_router)
v1_router.include_router(auth_register_signing_key_router)

# actors
v1_router.include_router(actors_get_router)
v1_router.include_router(actors_neighbors_router)
v1_router.include_router(actors_observations_router)
v1_router.include_router(actors_timeline_router)

# personas
v1_router.include_router(personas_get_router)
v1_router.include_router(personas_members_router)
v1_router.include_router(personas_merge_router)
v1_router.include_router(personas_split_router)

# linkages
v1_router.include_router(linkages_list_router)
v1_router.include_router(linkages_get_router)
v1_router.include_router(linkages_confirm_router)
v1_router.include_router(linkages_reject_router)
v1_router.include_router(linkages_suspect_router)

# documents (M10 classifier)
v1_router.include_router(documents_upload_router)
v1_router.include_router(documents_manifest_router)
v1_router.include_router(documents_access_router)

# graph
v1_router.include_router(graph_stats_router)
v1_router.include_router(graph_search_router)

# audit
v1_router.include_router(audit_list_router)
v1_router.include_router(audit_verify_router)
v1_router.include_router(audit_file_access_by_hash_router)
v1_router.include_router(audit_file_access_by_user_router)
v1_router.include_router(audit_list_anchors_router)

# attachments
v1_router.include_router(attachments_manifest_router)
v1_router.include_router(attachments_access_router)

# reclassify (§4.9 — sensitivity-tier promotion)
v1_router.include_router(reclassify_observation_router)
v1_router.include_router(reclassify_attachment_router)
v1_router.include_router(reclassify_document_router)

# cases (§4.10 — investigation primitives)
v1_router.include_router(cases_list_router)
v1_router.include_router(cases_create_router)
v1_router.include_router(cases_get_router)
v1_router.include_router(cases_update_router)
v1_router.include_router(cases_close_router)
v1_router.include_router(cases_reopen_router)
v1_router.include_router(cases_archive_router)
v1_router.include_router(cases_list_members_router)
v1_router.include_router(cases_add_member_router)
v1_router.include_router(cases_bulk_add_members_router)
v1_router.include_router(cases_bulk_remove_members_router)
v1_router.include_router(cases_remove_member_router)
v1_router.include_router(cases_list_collaborators_router)
v1_router.include_router(cases_add_collaborator_router)
v1_router.include_router(cases_revoke_collaborator_router)
# cases — seed roots (§4.12 discovery loop, M9.D4)
v1_router.include_router(cases_get_seed_roots_router)
v1_router.include_router(cases_replace_seed_roots_router)
v1_router.include_router(cases_promote_seed_root_router)

# clearance
v1_router.include_router(clearance_list_grants_router)
v1_router.include_router(clearance_grant_router)
v1_router.include_router(clearance_get_grant_router)
v1_router.include_router(clearance_revoke_grant_router)

# collectors (§4.11 — discovery fleet, M9.D2).
# /collectors/health MUST precede /collectors/{collector_id} (literal vs UUID).
v1_router.include_router(collectors_health_router)
v1_router.include_router(collectors_list_router)
v1_router.include_router(collectors_create_router)
v1_router.include_router(collectors_get_router)
v1_router.include_router(collectors_update_router)
v1_router.include_router(collectors_start_router)
v1_router.include_router(collectors_stop_router)
v1_router.include_router(collectors_memberships_router)
v1_router.include_router(collectors_delete_router)

# sources + source domains (§4.13 — discovery storage surface, M9.D1)
v1_router.include_router(sources_list_router)
v1_router.include_router(sources_create_router)
v1_router.include_router(sources_get_router)
v1_router.include_router(sources_update_router)
v1_router.include_router(sources_list_domains_router)
v1_router.include_router(sources_add_domain_router)
v1_router.include_router(sources_update_domain_router)
v1_router.include_router(sources_remove_domain_router)
v1_router.include_router(sources_bridge_summary_router)

# candidates (§4.12 — discovery triage queue, M9.D3)
v1_router.include_router(candidates_list_router)
v1_router.include_router(candidates_get_router)
v1_router.include_router(candidates_approve_router)
v1_router.include_router(candidates_reject_router)
v1_router.include_router(candidates_park_router)
v1_router.include_router(candidates_retry_router)

# identities + panic
v1_router.include_router(identities_claim_router)
v1_router.include_router(identities_release_router)
v1_router.include_router(identities_freeze_router)
v1_router.include_router(identities_burn_router)
v1_router.include_router(identities_freeze_all_router)
v1_router.include_router(control_panic_router)

# stream
v1_router.include_router(stream_linkages_router)
v1_router.include_router(stream_personas_router)
v1_router.include_router(stream_audit_router)
v1_router.include_router(stream_control_router)
v1_router.include_router(stream_all_router)

# health + metrics
v1_router.include_router(health_live_router)
v1_router.include_router(health_ready_router)
v1_router.include_router(health_metrics_router)
v1_router.include_router(system_stats_router)

# meta — gated OpenAPI schema (replaces the anonymous built-in, §12.5)
v1_router.include_router(meta_openapi_router)


__all__ = ["v1_router"]
