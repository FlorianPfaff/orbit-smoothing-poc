#!/usr/bin/env bash
# Future execution only. Exact expected-parent lease plus verified direct-child
# commit prevents any history rewrite; an exclusive directory owns one attempt.
# Never edits PR metadata, substitutes a parent or retries.
set -euo pipefail
[[ $# == 4 ]] || { printf 'usage: push_commit.sh PREPARED_OUTPUT REQUEST_SHA TOOLING_LEDGER_SHA COMMIT_RECEIPT_SHA\n' >&2; exit 2; }
source "$(dirname -- "${BASH_SOURCE[0]}")/publication_contract.sh"
PUB_OUT=$1; request_sha=$2; tools_sha=$3; receipt_sha=$4
[[ $PUB_OUT =~ ^/mnt/d/orbit-v41-recovery02/candidate07-git-publication-run[0-9]{2,}$ && $(realpath -e -- "$PUB_OUT") == "$PUB_OUT" && ! -L $PUB_OUT ]] || pub_fail 'Prepared dedicated output required'
[[ $receipt_sha =~ ^[0-9a-f]{64}$ && ! -e $PUB_OUT/push-attempt.json && ! -L $PUB_OUT/push-attempt.json && ! -e $PUB_OUT/push-receipt.json && ! -L $PUB_OUT/push-receipt.json ]] || pub_fail 'Exact unpushed commit receipt required; no implicit retry'
pub_regular "$PUB_OUT/commit-receipt.json"
[[ $(pub_sha "$PUB_OUT/commit-receipt.json") == "$receipt_sha" ]] || pub_fail 'Prepared commit receipt differs'
pub_validate "$PUB_OUT/request.json" "$request_sha" "$tools_sha"
jq -e --arg request "$request_sha" --arg tools "$tools_sha" --arg parent "$PUB_PARENT" --arg audit "$PUB_AUDIT_SHA" --arg packet "$PUB_PACKET_SHA" '
 .schema=="candidate07-additive-evidence-commit-v1" and .request_sha256==$request and .publication_source_manifest_sha256==$tools
 and .parent==$parent and .audit_sha256==$audit and .packet_sha256sums_sha256==$packet
 and .files_modified==0 and .files_deleted==0 and .all_blobs_verified==true and .pushed==false
 and .active_source_changed==false and .frozen_benchmarks_changed==false and .release_authority==false' "$PUB_OUT/commit-receipt.json" >/dev/null
commit=$(jq -er .commit "$PUB_OUT/commit-receipt.json")
[[ $commit =~ ^[0-9a-f]{40}$ && $(pub_git rev-list --parents -n 1 "$commit") == "$commit $PUB_PARENT" ]] || pub_fail 'Commit is not a direct child of the reviewed parent'
[[ $(pub_git rev-parse "$commit^{tree}") == "$(jq -er .tree "$PUB_OUT/commit-receipt.json")" ]] || pub_fail 'Commit tree differs'
while IFS=$'\t' read -r from target blob sha; do
  pub_regular "$from"; pub_relative "$target"
  [[ $target == "$PUB_PREFIX/"* && $(pub_sha "$from") == "$sha" && $(pub_git rev-parse "$commit:$target") == "$blob" ]]
  pub_git cat-file blob "$blob" | cmp - "$from"
done < "$PUB_OUT/commit-files.tsv"
# Atomic directory creation is the one-attempt claim. A concurrent invocation
# loses here before writing any push-phase file. Never remove it after failure.
PUSH_OUT="$PUB_OUT/push-attempt01"
mkdir -- "$PUSH_OUT" || pub_fail 'Push attempt already claimed; preserve it and inspect separately'
set -o noclobber
jq -n --arg commit "$commit" --arg parent "$PUB_PARENT" --arg receipt "$receipt_sha" --argjson pid "$$" '{schema:"candidate07-additive-push-claim-v1",status:"claimed",claim_owner_pid:$pid,commit:$commit,expected_parent:$parent,commit_receipt_sha256:$receipt,transmission_started:false}' > "$PUSH_OUT/claim.json"
pub_git diff-tree --no-commit-id --name-status -r "$commit" > "$PUSH_OUT/verified-diff.tsv"
cmp "$PUB_OUT/commit-diff.tsv" "$PUSH_OUT/verified-diff.tsv"
awk -F '\t' -v prefix="$PUB_PREFIX/" 'NF!=2 || $1!="A" || index($2,prefix)!=1 {bad=1} END {exit bad}' "$PUSH_OUT/verified-diff.tsv"
[[ $(wc -l < "$PUSH_OUT/verified-diff.tsv") -eq $(jq -er .files_added "$PUB_OUT/commit-receipt.json") ]] || pub_fail 'Additive file count differs'
pub_remote_head "$PUSH_OUT/remote-before.txt"
jq -n --arg commit "$commit" --arg parent "$PUB_PARENT" --arg ref "$PUB_REF" --arg receipt "$receipt_sha" '{schema:"candidate07-additive-push-attempt-v2",status:"about_to_push",commit:$commit,expected_parent:$parent,expected_ref:$ref,commit_receipt_sha256:$receipt,explicit_expected_parent_lease:true,direct_child_verified:true,pushed:null}' > "$PUSH_OUT/attempt.json"
# Exact explicit lease is checked by Git's ref update. Unlike a plain push, a
# concurrent rewind/deletion also fails. The verified direct-child relation
# above permits only the reviewed fast-forward; no unconstrained force is used.
pub_git push --porcelain "--force-with-lease=$PUB_REF:$PUB_PARENT" "$PUB_REMOTE" "$commit:$PUB_REF" > "$PUSH_OUT/git-push.log" 2>&1
pub_clean_git ls-remote --exit-code --refs "$PUB_REMOTE" "$PUB_REF" > "$PUSH_OUT/remote-after.txt"
[[ $(wc -l < "$PUSH_OUT/remote-after.txt") -eq 1 && $(cut -f1 "$PUSH_OUT/remote-after.txt") == "$commit" && $(cut -f2 "$PUSH_OUT/remote-after.txt") == "$PUB_REF" ]] || pub_fail 'Remote outcome not confirmed; preserve attempt and inspect separately'
jq -n --arg commit "$commit" --arg parent "$PUB_PARENT" --arg ref "$PUB_REF" --arg remote "$PUB_REMOTE" --arg receipt "$receipt_sha" '{schema:"candidate07-additive-push-receipt-v2",commit:$commit,parent:$parent,remote:$remote,ref:$ref,commit_receipt_sha256:$receipt,pushed:true,remote_head_verified:true,explicit_expected_parent_lease:true,direct_child_verified:true,unconditional_force_push:false,history_rewrite:false,exclusive_attempt_claim:true,pr_metadata_changed:false,release_authority:false}' > "$PUSH_OUT/receipt.json"
cat "$PUSH_OUT/receipt.json"
