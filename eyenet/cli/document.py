"""``eyenet document *`` — operator surface for document classification (M10).

``ingest <path>`` runs the full classifier pipeline over a local file and
persists the settled tier. Containment is the same as the API path: the bytes
are stored host-side (custody sha256), parsed in the nsjail sandbox, and the
deterministic floors bind the tier (§0 — anything unreadable settles
CLASSIFIED). The classification decision is recorded to the (offline)
hash-chained audit log via an in-process bus publisher — audit-everything holds
even when no NATS daemon is attached.

Exit codes: ``0`` ok · ``1`` pipeline error (no row persisted).
"""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path

import typer

from eyenet.bus.memory import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.classifier.ingest import IngestResult, ingest_document
from eyenet.cli.config import RuntimeConfig
from eyenet.storage.factory import get_repository
from eyenet.telemetry.audit import AuditEmitter

document_app = typer.Typer(
    name="document",
    help="Classify operator-uploaded documents.",
    no_args_is_help=True,
)


@document_app.command("ingest")
def document_ingest(
    path: Path = typer.Argument(..., help="path to the document file to classify"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    """Classify + persist one local file; print its id, settled tier, and hash."""
    cfg = RuntimeConfig.from_env(data_dir=data_dir)
    if not path.is_file():
        typer.echo(f"ERROR: not a file: {path}", err=True)
        raise typer.Exit(code=1)
    blob = path.read_bytes()
    mime = mimetypes.guess_type(path.name)[0]

    async def _main() -> IngestResult:
        storage = get_repository(data_dir=cfg.data_dir)
        audit = AuditEmitter(
            BusEnvelopePublisher(MemoryBus()),
            storage,
            service="cli",
            instance_id="document-ingest",
        )
        try:
            return await ingest_document(
                blob,
                storage=storage,
                data_dir=cfg.data_dir,
                audit=audit,
                filename=path.name,
                mime=mime,
            )
        finally:
            await storage.close()

    result = asyncio.run(_main())
    review = "yes" if result.verdict.review_flags else "no"
    typer.echo(
        f"{result.document_id}  tier={result.verdict.tier.value}  "
        f"sha256={result.sha256}  review={review}"
    )
