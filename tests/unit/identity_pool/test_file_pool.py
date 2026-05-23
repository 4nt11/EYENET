"""FileIdentityPool — TOML round-trip + state machine."""

from __future__ import annotations

from pathlib import Path

import pytest

from eyenet.contracts.enums import IdentityState
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump, load


def _write_pool(tmp_path: Path, *, name: str = "tg_alpha") -> Path:
    session = tmp_path / f"{name}.session"
    session.touch()
    cfg = IdentityFile(
        identities=[
            IdentityFileEntry(
                name=name,
                source="telegram",  # type: ignore[arg-type]
                session_path=str(session),
                cooldown_seconds=0,
            )
        ]
    )
    cfg_path = tmp_path / "identities.toml"
    dump(cfg, cfg_path)
    return cfg_path


@pytest.mark.unit
def test_round_trip(tmp_path: Path) -> None:
    cfg_path = _write_pool(tmp_path)
    parsed = load(cfg_path)
    assert len(parsed.identities) == 1
    assert parsed.identities[0].name == "tg_alpha"


@pytest.mark.unit
def test_missing_session_file_refused(tmp_path: Path) -> None:
    cfg = IdentityFile(
        identities=[
            IdentityFileEntry(
                name="tg_alpha",
                source="telegram",  # type: ignore[arg-type]
                session_path=str(tmp_path / "nonexistent.session"),
            )
        ]
    )
    cfg_path = tmp_path / "identities.toml"
    dump(cfg, cfg_path)
    with pytest.raises(ValueError, match="session_path missing"):
        load(cfg_path)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_claim_release_cycle(tmp_path: Path) -> None:
    cfg_path = _write_pool(tmp_path)
    pool = FileIdentityPool(cfg_path)
    e = await pool.claim("tg_alpha")
    assert e.state == IdentityState.IN_USE
    await pool.release("tg_alpha", new_state=IdentityState.AVAILABLE)
    e = await pool.claim("tg_alpha")
    assert e.state == IdentityState.IN_USE


@pytest.mark.unit
@pytest.mark.asyncio
async def test_double_claim_refused(tmp_path: Path) -> None:
    cfg_path = _write_pool(tmp_path)
    pool = FileIdentityPool(cfg_path)
    await pool.claim("tg_alpha")
    with pytest.raises(RuntimeError, match="already in use"):
        await pool.claim("tg_alpha")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_identity(tmp_path: Path) -> None:
    cfg_path = _write_pool(tmp_path)
    pool = FileIdentityPool(cfg_path)
    with pytest.raises(KeyError):
        await pool.claim("does_not_exist")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_freeze_all(tmp_path: Path) -> None:
    cfg_path = _write_pool(tmp_path)
    pool = FileIdentityPool(cfg_path)
    await pool.freeze_all()
    with pytest.raises(RuntimeError, match="frozen"):
        await pool.claim("tg_alpha")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_crash_recovery_resets_in_use(tmp_path: Path) -> None:
    """A new pool instance resets stale IN_USE back to AVAILABLE.

    In production there is one pool per process (PLAN §2.1). If the process
    crashes mid-claim, the TOML is left with state=in_use. The next startup
    must recover it so the operator doesn't have to edit the file manually.
    """
    cfg_path = _write_pool(tmp_path)
    pool1 = FileIdentityPool(cfg_path)
    await pool1.claim("tg_alpha")

    # Simulate crash: abandon pool1 without releasing.
    # New pool construction should reset IN_USE → AVAILABLE.
    pool2 = FileIdentityPool(cfg_path)
    # Must be claimable again after recovery.
    entry = await pool2.claim("tg_alpha")
    assert entry.name == "tg_alpha"
