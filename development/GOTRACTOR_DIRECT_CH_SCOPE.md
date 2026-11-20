# Gotractor direct-to-ClickHouse ingestion (scope doc)

## The pain we are leaving behind

Current flow:

```
gotractor (Go)
  readFolder -> 4GB string heap of archive file contents
  RunRules -> result.Evaluations slice
  cmdRun -> for each evaluation, BulkParse -> emit JSON line to stdout
    (emit goes to lockedWriter -> 4096-slot channel -> writer goroutine
     -> bufio.Writer -> stdout pipe)

Python stealer-processor
  _reader_loop thread: reads stdout, json.loads each line, puts dict in Queue
  _iter: get() from Queue, yield dict to caller
  _gotractor_insert_daemon: for each dict, append to batch list, every 50k
    submit batch to ThreadPoolExecutor
  ThreadPoolExecutor worker: sink.insert_rows(batch)
    -> clickhouse-connect HTTP INSERT
```

Every record goes through: JSON serialise (Go) -> stdout syscall -> Python
Queue -> Python dict -> Python list -> clickhouse-connect serialise ->
HTTP body -> ClickHouse. Six representations of the same bytes.

Each stage can backpressure and deadlock the one upstream of it. Python
holds the data in dict form, which is ~2-3x the wire size. On a Khazan
archive with 4M cookie records that is 4-8 GB of Python heap on top
of the 4 GB Go heap for the archive itself. 15 GB prod box dies.

## What we want instead

```
gotractor (Go)
  readFolder stays as-is (the Go string heap is the price of the regex pass)
  cmdRun -> native ClickHouse INSERT via clickhouse-go, in Go-controlled
             batches, flushed directly to CH
  emit to stdout keeps metadata only: verdict, parse_errors, run_done.
    Records NEVER touch stdout again.

Python stealer-processor
  _iter yields only verdict, parse_error, run_done. Records are gone from
  the stream.
  _gotractor_insert_daemon's whole TPE + semaphore + batch list goes away.
  It becomes: "dispatch run, wait for run_done, log the summary".
```

Python keeps:
- Orchestration (which archive, which password, which attachment-id)
- parse_error -> file_audit bookkeeping (small count, OK through stdout)
- run_done -> log + stealer_processing state update

Python drops:
- Every byte of record data
- The 4096-slot stdout buffering concern
- The TPE + BoundedSemaphore gymnastics
- The 2-3 GB record-dict overhead

## Go-side design

### New daemon flag

`--ch-dsn <dsn>` (or env `EYENET_GOTRACTOR_CH_DSN`). Format:
`tcp://USER:PASS@HOST:9000/DB?secure=false` (placeholders, not real creds).  <!-- pragma: allowlist secret -->

Absent -> stay in legacy stdout-record mode so dev workflows keep working.
Present -> every record goes to CH; stdout carries only metadata.

### clickhouse-go integration

Add module dep: `github.com/ClickHouse/clickhouse-go/v2`.

Two options for insert:

1. **Prepared batch** (`conn.PrepareBatch(ctx, "INSERT INTO ...")`, then
   `batch.Append(...)` per record, then `batch.Send()`).
   - Idiomatic clickhouse-go.
   - Pros: typed columns, no JSON intermediate.
   - Cons: must flush periodically (not on every record).

2. **Native streaming via `clickhouse-go`'s `Prepare`** with an explicit
   `batch.Send()` every N records.
   - Same as (1) but with a flush interval we own.

Pick (1). Batch size at 10k records (~2 MB each). Flush every `_FLUSH_INTERVAL`
seconds (say 5s) or when batch hits size. Flush is async-safe because
clickhouse-go handles its own connection pool.

### Changed cmdRun body

