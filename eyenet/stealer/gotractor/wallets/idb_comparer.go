package wallets

import "bytes"

// idbComparer is the minimal shim goleveldb needs to open a Chromium
// IndexedDB-backed LevelDB. Chromium names its comparator 'idb_cmp1'
// and stores that name in the LevelDB MANIFEST; when goleveldb opens
// the file it rejects any mismatch, so we must claim the same name.
//
// The real idb_cmp1 implements IndexedDB's structured-key byte order
// (record type prefix + decoded key path). For READ-ONLY sequential
// iteration we only need to walk every key, not reproduce the exact
// sort order, so a bytewise Compare keeps goleveldb's internal
// traversal happy without implementing the full Chromium logic.
//
// Separator / Successor get default implementations (identity and
// nil) because they are only used at write time; this comparator is
// never exposed on a writable DB.
type idbComparer struct{}

func (idbComparer) Compare(a, b []byte) int        { return bytes.Compare(a, b) }
func (idbComparer) Name() string                   { return "idb_cmp1" }
func (idbComparer) Separator(dst, a, b []byte) []byte { return nil }
func (idbComparer) Successor(dst, b []byte) []byte    { return nil }
