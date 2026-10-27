#!/bin/bash
set -euo pipefail
HERE=/mnt/d/orbit-v41-recovery02/candidate07-density04-undamped-objective-controls01/preparation03
ORIGINAL=/mnt/d/orbit-v41-recovery02/candidate07-cold-density04/plan.json
PYTHON=/mnt/c/users/emper/documents/codex/2026-10-13/i-x20/work/numerics-v3.1/python/bin/python
test "$#" -ge 4 && test "$#" -le 5
case "$1" in prepare|preflight|evaluate) ;; *) exit 64;; esac
[[ "$2" =~ ^[0-9a-f]{64}$ && "$4" =~ ^[0-9a-f]{64}$ ]]
test "$(sha256sum "$HERE/inputs.sha256" | cut -d' ' -f1)" = "$2"
test "$(sha256sum "$ORIGINAL" | cut -d' ' -f1)" = 530221cae291e0689cdd5dce62deca1b18f27ad0682553c8e9d5ced11504cafb
test "$(sha256sum "$PYTHON" | cut -d' ' -f1)" = 58f0ee5f4cb0af42a69aed9f122d63cc535fcfa6bca71132a3d0e24be95c4ac8
mapfile -t environment < <(/usr/bin/jq -r '.jobs[0].environment|del(.ORBIT_POC_GNSS_DESIGN_SCRATCH,.ORBIT_POC_NUMERICS_SPOOL_DIRECTORY,.TMPDIR,.TMP,.TEMP)|to_entries[]|"\(.key)=\(.value)"' "$ORIGINAL")
arguments=("$HERE/objective_control.py" "$1" --source-sha256 "$2" --review "$3" --review-sha256 "$4")
if test "$#" -eq 5; then
 [[ "$5" =~ ^[0-9a-f]{64}$ ]]
 arguments+=(--plan-sha256 "$5")
fi
exec /usr/bin/env -i "${environment[@]}" "$PYTHON" -s -B "${arguments[@]}"