```go
func (d *Daemon) cmdRun(ctx context.Context, cmd commandEnv, w *lockedWriter) error {
    folder, err := readFolder(cmd.Input)
    if err != nil { return err }
    snap := d.catalog.Load()

    // Open CH batch for THIS run. One batch per archive keeps CH-side
    // part merging well-shaped (large parts, few of them).
    batch, err := d.ch.PrepareBatch(ctx, "INSERT INTO stealer.extracted_records ...")
    if err != nil { return fmt.Errorf("prepare batch: %w", err) }

    result, panicMsg := safeRunRules(snap.Rules, folder)
    if panicMsg != "" {
        w.emit({"kind":"parse_error", "rule_id":"", "file_path":"", "error":panicMsg})
    }

    w.emit({"kind":"verdict", "family": result.Family, ...})

    records := 0
    for _, ev := range result.Evaluations {
        if !ev.Matched || ev.Layer != "content" { continue }
        r := ruleByID[ev.RuleID]
        file := findFile(folder, ev.FilePath)
        bulk, panic := safeBulkParse(r, file, d.bulkLimit)
        if panic != "" {
            w.emit({"kind":"parse_error", "rule_id": r.ID, "file_path": ev.FilePath, "error": panic})
            continue
        }
        for _, rec := range bulk.Records {
            if err := batch.Append(
                cmd.ArchiveSha, cmd.SourceLabel,
                extractVictimFolder(ev.FilePath),
                ev.FilePath, r.ID, r.Family, rec,
            ); err != nil {
                return fmt.Errorf("batch append: %w", err)
            }
            records++
            d.metrics.recordsEmitted.WithLabelValues(r.ID, r.Family).Inc()
        }
    }

    if err := batch.Send(); err != nil {
        return fmt.Errorf("batch send: %w", err)
    }
    d.archives.Add(1)
    w.emit({"kind":"run_done", "records": records, "wall_ms": ms, "rules_fired": rulesFired})
    return nil
}
```

Points:
- `cmd.ArchiveSha`, `cmd.SourceLabel`: the run command gains these fields
  so the daemon can label records without Python round-tripping them.
- `extractVictimFolder(path)` mirrors the Python helper that derives the
  per-victim path segment [2]. Thirty lines of Go.
- On error the batch is abandoned (no `Send`), the caller gets an error via
  stdout. This is strict: a mid-archive failure means NO records land. That
  matches the semantics of "Python errors out and we throw away the pending
  queue" today, so no regression.

### Flow-control, deadlock elimination

- stdout only carries metadata (verdict, parse_error, run_done, truncated).
  Metadata volume per archive is ~dozen lines. Pipe never backpressures.
- Records bypass stdout entirely. The 4096-slot channel only sees metadata.
- Python has nothing to block on. No TPE. No semaphore. No pending batches.

## Python-side design

### gotractor_client.GotractorDaemon.run

Returns `(stream, done_q)` as today. The `stream` iterator now yields ONLY:
- `{"_kind": "verdict", "family": ..., "root": ..., "files": ...}`
- `{"_kind": "parse_error", "rule_id": ..., "file_path": ..., "error": ..., "kind_code": ...}`
- `{"_kind": "truncated", ...}`

Record messages never appear. If one does (bug, mixed mode), we drop it +
log a warning (`gotractor.daemon.unexpected_record`).

### pipeline._gotractor_insert_daemon

Shrinks to the orchestration skeleton:

```python
def _gotractor_insert_daemon(daemon, sink, dest, blob_path, source_label):
    sink.ensure_schema()
    archive_sha = blob_path.stem
    stream, done_q = daemon.run(
        dest, source_label=source_label, archive_sha=archive_sha,
    )
    families = []
    parse_errors = {}
    for msg in stream:
        if msg["_kind"] == "verdict":
            fam = msg.get("family")
            if fam: families.append(fam)
        elif msg["_kind"] == "parse_error":
            parse_errors[msg["file_path"] or ""] = (
                msg["kind_code"], msg["error"]
            )
            _log.warning("stealer.gotractor_parse_error", ...)
        # truncated: log, continue
    done = done_q.get(timeout=10)
    _log.info("stealer.gotractor_run", archive=archive_sha,
              records=done.records, families=families, ...)
    return done.records, families, parse_errors
```

