#!/usr/bin/env bash
# PoC sampler: pull a bounded, source-diverse sample from the live EYENET docker DB
# into development/poc-gliner/sample.jsonl. Unlike dataset/extract_messages.sh this
# carries the who/what/when columns (msg id, source kind, actor_key, sent_at, group)
# so the PoC can test the ACTUAL deliverable, not just extraction in a vacuum.
#
# Leans forum-heavy on purpose: forum prose is where orgs/tools/malware live; the
# telegram corpus is mostly short junk ("komi komi komi") and useless for NER.
#
# SENSITIVE: exports message bodies. Run it yourself:  ! bash development/poc-gliner/sample.sh
# Bodies go container-tmp -> docker cp, never through stdout.
set -euo pipefail

CONTAINER="${EYENET_CONTAINER:-docker-api-1}"
DB="${EYENET_DB:-/var/lib/eyenet/main.db}"
PER_FORUM="${PER_FORUM:-1500}"   # cap per forum source
PER_OTHER="${PER_OTHER:-500}"    # cap per telegram/matrix/etc source
OUT="$(dirname "$0")/sample.jsonl"
CTMP="/tmp/poc_gliner_sample.jsonl"

docker exec "$CONTAINER" python -c "
import sqlite3, json
c = sqlite3.connect('file:${DB}?mode=ro', uri=True)
# ponytail: ORDER BY RANDOM() is a full scan per source; fine for a one-shot few-k
# sample, swap to a sampled-rowid scheme only if the table makes this slow.
base = '''SELECT m.id, s.kind, s.display_name, a.actor_key, g.current_title,
                 m.sent_at_source, m.body, m.has_attachment
          FROM message m
          JOIN source s ON m.source_id = s.id
          JOIN actor  a ON m.actor_id  = a.id
          LEFT JOIN group_ g ON m.group_id = g.id
          WHERE m.body IS NOT NULL AND trim(m.body) != '' AND s.id = ?
          ORDER BY RANDOM() LIMIT ?'''
n = 0
with open('${CTMP}', 'w', encoding='utf-8') as f:
    for sid, kind in c.execute('SELECT id, kind FROM source').fetchall():
        cap = ${PER_FORUM} if kind == 'forum' else ${PER_OTHER}
        for mid, k, disp, akey, title, sent, body, att in c.execute(base, (sid, cap)):
            f.write(json.dumps({
                'msg_id': mid, 'source_kind': k, 'source': disp,
                'actor_key': akey, 'group': title, 'sent_at': sent,
                'text': body, 'has_attachment': bool(att),
            }, ensure_ascii=False) + '\n')
            n += 1
print('wrote', n, 'rows')
"

docker cp "$CONTAINER:$CTMP" "$OUT"
docker exec "$CONTAINER" rm -f "$CTMP"
echo "-> $OUT ($(wc -l < "$OUT") lines)"
