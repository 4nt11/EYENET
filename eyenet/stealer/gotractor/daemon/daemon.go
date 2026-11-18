// Package daemon implements the long-lived serve mode for gotractor.
//
// Protocol: newline-delimited JSON on stdin + stdout. One command per line
// in, zero or more lines out per command, framed by a terminating line.
//
// Commands:
//   {"cmd":"run","req_id":"...","input":"/path/to/folder","source_label":"..."}
//   {"cmd":"reload","req_id":"..."}
//   {"cmd":"stats","req_id":"..."}
//   {"cmd":"shutdown","req_id":"..."}
//
// Responses (every line carries the req_id so the caller can demultiplex
// if it pipelines commands):
//   {"kind":"verdict","req_id":"...","family":"...","root":"...","files":N}
//   {"kind":"record","req_id":"...","rule_id":"...","family":"...","file_path":"...","fields":{...}}
//   {"kind":"truncated","req_id":"...","rule_id":"...","file_path":"...","emitted":N,"total_seen":N}
//   {"kind":"parse_error","req_id":"...","rule_id":"...","file_path":"...","error":"...","kind_code":"panic|timeout|decode"}
//   {"kind":"run_done","req_id":"...","records":N,"wall_ms":N,"rules_fired":{"<rule_id>":N}}
//   {"kind":"reloaded","req_id":"...","rules":N,"families":N,"trigger":"cmd|fs"}
//   {"kind":"stats","req_id":"...","uptime_ms":N,"archives":N,"records":N,"catalog":{"rules":N,"families":N,"loaded_at":"..."}}
//   {"kind":"shutdown_ack","req_id":"..."}
//   {"kind":"error","req_id":"...","error":"..."}
//
// Catalog is reloaded automatically when any *.yaml file under rules-dir
// or families-dir changes (fsnotify watcher goroutine). Writes are
// debounced so a batch of editor saves ends in one reload.
//
// Prometheus HTTP endpoint on --metrics-port. Metrics:
//   gotractor_archives_total               counter
//   gotractor_records_emitted_total        counter{rule_id,family}
//   gotractor_records_rejected_total       counter{rule_id}
//   gotractor_archive_duration_seconds     histogram
//   gotractor_catalog_rules                gauge
//   gotractor_catalog_families              gauge
//   gotractor_catalog_reloads_total        counter{trigger}
//   gotractor_catalog_reload_errors_total  counter
package daemon

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"log"
	"net/http"
	_ "net/http/pprof" // registers /debug/pprof/* on the default mux (same mux as /metrics)
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/fsnotify/fsnotify"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"eyenet.io/stealer/gotractor/engine"
)

// Daemon owns the live rule set + metrics + command loop.
type Daemon struct {
	rulesDir    string
	familiesDir string
	bulkLimit   int

	// Atomic pointer to the current catalog so reads from the run loop
	// never block a hot-reload and vice versa.
	catalog atomic.Pointer[catalogSnapshot]

	// Process-level stats surfaced via the stats command.
	startedAt time.Time
	archives  atomic.Uint64
	records   atomic.Uint64

	metrics *metrics
}

type catalogSnapshot struct {
	Rules    []engine.Rule
	Families []engine.Family
	LoadedAt time.Time
}

type metrics struct {
	archivesTotal       prometheus.Counter
	recordsEmitted      *prometheus.CounterVec
	recordsRejected     *prometheus.CounterVec
	archiveDuration     prometheus.Histogram
	catalogRules        prometheus.Gauge
	catalogFamilies     prometheus.Gauge
	catalogReloads      *prometheus.CounterVec
	catalogReloadErrors prometheus.Counter
}

func newMetrics(reg *prometheus.Registry) *metrics {
	m := &metrics{
		archivesTotal: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "gotractor_archives_total",
			Help: "Total archives processed via the daemon run command.",
		}),
		recordsEmitted: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "gotractor_records_emitted_total",
			Help: "Extracted records per rule and family.",
		}, []string{"rule_id", "family"}),
		recordsRejected: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "gotractor_records_rejected_total",
			Help: "Records rejected by reject_patterns per rule.",
		}, []string{"rule_id"}),
		archiveDuration: prometheus.NewHistogram(prometheus.HistogramOpts{
			Name:    "gotractor_archive_duration_seconds",
			Help:    "Wall-clock time per archive run.",
			Buckets: prometheus.DefBuckets,
		}),
		catalogRules: prometheus.NewGauge(prometheus.GaugeOpts{
			Name: "gotractor_catalog_rules",
			Help: "Rules currently loaded.",
		}),
		catalogFamilies: prometheus.NewGauge(prometheus.GaugeOpts{
			Name: "gotractor_catalog_families",
			Help: "Families currently loaded.",
		}),
		catalogReloads: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "gotractor_catalog_reloads_total",
			Help: "Successful catalog reloads by trigger (cmd / fs / boot).",
		}, []string{"trigger"}),
		catalogReloadErrors: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "gotractor_catalog_reload_errors_total",
			Help: "Catalog reload attempts that failed (kept the previous catalog live).",
		}),
	}
	reg.MustRegister(
		m.archivesTotal, m.recordsEmitted, m.recordsRejected,
		m.archiveDuration, m.catalogRules, m.catalogFamilies,
		m.catalogReloads, m.catalogReloadErrors,
	)
	return m
}

