#!/usr/bin/env bash
# Re-extract the real corpus from the live EYENET docker DB into
# dataset/eyenet_messages.jsonl ({"group","text"} per line, WAL-visible).
#
# SENSITIVE: bulk-exports message bodies. Run it yourself (`! bash dataset/extract_messages.sh`)
# or under accept-edits. Bodies go container-tmp -> docker cp, never through stdout.
#
# After this: re-run bootstrap_silver.py, then label the new infostealer/actor_ops
# rows in labeler.html, then train_mmbert_ml.py.
set -euo pipefail

CONTAINER="${EYENET_CONTAINER:-docker-api-1}"
DB="${EYENET_DB:-/var/lib/eyenet/main.db}"
OUT="$(dirname "$0")/eyenet_messages.jsonl"
CTMP="/tmp/eyenet_messages.jsonl"

docker exec "$CONTAINER" python -c "
import sqlite3, json
c = sqlite3.connect('file:${DB}?mode=ro', uri=True)
q = '''SELECT g.current_title, m.body
       FROM message m JOIN group_ g ON m.group_id = g.id
       WHERE m.body IS NOT NULL AND trim(m.body) != '' '''
n = 0
with open('${CTMP}', 'w', encoding='utf-8') as f:
    for title, body in c.execute(q):
        f.write(json.dumps({'group': title, 'text': body}, ensure_ascii=False) + '\n')
        n += 1
print('wrote', n, 'rows')
"

docker cp "$CONTAINER:$CTMP" "$OUT"
docker exec "$CONTAINER" rm -f "$CTMP"
echo "-> $OUT ($(wc -l < "$OUT") lines)"
