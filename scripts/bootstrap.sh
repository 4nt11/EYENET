#!/usr/bin/env bash
# Fresh-clone bootstrap. Run once after cloning.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "▸ wiring git hooks"
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit .githooks/pre-push
chmod +x .githooks/lib/*.sh

echo "▸ checking uv"
if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found — install: pip install uv  (or: curl -LsSf https://astral.sh/uv/install.sh | sh)"
  exit 1
fi

echo "▸ uv sync --extra dev"
uv sync --extra dev

echo "▸ initializing detect-secrets baseline (if missing)"
[[ -f .secrets.baseline ]] || uv run detect-secrets scan > .secrets.baseline

echo "✓ bootstrap done. Activate the venv with:  source .venv/bin/activate"
