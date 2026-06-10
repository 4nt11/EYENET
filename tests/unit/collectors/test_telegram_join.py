# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the telethon-free E5 join core (eyenet/collectors/telegram/_join.py).

The live telethon issuance in real.py is coverage-omitted; this is where the
join state machine (joined / failed / ban→quarantine) is validated, with no
network and no telethon import.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.bus.memory import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.collectors.telegram._join import (
    CollectorJoinHandler,
    JoinAction,
    JoinOutcome,
    artifact_state_for_error,
    candidate_match_forms,
    classify_join_error,
    parse_invite_hash,
    select_join_action,
)
from eyenet.contracts.enums import (
    ArtifactSubjectKind,
    ArtifactValidationState,
    CandidateState,
    GroupAccessKind,
    GroupKind,
    IdentityRole,
    IdentityState,
    JoinedVia,
    MentionKind,
    SourceKind,
)
from eyenet.contracts.supervisor import JoinGroupCommand
from eyenet.services.discovery.scout_graduation import ScoutGraduationService
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 6, tzinfo=UTC)
_ACTOR = UUID("00000000-0000-0000-0000-0000000000a1")


class _FakePool:
    """Duck-typed IdentityPool recording release() calls."""

    def __init__(self) -> None:
        self.released: list[tuple[str, IdentityState]] = []

    async def release(self, name: str, *, new_state: IdentityState) -> None:
        self.released.append((name, new_state))


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _handler(storage: BaseRepository, pool: _FakePool, *, identity_name: str = "scout"):
    bus = MemoryBus()
    audit = AuditEmitter(BusEnvelopePublisher(bus), storage, service="test", instance_id="t0")
    return CollectorJoinHandler(
        storage=storage,
        audit=audit,
        pool=pool,  # type: ignore[arg-type]  — duck-typed fake
        scout_graduation=ScoutGraduationService(bus=bus, storage=storage),
        identity_name=identity_name,
    )


async def _source(storage: BaseRepository) -> UUID:
    return await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )


async def _collector(storage: BaseRepository, src: UUID) -> UUID:
    ident = await storage.create_identity(name="id_c", source_id=src, session_path="/c")
    row = await storage.create_collector(
        instance_name="collector-c",
        kind=SourceKind.TELEGRAM,
        source_id=src,
        identity_id=ident.id,
        config={},
        created_at=_NOW,
        created_by_user_id=uuid4(),
    )
    return row.id


async def _joining_candidate(storage: BaseRepository, src: UUID, collector_id: UUID) -> UUID:
    cand, _ = await storage.record_candidate_mention(
        source_id=src,
        platform_groupid="@target",
        observed_by_collector_id=collector_id,
        observed_in_group_id=uuid4(),
        seed_root_id=uuid4(),
        depth_from_root=1,
        mention_evidence_ref="e1",
        mention_kind=MentionKind.USERNAME_MENTION,
        mentioned_at_source=_NOW,
        mentioned_at_ingest=_NOW,
        mentioning_actor_id=_ACTOR,
        kind_hint=GroupKind.CHANNEL,
    )
    await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.QUEUED)
    await storage.transition_candidate(
        candidate_id=cand.id, to_state=CandidateState.APPROVED, assigned_collector_id=collector_id
    )
    await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.JOINING)
    return cand.id


# -- classifier --------------------------------------------------------------


def test_classify_ban_vs_fail() -> None:
    assert classify_join_error("UserBannedInChannelError") is JoinOutcome.BANNED
    assert classify_join_error("FloodWaitError") is JoinOutcome.FAILED
    assert classify_join_error("InviteHashExpiredError") is JoinOutcome.FAILED
    # unknown errors are NOT treated as bans (we don't burn a scout we don't understand)
    assert classify_join_error("SomeBrandNewTelethonError") is JoinOutcome.FAILED


def test_classify_join_request_sent_is_requested() -> None:
    # M9.E5.5: an approval-gated group accepted the request → pending, not failed.
    assert classify_join_error("InviteRequestSentError") is JoinOutcome.REQUESTED


# -- E5.5 pure helpers: select_join_action / parse_invite_hash / artifact_state


