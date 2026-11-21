// Package engine implements the EYENET stealer DSL rule engine in Go.
// Byte-parity with the Python (eyenet/stealer/rules/) and browser-side
// (eyenet-fe/src/lib/stealer-engine/) engines, enforced by the shared
// golden fixtures in tests/fixtures/stealer_rules/.
package engine

// Rule is the engine-internal representation of a catalog rule. Loaded
// from YAML by catalog.go; identical shape to the Python TypedDict.
// Match/Extract/Map bodies are kept as free-form maps because each of
// the 8 matcher types carries its own body shape; typing them strictly
// would fight the DSL.
type Rule struct {
	ID                        string                 `yaml:"id"                        json:"id"`
	Version                   int                    `yaml:"version"                   json:"version"`
	Layer                     string                 `yaml:"layer"                     json:"layer"` // "container" | "content"
	Family                    string                 `yaml:"family"                    json:"family"`
	Priority                  int                    `yaml:"priority"                  json:"priority"`
	Description               string                 `yaml:"description,omitempty"     json:"description,omitempty"`
	PathGlob                  string                 `yaml:"path_glob,omitempty"       json:"path_glob,omitempty"`
	RequiresContainerFamily   string                 `yaml:"requires_container_family,omitempty" json:"requires_container_family,omitempty"`
	Match                     map[string]any         `yaml:"match"                     json:"match"`
	Extract                   map[string]any         `yaml:"extract,omitempty"         json:"extract,omitempty"`
	Map                       map[string]any         `yaml:"map,omitempty"             json:"map,omitempty"`
	RejectPatterns            []string               `yaml:"reject_patterns,omitempty" json:"reject_patterns,omitempty"`
	Normalize                 []map[string]any       `yaml:"normalize,omitempty"       json:"normalize,omitempty"`
}

// Family is the engine's view of a family catalog entry. Only the slug
// and status are load-bearing; the other fields are operator metadata
// that the engine passes through unchanged.
type Family struct {
	Slug                 string           `yaml:"slug" json:"slug"`
	Name                 string           `yaml:"name" json:"name"`
	Status               string           `yaml:"status" json:"status"`
	FirstSeenYear        int              `yaml:"first_seen_year,omitempty" json:"first_seen_year,omitempty"`
	Aliases              []string         `yaml:"aliases,omitempty" json:"aliases,omitempty"`
	SignatureFiles       []string         `yaml:"signature_files,omitempty" json:"signature_files,omitempty"`
	Loaders              []string         `yaml:"loaders,omitempty" json:"loaders,omitempty"`
	DistributionChannels []string         `yaml:"distribution_channels,omitempty" json:"distribution_channels,omitempty"`
	References           []map[string]any `yaml:"references,omitempty" json:"references,omitempty"`
	Notes                string           `yaml:"notes,omitempty" json:"notes,omitempty"`
}

// ContentInput is one file as seen by a content-layer matcher.
type ContentInput struct {
	Path string
	Text string
}

// ContainerInput is the set of relative paths inside a victim folder.
// Only the paths are needed; container matchers never read file bytes.
type ContainerInput struct {
	Paths []string
}

// VictimFolder wraps a list of ContentInputs under a shared root name.
type VictimFolder struct {
	RootName string
	Files    []ContentInput
}

// EvalResult mirrors the Python/JS EvalResult: one record per rule
// evaluation. For content-layer rules, FilePath carries the file that
// was evaluated; for container rules, FilePath is empty.
type EvalResult struct {
	RuleID   string         `json:"rule_id"`
	Layer    string         `json:"layer"`
	Family   string         `json:"family"`
	Priority int            `json:"priority"`
	Matched  bool           `json:"matched"`
	Fields   map[string]any `json:"fields,omitempty"`
	Reason   string         `json:"reason,omitempty"`
	FilePath string         `json:"file_path,omitempty"`
}

// RunResult is the full output of running a rule set against one folder.
// Family is any (string or nil) to match the Python / JS surface: null
// means no container rule matched. A plain Go string with "" zero-value
// would serialise as the empty string and break golden-fixture parity.
type RunResult struct {
	Family      any            `json:"family"`
	Fields      map[string]any `json:"fields"`
	Evaluations []EvalResult   `json:"evaluations"`
}

// BulkMeta is the return value of the streaming BulkParse: counts only,
// no materialised records. The yield callback receives each record as
// it is produced, so the caller decides how to retain (or drop) them.
type BulkMeta struct {
	Total     int  `json:"total"`
	Truncated bool `json:"truncated"`
}

// BulkResult is the pre-v1.3.11 shape of BulkParse: every record a
// matcher emits for a single (rule, file) pair, bounded by Limit, held
// in a slice. Preserved only for BulkParseCollect (tests, Workbench
// preview); production callers stream.
type BulkResult struct {
	Records   []map[string]any `json:"records"`
	Total     int              `json:"total"`
	Truncated bool             `json:"truncated"`
}
