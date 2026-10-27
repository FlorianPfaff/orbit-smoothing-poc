#!/usr/bin/env bash
# Small additive evidence assembler; no numerical tools, rendering or Git.
set -euo pipefail
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
OUT=/mnt/d/orbit-v41-recovery02/candidate07-density04-publication01/packet
[[ ! -e "$OUT" && ! -L "$OUT" ]] || { printf 'Preserve existing packet\n' >&2; exit 1; }
mkdir "$OUT"
while IFS=$'\t' read -r target source sha bytes; do
 [[ -f "$source" && ! -L "$source" && $(realpath -e -- "$source") == "$source" ]] || exit 1
 [[ $(stat -c%s -- "$source") == "$bytes" && $bytes -le 4194304 ]] || exit 1
 actual=$(sha256sum -- "$source"); [[ ${actual%% *} == "$sha" ]] || exit 1
 mkdir -p -- "$OUT/$(dirname -- "$target")"
 cp -- "$source" "$OUT/$target"
 cmp -- "$source" "$OUT/$target"
done < <(jq -r '.[]|[.target,.path,.sha256,(.bytes|tostring)]|@tsv' "$SOURCE/receipt-pins.json")
# Preserve both body and exact source manifests; nothing here calls a renderer.
mkdir "$OUT/assembly-source"
cp "$SOURCE"/{build_packet.sh,report.jq,receipt-sources.tsv,receipt-pins.json,external-pins.json,index.html,README.txt} "$OUT/assembly-source/"
cp "$SOURCE/index.html" "$OUT/index.html"
cp "$SOURCE/README.txt" "$OUT/README.txt"
jq -n --slurpfile inputs "$SOURCE/receipt-pins.json" --slurpfile external "$SOURCE/external-pins.json" \
 '{schema:"candidate07-density04-publication-inputs-v1",copied_receipts:$inputs[0],external_exact_pins:$external[0].files}' > "$OUT/inputs-manifest.json"
jq -n --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --slurpfile inputs "$SOURCE/receipt-pins.json" \
 --slurpfile correctness "$OUT/receipts/correctness03/result.json" \
 --slurpfile pulse "$OUT/receipts/pulse03/strict-result.json" \
 --slurpfile terminal "$OUT/receipts/density04/detached-result.json" \
 --slurpfile supervisor "$OUT/receipts/density04/supervisor.json" \
 --slurpfile history "$OUT/receipts/density04/iterations.json" \
 -f "$SOURCE/report.jq" > "$OUT/report.json"
# Rehash actual source receipts after copying, preserving the original pins.
while IFS=$'\t' read -r source sha; do
 actual=$(sha256sum -- "$source"); [[ ${actual%% *} == "$sha" ]] || exit 1
done < <(jq -r '.[]|[.path,.sha256]|@tsv' "$SOURCE/receipt-pins.json")
(cd "$OUT" && find . -type f ! -path './SHA256SUMS' -printf '%P\n' | LC_ALL=C sort | while IFS= read -r member; do sha256sum "$member"; done) > "$OUT/SHA256SUMS"
(cd "$OUT" && LC_ALL=C sort -o SHA256SUMS SHA256SUMS && sha256sum -c --quiet SHA256SUMS)
