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
	"strings"
	"time"

	"github.com/ClickHouse/clickhouse-go/v2"
	"github.com/ClickHouse/clickhouse-go/v2/lib/driver"
)

// RecordColumns is the extracted_records insert schema, in the order
// expected by batch.Append. Keep in lock-step with eyenet/stealer/
// clickhouse.py _RECORDS_CREATE.
//
//	archive_sha256 FixedString(64)
//	source         LowCardinality(String)
//	victim_folder  String
//	file_path      String
//	rule_id        LowCardinality(String)
//	family         LowCardinality(String)
//	fields         Map(String, String)
var RecordColumns = []string{
	"archive_sha256", "source", "victim_folder",
	"file_path", "rule_id", "family", "fields",
}

const defaultTable = "stealer.extracted_records"

// CH is a per-process sink. One instance per daemon; a fresh batch is
// opened per archive run via BeginArchive.
type CH struct {
	conn     driver.Conn
	table    string
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
	return &CH{conn: conn, table: defaultTable, dialTime: time.Now()}, nil
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

// ArchiveBatch is one archive's INSERT-in-progress. Short-lived: the
// daemon opens one at the start of a run, calls Append per record,
// Send once at the end. Not goroutine-safe: single-run, single-thread
// per instance.
type ArchiveBatch struct {
	batch driver.Batch
	count int
}

// BeginArchive opens a prepared INSERT batch for the given archive.
// The caller is responsible for calling Send OR Abort before letting
// this value go out of scope -- an un-finished batch leaks a server-
// side connection until the pool reaps it.
func (c *CH) BeginArchive(ctx context.Context) (*ArchiveBatch, error) {
	if !c.Enabled() {
		return nil, fmt.Errorf("sink.CH is not enabled")
	}
	sql := fmt.Sprintf(
		"INSERT INTO %s (%s)",
		c.table, strings.Join(RecordColumns, ", "),
	)
	b, err := c.conn.PrepareBatch(ctx, sql)
	if err != nil {
		return nil, fmt.Errorf("prepare batch: %w", err)
	}
	return &ArchiveBatch{batch: b}, nil
}

// Append queues one record for insert. Field types must match the
// column order in RecordColumns:
//
//	archiveSha256 string (hex, 64 chars)
//	source        string
//	victimFolder  string
//	filePath      string
//	ruleID        string
//	family        string
//	fields        map[string]string
//
// Returns an error only on type mismatch at the driver boundary; EOF /
// network errors surface at Send time.
func (ab *ArchiveBatch) Append(
	archiveSha256, source, victimFolder, filePath, ruleID, family string,
	fields map[string]string,
) error {
	if err := ab.batch.Append(
		archiveSha256, source, victimFolder, filePath, ruleID, family, fields,
	); err != nil {
		return fmt.Errorf("append: %w", err)
	}
	ab.count++
	return nil
}

// Count is how many records have been appended since BeginArchive.
// The daemon uses this as the run_done `records` field so Python sees
// the same count whether sink mode or stdout mode is in play.
func (ab *ArchiveBatch) Count() int { return ab.count }

// Flush ships the currently-buffered rows to CH and keeps the batch
// usable. On the native protocol this is a block-level transmit that
// resets the client-side buffer; subsequent Append calls continue
// building the same logical INSERT. Caller flushes periodically so
// the Go heap never holds the full archive worth of rows.
func (ab *ArchiveBatch) Flush() error {
	if err := ab.batch.Flush(); err != nil {
		return fmt.Errorf("flush: %w", err)
	}
	return nil
}

// Send finalises the INSERT. After Send, the batch is unusable --
// start a new one for the next archive. Blocks on network + CH
// acceptance; the caller runs this at end-of-run so stdout stays
// clear of the record stream.
func (ab *ArchiveBatch) Send() error {
	if err := ab.batch.Send(); err != nil {
		return fmt.Errorf("send: %w", err)
	}
	return nil
}

// Abort discards the batch without sending. Used when a parse or panic
// takes down a run mid-stream; the caller emits a parse_error on stdout
// and abandons whatever rows had been queued. Matches the pre-change
// semantics (Python abandons its in-flight list on run failure).
func (ab *ArchiveBatch) Abort() error {
	return ab.batch.Abort()
}