// New boots a Daemon, loads the initial catalog, and starts the
// fsnotify watcher. Caller is expected to call Serve to run the loop.
func New(rulesDir, familiesDir string, bulkLimit int) (*Daemon, error) {
	if bulkLimit <= 0 {
		bulkLimit = 100000
	}
	reg := prometheus.NewRegistry()
	d := &Daemon{
		rulesDir:    rulesDir,
		familiesDir: familiesDir,
		bulkLimit:   bulkLimit,
		startedAt:   time.Now(),
		metrics:     newMetrics(reg),
	}
	if err := d.loadCatalog("boot"); err != nil {
		return nil, err
	}
	// Register the Prometheus registry for HTTP exposure.
	http.Handle("/metrics", promhttp.HandlerFor(reg, promhttp.HandlerOpts{}))
	return d, nil
}

// ServeMetrics binds a Prometheus /metrics endpoint on the given port.
// Non-blocking; errors from the listener go to the log.
func (d *Daemon) ServeMetrics(port int) {
	addr := fmt.Sprintf(":%d", port)
	go func() {
		srv := &http.Server{Addr: addr, ReadHeaderTimeout: 5 * time.Second}
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Printf("metrics http: %v", err)
		}
	}()
	log.Printf("gotractor: metrics on http://localhost%s/metrics", addr)
}

// Serve runs the command loop until stdin closes or a 'shutdown' command
// arrives. Writes one JSON message per line to w.
func (d *Daemon) Serve(ctx context.Context, r io.Reader, w io.Writer) error {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()

	// fsnotify watcher. Catalog reloads are debounced so a wave of
	// editor saves ends in one reload.
	watcher, err := fsnotify.NewWatcher()
	if err != nil {
		return fmt.Errorf("fsnotify: %w", err)
	}
	defer watcher.Close()
	if err := watcher.Add(d.rulesDir); err != nil {
		log.Printf("watch %s: %v", d.rulesDir, err)
	}
	if err := watcher.Add(d.familiesDir); err != nil {
		log.Printf("watch %s: %v", d.familiesDir, err)
	}
	// Stream + batch: workers do channel-send only (atomic, zero
	// contention), one goroutine drains into a 64KB bufio to stdout.
	// watchLoop shares this writer so the only process touching stdout
	// is the drain goroutine; before this patch, watchLoop constructed
	// its OWN lockedWriter around the same stdout, so two independent
	// mutexes could interleave bytes on a hot reload. Fixed.
	writer := newLockedWriter(w)
	defer writer.close()
	go d.watchLoop(ctx, watcher, writer)
	// Run-command concurrency: the catalog is an atomic pointer,
	// metrics are prom counters (goroutine-safe), writer is locked.
	// Everything else cmdRun touches is request-local, so N runs can
	// execute in parallel. Bound at NumCPU; override with
	// EYENET_GOTRACTOR_WORKERS. reload/stats/shutdown stay serial and
	// drain in-flight runs first so shutdown_ack is truly the last line.
	workers := runtime.NumCPU()
	if v := os.Getenv("EYENET_GOTRACTOR_WORKERS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			workers = n
		}
	}
	sem := make(chan struct{}, workers)
	var wg sync.WaitGroup
	scan := bufio.NewScanner(r)
	scan.Buffer(make([]byte, 64*1024), 16*1024*1024)
	for scan.Scan() {
		line := strings.TrimSpace(scan.Text())
		if line == "" {
			continue
		}
		var peek commandEnv
		if json.Unmarshal([]byte(line), &peek) == nil && peek.Cmd == "run" {
			wg.Add(1)
			sem <- struct{}{}
			go func(ln string) {
				defer wg.Done()
				defer func() { <-sem }()
				if cmd, err := d.dispatch(ctx, ln, writer); err != nil {
					writer.emit(map[string]any{
						"kind": "error", "req_id": cmd.ReqID, "error": err.Error(),
					})
				}
			}(line)
			continue
		}
		// Serial path: reload / stats / shutdown. Drain in-flight runs
		// before touching these so stats and shutdown_ack reflect the
		// final state.
		wg.Wait()
		if cmd, err := d.dispatch(ctx, line, writer); err != nil {
			writer.emit(map[string]any{
				"kind": "error", "req_id": cmd.ReqID, "error": err.Error(),
			})
		} else if cmd.Cmd == "shutdown" {
			return nil
		}
	}
	wg.Wait()
	return scan.Err()
}

