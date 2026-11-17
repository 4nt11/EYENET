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

func main() {
	rulesDir := flag.String("rules-dir", envOr("EYENET_STEALER_RULES_DIR", ""), "catalog YAML directory")
	familiesDir := flag.String("families-dir", envOr("EYENET_STEALER_FAMILIES_DIR", ""), "family catalog directory")
	input := flag.String("input", "", "victim folder (or single file) to evaluate (records / summary)")
	mode := flag.String("mode", "records", "records | summary | daemon | selftest | extract-wallets")
	limit := flag.Int("limit", 100000, "bulkParse record cap per file per rule")
	metricsPort := flag.Int("metrics-port", 0, "daemon: bind Prometheus /metrics on this port (0 disables)")
	flag.Parse()

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
		if *metricsPort > 0 {
			d.ServeMetrics(*metricsPort)
		}
		ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
		defer cancel()
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
		bulk := engine.BulkParse(rr, file, limit)
		for _, rec := range bulk.Records {
			_ = enc.Encode(map[string]any{
				"kind":      "record",
				"rule_id":   rr.ID,
				"family":    rr.Family,
				"file_path": ev.FilePath,
				"fields":    rec,
			})
		}
		if bulk.Truncated {
			_ = enc.Encode(map[string]any{
				"kind":       "truncated",
				"rule_id":    rr.ID,
				"file_path":  ev.FilePath,
				"emitted":    len(bulk.Records),
				"total_seen": bulk.Total,
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
// extracted vault to the writer. Errors per directory are logged
// but do not abort the walk - a stealer dump often has half-grabbed
// extension directories.
func runExtractWallets(root string, w *os.File) error {
	hits, err := wallets.FindWalletDirs(root)
	if err != nil {
		return err
	}
	enc := json.NewEncoder(w)
	okCount, errCount, vaultCount := 0, 0, 0
	for _, h := range hits {
		recs, err := wallets.ExtractVaults(h.Path, h.Extension)
		if err != nil {
			fmt.Fprintf(os.Stderr, "extract %s (%s): %v\n", h.Path, h.Extension.Name, err)
			errCount++
			continue
		}
		okCount++
		for _, r := range recs {
			if err := enc.Encode(r); err != nil {
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
