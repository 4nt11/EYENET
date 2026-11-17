package engine

import (
	"errors"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"
)

// LoadRules reads every *.yaml file in dir, parses each as a Rule, and
// returns them sorted by filename (stable, deterministic ordering).
// Duplicate rule ids are a fatal error (same contract as the Python
// loader). The family catalog is loaded alongside and used to warn on
// unknown rule.family references (never fatal, matching Python).
func LoadRules(rulesDir, familiesDir string) ([]Rule, []Family, error) {
	families, err := LoadFamilies(familiesDir)
	if err != nil {
		return nil, nil, fmt.Errorf("families load: %w", err)
	}
	validSlugs := map[string]bool{}
	for _, f := range families {
		validSlugs[f.Slug] = true
	}

	entries, err := os.ReadDir(rulesDir)
	if err != nil {
		return nil, nil, fmt.Errorf("read rules dir %q: %w", rulesDir, err)
	}
	var paths []string
	for _, e := range entries {
		if !e.IsDir() && strings.HasSuffix(e.Name(), ".yaml") {
			paths = append(paths, filepath.Join(rulesDir, e.Name()))
		}
	}
	sort.Strings(paths)

	seen := map[string]string{}
	rules := make([]Rule, 0, len(paths))
	for _, p := range paths {
		var r Rule
		b, err := os.ReadFile(p)
		if err != nil {
			return nil, nil, fmt.Errorf("read %s: %w", p, err)
		}
		if err := yaml.Unmarshal(b, &r); err != nil {
			return nil, nil, fmt.Errorf("parse %s: %w", p, err)
		}
		if r.ID == "" {
			return nil, nil, fmt.Errorf("%s: missing rule id", p)
		}
		if prev, dup := seen[r.ID]; dup {
			return nil, nil, fmt.Errorf("%s: duplicate rule id %q (also in %s)", p, r.ID, prev)
		}
		seen[r.ID] = p
		if r.Family != "" && !validSlugs[r.Family] {
			log.Printf("warn: rule %q references unknown family %q (add it under %s/)", r.ID, r.Family, familiesDir)
		}
		rules = append(rules, r)
	}
	return rules, families, nil
}

// LoadFamilies reads every *.yaml file in dir as a Family entry.
// Duplicate slugs and bad status values are fatal.
func LoadFamilies(dir string) ([]Family, error) {
	validStatus := map[string]bool{
		"active": true, "retired": true, "dormant": true, "new": true, "suspected": true,
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, fmt.Errorf("read families dir %q: %w", dir, err)
	}
	var paths []string
	for _, e := range entries {
		if !e.IsDir() && strings.HasSuffix(e.Name(), ".yaml") {
			paths = append(paths, filepath.Join(dir, e.Name()))
		}
	}
	sort.Strings(paths)

	seen := map[string]string{}
	families := make([]Family, 0, len(paths))
	for _, p := range paths {
		var f Family
		b, err := os.ReadFile(p)
		if err != nil {
			return nil, fmt.Errorf("read %s: %w", p, err)
		}
		if err := yaml.Unmarshal(b, &f); err != nil {
			return nil, fmt.Errorf("parse %s: %w", p, err)
		}
		if f.Slug == "" {
			return nil, fmt.Errorf("%s: missing slug", p)
		}
		if f.Name == "" {
			return nil, fmt.Errorf("%s: missing name", p)
		}
		if !validStatus[f.Status] {
			return nil, fmt.Errorf("%s: status %q not in {active,retired,dormant,new,suspected}", p, f.Status)
		}
		if prev, dup := seen[f.Slug]; dup {
			return nil, fmt.Errorf("%s: duplicate slug %q (also in %s)", p, f.Slug, prev)
		}
		seen[f.Slug] = p
		families = append(families, f)
	}
	return families, nil
}

// ErrNotFound is returned when a single rule or family lookup misses.
var ErrNotFound = errors.New("not found")