type commandEnv struct {
	Cmd         string `json:"cmd"`
	ReqID       string `json:"req_id"`
	Input       string `json:"input,omitempty"`
	SourceLabel string `json:"source_label,omitempty"`
}

func (d *Daemon) dispatch(ctx context.Context, line string, w *lockedWriter) (commandEnv, error) {
	var cmd commandEnv
	if err := json.Unmarshal([]byte(line), &cmd); err != nil {
		return cmd, fmt.Errorf("parse command: %w", err)
	}
	switch cmd.Cmd {
	case "run":
		return cmd, d.cmdRun(ctx, cmd, w)
	case "reload":
		if err := d.loadCatalog("cmd"); err != nil {
			return cmd, err
		}
		snap := d.catalog.Load()
		w.emit(map[string]any{
			"kind": "reloaded", "req_id": cmd.ReqID,
			"rules": len(snap.Rules), "families": len(snap.Families), "trigger": "cmd",
		})
		return cmd, nil
	case "stats":
		snap := d.catalog.Load()
		w.emit(map[string]any{
			"kind":      "stats",
			"req_id":    cmd.ReqID,
			"uptime_ms": time.Since(d.startedAt).Milliseconds(),
			"archives":  d.archives.Load(),
			"records":   d.records.Load(),
			"catalog": map[string]any{
				"rules":     len(snap.Rules),
				"families":  len(snap.Families),
				"loaded_at": snap.LoadedAt.UTC().Format(time.RFC3339),
			},
		})
		return cmd, nil
	case "shutdown":
		w.emit(map[string]any{"kind": "shutdown_ack", "req_id": cmd.ReqID})
		return cmd, nil
	}
	return cmd, fmt.Errorf("unknown cmd: %q", cmd.Cmd)
}

func (d *Daemon) cmdRun(_ context.Context, cmd commandEnv, w *lockedWriter) error {
	if cmd.Input == "" {
		return fmt.Errorf("'run' needs an 'input' path")
	}
	start := time.Now()
	folder, err := readFolder(cmd.Input)
	if err != nil {
		return err
	}
	snap := d.catalog.Load()
	rules := snap.Rules
	ruleByID := map[string]engine.Rule{}
	for _, r := range rules {
		ruleByID[r.ID] = r
	}
	result, runPanic := safeRunRules(rules, folder)
	if runPanic != "" {
		// RunRules took down the whole folder evaluation. We cannot
		// attribute this to a single file (RunRules does not stream),
		// so emit one archive-wide parse_error row keyed on an empty
		// file_path. The Python side writes this onto every file in
		// the archive that had no better attribution.
		w.emit(map[string]any{
			"kind":      "parse_error",
			"req_id":    cmd.ReqID,
			"rule_id":   "",
			"file_path": "",
			"error":     runPanic,
			"kind_code": "panic",
		})
	}

	w.emit(map[string]any{
		"kind":   "verdict",
		"req_id": cmd.ReqID,
		"family": result.Family,
		"root":   folder.RootName,
		"files":  len(folder.Files),
	})

	records := 0
	rulesFired := map[string]int{}
	seen := map[string]bool{}
	for _, ev := range result.Evaluations {
		if !ev.Matched || ev.Layer != "content" {
			continue
		}
		key := ev.RuleID + "::" + ev.FilePath
		if seen[key] {
			continue
		}
		seen[key] = true
		r, ok := ruleByID[ev.RuleID]
		if !ok {
			continue
		}
		var file engine.ContentInput
		for _, f := range folder.Files {
			if f.Path == ev.FilePath {
				file = f
				break
			}
		}
		bulk, bulkPanic := safeBulkParse(r, file, d.bulkLimit)
		if bulkPanic != "" {
			w.emit(map[string]any{
				"kind":      "parse_error",
				"req_id":    cmd.ReqID,
				"rule_id":   r.ID,
				"file_path": ev.FilePath,
				"error":     bulkPanic,
				"kind_code": "panic",
			})
			d.metrics.recordsRejected.WithLabelValues(r.ID).Inc()
			continue
		}
		for _, rec := range bulk.Records {
			w.emit(map[string]any{
				"kind":      "record",
				"req_id":    cmd.ReqID,
				"rule_id":   r.ID,
				"family":    r.Family,
				"file_path": ev.FilePath,
				"fields":    rec,
			})
			records++
			rulesFired[r.ID]++
			d.metrics.recordsEmitted.WithLabelValues(r.ID, r.Family).Inc()
		}
		if bulk.Truncated {
			rejected := bulk.Total - len(bulk.Records)
			d.metrics.recordsRejected.WithLabelValues(r.ID).Add(float64(rejected))
			w.emit(map[string]any{
				"kind":       "truncated",
				"req_id":     cmd.ReqID,
				"rule_id":    r.ID,
				"file_path":  ev.FilePath,
				"emitted":    len(bulk.Records),
				"total_seen": bulk.Total,
			})
		}
	}

	wall := time.Since(start)
	d.archives.Add(1)
	d.records.Add(uint64(records))
	d.metrics.archivesTotal.Inc()
	d.metrics.archiveDuration.Observe(wall.Seconds())

	w.emit(map[string]any{
		"kind":        "run_done",
		"req_id":      cmd.ReqID,
		"records":     records,
		"wall_ms":     wall.Milliseconds(),
		"rules_fired": rulesFired,
	})
	return nil
}

