-- Create the two EYENET databases on a fresh Postgres volume.
--
-- The official postgres image's docker-entrypoint only auto-creates the
-- single database named in POSTGRES_DB. We set that to `postgres` (the
-- default system db) so this init script is the ONE place that knows
-- about EYENET's two-database layout: `eyenet` for the operating state,
-- `eyenet_audit` for the hash-chained audit log in its own physical
-- database (tamper-evidence isolation per CLAUDE.md section 2.6).
--
-- Only runs on first boot of an empty data volume. On every subsequent
-- restart the docker-entrypoint sees an initialized PGDATA and skips
-- this directory entirely. Safe to leave checked in.
--
-- Historical note: compose.yaml used to carry a comment saying "the
-- cutover creates eyenet + eyenet_audit", referring to the 2026-10-11
-- SQLite -> Postgres cutover (a one-shot migration). That cutover left
-- prod with the databases already in place, so new fresh deploys silently
-- never got them -- until nico-g hit the FATAL on his test box and
-- flagged the gap. Shoutout to nico-g for actively test-driving EYENET
-- and surfacing this fresh-install bug. This file closes it.

SELECT 'CREATE DATABASE eyenet OWNER eyenet'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'eyenet')\gexec

SELECT 'CREATE DATABASE eyenet_audit OWNER eyenet'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'eyenet_audit')\gexec
