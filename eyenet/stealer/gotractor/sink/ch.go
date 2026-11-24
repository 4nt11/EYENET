// Package sink owns the per-run ClickHouse batch insert for records
// emitted from the daemon run loop. See development/GOTRACTOR_DIRECT_CH_SCOPE.md.
//
// The design is a thin wrapper over clickhouse-go/v2's prepared-batch
// API. Daemon opens ONE batch per run (= per archive), appends every
// emitted record to it, sends the batch at end-of-run. Records never
// leave Go memory for the stdout path.
//
// Legacy stdout-record mode stays available when --ch-dsn is not set
// or when Dial fails -- the caller falls back and emits records on
// stdout as before. Dev workflows + manual CLI runs keep working.
package sink

import (
	"context"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/ClickHouse/clickhouse-go/v2"
	"github.com/ClickHouse/clickhouse-go/v2/lib/driver"
)

func envU64(k string, def uint64) uint64 {
	if v := os.Getenv(k); v != "" {
		if n, err := strconv.ParseUint(v, 10, 64); err == nil {
			return n
		}
	}
	return def
}

// RecordColumns is the extracted_records insert schema, in the order
// expected by batch.Append. Keep in lock-step with eyenet/stealer/
// clickhouse.py _RECORDS_CREATE.
//
//	archive_sha256 FixedString(64)
//	source         LowCardinality(String)
//	archive_type   LowCardinality(String)  -- plane tag: stealer_victim | flat_credlist
//	victim_folder  String
//	file_path      String
//	rule_id        LowCardinality(String)
//	family         LowCardinality(String)
//	fields         Map(String, String)
var RecordColumns = []string{
	"archive_sha256", "source", "archive_type", "victim_folder",
	"file_path", "rule_id", "family", "fields",
}

// Plane base tables. The shared extracted_records table is retired in
// favour of two physical planes so the victim-plane MVs never scan a
// firehose block. See development/CH_PLANE_SEPARATION_SCOPE.md.
const (
	tableCredlist = "stealer.extracted_records_credlist" // flat_credlist firehose
	tableVictim   = "stealer.extracted_records_victim"   // stealer_victim plane
)

// tableFor routes a row to its physical base table by plane tag. Unknown
// tags fall to the firehose: the firehose is the safe dumping ground.
// Misrouting INTO the small victim plane poisons its MVs; misrouting out
// of it only dilutes the firehose it is 96.7% of anyway.
// ponytail: two planes, two tables; a third plane = a third branch here.
func tableFor(archiveType string) string {
	if archiveType == "stealer_victim" {
		return tableVictim
	}
	return tableCredlist
}

// CH is a per-process sink. One instance per daemon; a fresh batch is
// opened per archive run via BeginArchive.
type CH struct {
	conn     driver.Conn
	dialTime time.Time
}

// Open resolves dsn (clickhouse-go URL form) and verifies the server
// is reachable. Returns (nil, nil) when dsn is empty (opt-in mode);
// returns (nil, err) when dsn is set but Dial failed so the caller
// can choose whether to fall back or fail hard.
func Open(ctx context.Context, dsn string) (*CH, error) {
	if strings.TrimSpace(dsn) == "" {
		return nil, nil
	}
	opts, err := clickhouse.ParseDSN(dsn)
	if err != nil {
		return nil, fmt.Errorf("parse dsn: %w", err)
	}
	// Idle connection pool kept small: the daemon runs archives serially
	// (one `run` command at a time per req_id in the stealer-processor
	// use case), so 2 is plenty. The ingest pool CH wants on its side is
	// separate and driven by part merges.
	if opts.MaxOpenConns == 0 {
		opts.MaxOpenConns = 4
	}
	if opts.MaxIdleConns == 0 {
		opts.MaxIdleConns = 2
	}
	opts.ConnMaxLifetime = 30 * time.Minute
	// Suppress unsolicited server->client log packets during long INSERTs.
	// Without this CH's TCPHandler::sendProfileEvents() blocks on a full
	// send buffer, trips send_timeout (300s), and RSTs the socket -- the
	// client sees "connection reset by peer" on the next batch.Flush().
	// ponytail: send_logs_level=none, revisit if we ever want server logs.
	if opts.Settings == nil {
		opts.Settings = clickhouse.Settings{}
	}
	opts.Settings["send_logs_level"] = "none"
	conn, err := clickhouse.Open(opts)
	if err != nil {
		return nil, fmt.Errorf("open conn: %w", err)
	}
	pingCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	if err := conn.Ping(pingCtx); err != nil {
		_ = conn.Close()
		return nil, fmt.Errorf("ping ch: %w", err)
	}
	return &CH{conn: conn, dialTime: time.Now()}, nil
}