func (d *Daemon) loadCatalog(trigger string) error {
	rules, families, err := engine.LoadRules(d.rulesDir, d.familiesDir)
	if err != nil {
		if d.metrics != nil {
			d.metrics.catalogReloadErrors.Inc()
		}
		return err
	}
	d.catalog.Store(&catalogSnapshot{
		Rules:    rules,
		Families: families,
		LoadedAt: time.Now(),
	})
	if d.metrics != nil {
		d.metrics.catalogRules.Set(float64(len(rules)))
		d.metrics.catalogFamilies.Set(float64(len(families)))
		d.metrics.catalogReloads.WithLabelValues(trigger).Inc()
	}
	log.Printf("gotractor: catalog loaded (%s): %d rules, %d families", trigger, len(rules), len(families))
	return nil
}

// watchLoop debounces fsnotify events (editor saves tend to burst) so a
// single operator save ends in a single catalog reload. On reload the
// daemon emits a reloaded message so the Python client can refresh any
// caches it keeps.
func (d *Daemon) watchLoop(ctx context.Context, w *fsnotify.Watcher, writer *lockedWriter) {
	const debounce = 250 * time.Millisecond
	var timer *time.Timer
	for {
		select {
		case <-ctx.Done():
			return
		case err, ok := <-w.Errors:
			if !ok {
				return
			}
			log.Printf("fsnotify error: %v", err)
		case ev, ok := <-w.Events:
			if !ok {
				return
			}
			if !strings.HasSuffix(ev.Name, ".yaml") {
				continue
			}
			if ev.Op&(fsnotify.Write|fsnotify.Create|fsnotify.Remove|fsnotify.Rename) == 0 {
				continue
			}
			if timer != nil {
				timer.Stop()
			}
			timer = time.AfterFunc(debounce, func() {
				if err := d.loadCatalog("fs"); err != nil {
					log.Printf("auto-reload failed: %v", err)
					writer.emit(map[string]any{
						"kind":  "error",
						"error": fmt.Sprintf("auto-reload failed: %v", err),
					})
					return
				}
				snap := d.catalog.Load()
				writer.emit(map[string]any{
					"kind":     "reloaded",
					"rules":    len(snap.Rules),
					"families": len(snap.Families),
					"trigger":  "fs",
				})
			})
		}
	}
}

// lockedWriter streams JSON-per-line emits through a dedicated writer
// goroutine so the N parallel run workers never contend on a mutex or
// on the stdout syscall. Design:
//
//   1. Workers marshal to a pooled bytes.Buffer in parallel. All the
//      reflection cost of encoding/json moves off the serial writer
//      goroutine and onto the N parallel matchers (where it scales).
//   2. The channel carries *bytes.Buffer, not `any`. No interface
//      boxing per record (300k/s hot path).
//   3. The writer goroutine owns stdout and a 64KB bufio.Writer. Its
//      only work per record is `bw.Write(buf.Bytes())` + Put the buf
//      back to the pool.
//   4. Time-based flush every 10ms for latency; byte-triggered flush
//      amortises syscalls.
type lockedWriter struct {
	ch   chan *bytes.Buffer
	done chan struct{}
}

