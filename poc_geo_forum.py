#!/usr/bin/env python
"""PoC: run victim-country attribution over forum threads in the EYENET DB.

Read-only, from outside the services. Groups every message by its thread
(``group_``), concatenates the bodies, runs :func:`classify_country`, and prints
a per-thread verdict plus a rollup of how many threads smell like each country.

    uv run python poc_geo_forum.py                 # forum threads (default)
    uv run python poc_geo_forum.py --kind ALL      # every thread, any source
    uv run python poc_geo_forum.py --kind TELEGRAM # the current dev DB has these
    uv run python poc_geo_forum.py --db data/main.db --limit 20

ponytail: deliberately bypasses the repository abstraction (read-only, throwaway
PoC over local bytes). If this graduates past a PoC, move it onto
get_repository() + a real list-forum-threads method. SQLAlchemy persists enum
NAMES uppercase, so source/group kinds in the DB are 'FORUM', 'FORUM_THREAD'.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from collections import Counter
from itertools import groupby
from pathlib import Path

import structlog

from eyenet.classifier.geo import classify_country

# PoC: keep the per-classification INFO log off the table output.
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))


def _rows(db: Path, kind: str | None) -> list[tuple[str, str, str, str]]:
    """(group_id, source_kind, thread_title, body) for the selected threads, thread-ordered."""
    uri = f"file:{db}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        sql = (
            "SELECT m.group_id, s.kind, g.current_title, m.body "
            "FROM message m "
            'JOIN "group_" g ON g.id = m.group_id '
            "JOIN source s ON s.id = m.source_id "
        )
        params: tuple[str, ...] = ()
        if kind is not None:
            sql += "WHERE s.kind = ? "
            params = (kind,)
        sql += "ORDER BY m.group_id"
        return list(conn.execute(sql, params))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=Path("data/main.db"))
    ap.add_argument(
        "--kind",
        default="FORUM",
        help="source kind filter (uppercase enum name); ALL for no filter",
    )
    ap.add_argument("--limit", type=int, default=0, help="max threads to print (0 = all)")
    args = ap.parse_args()

    if not args.db.exists():
        raise SystemExit(f"no DB at {args.db} — run `eyenet init` or point --db at one")

    kind = None if args.kind.upper() == "ALL" else args.kind.upper()
    rows = _rows(args.db, kind)
    if not rows:
        scope = "any source" if kind is None else kind
        print(f"no threads found for {scope} in {args.db}. Nothing to classify.")
        return

    rollup: Counter[str] = Counter()
    printed = 0
    print(f"{'thread':<34} {'decided_by':<13} {'msgs':>5}  {'iso':<8} title")
    print("-" * 95)
    for gid, grp in groupby(rows, key=lambda r: r[0]):
        posts = list(grp)
        title = posts[0][2]
        verdict = classify_country("\n".join(p[3] for p in posts), title=title)
        rollup[verdict.country or verdict.status] += 1

        if args.limit and printed >= args.limit:
            continue
        printed += 1
        label = verdict.country or verdict.status.upper()
        by = verdict.decided_by or "-"
        print(f"{gid:<34} {by:<13} {len(posts):>5}  {label:<8} {(title or '')[:38]}")

    print("-" * 78)
    total = sum(rollup.values())
    print(f"{total} threads classified. Rollup (country / status):")
    for key, n in rollup.most_common():
        print(f"  {key:<10} {n:>5}  ({n / total:.0%})")


if __name__ == "__main__":
    main()
