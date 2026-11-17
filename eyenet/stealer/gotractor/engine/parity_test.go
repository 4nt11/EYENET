package engine

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"testing"

	"gopkg.in/yaml.v3"
)

// Shared golden fixtures live at the repo root. Point at the dir
// via EYENET_STEALER_FIXTURES_DIR, or fall back to the standard
// relative path from the gotractor module root.
func fixturesDir(t *testing.T) string {
	t.Helper()
	if p := os.Getenv("EYENET_STEALER_FIXTURES_DIR"); p != "" {
		return p
	}
	// gotractor/engine/ -> gotractor -> stealer -> eyenet -> repo root
	return filepath.Join("..", "..", "..", "..", "tests", "fixtures", "stealer_rules")
}

func TestParityAgainstGoldenFixtures(t *testing.T) {
	root := fixturesDir(t)
	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatalf("read fixtures dir %q: %v", root, err)
	}
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		name := e.Name()
		t.Run(name, func(t *testing.T) {
			runFixture(t, filepath.Join(root, name))
		})
	}
}

func runFixture(t *testing.T, fdir string) {
	t.Helper()
	// rule.yaml may be a single rule OR a list (container + content pair).
	ruleBytes, err := os.ReadFile(filepath.Join(fdir, "rule.yaml"))
	if err != nil {
		t.Fatalf("read rule.yaml: %v", err)
	}
	var raw any
	if err := yaml.Unmarshal(ruleBytes, &raw); err != nil {
		t.Fatalf("parse rule.yaml: %v", err)
	}
	var rules []Rule
	switch rawTyped := raw.(type) {
	case []any:
		for _, item := range rawTyped {
			var r Rule
			b, _ := yaml.Marshal(item)
			if err := yaml.Unmarshal(b, &r); err != nil {
				t.Fatalf("parse rule list item: %v", err)
			}
			rules = append(rules, r)
		}
	default:
		var r Rule
		if err := yaml.Unmarshal(ruleBytes, &r); err != nil {
			t.Fatalf("parse rule: %v", err)
		}
		rules = append(rules, r)
	}

	// Two input styles: single input.* file OR a full input_folder/ tree.
	folderDir := filepath.Join(fdir, "input_folder")
	var files []ContentInput
	if info, err := os.Stat(folderDir); err == nil && info.IsDir() {
		err := filepath.Walk(folderDir, func(p string, inf os.FileInfo, e error) error {
			if e != nil || inf.IsDir() {
				return e
			}
			rel, _ := filepath.Rel(folderDir, p)
			rel = filepath.ToSlash(rel)
			b, err := os.ReadFile(p)
			if err != nil {
				return err
			}
			files = append(files, ContentInput{Path: rel, Text: string(b)})
			return nil
		})
		if err != nil {
			t.Fatalf("walk input_folder: %v", err)
		}
	} else {
		var inputFile string
		entries, _ := os.ReadDir(fdir)
		for _, e := range entries {
			if strings.HasPrefix(e.Name(), "input.") {
				inputFile = filepath.Join(fdir, e.Name())
				break
			}
		}
		if inputFile == "" {
			t.Fatal("no input.* file or input_folder/")
		}
		text, err := os.ReadFile(inputFile)
		if err != nil {
			t.Fatalf("read input: %v", err)
		}
		filePath := filepath.Base(inputFile)
		for _, r := range rules {
			if r.Layer == "content" && r.PathGlob != "" {
				filePath = r.PathGlob
				break
			}
		}
		files = []ContentInput{{Path: filePath, Text: string(text)}}
	}

	folder := VictimFolder{
		RootName: filepath.Base(fdir),
		Files:    files,
	}
	got := RunRules(rules, folder)

	expectedBytes, err := os.ReadFile(filepath.Join(fdir, "expected.json"))
	if err != nil {
		t.Fatalf("read expected.json: %v", err)
	}
	var want struct {
		Family any            `json:"family"`
		Fields map[string]any `json:"fields"`
	}
	if err := json.Unmarshal(expectedBytes, &want); err != nil {
		t.Fatalf("parse expected.json: %v", err)
	}
	// Normalise both sides through JSON round-trip + sort key order,
	// same approach as the Python parity harness.
	gotWire := canon(map[string]any{"family": got.Family, "fields": got.Fields})
	wantWire := canon(map[string]any{"family": want.Family, "fields": want.Fields})
	if !reflect.DeepEqual(gotWire, wantWire) {
		t.Errorf("parity divergence\n  actual:   %v\n  expected: %v", gotWire, wantWire)
	}
}

func canon(v any) any {
	b, _ := json.Marshal(v)
	var out any
	_ = json.Unmarshal(b, &out)
	return sortKeys(out)
}

func sortKeys(v any) any {
	switch x := v.(type) {
	case map[string]any:
		keys := make([]string, 0, len(x))
		for k := range x {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		out := map[string]any{}
		for _, k := range keys {
			out[k] = sortKeys(x[k])
		}
		return out
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = sortKeys(e)
		}
		return out
	default:
		return x
	}
}
