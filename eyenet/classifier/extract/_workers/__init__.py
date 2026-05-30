"""In-jail extraction workers — standalone scripts, NOT an importable API.

Every module here is bind-mounted into the nsjail at ``/worker.py`` and executed
by the in-jail interpreter against the read-only ``/input``. They print the
``{"text", "meta"}`` envelope on stdout. EYENET never imports them in-process —
they exist only to run behind the chokepoint — so they are excluded from ruff,
mypy, and coverage (see pyproject). This package marker exists only so the
scripts are packaged into the wheel and resolvable by path at runtime.
"""
