// gotractor is the Go implementation of the EYENET stealer DSL rule
// engine, byte-parity with the Python (eyenet/stealer/rules/) and
// browser (eyenet-fe/src/lib/stealer-engine/) engines.
//
// Usage:
//   gotractor --rules-dir /etc/eyenet/rules/stealer \
//             --families-dir /etc/eyenet/families/stealer \
//             --input /path/to/victim/folder
//
// Output: one JSON line per EXTRACTED RECORD on stdout. Shape:
//   {"rule_id": "...", "family": "...", "file_path": "...", "fields": {...}}
//
// This replaces the old ulpextract.go monolith with a fully catalog-
// driven extractor. Pipeline-side consumers batch these JSON lines
// straight into the stealer.creds table (new Map(String, String) schema).
//
// Operational modes:
//   --mode records   (default) emit one JSON per extracted record
//   --mode summary   emit a single JSON RunResult (family + merged fields + evaluations)
//   --mode daemon    long-lived; read commands from stdin, emit records
//                    + reloads + stats on stdout; Prometheus /metrics on
//                    --metrics-port; fsnotify auto-reload on catalog changes
//   --mode selftest  run against the shared golden fixtures and exit
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io/fs"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"

	"eyenet.io/stealer/gotractor/daemon"
	"eyenet.io/stealer/gotractor/engine"
	"eyenet.io/stealer/gotractor/wallets"
)

// Build identity. Populated by the Dockerfile via -ldflags at build
// time ("-X main.buildVersion=... -X main.buildCommit=... -X
// main.buildTime=..."). Defaults to "unknown" for a local
// `go build .` so the binary still runs. Surfaced through the
// --version flag, logged on daemon boot, and returned in the stats
// command so "which gotractor is running" is answerable from logs,
// pprof, or a stats ping without guessing.
var (
	buildVersion = "unknown"
	buildCommit  = "unknown"
	buildTime    = "unknown"
)

func main() {
	rulesDir := flag.String("rules-dir", envOr("EYENET_STEALER_RULES_DIR", ""), "catalog YAML directory")
	familiesDir := flag.String("families-dir", envOr("EYENET_STEALER_FAMILIES_DIR", ""), "family catalog directory")
	input := flag.String("input", "", "victim folder (or single file) to evaluate (records / summary)")
	mode := flag.String("mode", "records", "records | summary | daemon | selftest | extract-wallets")
	limit := flag.Int("limit", 100000, "bulkParse record cap per file per rule")
	metricsPort := flag.Int("metrics-port", 0, "daemon: bind Prometheus /metrics on this port (0 disables)")
	showVersion := flag.Bool("version", false, "print build identity (version, commit, build time) and exit")
	// v1.4.0: direct-to-ClickHouse ingestion. When set the daemon inserts
	// every extracted record into CH via clickhouse-go in a per-archive
	// prepared batch; stdout then carries only metadata (verdict,
	// parse_error, run_done). Legacy stdout-record mode runs when empty
	// so dev workflows + records-mode CLI runs keep working unchanged.
	chDSN := flag.String(
		"ch-dsn",
		envOr("EYENET_GOTRACTOR_CH_DSN", ""),
		"ClickHouse DSN (clickhouse-go URL form). Daemon only. Empty = legacy stdout-record mode.",
	)
	flag.Parse()

	if *showVersion {
		fmt.Printf("gotractor version=%s commit=%s built=%s\n", buildVersion, buildCommit, buildTime)
		return
	}

	// extract-wallets bypasses rule catalog - it is a binary pre-extractor
	// that feeds synthetic vault JSON files into the DSL pipeline downstream.
	if *mode == "extract-wallets" {
		if *input == "" {
			log.Fatal("--input is required for extract-wallets mode")
		}
		if err := runExtractWallets(*input, os.Stdout); err != nil {
			log.Fatalf("extract-wallets: %v", err)
		}
		return
	}

	if *rulesDir == "" || *familiesDir == "" {
		log.Fatal("--rules-dir and --families-dir are required (or set EYENET_STEALER_RULES_DIR / EYENET_STEALER_FAMILIES_DIR)")
	}

	if *mode == "daemon" {
		d, err := daemon.New(*rulesDir, *familiesDir, *limit)
		if err != nil {
			log.Fatalf("daemon boot: %v", err)
		}
		d.SetBuildInfo(buildVersion, buildCommit, buildTime)
		ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
		defer cancel()
		// Open the CH sink if a DSN was provided. Dial failure is fatal
		// so the operator gets loud feedback instead of silent fallback
		// to a mode that would then OOM the box (the exact bug the sink
		// is meant to kill). If the DSN is empty, Open returns (nil, nil)
		// and the daemon stays in legacy stdout-record mode.
		if err := d.OpenSink(ctx, *chDSN); err != nil {
			log.Fatalf("daemon ch sink: %v", err)
		}
		defer d.CloseSink()
		if *metricsPort > 0 {
			d.ServeMetrics(*metricsPort)
		}
		if err := d.Serve(ctx, os.Stdin, os.Stdout); err != nil {
			log.Fatalf("daemon serve: %v", err)
		}
		return
	}

	rules, _, err := engine.LoadRules(*rulesDir, *familiesDir)
	if err != nil {
		log.Fatalf("catalog load: %v", err)
	}

	if *mode == "selftest" {
		fmt.Fprintf(os.Stderr, "selftest: %d rules loaded\n", len(rules))
		return
	}
	if *input == "" {
		log.Fatal("--input is required")
	}

	folder, err := readFolder(*input)
	if err != nil {
		log.Fatalf("read input: %v", err)
	}

	switch *mode {
	case "summary":
		emitSummary(rules, folder)
	default:
		emitRecords(rules, folder, *limit)
	}
}