def test_select_join_action_per_kind() -> None:
    assert select_join_action(GroupAccessKind.PUBLIC_IDENTIFIER) is JoinAction.PUBLIC
    assert select_join_action(GroupAccessKind.INVITE_LINK) is JoinAction.INVITE_HASH
    # invite-link-only scope: everything else is unsupported for now.
    for kind in (
        GroupAccessKind.QR_CODE,
        GroupAccessKind.DIRECT_INVITE,
        GroupAccessKind.PAID_SUBSCRIPTION,
        GroupAccessKind.ACCESS_BLOCKED,
        GroupAccessKind.RESTRICTED_OTHER,
    ):
        assert select_join_action(kind) is JoinAction.UNSUPPORTED


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://t.me/+AbC_dEf-123", "AbC_dEf-123"),
        ("t.me/+xyz789", "xyz789"),
        ("https://t.me/joinchat/AAAAAEHbEkabc", "AAAAAEHbEkabc"),
        ("tg://join?invite=Qw3rTy", "Qw3rTy"),
        # public handles / channel links carry no invite token → None
        ("https://t.me/publicchannel", None),
        ("@publichandle", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_invite_hash(value: str | None, expected: str | None) -> None:
    assert parse_invite_hash(value) == expected


def test_artifact_state_for_error_maps_dead_links_only() -> None:
    assert artifact_state_for_error("InviteHashExpiredError") is ArtifactValidationState.EXPIRED
    assert artifact_state_for_error("InviteHashInvalidError") is ArtifactValidationState.REVOKED
    # errors that aren't the link's fault leave the artifact untouched
    assert artifact_state_for_error("FloodWaitError") is None
    assert artifact_state_for_error("UserBannedInChannelError") is None


# -- candidate_match_forms (Defect 2 case-fold + pure event-form gen) --------


def test_candidate_match_forms_lowercases_username() -> None:
    # Defect 2: discovery stores f"@{username.lower()}"; the event path must
    # match it. @CryptoNews → @cryptonews (and the bare lowercased handle).
    forms = candidate_match_forms(-1001234567890, "CryptoNews")
    assert "@cryptonews" in forms
    assert "cryptonews" in forms
    # raw mixed-case must NOT leak through
    assert "@CryptoNews" not in forms


def test_candidate_match_forms_numeric_and_stripped() -> None:
    # both the signed chat_id and the -100-stripped raw id are present
    forms = candidate_match_forms(-1001234567890, None)
    assert str(-1001234567890) in forms
    assert "1234567890" in forms


def test_candidate_match_forms_empty_username_no_broad_form() -> None:
    # A falsy username must NOT produce a broad-matching empty "@" / "" form.
    forms = candidate_match_forms(-1001234567890, None)
    assert "@" not in forms
    assert "" not in forms
    forms_empty = candidate_match_forms(-1001234567890, "")
    assert "@" not in forms_empty
    assert "" not in forms_empty


# -- finalize_joined ---------------------------------------------------------


async def test_finalize_joined_writes_group_membership_and_transition(
    storage: BaseRepository,
) -> None:
    src = await _source(storage)
    coll = await _collector(storage, src)
    cand = await _joining_candidate(storage, src, coll)
    scout_id = uuid4()
    cmd = JoinGroupCommand(
        candidate_id=cand, platform_groupid="@target", scout_identity_id=scout_id
    )

    handler = _handler(storage, _FakePool())
    group_id = await handler.finalize_joined(
        cmd, source_uuid=src, collector_id=coll, kind=GroupKind.CHANNEL, title="Target", now=_NOW
    )

    row = await storage.get_candidate(cand)
    assert row.state is CandidateState.JOINED
    assert row.resulting_group_id == group_id

    memberships = await storage.list_active_memberships(collector_id=coll)
    assert len(memberships) == 1
    assert memberships[0].group_id == group_id
    assert memberships[0].joined_via is JoinedVia.CANDIDATE
    assert memberships[0].joined_via_candidate_id == cand

    events = [r.event for r in await storage.all_audit()]
    assert "eyenet.audit.candidate.joined" in events


# -- fail_candidate ----------------------------------------------------------


async def test_fail_candidate_transitions_and_records_reason(storage: BaseRepository) -> None:
    src = await _source(storage)
    coll = await _collector(storage, src)
    cand = await _joining_candidate(storage, src, coll)
    cmd = JoinGroupCommand(candidate_id=cand, platform_groupid="@target", scout_identity_id=uuid4())

    handler = _handler(storage, _FakePool())
    await handler.fail_candidate(cmd, reason="FloodWaitError: wait 42s")

    row = await storage.get_candidate(cand)
    assert row.state is CandidateState.FAILED
    assert row.rejection_reason == "FloodWaitError: wait 42s"
    events = [r.event for r in await storage.all_audit()]
    assert "eyenet.audit.candidate.failed" in events


# -- quarantine_on_ban -------------------------------------------------------


async def test_quarantine_on_ban_fails_candidate_and_burns_scout(storage: BaseRepository) -> None:
    src = await _source(storage)
    coll = await _collector(storage, src)
    cand = await _joining_candidate(storage, src, coll)
    scout = await storage.create_identity(
        name="scout",
        source_id=src,
        session_path="/s",
        role=IdentityRole.SCOUT,
        state=IdentityState.IN_USE,
    )
    cmd = JoinGroupCommand(
        candidate_id=cand, platform_groupid="@target", scout_identity_id=scout.id
    )

    pool = _FakePool()
    handler = _handler(storage, pool, identity_name="scout")
    await handler.quarantine_on_ban(cmd)

    # candidate failed (never reached joined)
    row = await storage.get_candidate(cand)
    assert row.state is CandidateState.FAILED
    assert row.rejection_reason == "banned_on_join"

    # scout burned + quarantined in the DB
    burned = await storage.get_identity(scout.id)
    assert burned.state is IdentityState.BURNED
    assert burned.role is IdentityRole.QUARANTINE

    # file pool reflects the burn (so restart-recovery can't re-offer it)
    assert pool.released == [("scout", IdentityState.BURNED)]

    events = [r.event for r in await storage.all_audit()]
    assert "eyenet.audit.candidate.failed" in events
    assert "eyenet.audit.identity.burned" in events


# -- mark_join_requested (E5.5) ----------------------------------------------


async def test_mark_join_requested_transitions_and_audits(storage: BaseRepository) -> None:
    src = await _source(storage)
    coll = await _collector(storage, src)
    cand = await _joining_candidate(storage, src, coll)
    cmd = JoinGroupCommand(candidate_id=cand, platform_groupid="@target", scout_identity_id=uuid4())

    handler = _handler(storage, _FakePool())
    await handler.mark_join_requested(cmd)

    row = await storage.get_candidate(cand)
    assert row.state is CandidateState.REQUESTED
    assert row.rejection_reason == "join_request_sent"
    events = [r.event for r in await storage.all_audit()]
    assert "eyenet.audit.candidate.join_requested" in events


# -- record_artifact_validation (E5.5) ---------------------------------------


async def _candidate_invite_artifact(storage: BaseRepository, src: UUID, coll: UUID) -> UUID:
    cand = await _joining_candidate(storage, src, coll)
    art = await storage.add_group_access_artifact(
        subject_kind=ArtifactSubjectKind.CANDIDATE,
        group_id=None,
        candidate_id=cand,
        kind=GroupAccessKind.INVITE_LINK,
        value="https://t.me/+dead",
        discovered_at_ingest=_NOW,
    )
    return art.id


async def test_record_artifact_validation_writes_dead_link_state(
    storage: BaseRepository,
) -> None:
    src = await _source(storage)
    coll = await _collector(storage, src)
    artifact_id = await _candidate_invite_artifact(storage, src, coll)

    handler = _handler(storage, _FakePool())
    await handler.record_artifact_validation(artifact_id, "InviteHashExpiredError", now=_NOW)

    art = await storage.get_group_access_artifact(artifact_id)
    assert art is not None
    assert art.validation_state is ArtifactValidationState.EXPIRED
    assert art.last_validated_at == _NOW


async def test_record_artifact_validation_noop_for_non_link_error(
    storage: BaseRepository,
) -> None:
    src = await _source(storage)
    coll = await _collector(storage, src)
    artifact_id = await _candidate_invite_artifact(storage, src, coll)

    handler = _handler(storage, _FakePool())
    # A flood-wait says nothing about the link — leave the artifact untouched.
    await handler.record_artifact_validation(artifact_id, "FloodWaitError", now=_NOW)

    art = await storage.get_group_access_artifact(artifact_id)
    assert art is not None
    assert art.validation_state is ArtifactValidationState.UNVERIFIED
    assert art.last_validated_at is None


# -- confirm_requested_membership (E5.6) -------------------------------------


async def _requested_candidate(storage: BaseRepository, src: UUID, collector_id: UUID) -> UUID:
    """A candidate driven JOINING→REQUESTED (the approval-gated pending state)."""
    cand = await _joining_candidate(storage, src, collector_id)
    await storage.transition_candidate(
        candidate_id=cand,
        to_state=CandidateState.REQUESTED,
        rejection_reason="join_request_sent",
    )
    return cand


async def test_confirm_requested_opens_one_membership_and_joins(
    storage: BaseRepository,
) -> None:
    src = await _source(storage)
    coll = await _collector(storage, src)
    cand = await _requested_candidate(storage, src, coll)

    handler = _handler(storage, _FakePool())
    confirmed = await handler.confirm_requested_membership(cand, now=_NOW)

    assert confirmed is True
    row = await storage.get_candidate(cand)
    assert row.state is CandidateState.JOINED
    assert row.resulting_group_id is not None

    memberships = await storage.list_active_memberships(collector_id=coll)
    assert len(memberships) == 1
    assert memberships[0].group_id == row.resulting_group_id
    assert memberships[0].joined_via is JoinedVia.CANDIDATE
    assert memberships[0].joined_via_candidate_id == cand

    events = [r.event for r in await storage.all_audit()]
    assert "eyenet.audit.candidate.joined" in events


async def test_confirm_requested_is_idempotent(storage: BaseRepository) -> None:
    src = await _source(storage)
    coll = await _collector(storage, src)
    cand = await _requested_candidate(storage, src, coll)

    handler = _handler(storage, _FakePool())
    first = await handler.confirm_requested_membership(cand, now=_NOW)
    # A redundant event + probe firing for the same candidate must no-op: the
    # state is now JOINED, so exactly one membership + one audit survive.
    second = await handler.confirm_requested_membership(cand, now=_NOW)

    assert first is True
    assert second is False
    memberships = await storage.list_active_memberships(collector_id=coll)
    assert len(memberships) == 1
    joined_events = [
        r.event for r in await storage.all_audit() if r.event == "eyenet.audit.candidate.joined"
    ]
    assert len(joined_events) == 1


@pytest.mark.parametrize(
    "terminal",
    [CandidateState.FAILED, CandidateState.PARKED],
)
async def test_confirm_requested_noop_on_terminal_state(
    storage: BaseRepository, terminal: CandidateState
) -> None:
    src = await _source(storage)
    coll = await _collector(storage, src)
    cand = await _requested_candidate(storage, src, coll)
    await storage.transition_candidate(candidate_id=cand, to_state=terminal)

    handler = _handler(storage, _FakePool())
    confirmed = await handler.confirm_requested_membership(cand, now=_NOW)

    assert confirmed is False
    row = await storage.get_candidate(cand)
    assert row.state is terminal
    assert await storage.list_active_memberships(collector_id=coll) == []


async def test_confirm_requested_noop_on_non_requested_state(storage: BaseRepository) -> None:
    # A JOINING candidate (not yet REQUESTED) must not be flipped by this path.
    src = await _source(storage)
    coll = await _collector(storage, src)
    cand = await _joining_candidate(storage, src, coll)

    handler = _handler(storage, _FakePool())
    confirmed = await handler.confirm_requested_membership(cand, now=_NOW)

    assert confirmed is False
    row = await storage.get_candidate(cand)
    assert row.state is CandidateState.JOINING


async def test_confirm_requested_noop_on_missing_candidate(storage: BaseRepository) -> None:
    handler = _handler(storage, _FakePool())
    confirmed = await handler.confirm_requested_membership(uuid4(), now=_NOW)
    assert confirmed is False


async def test_confirm_requested_requested_without_collector_raises(
    storage: BaseRepository,
) -> None:
    # reviewer-3: a REQUESTED candidate with assigned_collector_id is None is a
    # data-invariant violation — confirm must raise a TYPED RuntimeError (not an
    # assert, §4.1) rather than open a membership against an unknown collector.
    src = await _source(storage)
    cand, _ = await storage.record_candidate_mention(
        source_id=src,
        platform_groupid="@target",
        observed_by_collector_id=uuid4(),
        observed_in_group_id=uuid4(),
        seed_root_id=uuid4(),
        depth_from_root=1,
        mention_evidence_ref="e_nocoll",
        mention_kind=MentionKind.USERNAME_MENTION,
        mentioned_at_source=_NOW,
        mentioned_at_ingest=_NOW,
        mentioning_actor_id=_ACTOR,
        kind_hint=GroupKind.CHANNEL,
    )
    # Drive to REQUESTED WITHOUT ever assigning a collector.
    await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.QUEUED)
    await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.APPROVED)
    await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.JOINING)
    await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.REQUESTED)

    handler = _handler(storage, _FakePool())
    with pytest.raises(RuntimeError, match="assigned_collector_id"):
        await handler.confirm_requested_membership(cand.id, now=_NOW)


