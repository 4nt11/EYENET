# SPDX-License-Identifier: AGPL-3.0-or-later
"""``eyenet identity *`` — the file↔DB identity bridge (M9.E5).

``sync`` reconciles ``identities.toml`` into the ``IdentityTable`` so the
discovery supervisor can lease scouts. Idempotent: run it after editing the
pool file (e.g. to mark an identity ``role = "scout"``). The reconcile logic
lives in :func:`eyenet.services.discovery.identity_provisioning.provision_identities`
(tested); this is the live CLI wiring.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from eyenet.cli.config import RuntimeConfig
from eyenet.identity_pool.loader import load as load_identities
from eyenet.services.discovery.identity_provisioning import ProvisionResult, provision_identities
from eyenet.storage.factory import get_repository

identity_app = typer.Typer(
    name="identity",
    help="Identity pool ↔ database bridge.",
    no_args_is_help=True,
)


@identity_app.command("sync")  # pragma: no cover — live CLI wiring (§3.4)
def identity_sync(
    identities: Path | None = typer.Option(None, "--identities"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    """Reconcile identities.toml into the IdentityTable (create + role update)."""
    cfg = RuntimeConfig.from_env(data_dir=data_dir, identities_path=identities)
    if cfg.identities_path is None:
        raise typer.BadParameter("identities path is required (--identities or EYENET_IDENTITIES)")
    pool_file = load_identities(cfg.identities_path, check_session_files=False)

    async def _main() -> ProvisionResult:
        storage = get_repository(data_dir=cfg.data_dir)
        try:
            return await provision_identities(storage, pool_file)
        finally:
            await storage.close()

    result = asyncio.run(_main())
    typer.echo(
        f"created={len(result.created)} updated={len(result.updated)} "
        f"unchanged={len(result.unchanged)}"
    )
    for name in result.created:
        typer.echo(f"  + {name}")
    for name in result.updated:
        typer.echo(f"  ~ {name} (role updated)")
