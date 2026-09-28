#!/usr/bin/env bash
# Re-extract the real corpus from the live EYENET docker DB into
# dataset/eyenet_messages.jsonl. Each line: {"group","text","has_attachment",
# and (when present) "att_files"/"att_kinds"}. Attachment PRESENCE + filename is a
# strong incident signal (a "Pass: @x" post next to logs_2025.zip is a log cloud);
# contents are irrelevant to this subsystem, only presence/name. WAL-visible.
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
q = '''SELECT g.current_title, m.body, m.has_attachment,
         (SELECT group_concat(a.filename, '|') FROM attachment a WHERE a.message_id = m.id),
         (SELECT group_concat(a.kind, '|')     FROM attachment a WHERE a.message_id = m.id)
       FROM message m JOIN group_ g ON m.group_id = g.id
       WHERE m.body IS NOT NULL AND trim(m.body) != '' '''
n = 0
with open('${CTMP}', 'w', encoding='utf-8') as f:
    for title, body, has_att, fnames, kinds in c.execute(q):
        rec = {'group': title, 'text': body, 'has_attachment': bool(has_att)}
        if fnames:
            rec['att_files'] = [x for x in fnames.split('|') if x]
        if kinds:
            rec['att_kinds'] = [x for x in kinds.split('|') if x]
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        n += 1
print('wrote', n, 'rows')
"

docker cp "$CONTAINER:$CTMP" "$OUT"
docker exec "$CONTAINER" rm -f "$CTMP"
echo "-> $OUT ($(wc -l < "$OUT") lines)"