async def test_confirm_requested_dual_caller_opens_exactly_one(
    storage: BaseRepository,
) -> None:
    # Defect 4: the event path and the probe can both fire for one approval. The
    # CAS guarantees exactly ONE membership + ONE candidate.joined audit, and the
    # loser returns False (does NOT crash, does NOT open a second membership).
    src = await _source(storage)
    coll = await _collector(storage, src)
    cand = await _requested_candidate(storage, src, coll)

    handler = _handler(storage, _FakePool())
    first = await handler.confirm_requested_membership(cand, now=_NOW)
    second = await handler.confirm_requested_membership(cand, now=_NOW)

    assert first is True
    assert second is False
    memberships = await storage.list_active_memberships(collector_id=coll)
    assert len(memberships) == 1
    joined = [
        r.event for r in await storage.all_audit() if r.event == "eyenet.audit.candidate.joined"
    ]
    assert len(joined) == 1


async def test_confirm_requested_resolved_groupid_overrides_joinchat(
    storage: BaseRepository,
) -> None:
    # Defect 1: an invite-link candidate is stored as joinchat:<hash>, which can
    # never be a real group id. The probe resolves the live chat and passes the
    # real numeric id through resolved_platform_groupid; the membership + group
    # must open against THAT, not the joinchat placeholder.
    src = await _source(storage)
    coll = await _collector(storage, src)
    cand, _ = await storage.record_candidate_mention(
        source_id=src,
        platform_groupid="joinchat:AAAAAEHbEkabc",
        observed_by_collector_id=coll,
        observed_in_group_id=uuid4(),
        seed_root_id=uuid4(),
        depth_from_root=1,
        mention_evidence_ref="e_joinchat",
        mention_kind=MentionKind.INVITE_LINK,
        mentioned_at_source=_NOW,
        mentioned_at_ingest=_NOW,
        mentioning_actor_id=_ACTOR,
        kind_hint=GroupKind.CHANNEL,
    )
    await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.QUEUED)
    await storage.transition_candidate(
        candidate_id=cand.id, to_state=CandidateState.APPROVED, assigned_collector_id=coll
    )
    await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.JOINING)
    await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.REQUESTED)

    handler = _handler(storage, _FakePool())
    confirmed = await handler.confirm_requested_membership(
        cand.id,
        kind=GroupKind.CHANNEL,
        title="Resolved Group",
        resolved_platform_groupid="4964840750",
        now=_NOW,
    )
    assert confirmed is True
    row = await storage.get_candidate(cand.id)
    assert row.state is CandidateState.JOINED
    # The group was opened against the RESOLVED numeric id, not the joinchat:
    # placeholder. upsert_group is idempotent on (source, platform_groupid), so a
    # repeat upsert of the resolved id returns the SAME group id, while a repeat
    # of the joinchat: placeholder would return a DIFFERENT (new) id.
    resolved_again = await storage.upsert_group(
        source_id=src,
        platform_groupid="4964840750",
        kind=GroupKind.CHANNEL,
        title="Resolved Group",
        seen_at=_NOW,
    )
    assert resolved_again == row.resulting_group_id
    joinchat_again = await storage.upsert_group(
        source_id=src,
        platform_groupid="joinchat:AAAAAEHbEkabc",
        kind=GroupKind.CHANNEL,
        title=None,
        seen_at=_NOW,
    )
    assert joinchat_again != row.resulting_group_id