var bufPool = sync.Pool{New: func() any {
	// Pre-size for the common record frame (~200-400 bytes). Records
	// with fat fields maps will grow; sync.Pool caps the retained
	// capacity after a few GCs, so a transient big record does not
	// permanently bloat the pool.
	b := new(bytes.Buffer)
	b.Grow(512)
	return b
}}

func getBuf() *bytes.Buffer {
	b := bufPool.Get().(*bytes.Buffer)
	b.Reset()
	return b
}

func newLockedWriter(w io.Writer) *lockedWriter {
	lw := &lockedWriter{
		ch:   make(chan *bytes.Buffer, 4096),
		done: make(chan struct{}),
	}
	go lw.run(w)
	return lw
}

func (l *lockedWriter) run(w io.Writer) {
	bw := bufio.NewWriterSize(w, 128*1024)
	ticker := time.NewTicker(10 * time.Millisecond)
	defer ticker.Stop()
	dirty := false
	for {
		select {
		case buf, ok := <-l.ch:
			if !ok {
				if dirty {
					_ = bw.Flush()
				}
				close(l.done)
				return
			}
			_, _ = bw.Write(buf.Bytes())
			// Bound retained capacity. One huge record (fat delimiter
			// row, 100KB+ fields map) must not permanently bloat a
			// pool slot: sync.Pool keeps the whole backing array even
			// after Reset. Drop oversize buffers; GC reclaims them.
			if buf.Cap() <= 8192 {
				bufPool.Put(buf)
			}
			dirty = true
		case <-ticker.C:
			if dirty {
				_ = bw.Flush()
				dirty = false
			}
		}
	}
}

// emit marshals v on the CALLING goroutine (workers parallelise this
// for free) and hands the serialised line to the writer goroutine.
// Trailing newline comes from json.Encoder.Encode.
func (l *lockedWriter) emit(v any) {
	buf := getBuf()
	enc := json.NewEncoder(buf)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(v)
	l.ch <- buf
}

func (l *lockedWriter) close() {
	close(l.ch)
	<-l.done
}

// safeBulkParse wraps engine.BulkParse in a defer/recover so a single
// bad file (parser panic on a malformed cookie JSON, OOB slice on a
// surprise byte sequence) does not take the whole daemon down. On
// recover the caller emits a parse_error msg attributed to the file,
// then continues with the next (rule, file) pair.
func safeBulkParse(r engine.Rule, file engine.ContentInput, limit int) (result engine.BulkResult, panicMsg string) {
	defer func() {
		if rec := recover(); rec != nil {
			panicMsg = truncErr(fmt.Sprint(rec))
		}
	}()
	return engine.BulkParse(r, file, limit), ""
}

// safeRunRules wraps engine.RunRules. A panic here cannot be attributed
// to a single file (RunRules folds the whole folder before returning),
// so the caller emits one archive-wide parse_error marker and then
// continues with an empty evaluation list.
func safeRunRules(rules []engine.Rule, folder engine.VictimFolder) (result engine.RunResult, panicMsg string) {
	defer func() {
		if rec := recover(); rec != nil {
			panicMsg = truncErr(fmt.Sprint(rec))
		}
	}()
	return engine.RunRules(rules, folder), ""
}

func truncErr(s string) string {
	const max = 400
	if len(s) > max {
		return s[:max]
	}
	return s
}

// readFolder mirrors the main CLI helper but lives here to keep the
// daemon package self-contained. On a single-file input it wraps it as
// a one-file folder; on a directory it walks the tree reading every
// file as UTF-8 text.
func readFolder(path string) (engine.VictimFolder, error) {
	info, err := os.Stat(path)
	if err != nil {
		return engine.VictimFolder{}, err
	}
	if !info.IsDir() {
		b, err := os.ReadFile(path)
		if err != nil {
			return engine.VictimFolder{}, err
		}
		return engine.VictimFolder{
			RootName: filepath.Base(path),
			Files:    []engine.ContentInput{{Path: filepath.Base(path), Text: string(b)}},
		}, nil
	}
	root := filepath.Clean(path)
	var files []engine.ContentInput
	err = filepath.WalkDir(root, func(p string, d fs.DirEntry, werr error) error {
		if werr != nil {
			return nil
		}
		if d.IsDir() {
			return nil
		}
		rel, _ := filepath.Rel(root, p)
		rel = filepath.ToSlash(rel)
		b, err := os.ReadFile(p)
		if err != nil {
			return nil
		}
		files = append(files, engine.ContentInput{Path: rel, Text: string(b)})
		return nil
	})
	if err != nil {
		return engine.VictimFolder{}, err
	}
	return engine.VictimFolder{RootName: filepath.Base(root), Files: files}, nil
}
