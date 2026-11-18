# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-family victim-count read for the families landing page.

Kept in its own module to avoid bloating eyenet/stealer/query.py further;
this read is independent of the per-victim detail path and has its own
not-initialized handling. Returns sorted (slug, count) tuples; the empty
slug is the "no-verdict" bucket and is included for honesty."""

from __future__ import annotations

from eyenet.stealer.clickhouse import clickhouse_db, get_async_clickhouse_client
from eyenet.stealer.query import StealerCorpusUninitializedError, _is_unknown_table


async def family_counts() -> list[tuple[str, int]]:
    client = await get_async_clickhouse_client()
    db = clickhouse_db()
    try:
        result = await client.query(
            "SELECT slug, count() AS n "  # noqa: S608  # nosec B608
            f"FROM {db}.victim_family_verdict FINAL "
            "GROUP BY slug "
            "ORDER BY n DESC, slug ASC"
        )
    except Exception as exc:
        if _is_unknown_table(exc):
            raise StealerCorpusUninitializedError(
                "stealer.victim_family_verdict table does not exist yet"
            ) from exc
        raise
    return [(str(slug or ""), int(n)) for slug, n in result.result_rows]


__all__ = ["family_counts"]
