# SPDX-License-Identifier: AGPL-3.0-or-later
"""PostgreSQL backend — the high-ingest prod target.

Concrete override of :class:`SQLModelRepository` for PostgreSQL (asyncpg request
path, psycopg DDL path). Chosen when SQLite's single-writer wall bites under
concurrent collector writes. See ``development/POSTGRES_PORT.md``.
"""

from eyenet.storage.postgres_repo.repository import PostgresRepository

__all__ = ["PostgresRepository"]