# -- FIX 1: self-healing compensation on the JOINED writeback ----------------


async def test_confirm_requested_rolls_back_when_membership_open_fails(
    storage: BaseRepository,
) -> None:
    # FIX 1: the CAS commits REQUESTED→JOINED FIRST, then open_membership runs as
    # a separate awaited write. If it raises, the candidate would otherwise be
    # permanently JOINED with no membership and no audit, and a retry CAS-loses.
    # The compensation must roll JOINED→REQUESTED, open NO membership, re-raise —
    # and a later call with working storage must then succeed cleanly.
    src = await _source(storage)
    coll = await _collector(storage, src)
    cand = await _requested_candidate(storage, src, coll)

    handler = _handler(storage, _FakePool())

    real_open = storage.open_membership
    calls = {"n": 0}

    async def _flaky_open(**kwargs: object) -> UUID:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated main.db write failure")
        return await real_open(**kwargs)  # type: ignore[arg-type]

    storage.open_membership = _flaky_open  # type: ignore[method-assign,assignment]

    with pytest.raises(RuntimeError, match=r"simulated main\.db write failure"):
        await handler.confirm_requested_membership(cand, now=_NOW)

    # Compensated: rolled back to REQUESTED (the state field gates retry), not
    # left JOINED; no membership; no candidate.joined audit emitted. The CAS
    # rollback restores STATE only — resulting_group_id is a harmless stale
    # pointer (the next successful join overwrites it; clearing it would require
    # a CAS change the primitive deliberately doesn't support).
    row = await storage.get_candidate(cand)
    assert row.state is CandidateState.REQUESTED
    assert await storage.list_active_memberships(collector_id=coll) == []
    joined = [
        r.event for r in await storage.all_audit() if r.event == "eyenet.audit.candidate.joined"
    ]
    assert joined == []

    # A second call (storage now healthy) self-heals: opens EXACTLY one membership.
    confirmed = await handler.confirm_requested_membership(cand, now=_NOW)
    assert confirmed is True
    row = await storage.get_candidate(cand)
    assert row.state is CandidateState.JOINED
    memberships = await storage.list_active_memberships(collector_id=coll)
    assert len(memberships) == 1


