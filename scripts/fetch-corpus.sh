#!/usr/bin/env bash
# Placeholder — fetch & decrypt the labeled calibration corpus.
# Real implementation lands at Milestone 5 (calibration).
set -euo pipefail

if [[ -z "${RUTIFY_CORPUS_KEY:-}" ]]; then
  echo "RUTIFY_CORPUS_KEY not set — skipping corpus fetch"
  exit 0
fi

echo "TODO: implement corpus fetch + age decrypt at Milestone 5"
