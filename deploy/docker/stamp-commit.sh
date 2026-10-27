#!/usr/bin/env bash
# Regenerate deploy/docker/commit.json from the current git HEAD.
# Run on the prod box right before `docker compose up -d` so the stamp
# reflects exactly what's deployed. Run from anywhere in the repo.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
out="deploy/docker/commit.json"
cat > "$out" <<EOF
{
  "commit": "$(git rev-parse HEAD)",
  "short": "$(git rev-parse --short HEAD)",
  "branch": "$(git rev-parse --abbrev-ref HEAD)",
  "subject": "$(git log -1 --pretty=%s | sed 's/"/\\"/g')",
  "committed_at": "$(git log -1 --date=iso-strict --pretty=%cd)",
  "stamped_at": "$(date -Is)",
  "image_tag": "eyenet:base"
}
EOF
echo "wrote $out -> $(git rev-parse --short HEAD)"