func readFolder(path string) (engine.VictimFolder, error) {
	info, err := os.Stat(path)
	if err != nil {
		return engine.VictimFolder{}, err
	}
	if !info.IsDir() {
		// Single-file input: treat the file alone as a one-file folder.
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
			// Report-and-continue on unreadable subpaths.
			log.Printf("warn: %s: %v", p, werr)
			return nil
		}
		if d.IsDir() {
			return nil
		}
		rel, _ := filepath.Rel(root, p)
		rel = filepath.ToSlash(rel)
		b, err := os.ReadFile(p)
		if err != nil {
			log.Printf("warn: %s: %v", p, err)
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

func emitSummary(rules []engine.Rule, folder engine.VictimFolder) {
	r := engine.RunRules(rules, folder)
	enc := json.NewEncoder(os.Stdout)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(r); err != nil {
		log.Fatalf("encode summary: %v", err)
	}
}

// emitRecords: for every content rule that matches a file, run bulkParse
// and emit one JSON line per record. Container-rule verdicts also emit
// one summary line (useful for the pipeline to tag the batch with a
// family). This matches the shape the pipeline expects to insert into
// the new stealer.creds table.
func emitRecords(rules []engine.Rule, folder engine.VictimFolder, limit int) {
	r := engine.RunRules(rules, folder)
	enc := json.NewEncoder(os.Stdout)
	enc.SetEscapeHTML(false)

	// First, emit a header line carrying the container verdict.
	_ = enc.Encode(map[string]any{
		"kind":    "verdict",
		"family":  r.Family,
		"root":    folder.RootName,
		"files":   len(folder.Files),
	})

	// Then, per matched content rule + file, emit every bulkParse record.
	ruleByID := map[string]engine.Rule{}
	for _, rr := range rules {
		ruleByID[rr.ID] = rr
	}
	seen := map[string]bool{}
	for _, ev := range r.Evaluations {
		if !ev.Matched || ev.Layer != "content" {
			continue
		}
		key := ev.RuleID + "::" + ev.FilePath
		if seen[key] {
			continue
		}
		seen[key] = true
		rr, ok := ruleByID[ev.RuleID]
		if !ok {
			continue
		}
		// Locate the file text.
		var file engine.ContentInput
		for _, f := range folder.Files {
			if f.Path == ev.FilePath {
				file = f
				break
			}
		}
		// v1.3.11: stream records as they are produced instead of
		// materialising them in a slice. Yield fires in the same
		// goroutine; the encoder writes directly to stdout.
		emitted := 0
		meta := engine.BulkParse(rr, file, limit, func(rec map[string]any) bool {
			_ = enc.Encode(map[string]any{
				"kind":      "record",
				"rule_id":   rr.ID,
				"family":    rr.Family,
				"file_path": ev.FilePath,
				"fields":    rec,
			})
			emitted++
			return true
		})
		if meta.Truncated {
			_ = enc.Encode(map[string]any{
				"kind":       "truncated",
				"rule_id":    rr.ID,
				"file_path":  ev.FilePath,
				"emitted":    emitted,
				"total_seen": meta.Total,
			})
		}
	}
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

// runExtractWallets walks a victim folder for known wallet LevelDB
// directories, opens each read-only, and emits one JSON line per
// extracted vault to the writer. Record shape matches the DSL
// records emitter so the pipeline consumer ingests both uniformly:
//
//   {"rule_id": "wallet_vault_leveldb:<family>:<shape>",
//    "family":  "<wallet_family>",
//    "file_path": "<leveldb dir>",
//    "fields": {wallet_name, extension_id, extension_storage,
//               vault_key, vault_shape, vault_payload}}
//
// vault_payload is the JSON-stringified decoded payload for
// downstream consumers that want to re-parse it (hashcat vault
// format converters, address classifiers). It is a string per the
// pipeline's Map(String, String) fields column.
//
// Errors per directory go to stderr but do not abort the walk; a
// stealer dump often has half-grabbed extension directories.
func runExtractWallets(root string, w *os.File) error {
	hits, err := wallets.FindWalletDirs(root)
	if err != nil {
		return err
	}
	enc := json.NewEncoder(w)
	okCount, errCount, vaultCount := 0, 0, 0
	for _, h := range hits {
		recs, err := wallets.ExtractVaults(h.Path, h.Extension, h.Kind)
		if err != nil {
			fmt.Fprintf(os.Stderr, "extract %s (%s): %v\n", h.Path, h.Extension.Name, err)
			errCount++
			continue
		}
		okCount++
		for _, r := range recs {
			rec := map[string]any{
				"rule_id":   "wallet_vault_leveldb:" + r.WalletFamily + ":" + r.Shape,
				"family":    r.WalletFamily,
				"file_path": r.SourceDir,
				"fields": map[string]string{
					"wallet_name":       r.WalletName,
					"extension_id":      r.ExtensionID,
					"extension_storage": string(h.Kind),
					"vault_key":         r.VaultKey,
					"vault_shape":       r.Shape,
					"vault_payload":     string(r.Payload),
				},
			}
			if err := enc.Encode(rec); err != nil {
				fmt.Fprintf(os.Stderr, "encode vault %s/%s: %v\n", h.Extension.Name, r.VaultKey, err)
				continue
			}
			vaultCount++
		}
	}
	fmt.Fprintf(os.Stderr, "extract-wallets: %d wallet dirs found, %d opened ok, %d errored, %d vaults emitted\n",
		len(hits), okCount, errCount, vaultCount)
	return nil
}