async def test_confirm_requested_keeps_membership_when_audit_emit_fails(
    storage: BaseRepository,
) -> None:
    # FIX 1: open_membership is the durable evidence; if audit.emit raises AFTER
    # membership succeeded, do NOT roll back. Membership EXISTS, candidate stays
    # JOINED, the error is raised (a missing audit is a lesser, logged
    # inconsistency — never a reason to discard a real join).
    src = await _source(storage)
    coll = await _collector(storage, src)
    cand = await _requested_candidate(storage, src, coll)

    handler = _handler(storage, _FakePool())

    async def _boom(**kwargs: object) -> None:
        raise RuntimeError("simulated audit.db emit failure")

    handler._audit.emit = _boom  # type: ignore[method-assign,assignment]

    with pytest.raises(RuntimeError, match=r"simulated audit\.db emit failure"):
        await handler.confirm_requested_membership(cand, now=_NOW)

    # Membership row exists; candidate stays JOINED (NOT rolled back).
    row = await storage.get_candidate(cand)
    assert row.state is CandidateState.JOINED
    memberships = await storage.list_active_memberships(collector_id=coll)
    assert len(memberships) == 1
    assert memberships[0].joined_via is JoinedVia.CANDIDATE
    # The audit never landed (emit raised before writing).
    joined = [
        r.event for r in await storage.all_audit() if r.event == "eyenet.audit.candidate.joined"
    ]
    assert joined == []
