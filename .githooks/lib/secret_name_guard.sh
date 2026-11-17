#!/usr/bin/env bash
# Reject staged / pushed paths whose basename matches known-dangerous
# secret-file naming patterns. Backstops detect-secrets which only
# inspects FILE CONTENTS. A new `.vendorname` dotfile with a 24-byte
# high-entropy key may not trigger detect-secrets's heuristics; this
# guard rejects based on NAME alone, regardless of content.
#
# Usage: source this script, then call `secret_name_guard <file1> <file2> ...`
#        Returns non-zero and prints to stderr on first dangerous-name hit.

secret_name_guard() {
  local hits=()
  local f base
  for f in "$@"; do
    # Allowlist: paths that LEGITIMATELY carry a dangerous-looking name
    # because they are part of our OWN secret-detection machinery, test
    # fixtures, or baseline files. Narrow full-path matches, never globs.
    case "$f" in
      .githooks/lib/secret_name_guard.sh)      continue ;;
      .secrets.baseline)                        continue ;;
      tests/fixtures/stealer_rules/*/input.*)   continue ;;  # test inputs
      tests/fixtures/stealer_rules/*/expected.*) continue ;;
    esac
    base="$(basename -- "$f")"
    case "$base" in
      # Specific vendor dotfiles observed in the wild
      .abuse*|.virustotal*|.vt|.vt.*|.urlhaus*|.threatfox*)
        hits+=("$f (vendor API dotfile)")
        ;;
      # AWS / cloud credential bags
      .aws|.aws.*|credentials|config.credentials|authinfo|.authinfo|.netrc|.pgpass)
        hits+=("$f (cloud credential bag)")
        ;;
      # Generic high-risk shapes
      *api_key*|*apikey*|*api-key*)
        hits+=("$f (api_key naming)")
        ;;
      *_secret*|*secret_*|*secrets.txt|*secrets.yaml|*secrets.yml|*secrets.json)
        hits+=("$f (secret naming)")
        ;;
      *_token|*_token.*|*.token|*.tokens)
        hits+=("$f (token naming)")
        ;;
      *passwd|*passwd.*|*password.txt|*passwords.txt)
        hits+=("$f (password naming)")
        ;;
      *.pem|*.p12|*.pfx)
        hits+=("$f (certificate / key material)")
        ;;
      .env.bak|.env.old|*.env.swp|*.env~)
        hits+=("$f (backup of .env)")
        ;;
      *.age.key|*.age)
        hits+=("$f (age encryption key)")
        ;;
      id_rsa|id_ecdsa|id_ed25519|*.id_rsa|*.id_ed25519)
        hits+=("$f (ssh private key)")
        ;;
    esac

    # Fixture paths in `tests/fixtures/stealer_rules/` legitimately have
    # input files with names like `input.txt` that contain FAKE credential
    # data for parsing tests. Those are opt-in via per-file content. The
    # guard above is name-based only, so test-fixture inputs pass through.
  done

  if ((${#hits[@]} > 0)); then
    printf >&2 '\n\e[31mBLOCKED by secret_name_guard:\e[0m\n'
    printf >&2 '  %s\n' "${hits[@]}"
    printf >&2 '\nAdd one of these if the file is NOT a secret:\n'
    printf >&2 "  1. Explicit allowlist: '!%s' in .gitignore (narrow path, never a glob)\n" \
      "${hits[0]%% *}"
    printf >&2 '  2. Rename to a non-sensitive pattern\n'
    printf >&2 '  3. Move the secret outside the repo (e.g. ~/.config/eyenet/secrets/)\n'
    return 1
  fi
  return 0
}
