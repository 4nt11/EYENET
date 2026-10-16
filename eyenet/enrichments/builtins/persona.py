# SPDX-License-Identifier: AGPL-3.0-or-later
"""Persona-source enrichments. A persona is a cluster of actors, so almost anything
you can enrich from an actor you can enrich from a persona - evaluated over the UNION
of its member actors (via ``persona_membership``), edging DIRECTLY persona -> neighbour
(it bypasses the member actors unless you ask for them explicitly).

- actors    : the member actors themselves
- messages  : messages any member authored
- artifacts : infrastructure artifacts mentioned in members' messages
- wallets   : those artifacts narrowed to crypto-wallet kinds
- groups    : groups any member is active in
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlmodel import col, select

from eyenet.enrichments.base import LocalSQLEnrichment
from eyenet.models import (
    InfrastructureArtifactMentionTable,
    InfrastructureArtifactTable,
    MessageTable,
    PersonaMembershipTable,
)

if TYPE_CHECKING:
    from uuid import UUID

_M = MessageTable
_MN = InfrastructureArtifactMentionTable
_IA = InfrastructureArtifactTable
_PM = PersonaMembershipTable

_WALLET_KINDS = ("wallet_btc", "wallet_eth", "wallet_xmr", "wallet_tron")


def _members(src_id: UUID) -> Any:
    """Scalar subquery: the persona's member actor ids."""
    return select(_PM.actor_id).where(_PM.persona_id == src_id)


class PersonaActors(LocalSQLEnrichment):
    src_type = "persona"
    name = "actors"
    output_type = "actor"
    edge_kind = "member"

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        return select(_PM.actor_id).where(_PM.persona_id == src_id), col(_PM.actor_id)


class PersonaMessages(LocalSQLEnrichment):
    src_type = "persona"
    name = "messages"
    output_type = "message"
    edge_kind = "authored"

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        return select(_M.id).where(col(_M.actor_id).in_(_members(src_id))), col(_M.id)


class PersonaArtifacts(LocalSQLEnrichment):
    src_type = "persona"
    name = "artifacts"
    output_type = "artifact"
    edge_kind = "uses_infra"

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        return (
            select(_MN.artifact_id)
            .join(_M, col(_MN.message_id) == col(_M.id))
            .where(col(_M.actor_id).in_(_members(src_id)))
            .distinct()
        ), col(_MN.artifact_id)


class PersonaWallets(LocalSQLEnrichment):
    src_type = "persona"
    name = "wallets"
    output_type = "artifact"
    edge_kind = "uses_infra"

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        return (
            select(_MN.artifact_id)
            .join(_M, col(_MN.message_id) == col(_M.id))
            .join(_IA, col(_MN.artifact_id) == col(_IA.id))
            .where(col(_M.actor_id).in_(_members(src_id)), col(_IA.kind).in_(_WALLET_KINDS))
            .distinct()
        ), col(_MN.artifact_id)


class PersonaGroups(LocalSQLEnrichment):
    src_type = "persona"
    name = "groups"
    output_type = "group"
    edge_kind = "active_in"

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        return (
            select(_M.group_id).where(col(_M.actor_id).in_(_members(src_id))).distinct(),
            col(_M.group_id),
        )
