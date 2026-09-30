"""EYENET CLI entrypoint."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import typer
from sqlmodel import col, select

from eyenet import __version__
from eyenet.bus import MemoryBus, NATSBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.classifier.service import ClassifierService
from eyenet.cli.config import LinkerConfig, RuntimeConfig, VerifierConfig
from eyenet.collectors.forum.real import MyBBForumCollector
from eyenet.collectors.matrix.real import MatrixCollector
from eyenet.collectors.matrix.stub import MatrixCollectorStub
from eyenet.collectors.telegram.real import TelegramCollector
from eyenet.collectors.telegram.stub import TelegramCollectorStub
from eyenet.contracts._base import TraceContext
from eyenet.contracts.attribution import (
    SUBJECT_LINKAGE_CONFIRMED,
    SUBJECT_LINKAGE_REJECTED,
    SUBJECT_LINKAGE_SUSPECTED,
    LinkageConfirmedEnvelope,
    LinkageRejectedEnvelope,
    LinkageRow,
    LinkageSuspectedEnvelope,
)
from eyenet.contracts.bus import Bus
from eyenet.contracts.enums import GroupKind, LinkageState, SourceKind
from eyenet.crypto import load_session_key
from eyenet.engine.engine import Engine
from eyenet.graph.graph import Graph
from eyenet.identity_pool import FileIdentityPool
from eyenet.identity_pool.db import DbIdentityPool
from eyenet.incidents.service import IncidentClassifierService
from eyenet.linker.infra_linker import run_infra_linker
from eyenet.linker.linker import Linker
from eyenet.models import MessageTable
from eyenet.models._base import new_uuid7
from eyenet.models.profile import ProfileTable
from eyenet.sensor.discovery import DISCOVERY_EXTRACTORS, MessageContext
from eyenet.sensor.discovery_sensor import DiscoverySensor
from eyenet.sensor.skeleton import SensorSkeleton
from eyenet.sensor.stylometric import StylometricSensor
from eyenet.service import ServiceBase, run_service
from eyenet.services.anchor_emitter import AnchorEmitter
from eyenet.services.collector_supervisor import CollectorSupervisor
from eyenet.services.geo_attribution import GeoAttributionService
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from eyenet.storage.sqlmodel_repo.messages import DiscoveryBackfillMessage
from eyenet.verifier.service import VerifierService

app = typer.Typer(
    name="eyenet",
    help="EYENET — Don't look. Observe.",
    no_args_is_help=True,
)

linkage_app = typer.Typer(name="linkage", help="Manage linkage lifecycle.", no_args_is_help=True)
app.add_typer(linkage_app, name="linkage")

from eyenet.cli.user import user_app  # noqa: E402

app.add_typer(user_app, name="user")

from eyenet.cli.document import document_app  # noqa: E402

app.add_typer(document_app, name="document")

from eyenet.cli.identity import identity_app  # noqa: E402

app.add_typer(identity_app, name="identity")


@app.callback()
def _root() -> None:
    """Root callback — forces subcommand mode even with a single command."""


@app.command()
def version() -> None:
    """Print the EYENET version."""

    typer.echo(__version__)


# -- helpers ----------------------------------------------------------------


async def _connect_bus(cfg: RuntimeConfig) -> Bus:  # pragma: no cover
    if cfg.use_memory_bus:
        return MemoryBus()
    url = cfg.nats_url
    if not url.startswith("nats://"):
        url = f"nats://{url}"
    return await NATSBus.connect(url)


def _run(
    service_factory: object, cfg: RuntimeConfig, *, tick: float = 0.0
) -> None:  # pragma: no cover
    async def _main() -> None:
        bus = await _connect_bus(cfg)
        storage = get_repository(data_dir=cfg.data_dir)
        try:
            svc: ServiceBase = service_factory(bus, storage)  # type: ignore[operator]
            await run_service(svc, tick_interval=tick)
        finally:
            await bus.close()
            await storage.close()

    asyncio.run(_main())


async def _seed_fixture(  # pragma: no cover
    storage: BaseRepository,
    records: list[dict[str, Any]],
    now: datetime,
) -> None:
    """Seed MessageTable rows from fixture records, setting reply_to_msg_id."""
    source_id = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:tg_alpha", created_at=now
    )
    group_id = await storage.upsert_group(
        source_id=source_id,
        platform_groupid="-100",
        kind=GroupKind.CHAT,
        title="Smoke",
        seen_at=now,
    )
    actor_ids: dict[str, object] = {}
    for rec in records:
        ak = rec["actor_key"]
        if ak not in actor_ids:
            actor_ids[ak] = await storage.upsert_actor(
                source_id=source_id,
                actor_key=ak,
                platform_userid=ak[-8:],
                handle=None,
                display_name=None,
                seen_at=now,
            )

    platform_to_uuid: dict[str, object] = {}
    for rec in records:
        body = rec.get("body", "")
        msgid = rec["platform_msgid"]
        ref = f"telegram:-100:{msgid}"
        sent_raw = rec.get("sent_at_source")
        sent = datetime.fromisoformat(sent_raw) if sent_raw else now
        row = MessageTable(
            id=new_uuid7(),
            source_id=source_id,
            group_id=group_id,
            actor_id=actor_ids[rec["actor_key"]],  # type: ignore[arg-type]
            platform_msgid=msgid,
            evidence_ref=ref,
            body=body,
            length_chars=len(body),
            length_words=len(body.split()),
            sent_at_source=sent,
            ingested_at=now,
        )
        await storage.put_message(row)
        platform_to_uuid[msgid] = row.id

    async with storage.session() as session:
        for rec in records:
            rkey = rec.get("reply_to_platform_msgid")
            if rkey and rkey in platform_to_uuid:
                ref = f"telegram:-100:{rec['platform_msgid']}"
                result = await session.exec(
                    select(MessageTable).where(MessageTable.evidence_ref == ref)
                )
                msg = result.first()
                if msg is not None:
                    msg.reply_to_msg_id = platform_to_uuid[rkey]
                    session.add(msg)
        await session.commit()


async def _smoke_run(  # pragma: no cover
    cfg: RuntimeConfig,
    records: list[dict[str, Any]],
    fixture: Path,
    duration: float,
    dump_profiles: bool,
) -> None:
    """Smoke-test mode: Collector+Sensor+Engine against a JSONL fixture."""
    bus = await _connect_bus(cfg)
    storage = get_repository(data_dir=cfg.data_dir)
    now = datetime.now(tz=UTC)

    try:
        await _seed_fixture(storage, records, now)

        identity_cfg = cfg.identities_path
        if identity_cfg is None:
            raise typer.BadParameter("--identities required for smoke mode")

        pool = FileIdentityPool(identity_cfg)
        sensor = StylometricSensor(bus=bus, storage=storage)
        engine = Engine(bus=bus, storage=storage)
        collector = TelegramCollectorStub(
            bus=bus,
            storage=storage,
            pool=pool,
            identity_name="tg_alpha",
            fixture_path=fixture,
        )

        sensor_task = asyncio.create_task(run_service(sensor))
        engine_task = asyncio.create_task(run_service(engine))
        collector_task = asyncio.create_task(run_service(collector, tick_interval=0.001))

        await asyncio.sleep(duration)

        await collector.shutdown()
        await sensor.shutdown()
        await engine.shutdown()
        await asyncio.gather(sensor_task, engine_task, collector_task)

        if dump_profiles:
            async with storage.session() as session:
                result = await session.exec(
                    select(ProfileTable)
                    .where(col(ProfileTable.is_current).is_(True))
                    .order_by(col(ProfileTable.derived_at))
                )
                rows = list(result.all())
            for row in rows:
                print(json.dumps(row.model_dump(), default=str))

    finally:
        await bus.close()
        await storage.close()


def _make_trace_context() -> TraceContext:
    from eyenet.telemetry.propagation import current_traceparent  # noqa: PLC0415

    tp = current_traceparent()
    if tp is None:
        tp = "00-" + "0" * 32 + "-" + "0" * 16 + "-00"
    return TraceContext(traceparent=tp)


# -- service commands -------------------------------------------------------


_COLLECTOR_TYPES = ("telegram-stub", "telegram", "matrix-stub", "matrix", "forum", "stub")
# `stub` is the legacy alias for `telegram-stub` — kept for one release to
# avoid breaking operator scripts written against M1/M2 docs.
_LEGACY_TELEGRAM_STUB_ALIAS = "stub"


@app.command("collector")
def collector_run(  # pragma: no cover
    identity: str = typer.Option(..., "--identity", help="identity name from pool"),
    collector: str = typer.Option(
        "telegram-stub",
        "--type",
        help="one of: telegram-stub, telegram, matrix-stub, matrix",
    ),
    fixture: Path | None = typer.Option(
        None, "--fixture", help="JSONL replay file (stub types only)"
    ),
    backfill: bool = typer.Option(False, "--backfill", help="replay full history oldest-first"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    identities: Path | None = typer.Option(None, "--identities"),
    nats_url: str | None = typer.Option(None, "--nats-url"),
    memory_bus: bool = typer.Option(False, "--memory-bus", help="use in-process bus"),
    tick: float = typer.Option(1.0, "--tick", help="emission interval for stub types (s)"),
) -> None:
    """Run a collector. Use --type to select the source + mode."""

    if collector == _LEGACY_TELEGRAM_STUB_ALIAS:
        typer.echo(
            "warning: --type stub is deprecated; use --type telegram-stub.",
            err=True,
        )
        collector = "telegram-stub"
    if collector not in _COLLECTOR_TYPES:
        raise typer.BadParameter(
            f"unknown --type {collector!r}; expected one of "
            f"{', '.join(t for t in _COLLECTOR_TYPES if t != _LEGACY_TELEGRAM_STUB_ALIAS)}"
        )

    cfg = RuntimeConfig.from_env(
        data_dir=data_dir,
        identities_path=identities,
        nats_url=nats_url,
        use_memory_bus=memory_bus,
    )
    # Telegram's live path is DB-backed: the encrypted session comes from the
    # IdentityTable (provisioned via POST /v1/identities or `eyenet identity
    # sync`), NOT the TOML pool. The blob is decrypted into an in-memory
    # StringSession at boot via the session key.
    if collector == "telegram":
        session_key = load_session_key(cfg.data_dir)

        def _factory(bus: Bus, storage: BaseRepository) -> ServiceBase:
            return TelegramCollector(
                bus=bus,
                storage=storage,
                pool=DbIdentityPool(storage),
                identity_name=identity,
                backfill=backfill,
                session_key=session_key,
            )

        _run(_factory, cfg, tick=0.0)
        return

    # Forum is DB-backed too: the encrypted cookies.txt lives in the IdentityTable
    # (provisioned via POST /v1/identities), decrypted into an in-memory cookie
    # jar at boot. Poll-based, so default to 60s when --tick is omitted.
    if collector == "forum":
        session_key = load_session_key(cfg.data_dir)

        def _factory(bus: Bus, storage: BaseRepository) -> ServiceBase:
            return MyBBForumCollector(
                bus=bus,
                storage=storage,
                pool=DbIdentityPool(storage),
                identity_name=identity,
                session_key=session_key,
            )

        _run(_factory, cfg, tick=tick or 60.0)
        return

    # Matrix + stub collectors still read the file-backed pool (Matrix auth is
    # not encrypted yet; the generic seam extends to it when it is).
    if cfg.identities_path is None:
        raise typer.BadParameter("identities path is required (--identities or EYENET_IDENTITIES)")
    pool = FileIdentityPool(cfg.identities_path, check_session_files=False)

    if collector == "matrix":

        def _factory(bus: Bus, storage: BaseRepository) -> ServiceBase:
            return MatrixCollector(
                bus=bus,
                storage=storage,
                pool=pool,
                identity_name=identity,
                backfill=backfill,
            )

        _run(_factory, cfg, tick=0.0)
    elif collector == "matrix-stub":

        def _factory(bus: Bus, storage: BaseRepository) -> ServiceBase:
            return MatrixCollectorStub(
                bus=bus,
                storage=storage,
                pool=pool,
                identity_name=identity,
                fixture_path=fixture,
            )

        _run(_factory, cfg, tick=tick)
    else:  # telegram-stub

        def _factory(bus: Bus, storage: BaseRepository) -> ServiceBase:
            return TelegramCollectorStub(
                bus=bus,
                storage=storage,
                pool=pool,
                identity_name=identity,
                fixture_path=fixture,
            )

        _run(_factory, cfg, tick=tick)


@app.command("sensor")
def sensor_run(  # pragma: no cover
    profile: str = typer.Option("skeleton", "--profile", help="'skeleton' or 'stylometric'"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    nats_url: str | None = typer.Option(None, "--nats-url"),
    memory_bus: bool = typer.Option(False, "--memory-bus"),
) -> None:
    """Run the sensor."""

    cfg = RuntimeConfig.from_env(data_dir=data_dir, nats_url=nats_url, use_memory_bus=memory_bus)
    if profile == "stylometric":
        _run(lambda bus, storage: StylometricSensor(bus=bus, storage=storage), cfg)
    else:
        _run(lambda bus, storage: SensorSkeleton(bus=bus, storage=storage), cfg)


@app.command("discovery")
def discovery_run(  # pragma: no cover
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    nats_url: str | None = typer.Option(None, "--nats-url"),
    memory_bus: bool = typer.Option(False, "--memory-bus"),
) -> None:
    """Run the discovery sensor — extracts group references from every raw
    message and records DISCOVERED candidates. Separate queue group from the
    stylometric sensor, so it sees every message."""

    cfg = RuntimeConfig.from_env(data_dir=data_dir, nats_url=nats_url, use_memory_bus=memory_bus)
    _run(lambda bus, storage: DiscoverySensor(bus=bus, storage=storage), cfg)


@app.command("discovery-backfill")
def discovery_backfill(  # pragma: no cover
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    batch: int = typer.Option(1000, "--batch", help="messages per keyset page"),
    max_messages: int | None = typer.Option(
        None, "--max-messages", help="stop after N messages (smoke/limited runs)"
    ),
) -> None:
    """Run the discovery extractors over the STORED message corpus (one-shot).

    The live discovery sensor only sees new messages off the bus; this mines the
    history. Idempotent (record_candidate_mention dedupes on evidence ref), so it
    is safe to re-run. New groups land as DISCOVERED — nothing auto-joins."""

    async def _main() -> None:
        cfg = RuntimeConfig.from_env(data_dir=data_dir)
        storage = get_repository(data_dir=cfg.data_dir)
        lineage: dict[UUID, tuple[UUID | None, int]] = {}  # group_id -> (seed_root, depth), cached
        after_id: UUID | None = None
        seen = 0
        rows_written = 0
        try:
            while True:
                page = cast(
                    "list[DiscoveryBackfillMessage]",
                    await storage.messages_for_discovery_backfill(limit=batch, after_id=after_id),
                )
                if not page:
                    break
                for m in page:
                    if m.group_id not in lineage:
                        lineage[m.group_id] = await storage.group_lineage(m.group_id)
                    seed_root_id, depth = lineage[m.group_id]
                    ctx = MessageContext(
                        text=m.body,
                        source_id=m.source_id,
                        observed_by_collector_id=m.observed_by_collector_id,
                        observed_in_group_id=m.group_id,
                        seed_root_id=seed_root_id,
                        depth_from_root=depth,
                        mentioning_actor_id=m.actor_id,
                        evidence_ref=m.evidence_ref,
                        sent_at_source=m.sent_at_source,
                        collected_at=m.ingested_at,
                    )
                    for extractor in DISCOVERY_EXTRACTORS:
                        rows_written += await extractor.process(ctx, storage)
                    after_id = m.id
                    seen += 1
                    if max_messages is not None and seen >= max_messages:
                        break
                typer.echo(f"  scanned {seen} messages, {rows_written} discovery rows written")
                if max_messages is not None and seen >= max_messages:
                    break
        finally:
            await storage.close()
        typer.echo(f"done: {seen} messages scanned, {rows_written} discovery rows written")

    asyncio.run(_main())


@app.command("incident-classifier")
def incident_classifier_run(  # pragma: no cover
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    nats_url: str | None = typer.Option(None, "--nats-url"),
    memory_bus: bool = typer.Option(False, "--memory-bus"),
    batch_size: int = typer.Option(32, "--batch-size", help="messages per inference batch"),
    flush_interval: float = typer.Option(
        1.0, "--flush-interval", help="max seconds a message waits before a partial batch flushes"
    ),
) -> None:
    """Run the incident classifier: batched multi-label detection off the bus.

    Set the model directory via EYENET_INCIDENT_MODEL_DIR (default dataset/mmbert-incident-ml).
    Flushes a batch at --batch-size messages OR every --flush-interval seconds.
    """

    cfg = RuntimeConfig.from_env(data_dir=data_dir, nats_url=nats_url, use_memory_bus=memory_bus)
    _run(
        lambda bus, storage: IncidentClassifierService(
            bus=bus, storage=storage, batch_size=batch_size, flush_interval=flush_interval
        ),
        cfg,
        tick=flush_interval,
    )


@app.command("geo")
def geo_run(  # pragma: no cover
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    nats_url: str | None = typer.Option(None, "--nats-url"),
    memory_bus: bool = typer.Option(False, "--memory-bus"),
    batch_size: int = typer.Option(500, "--batch-size", help="messages per attribution batch"),
    interval: float = typer.Option(
        2.0, "--interval", help="seconds between attribution batches (0 = one pass then wait)"
    ),
) -> None:
    """Run victim-country attribution over incident-flagged messages.

    Tick-driven: each tick attributes a batch of flagged messages that have no geo
    verdict yet, so it backfills the existing corpus then stays live. Results land in
    the message_geo sidecar and surface on the incident feed.
    """

    cfg = RuntimeConfig.from_env(data_dir=data_dir, nats_url=nats_url, use_memory_bus=memory_bus)
    _run(
        lambda bus, storage: GeoAttributionService(bus=bus, storage=storage, batch_size=batch_size),
        cfg,
        tick=interval,
    )


@app.command("engine")
def engine_run(  # pragma: no cover
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    nats_url: str | None = typer.Option(None, "--nats-url"),
    memory_bus: bool = typer.Option(False, "--memory-bus"),
    fixture: Path | None = typer.Option(None, "--fixture", help="JSONL fixture for smoke mode"),
    duration: float = typer.Option(10.0, "--duration", help="smoke-mode run duration in seconds"),
    dump_profiles: bool = typer.Option(False, "--dump-profiles", help="print ProfileRow JSON"),
) -> None:
    """Run the engine."""

    cfg = RuntimeConfig.from_env(data_dir=data_dir, nats_url=nats_url, use_memory_bus=memory_bus)

    if fixture is not None:
        records: list[dict[str, object]] = [
            json.loads(line) for line in fixture.read_text().splitlines() if line.strip()
        ]
        asyncio.run(_smoke_run(cfg, records, fixture, duration, dump_profiles))
    else:
        _run(lambda bus, storage: Engine(bus=bus, storage=storage), cfg)


@app.command("linker")
def linker_run(  # pragma: no cover
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    nats_url: str | None = typer.Option(None, "--nats-url"),
    memory_bus: bool = typer.Option(False, "--memory-bus"),
) -> None:
    """Run the linker."""

    cfg = RuntimeConfig.from_env(data_dir=data_dir, nats_url=nats_url, use_memory_bus=memory_bus)
    linker_cfg = LinkerConfig()
    _run(lambda bus, storage: Linker(bus=bus, storage=storage, config=linker_cfg), cfg)


@app.command("link-infra")
def link_infra(  # pragma: no cover
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    max_df: int = typer.Option(
        15, "--max-df", help="ignore indicators shared by more than N actors (ambient)"
    ),
    weight_floor: float = typer.Option(0.15, "--weight-floor", help="min edge score to propose"),
) -> None:
    """Batch-propose shared-infrastructure linkages over stored messages (anti-spam §B).

    Links actors by the contact handles / t.me / wallets they share in message
    bodies — high precision on templated-spam populations where stylometry fails.
    """

    async def _main() -> None:
        cfg = RuntimeConfig.from_env(data_dir=data_dir)
        storage = get_repository(data_dir=cfg.data_dir)
        n = await run_infra_linker(storage, max_df=max_df, weight_floor=weight_floor)
        await storage.close()
        typer.echo(f"proposed {n} shared_infra linkages")

    asyncio.run(_main())


@app.command("detect-copypasta")
def detect_copypasta(  # pragma: no cover
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    """Batch-detect copypasta templates over stored messages (anti-spam §A).

    Groups message bodies by masked fingerprint, flags templates that are long and
    posted by many actors, and tags those messages so the stylometric sensor skips
    them (templated ad text is not authorship signal).
    """

    async def _main() -> None:
        cfg = RuntimeConfig.from_env(data_dir=data_dir)
        storage = get_repository(data_dir=cfg.data_dir)
        n = await storage.detect_copypasta_templates()
        await storage.close()
        typer.echo(f"flagged {n} copypasta templates")

    asyncio.run(_main())


@app.command("incidents-backfill")
def incidents_backfill(  # pragma: no cover
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    batch_size: int = typer.Option(64, "--batch-size", help="messages per inference batch"),
    limit: int | None = typer.Option(None, "--limit", help="cap total messages scanned"),
) -> None:
    """Classify stored messages that predate the classifier service (history backfill).

    Runs the same cascade as the live service (calibrated model + prefilter + operator
    rules) over messages with no incident row yet. Re-runnable; already-classified
    messages are skipped. Set EYENET_INCIDENT_MODEL_DIR to pick the model directory.
    """
    from eyenet.incidents.backfill import run_backfill  # noqa: PLC0415

    async def _main() -> None:
        cfg = RuntimeConfig.from_env(data_dir=data_dir)
        storage = get_repository(data_dir=cfg.data_dir)
        scanned, fired = await run_backfill(storage, batch_size=batch_size, limit=limit)
        await storage.close()
        typer.echo(f"scanned {scanned} messages, stored {fired} incidents")

    asyncio.run(_main())


@app.command("incidents-export-labels")
def incidents_export_labels(  # pragma: no cover
    out: Path = typer.Option(
        Path("dataset/operator_corrections.mllabels.jsonl"),
        "--out",
        help="output JSONL (keep the .mllabels.jsonl suffix so the trainer picks it up)",
    ),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    """Export operator label corrections as gold training data (closes the retraining loop).

    Writes {text, labels} JSONL that dataset/train_mmbert_ml.py consumes as human truth.
    Re-run after operators relabel, then retrain to fold the corrections in.
    """
    from eyenet.incidents.export import export_operator_labels  # noqa: PLC0415

    async def _main() -> None:
        cfg = RuntimeConfig.from_env(data_dir=data_dir)
        storage = get_repository(data_dir=cfg.data_dir)
        n = await export_operator_labels(storage, out)
        await storage.close()
        typer.echo(f"exported {n} operator corrections -> {out}")

    asyncio.run(_main())


@app.command("crew-cases")
def crew_cases(  # pragma: no cover
    as_user: str = typer.Option(..., "--as", help="username to own the auto-opened cases"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    min_size: int = typer.Option(8, "--min-size", help="auto-open crews with >= N members"),
    min_score: float = typer.Option(0.8, "--min-score", help="and max edge score >= this"),
) -> None:
    """Auto-open Cases for large, high-confidence crews (anti-spam §3).

    Idempotent: crews that already have a case (by crew key) are skipped. The long
    tail is left for operator promotion via POST /v1/actor-groups/case.
    """
    from eyenet.linker.crew_cases import open_cases_for_big_crews  # noqa: PLC0415

    async def _main() -> None:
        cfg = RuntimeConfig.from_env(data_dir=data_dir)
        storage = get_repository(data_dir=cfg.data_dir)
        user = await storage.get_system_user_by_username(as_user)
        if user is None:
            await storage.close()
            raise typer.BadParameter(f"unknown user: {as_user!r}")
        n = await open_cases_for_big_crews(
            storage,
            opened_by_user_id=user.id,
            service="cli",
            instance_id="crew-cases",
            min_size=min_size,
            min_score=min_score,
        )
        await storage.close()
        typer.echo(f"opened {n} crew cases")

    asyncio.run(_main())


@app.command("verifier")
def verifier_run(  # pragma: no cover
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    nats_url: str | None = typer.Option(None, "--nats-url"),
    memory_bus: bool = typer.Option(False, "--memory-bus"),
    impostor_pool: Path | None = typer.Option(
        None,
        "--impostor-pool",
        help="JSONL impostor-pool fixture; one actor per line "
        "(default: tests/fixtures/calibration/impostor_pool.jsonl if present)",
    ),
) -> None:
    """Run the M8 Verifier — push-mode service on linkage.proposed."""

    cfg = RuntimeConfig.from_env(data_dir=data_dir, nats_url=nats_url, use_memory_bus=memory_bus)
    verifier_cfg = VerifierConfig()

    default_pool = Path("tests/fixtures/calibration/impostor_pool.jsonl")
    pool_path = (
        impostor_pool
        if impostor_pool is not None
        else (default_pool if default_pool.exists() else None)
    )

    def _factory(bus: Bus, storage: BaseRepository) -> ServiceBase:
        return VerifierService(
            bus=bus,
            storage=storage,
            config=verifier_cfg,
            impostor_pool_path=pool_path,
        )

    _run(_factory, cfg)


@app.command("classifier")
def classifier_run(  # pragma: no cover
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    nats_url: str | None = typer.Option(None, "--nats-url"),
    memory_bus: bool = typer.Option(False, "--memory-bus"),
    instance_id: str = typer.Option("classifier_1", "--instance-id"),
) -> None:
    """Run the M10 Document Classifier — async worker on classify.* triggers."""

    cfg = RuntimeConfig.from_env(data_dir=data_dir, nats_url=nats_url, use_memory_bus=memory_bus)

    def _factory(bus: Bus, storage: BaseRepository) -> ServiceBase:
        return ClassifierService(bus=bus, storage=storage, instance_id=instance_id)

    _run(_factory, cfg)


@app.command("api")
def api_run(  # pragma: no cover
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    nats_url: str | None = typer.Option(None, "--nats-url"),
    memory_bus: bool = typer.Option(False, "--memory-bus"),
    workers: int = typer.Option(1, "--workers"),
    certfile: str | None = typer.Option(None, "--certfile"),
    keyfile: str | None = typer.Option(None, "--keyfile"),
    enable_h3: bool = typer.Option(
        False, "--h3/--no-h3", help="offer HTTP/3 (QUIC); requires TLS (§12.1.1)"
    ),
    allow_insecure_bind: bool = typer.Option(
        False, "--allow-insecure-bind", help="non-loopback bind with TLS terminated upstream"
    ),
) -> None:
    """Serve the operator HTTP API over Hypercorn (h2, optional h3; never h1)."""

    from hypercorn.asyncio import serve  # noqa: PLC0415
    from hypercorn.typing import ASGIFramework  # noqa: PLC0415

    from eyenet.api._serve import build_config  # noqa: PLC0415
    from eyenet.api.app import create_app  # noqa: PLC0415

    cfg = RuntimeConfig.from_env(data_dir=data_dir, nats_url=nats_url, use_memory_bus=memory_bus)
    hcfg = build_config(
        host,
        port,
        enable_h3=enable_h3,
        certfile=certfile,
        keyfile=keyfile,
        workers=workers,
        allow_insecure_bind=allow_insecure_bind,
    )

    async def _main() -> None:
        bus = await _connect_bus(cfg)
        storage = get_repository(data_dir=cfg.data_dir)
        try:
            fastapi_app = create_app(
                storage=storage,
                data_dir=cfg.data_dir,
                publisher=BusEnvelopePublisher(bus),
            )
            # FastAPI is a valid ASGI3 app; hypercorn's ASGIFramework Protocol is
            # narrower than what create_app returns, so bridge the two explicitly.
            await serve(cast("ASGIFramework", fastapi_app), hcfg)
        finally:
            await bus.close()
            await storage.close()

    asyncio.run(_main())


@app.command("graph")
def graph_run(  # pragma: no cover
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    nats_url: str | None = typer.Option(None, "--nats-url"),
    memory_bus: bool = typer.Option(False, "--memory-bus"),
) -> None:
    """Run the graph service."""

    cfg = RuntimeConfig.from_env(data_dir=data_dir, nats_url=nats_url, use_memory_bus=memory_bus)
    _run(lambda bus, storage: Graph(bus=bus, storage=storage), cfg)


@app.command("supervisor")
def supervisor_run(  # pragma: no cover
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    nats_url: str | None = typer.Option(None, "--nats-url"),
    memory_bus: bool = typer.Option(False, "--memory-bus"),
    tick: float = typer.Option(5.0, "--tick", help="reconcile interval in seconds"),
) -> None:
    """Run the collector supervisor (reconciles observed_state → desired; M9.E3)."""

    cfg = RuntimeConfig.from_env(data_dir=data_dir, nats_url=nats_url, use_memory_bus=memory_bus)
    _run(lambda bus, storage: CollectorSupervisor(bus=bus, storage=storage), cfg, tick=tick)


@app.command("anchor")
def anchor_run(  # pragma: no cover
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    nats_url: str | None = typer.Option(None, "--nats-url"),
    memory_bus: bool = typer.Option(False, "--memory-bus"),
    tick: float = typer.Option(300.0, "--tick", help="anchor interval in seconds"),
) -> None:
    """Run the external-witness anchor emitter (signs audit+journal heads; §5.9)."""

    cfg = RuntimeConfig.from_env(data_dir=data_dir, nats_url=nats_url, use_memory_bus=memory_bus)
    _run(
        lambda bus, storage: AnchorEmitter(bus=bus, storage=storage, data_dir=cfg.data_dir),
        cfg,
        tick=tick,
    )


@app.command("panic")
def panic(  # pragma: no cover
    nats_url: str | None = typer.Option(None, "--nats-url"),
) -> None:
    """Publish `eyenet.control.global.panic` — kill switch (PLAN §6.2)."""

    async def _main() -> None:
        cfg = RuntimeConfig.from_env(nats_url=nats_url)
        bus = await NATSBus.connect(cfg.nats_url)
        try:
            await bus.publish("eyenet.control.global.panic", b"")
        finally:
            await bus.close()

    asyncio.run(_main())
    typer.echo("panic published")


# -- linkage subcommands ----------------------------------------------------


@linkage_app.command("list")
def linkage_list(
    actor_id: UUID | None = typer.Option(None, "--actor", help="filter by actor UUID"),
    state: str | None = typer.Option(None, "--state", help="filter by state"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    limit: int = typer.Option(50, "--limit"),
) -> None:
    """List linkage rows."""

    cfg = RuntimeConfig.from_env(data_dir=data_dir)
    storage = get_repository(data_dir=cfg.data_dir)

    async def _main() -> None:
        rows = await storage.list_linkages(actor_id=actor_id, state=state, limit=limit)
        if not rows:
            typer.echo("no linkages found")
            return
        for row in rows:
            r = cast("LinkageRow", row)
            typer.echo(
                f"{r.id}  {r.actor_a_id}↔{r.actor_b_id}  "
                f"[{r.state.value}]  method={r.method}  score={r.score:.3f}"
            )
        await storage.close()

    asyncio.run(_main())


def _decision_command(
    linkage_id: UUID,
    decided_by: str,
    notes: str | None,
    new_state: LinkageState,
    subject: str,
    envelope_cls: type[Any],
    data_dir: Path | None,
    nats_url: str | None,
    memory_bus: bool,
) -> None:
    cfg = RuntimeConfig.from_env(data_dir=data_dir, nats_url=nats_url, use_memory_bus=memory_bus)

    async def _main() -> None:
        storage = get_repository(data_dir=cfg.data_dir)
        bus = await _connect_bus(cfg)
        try:
            row = await storage.get_linkage(linkage_id)
            if row is None:
                typer.echo(f"ERROR: linkage {linkage_id} not found", err=True)
                raise typer.Exit(code=1)

            r = row

            await storage.transition_linkage(
                linkage_id, new_state, decided_by=decided_by, notes=notes
            )

            now = datetime.now(tz=UTC)

            # M8: confirm = SAME-author ground truth; reject = DIFF-author
            # ground truth. suspect is operator triage, still ambiguous —
            # no feedback row. Failure here MUST NOT roll back the state
            # transition; log and continue.
            feedback_truth = {
                LinkageState.CONFIRMED: "same",
                LinkageState.REJECTED: "diff",
            }.get(new_state)
            if feedback_truth is not None:
                try:
                    await storage.record_feedback_pair(
                        linkage_id=linkage_id,
                        actor_a=r.actor_a_id,
                        actor_b=r.actor_b_id,
                        ground_truth=feedback_truth,
                        decided_by=decided_by,
                        decided_at=now,
                        notes=notes,
                    )
                except ValueError as exc:
                    # ground_truth validation — should never fire because
                    # the dict literal above is closed-set, but be loud
                    # if it does.
                    typer.echo(f"WARN: feedback_pairs.record failed: {exc}", err=True)

            publisher = BusEnvelopePublisher(bus)
            tc = _make_trace_context()
            env = envelope_cls.from_pair(
                r.actor_a_id,
                r.actor_b_id,
                linkage_id=linkage_id,
                decided_by=decided_by,
                decided_at=now,
                notes=notes,
                trace_context=tc,
            )
            await publisher.publish(subject, env)
            typer.echo(f"OK: linkage {linkage_id} → {new_state.value} by {decided_by}")
        finally:
            await bus.close()
            await storage.close()

    asyncio.run(_main())


@linkage_app.command("suspect")
def linkage_suspect(
    linkage_id: UUID = typer.Argument(..., help="linkage UUID"),
    by: str = typer.Option(..., "--by", help="operator name"),
    notes: str | None = typer.Option(None, "--notes"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    nats_url: str | None = typer.Option(None, "--nats-url"),
    memory_bus: bool = typer.Option(False, "--memory-bus"),
) -> None:
    """Promote a PROPOSED linkage to SUSPECTED (operator triage)."""

    _decision_command(
        linkage_id,
        by,
        notes,
        LinkageState.SUSPECTED,
        SUBJECT_LINKAGE_SUSPECTED,
        LinkageSuspectedEnvelope,
        data_dir,
        nats_url,
        memory_bus,
    )


@linkage_app.command("confirm")
def linkage_confirm(
    linkage_id: UUID = typer.Argument(..., help="linkage UUID"),
    by: str = typer.Option(..., "--by", help="operator name"),
    notes: str | None = typer.Option(None, "--notes"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    nats_url: str | None = typer.Option(None, "--nats-url"),
    memory_bus: bool = typer.Option(False, "--memory-bus"),
) -> None:
    """Confirm a PROPOSED or SUSPECTED linkage — drives Persona aggregation."""

    _decision_command(
        linkage_id,
        by,
        notes,
        LinkageState.CONFIRMED,
        SUBJECT_LINKAGE_CONFIRMED,
        LinkageConfirmedEnvelope,
        data_dir,
        nats_url,
        memory_bus,
    )


@linkage_app.command("reject")
def linkage_reject(
    linkage_id: UUID = typer.Argument(..., help="linkage UUID"),
    by: str = typer.Option(..., "--by", help="operator name"),
    notes: str | None = typer.Option(None, "--notes"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    nats_url: str | None = typer.Option(None, "--nats-url"),
    memory_bus: bool = typer.Option(False, "--memory-bus"),
) -> None:
    """Reject a PROPOSED or SUSPECTED linkage — terminal."""

    _decision_command(
        linkage_id,
        by,
        notes,
        LinkageState.REJECTED,
        SUBJECT_LINKAGE_REJECTED,
        LinkageRejectedEnvelope,
        data_dir,
        nats_url,
        memory_bus,
    )


from eyenet.calibration.cli import app as calibrate_app  # noqa: E402

app.add_typer(calibrate_app, name="calibrate", help="M5 calibration grid + artifact tooling")


if __name__ == "__main__":
    app()