That is it. No batching, no TPE, no semaphore, no sink.insert_rows anywhere.

### sink.ClickHouseRecordsSink

Stays. The ensure_schema() + MV + sentinel-repair work still belongs
to Python (schema is operator concern, not per-record). insert_rows()
is unused by the pipeline but kept for backfill CLI tools and tests.

## Compose / deploy

- `compose.yaml` stealer-processor env adds `EYENET_GOTRACTOR_CH_DSN`
  pointing at the internal CH service (`tcp://eyenet:${CH_PASSWORD}@clickhouse:9000/stealer`).
- CH user has GRANT INSERT ON stealer.extracted_records already (via existing eyenet role).

## Testability

- Dev workflows that run gotractor without CH (manual catalog testing,
  poc work in `development/poc-gotractor/`) keep working because the
  DSN is optional. Without it, gotractor stays in legacy stdout mode.
  This matches how Python's sink is optional today.
- Add one integration test: spin up a dev CH container, run gotractor
  with DSN, assert extracted_records rows land with the right shape.
  Lives under `tests/integration/stealer/test_gotractor_direct_ch.py`
  behind the `integration` marker + `EYENET_E2E=1` gate.

## Rollout plan

1. Land the Go side behind `--ch-dsn` opt-in. Legacy path still works.
2. Ship as v1.4.0 (not a point release: this changes the service's
   data path).
3. Deploy with `EYENET_GOTRACTOR_CH_DSN` set.
4. Watch `gotractor_archives_total`, `records_emitted_total`,
   `docker stats` RSS for both processes. Expected:
   - Python RSS: ~400 MB total (no pending batches, no record dicts)
   - Go RSS: ~2-3 GB per archive (just readFolder's heap)
   - Combined: ~3 GB well under 15 GB
5. Reindex finishes. Prod stays breathable.

## What we are explicitly NOT doing in this scope

- Streaming readFolder (one file at a time through the extraction).
  That is the next-level optimisation, saves 2-3 GB of Go heap. Worth it
  but orthogonal: the deadlock + Python blowup goes away without it.
- Rewriting the Python sink to use clickhouse-connect's native protocol.
  Dead code post-this-change, left alone.
- Changing MV-cascade behaviour or part-merge settings. CH-side tuning
  is a separate scope. Expected: smaller batches from Go (10k) create
  smaller parts than Python (50k) did, so merges happen more often but
  each is cheaper.

## Open questions before coding

1. Do we also move extract_wallets to Go-direct? It is the second
   insert path. Scope creep but same shape of fix. Vote: yes, same patch,
   same flag.
2. CH connection failure handling. Right now Python's sink retries
   via clickhouse-connect default. Go's clickhouse-go has similar. Use
   its default retry policy; surface errors through the parse_error
   channel so Python's file_audit bookkeeping sees them.
3. ClickHouse username/password in compose: reuse `EYENET_CLICKHOUSE_*`
   or introduce a dedicated `EYENET_GOTRACTOR_CH_*` set? Vote: reuse,
   less sprawl.

## Fight-me checklist (why this is the right call and not over-engineering)

- Python-as-data-conduit is strictly wasted effort: it owns no business
  logic about the records, it just moves bytes it cannot even hold. A
  pipeline stage that owns no business logic is dead weight.
- The deadlock and OOM we have been chasing all day are both symptoms
  of forcing records through Python. Delete the stage, delete the
  symptoms.
- clickhouse-go is a mature driver, part of ClickHouse Inc's own
  ecosystem. No new NIH.
- The stdout path stays for everything Python legitimately needs
  (metadata, orchestration), so the control plane is unchanged.
- Rollback is trivial: don't set EYENET_GOTRACTOR_CH_DSN, legacy path
  runs.