// Close releases the connection pool. Safe to call on a nil receiver
// so the daemon can call it unconditionally in defer.
func (c *CH) Close() error {
	if c == nil || c.conn == nil {
		return nil
	}
	return c.conn.Close()
}

// Enabled reports whether this sink will accept records. The daemon
// checks this once per cmdRun to decide "insert directly" vs "emit to
// stdout the old way."
func (c *CH) Enabled() bool { return c != nil && c.conn != nil }

// asyncFlushRowsPer is how many rows we pack into a single
// AsyncInsert call. 500 keeps each VALUES-form INSERT under the
// bumped max_query_size (100 MiB) even when the fields map is large,
// and keeps the client-side buffer small so Flush() is quick.
const asyncFlushRowsPer = 500

// rowData is one buffered record awaiting an AsyncInsert dispatch.
// The daemon calls Append; those rows accumulate here until either
// asyncFlushRowsPer is reached (auto-flush) or the daemon explicitly
// calls Flush / Send / Abort. Kept as a flat struct (not map) to
// avoid per-row allocation churn on the hot path.
type rowData struct {
	archiveSha256, source, archiveType, victimFolder, filePath, ruleID, family string
	fields                                                                     map[string]string
}

// ArchiveBatch is one archive's INSERT-in-progress. v1.3.11.2 switched
// from clickhouse-go's PrepareBatch (Native-protocol synchronous send
// per Flush) to AsyncInsert with VALUES-form SQL + async_insert=1 /
// wait_for_async_insert=0 settings. CH buffers the inserts server-side
// and acks as soon as the data is received, not merged. Throughput on
// ULP drops goes from ~2s per 2500-row Flush to sub-100ms per 500-row
// AsyncInsert fire-and-forget. Still not goroutine-safe: single-run,
// single-thread per instance.
type ArchiveBatch struct {
	ch     *CH
	ctx    context.Context
	buffer []rowData
	count  int // total appended since Begin, never reset
}

// BeginArchive opens a new logical INSERT for the given archive. Does
// not actually touch the wire yet; the first AsyncInsert fires on the
// first Flush() call. The caller is responsible for calling Send OR
// Abort before letting this value go out of scope - Abort drops the
// buffer so the Go heap does not retain the archive's rows.
func (c *CH) BeginArchive(ctx context.Context) (*ArchiveBatch, error) {
	if !c.Enabled() {
		return nil, fmt.Errorf("sink.CH is not enabled")
	}
	// v1.3.10.2 drain callbacks still needed: with async_insert=1 the
	// server emits ProgressEvents on INSERT ack just like the Native
	// path. Omitting the callbacks would re-surface the
	// "connection reset by peer" window.
	//
	// async_insert_busy_timeout_ms (10s) + async_insert_max_data_size
	// (100 MiB) let CH batch our 500-row AsyncInserts into merge-sized
	// blocks before writing parts. async_insert_use_adaptive_busy_timeout
	// lets CH shorten the busy timeout when throughput is high, so
	// steady-state we see sub-second end-to-end latency.
	//
	// wait_for_async_insert: FIRE-AND-FORGET (0) is the design (see the
	// ArchiveBatch doc). v1.4 fix: this had regressed to 1, which makes each
	// gotractor insert block until CH finishes the server-side flush. On the
	// Wasabi-primary prod the flush fans out to ~16 materialized views, each
	// writing parts to S3; a 100 MiB block's flush routinely exceeds the 120s
	// wait and trips "Wait for async insert timeout" (code 159), failing every
	// archive and wedging the reindex. The flush is S3-wait-bound, not CPU, so
	// blocking the producer buys nothing. With 0, gotractor acks on receipt and
	// CH drains to S3 in the background; per-archive extraction pauses let the
	// server catch up. Env-overridable for the rare batch-durable run that
	// wants to pay the wait. Durability note in the Send() doc still applies.
	//
	// max_query_size is bumped to 100 MB because a 500-row VALUES
	// insert with a fat fields map (say 50 KB per row of key:value
	// pairs) can produce a ~25 MB SQL text. CH's 256 KB default would
	// reject it.
	asyncCtx := clickhouse.Context(ctx,
		clickhouse.WithProgress(func(*clickhouse.Progress) {}),
		clickhouse.WithProfileEvents(func([]clickhouse.ProfileEvent) {}),
		clickhouse.WithSettings(clickhouse.Settings{
			"async_insert":                           uint8(1),
			"wait_for_async_insert":                  uint8(envU64("EYENET_CH_WAIT_FOR_ASYNC_INSERT", 0)),
			"async_insert_busy_timeout_ms":           envU64("EYENET_CH_ASYNC_BUSY_TIMEOUT_MS", 10_000),
			"async_insert_max_data_size":             envU64("EYENET_CH_ASYNC_MAX_DATA_SIZE", 104_857_600),
			"async_insert_use_adaptive_busy_timeout": uint8(1),
			"max_query_size":                         uint64(100_000_000),
		}),
	)
	return &ArchiveBatch{
		ch:     c,
		ctx:    asyncCtx,
		buffer: make([]rowData, 0, asyncFlushRowsPer*2),
	}, nil
}

