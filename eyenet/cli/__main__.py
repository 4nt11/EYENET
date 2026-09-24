# SPDX-License-Identifier: AGPL-3.0-or-later
"""Module entrypoint so ``python -m eyenet.cli ...`` runs the Typer app.

The supervisor spawns collector children via ``sys.executable -m eyenet.cli``,
which resolves regardless of whether the ``eyenet`` console script is on PATH.
"""

from __future__ import annotations

from eyenet.cli.main import app

if __name__ == "__main__":
    app()
