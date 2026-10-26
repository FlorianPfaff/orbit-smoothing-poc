#!/usr/bin/env bash
# Future execution only: verifies audited bytes, fetches exact parent, builds a local additive commit. Never pushes.
set -euo pipefail
[[ $# == 4 ]] || { printf 'usage: prepare_commit.sh REQUEST REQUEST_SHA TOOLING_LEDGER_SHA FRESH_OUTPUT\n' >&2; exit 2; }
source "$(dirname -- "${BASH_SOURCE[0]}")/publication_contract.sh"
request=$1; request_sha=$2; tools_sha=$3; PUB_OUT=$4
pub_validate "$request" "$request_sha" "$tools_sha"
[[ $PUB_OUT =~ ^/mnt/d/orbit-v41-recovery02/candidate07-git-publication-run[0-9]{2,}$ ]] || pub_fail "Output must be a fresh dedicated candidate07-git-publication-runNN directory"
[[ $PUB_OUT == /* && ! -e $PUB_OUT && ! -L $PUB_OUT && $(realpath -e -- "$(dirname -- "$PUB_OUT")") == "$(dirname -- "$PUB_OUT")" ]] || pub_fail 'Fresh canonical output leaf required'
mkdir -- "$PUB_OUT"
stage=initialization
trap 'code=$?; if ((code!=0)); then jq -n --arg stage "$stage" --argjson code "$code" "{schema:\"candidate07-additive-git-preparation-failure-v1\",status:\"failed\",stage:\$stage,exit_code:\$code,pushed:false}" > "$PUB_OUT/failure.json"; fi' EXIT
cp -- "$request" "$PUB_OUT/request.json"
cp -- "$PUB_AUDIT" "$PUB_OUT/independent-audit.json"
stage=remote_parent_check
pub_remote_head "$PUB_OUT/remote-before.txt"
stage=fetch
pub_clean_git init --bare "$PUB_OUT/git01" > "$PUB_OUT/git-init.log" 2>&1
pub_git fetch --no-tags "$PUB_REMOTE" "$PUB_REF" > "$PUB_OUT/git-fetch.log" 2>&1
[[ $(pub_git rev-parse FETCH_HEAD) == "$PUB_PARENT" ]] || pub_fail 'Fetched parent differs'
pub_git merge-base --is-ancestor "$PUB_HISTORY" "$PUB_PARENT" || pub_fail 'Published candidate06 evidence is not an ancestor'
[[ -z $(pub_git ls-tree -r "$PUB_PARENT" -- "$PUB_PREFIX") ]] || pub_fail 'Candidate07 publication prefix already exists'
stage=stage_additive_blobs
pub_git read-tree "$PUB_PARENT"
: > "$PUB_OUT/index-entries.txt"; : > "$PUB_OUT/commit-files.tsv"
add_blob() {
  local from=$1 target=$2 blob
  pub_regular "$from"; pub_relative "$target"
  [[ $target == "$PUB_PREFIX/"* ]] || pub_fail 'Target outside new additive prefix'
  blob=$(pub_git hash-object -w --stdin < "$from")
  printf '100644 %s\t%s\n' "$blob" "$target" >> "$PUB_OUT/index-entries.txt"
  printf '%s\t%s\t%s\t%s\n' "$from" "$target" "$blob" "$(pub_sha "$from")" >> "$PUB_OUT/commit-files.tsv"
}
while IFS= read -r path; do add_blob "$PUB_PACKET/$path" "$PUB_PREFIX/$path"; done < <(find "$PUB_PACKET" -type f -printf '%P\n' | LC_ALL=C sort)
# Full frozen tooling packet includes exact correction code, fixtures, old bases,
# original/portable diffs and source identity records, without changing live code.
while IFS= read -r line; do path=${line#*  }; path=${path#./}; pub_relative "$path"; add_blob "$PUB_TOOLS/$path" "$PUB_PREFIX/publication-tooling/$path"; done < "$PUB_TOOLS/source.sha256"
add_blob "$PUB_TOOLS/source.sha256" "$PUB_PREFIX/publication-tooling/source.sha256"
add_blob "$PUB_OUT/independent-audit.json" "$PUB_PREFIX/independent-audit.json"
add_blob "$PUB_OUT/request.json" "$PUB_PREFIX/publication-request.json"
[[ $(cut -f2 "$PUB_OUT/commit-files.tsv" | LC_ALL=C sort -u | wc -l) -eq $(wc -l < "$PUB_OUT/commit-files.tsv") ]] || pub_fail 'Duplicate Git targets'
pub_git update-index --index-info < "$PUB_OUT/index-entries.txt"
pub_git diff --cached --name-status "$PUB_PARENT" > "$PUB_OUT/commit-diff.tsv"
awk -F '\t' -v prefix="$PUB_PREFIX/" 'NF!=2 || $1!="A" || index($2,prefix)!=1 {bad=1} END {exit bad}' "$PUB_OUT/commit-diff.tsv"
[[ $(wc -l < "$PUB_OUT/commit-diff.tsv") -eq $(wc -l < "$PUB_OUT/commit-files.tsv") ]] || pub_fail 'Unexpected staged changes'
stage=commit
pub_validate "$PUB_OUT/request.json" "$request_sha" "$tools_sha"
pub_remote_head "$PUB_OUT/remote-before-commit.txt"
tree=$(pub_git write-tree)
cat > "$PUB_OUT/commit-message.txt" <<'MESSAGE'
Publish candidate07 diagnostic outcomes and archived correction

Preserve all thirteen planned outcomes, failures and scoped independent audits.
Archive the exact numerical-trial-closure correction, regression fixtures and
source identities. This additive publication changes no active estimator,
compatibility default, frozen benchmark, numerical threshold or release status.
MESSAGE
commit=$(pub_git -c user.name='Florian Pfaff' -c user.email='6773539+FlorianPfaff@users.noreply.github.com' commit-tree "$tree" -p "$PUB_PARENT" -F "$PUB_OUT/commit-message.txt")
while IFS=$'\t' read -r from target blob sha; do
  [[ $(pub_git rev-parse "$commit:$target") == "$blob" && $(pub_sha "$from") == "$sha" ]]
  pub_git cat-file blob "$blob" | cmp - "$from"
done < "$PUB_OUT/commit-files.tsv"
pub_git diff-tree --no-commit-id --name-status -r "$commit" > "$PUB_OUT/committed-diff.tsv"
cmp "$PUB_OUT/commit-diff.tsv" "$PUB_OUT/committed-diff.tsv"
pub_git update-ref refs/heads/candidate07-sequence03-publication "$commit"
printf '%s\n' "$commit" > "$PUB_OUT/commit.txt"
jq -n --arg commit "$commit" --arg tree "$tree" --arg parent "$PUB_PARENT" --arg request "$request_sha" --arg tools "$tools_sha" --arg audit "$PUB_AUDIT_SHA" --arg packet "$PUB_PACKET_SHA" --argjson count "$(wc -l < "$PUB_OUT/commit-files.tsv")" '{schema:"candidate07-additive-evidence-commit-v1",commit:$commit,tree:$tree,parent:$parent,request_sha256:$request,publication_source_manifest_sha256:$tools,audit_sha256:$audit,packet_sha256sums_sha256:$packet,files_added:$count,files_modified:0,files_deleted:0,all_blobs_verified:true,pushed:false,active_source_changed:false,frozen_benchmarks_changed:false,release_authority:false}' > "$PUB_OUT/commit-receipt.json"
stage=complete
cat "$PUB_OUT/commit-receipt.json"
