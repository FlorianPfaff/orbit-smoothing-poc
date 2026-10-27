#!/bin/bash
set -euo pipefail
here=/mnt/d/orbit-v41-recovery02/candidate07-density04-undamped-probe-fixture-controls01/preparation02
python=/mnt/c/users/emper/documents/codex/2026-10-13/i-x20/work/numerics-v3.1/python/bin/python
scratch=/home/emper/orbit-density04-undamped-probe-fixtures02
case "${1:-}" in prepare|run) ;; *) echo 'Use an explicitly reviewed prepare or run action.' >&2; exit 2;; esac
if [[ -e "$scratch" || -L "$scratch" ]]; then
  echo 'Preserve existing fixture scratch; this attempt cannot be reused.' >&2
  exit 2
fi
exec /usr/bin/env -i HOME=/home/emper PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
  VECLIB_MAXIMUM_THREADS=1 BLIS_NUM_THREADS=1 \
  "$python" -I -S -B -X "pycache_prefix=$scratch/pycache" "$here/fixture_control.py" "$@"
