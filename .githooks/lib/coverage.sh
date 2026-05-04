#!/usr/bin/env bash
# coverage_no_drop <coverage.json> <baseline.json>
#
# Refuses if the new line_rate is below the baseline by more than 1e-4 (rounding
# tolerance). On success, advances the baseline forward and stages it.
#
# Reads pytest-cov's JSON output:
#   $.totals.percent_covered  — float in [0, 100]
# Writes baseline as:
#   {"line_rate": <0..1>, "ts": "<iso8601>"}

coverage_no_drop() {
  local cov="$1" base="$2"

  if [[ ! -f "$cov" ]]; then
    abort "no coverage report at $cov — did pytest run with --cov-report=json:$cov ?"
  fi

  local new
  new=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['totals']['percent_covered']/100)" "$cov")

  if [[ ! -f "$base" ]] || [[ "$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('line_rate',0))" "$base")" == "0.0" ]]; then
    # First real measurement — seed the baseline.
    python3 -c "import json,sys,datetime;json.dump({'line_rate':float(sys.argv[1]),'ts':datetime.datetime.utcnow().isoformat()+'Z'},open(sys.argv[2],'w'))" "$new" "$base"
    git add "$base"
    ok "coverage baseline seeded at $(python3 -c "print(round(float('$new')*100,2))")%"
    return 0
  fi

  local old
  old=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['line_rate'])" "$base")

  python3 - "$new" "$old" <<'PY' || abort "coverage delta gate failed"
import sys
new = float(sys.argv[1])
old = float(sys.argv[2])
if new + 1e-4 < old:
    print(f"COVERAGE DROP: {old*100:.2f}% -> {new*100:.2f}% — refusing.")
    sys.exit(1)
PY

  # Update baseline forward only on improvement (or equal).
  python3 -c "import json,sys,datetime;d=json.load(open(sys.argv[2]));d['line_rate']=max(d['line_rate'],float(sys.argv[1]));d['ts']=datetime.datetime.utcnow().isoformat()+'Z';json.dump(d,open(sys.argv[2],'w'))" "$new" "$base"
  git add "$base"
  ok "coverage gate: $(python3 -c "print(round(float('$new')*100,2))")% (baseline $(python3 -c "print(round(float('$old')*100,2))")%)"
}