// Append queues one record. Auto-flushes when the buffer reaches
// asyncFlushRowsPer so the Go heap never holds more than ~1000 rows.
// Field types must match the column order in RecordColumns:
//
//	archiveSha256 string (hex, 64 chars)
//	source        string
//	archiveType   string (stealer_victim | flat_credlist)
//	victimFolder  string
//	filePath      string
//	ruleID        string
//	family        string
//	fields        map[string]string
//
// Returns an error only when the auto-flush fires and the server
// rejects the batch (schema mismatch, auth, offline). Transient
// network errors surface at the next Flush / Send.
func (ab *ArchiveBatch) Append(
	archiveSha256, source, archiveType, victimFolder, filePath, ruleID, family string,
	fields map[string]string,
) error {
	ab.buffer = append(ab.buffer, rowData{
		archiveSha256: archiveSha256, source: source, archiveType: archiveType,
		victimFolder: victimFolder, filePath: filePath, ruleID: ruleID, family: family, fields: fields,
	})
	ab.count++
	if len(ab.buffer) >= asyncFlushRowsPer {
		return ab.Flush()
	}
	return nil
}

// Count is how many records have been appended since BeginArchive.
// The daemon uses this as the run_done `records` field so Python sees
// the same count whether sink mode or stdout mode is in play.
func (ab *ArchiveBatch) Count() int { return ab.count }

// Flush ships the currently-buffered rows via one or more AsyncInsert
// calls, each carrying up to asyncFlushRowsPer rows. With wait=false
// the server acks on receipt (not merge), so each call returns in
// milliseconds. The server's own async-insert buffer handles merge
// cadence per async_insert_busy_timeout_ms.
func (ab *ArchiveBatch) Flush() error {
	if len(ab.buffer) == 0 {
		return nil
	}
	// Partition the buffer by target plane table, then chunk each
	// partition into asyncFlushRowsPer-row AsyncInserts. In practice an
	// archive is uniformly one plane so byTable has a single entry, but
	// routing per row keeps a mixed archive (e.g. a loose combolist .txt
	// inside a victim drop) correct without a per-archive assumption.
	byTable := make(map[string][]rowData, 2)
	for _, row := range ab.buffer {
		t := tableFor(row.archiveType)
		byTable[t] = append(byTable[t], row)
	}
	rowPlaceholder := "(" + strings.Repeat("?,", len(RecordColumns)-1) + "?)"
	colList := strings.Join(RecordColumns, ", ")
	for table, rows := range byTable {
		insertSQL := fmt.Sprintf("INSERT INTO %s (%s) VALUES ", table, colList)
		for start := 0; start < len(rows); start += asyncFlushRowsPer {
			end := start + asyncFlushRowsPer
			if end > len(rows) {
				end = len(rows)
			}
			slice := rows[start:end]

			var b strings.Builder
			b.Grow(len(insertSQL) + len(slice)*(len(rowPlaceholder)+1))
			b.WriteString(insertSQL)
			for i := range slice {
				if i > 0 {
					b.WriteByte(',')
				}
				b.WriteString(rowPlaceholder)
			}

			args := make([]any, 0, len(slice)*len(RecordColumns))
			for _, row := range slice {
				args = append(args,
					row.archiveSha256, row.source, row.archiveType, row.victimFolder,
					row.filePath, row.ruleID, row.family, row.fields,
				)
			}

			if err := ab.ch.conn.AsyncInsert(ab.ctx, b.String(), false, args...); err != nil {
				ab.buffer = ab.buffer[:0] // drop, caller abandons the run
				return fmt.Errorf("async insert %s (rows %d-%d of %d): %w",
					table, start, end, len(rows), err)
			}
		}
	}
	ab.buffer = ab.buffer[:0]
	return nil
}

// Send finalises the INSERT: flushes the remaining tail. Unlike the
// pre-v1.3.11.2 Native-protocol Send, this returns before CH has
// actually written the data to disk; the server-side async-insert
// buffer carries the work forward. A server crash in the sub-second
// window between Send() and disk-write drops the tail rows. For
// research/CTI workloads that trade-off is acceptable; a batch
// transactional workload would need wait_for_async_insert=1 and
// loses the throughput win.
func (ab *ArchiveBatch) Send() error { return ab.Flush() }

// Abort discards the buffer without sending. Used when a parse or
// panic takes down a run mid-stream; the caller emits a parse_error
// on stdout and abandons whatever rows had been queued.
func (ab *ArchiveBatch) Abort() error {
	ab.buffer = nil
	return nil
}
