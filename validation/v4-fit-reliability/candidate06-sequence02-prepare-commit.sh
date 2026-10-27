#!/usr/bin/env bash
set -euo pipefail
pub=/mnt/d/orbit-v41-recovery02/candidate06-sequence02-publication03
parent=845d71b44185ca83a23fd177c6f9266467ea751a
prefix=validation/v4-fit-reliability/candidate06-sequence02
audit=$1
audit_sha=$2
[[ $(sha256sum "$audit" | cut -d' ' -f1) = "$audit_sha" ]]
jq -e '.approved_for_publication == true' "$audit" >/dev/null
[[ $(sha256sum "$pub/packet/SHA256SUMS" | cut -d' ' -f1) = 992f44d28195e514074b0e0e2a92f9cd923ef40d26f76f79a85b944b5a29a676 ]]
[[ ! -e "$pub/commit.txt" && ! -e "$pub/index-entries.txt" ]]
g() { git --git-dir="$pub/git01" "$@"; }
[[ $(g rev-parse FETCH_HEAD) = "$parent" ]]
[[ -z $(g ls-tree -r "$parent" -- "$prefix" "$prefix-independent-audit.json" "$prefix-prepare-commit.sh") ]]
(cd "$pub/packet" && sha256sum -c SHA256SUMS) > "$pub/packet-checksums-before.txt"
g read-tree "$parent"
add_blob() {
  local source=$1 target=$2 blob
  [[ -f "$source" && ! -L "$source" ]]
  blob=$(g hash-object -w --stdin < "$source")
  printf '100644 %s\t%s\n' "$blob" "$target" >> "$pub/index-entries.txt"
  printf '%s\t%s\t%s\n' "$source" "$target" "$blob" >> "$pub/commit-files.tsv"
}
while IFS= read -r source; do
  add_blob "$source" "$prefix/${source#"$pub/packet/"}"
done < <(rg --files "$pub/packet" | sort)
add_blob "$audit" "$prefix-independent-audit.json"
add_blob "$pub/prepare_commit.sh" "$prefix-prepare-commit.sh"
g update-index --index-info < "$pub/index-entries.txt"
g diff --cached --name-status "$parent" > "$pub/commit-diff.tsv"
awk -F '\t' -v prefix="$prefix" 'NF != 2 || $1 != "A" || index($2,prefix) != 1 {bad=1} END {exit bad}' "$pub/commit-diff.tsv"
[[ $(wc -l < "$pub/commit-diff.tsv") = $(wc -l < "$pub/commit-files.tsv") ]]
tree=$(g write-tree)
cat > "$pub/commit-message.txt" <<'MESSAGE'
Publish audited candidate06 correctness and cold-fit outcomes

Retain all eleven passing correctness stages, the pulse cold-fit pass and the second-trial density failure. Include independent saved-output checks and their limitations, all preserved reader/reporting failures and exact provenance. This evidence-only publication changes no active estimator, frozen campaign, threshold or release status.
MESSAGE
commit=$(g -c user.name='Florian Pfaff' -c user.email='6773539+FlorianPfaff@users.noreply.github.com' commit-tree "$tree" -p "$parent" -F "$pub/commit-message.txt")
while IFS=$'\t' read -r source target blob; do
  [[ $(g rev-parse "$commit:$target") = "$blob" ]]
  g cat-file blob "$blob" | cmp - "$source"
done < "$pub/commit-files.tsv"
g diff-tree --no-commit-id --name-status -r "$commit" > "$pub/committed-diff.tsv"
cmp "$pub/commit-diff.tsv" "$pub/committed-diff.tsv"
g update-ref refs/heads/candidate06-sequence02-publication "$commit"
printf '%s\n' "$commit" > "$pub/commit.txt"
jq -n --arg commit "$commit" --arg tree "$tree" --arg parent "$parent" --arg audit "$audit" --arg sha "$audit_sha" --argjson count "$(wc -l < "$pub/commit-files.tsv")" '{schema:"additive-evidence-commit-v1",commit:$commit,tree:$tree,parent:$parent,files_added:$count,files_modified:0,files_deleted:0,all_blobs_verified:true,audit:{path:$audit,sha256:$sha},pushed:false,active_source_changed:false,frozen_benchmarks_changed:false}' > "$pub/commit-receipt.json"
cat "$pub/commit-receipt.json"
