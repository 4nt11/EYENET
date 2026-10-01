# SPDX-License-Identifier: AGPL-3.0-or-later
"""`ForumCollectorStub` - fixture-driven forum envelope producer.

Mirror of `MatrixCollectorStub`, but instead of replaying a synthetic JSONL it
runs the REAL engine parser (selected by ``engine`` via
:func:`eyenet.collectors.forum.get_parser`) over a saved thread page and emits
one :class:`RawMessageEnvelope` per parsed post. This is what proves a parser
feeds the ingest path + classifier without live network - for ANY engine
(MyBB, XenForo, ...), which is also how an operator replays saved pages offline.

Like the Matrix stub it does not store bodies: it is a synthetic envelope
producer for factory/bus tests. Body storage belongs to the real collector.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from eyenet.collectors.base.skeleton import CollectorSkeleton
from eyenet.collectors.forum import ParsedPost, get_parser, posted_at_to_utc
from eyenet.contracts._base import TraceContext
from eyenet.contracts.actor import actor_key
from eyenet.contracts.bus import Bus
from eyenet.contracts.enums import SourceKind
from eyenet.contracts.identity_pool import IdentityPool
from eyenet.contracts.raw_message import RawMessageEnvelope, subject_for
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.propagation import current_traceparent


class ForumCollectorStub(CollectorSkeleton):
    """Emits forum raw-message envelopes parsed from a saved thread (any engine)."""

    def __init__(
        self,
        *,
        bus: Bus,
        storage: BaseRepository,
        pool: IdentityPool,
        identity_name: str,
        thread_path: Path | None = None,
        thread_id: str = "0",
        board: str = "forum.invalid",
        engine: str = "mybb",
    ) -> None:
        super().__init__(
            bus=bus,
            storage=storage,
            pool=pool,
            identity_name=identity_name,
            source_kind=SourceKind.FORUM,
        )
        self._thread_id = thread_id
        self._board = board
        parser = get_parser(engine)  # raises on unknown engine (fail loud at boot)
        self._posts: list[ParsedPost] = []
        if thread_path and thread_path.exists():
            self._posts = parser.parse_thread(thread_path.read_text(encoding="utf-8"))

    async def tick(self) -> None:
        if not self._posts:
            return
        post = self._posts.pop(0)
        env = self._build_envelope(post)
        await self.publisher.publish(subject_for(SourceKind.FORUM, self.instance_id), env)
        self._record_emission()

    def _build_envelope(self, post: ParsedPost) -> RawMessageEnvelope:
        body = post.body_text
        body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
        # Board-scope the userid: MyBB slugs ("admin") collide across boards, so
        # the actor join key must carry the board, not just the source_kind.
        platform_userid = f"{self._board}|{post.author_username}"
        # Normalize to UTC engine-agnostically: aware (XenForo) is CONVERTED,
        # naive (MyBB board-local) gets UTC attached (the per-source tz offset is
        # a calibration knob). Fall back to now() when a relative date left
        # posted_at unparsed.
        sent_at = posted_at_to_utc(post.posted_at) or datetime.now(tz=UTC)
        return RawMessageEnvelope(
            source=SourceKind.FORUM,
            instance_id=self.instance_id,
            evidence_ref=f"forum:{self._board}:{self._thread_id}:{post.pid}",
            actor_key=actor_key(SourceKind.FORUM, platform_userid),
            platform_groupid=self._thread_id,
            platform_msgid=post.pid,
            sent_at_source=sent_at,
            collected_at=datetime.now(tz=UTC),
            length_chars=len(body),
            length_words=len(body.split()),
            body_sha256=body_sha256,
            is_forward=False,
            has_attachment=False,
            trace_context=TraceContext(
                traceparent=current_traceparent() or _zero_traceparent(),
            ),
        )


def _zero_traceparent() -> str:
    return "00-" + "0" * 32 + "-" + "0" * 16 + "-00"


# Back-compat: the stub was MyBB-only before engine dispatch. Existing callers
# (CLI, tests) keep working; the default engine is still "mybb".
MyBBCollectorStub = ForumCollectorStub

__all__ = ["ForumCollectorStub", "MyBBCollectorStub"]
