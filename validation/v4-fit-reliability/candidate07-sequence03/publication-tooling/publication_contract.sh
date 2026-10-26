#!/usr/bin/env bash
# Source definitions only. No Git/network mutation occurs merely by sourcing.
PUB_TOOLS=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
PUB_REMOTE=https://github.com/FlorianPfaff/orbit-smoothing-poc.git
PUB_REF=refs/heads/v4-fit-reliability
PUB_PREFIX=validation/v4-fit-reliability/candidate07-sequence03
PUB_HISTORY=fbbc72ffb628d98b9d4b61c5a5c5d2c4bd0c856a
PUB_CORRECTION_SHA=18cab9c4fb3c214798682f639e0e7bbc97fbd94d591226c7d620288ef616d6c9
PUB_SNAPSHOT_SHA=4b997bcda7c94bce973389542895dca05a3fde6e7a53fdb4178fb61eaf22646e
PUB_CANONICAL_SHA=b49cd3938791f1e3d6dcc828cb414d7010cf3175aa604d23c4631e95f485413a
pub_fail() { printf '%s\n' "$*" >&2; return 1; }
pub_sha() { sha256sum -- "$1" | cut -d' ' -f1; }
pub_regular() { [[ -f $1 && ! -L $1 && $(realpath -e -- "$1") == "$1" ]] || pub_fail "Not a canonical regular file: $1"; }
pub_relative() {
  [[ $1 =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ && $1 != *'//'* && "/$1/" != *'/../'* && "/$1/" != *'/./'* ]] || pub_fail "Unsafe relative member: $1"
}
pub_verify_packet() {
  local root=$1 expected=$2 line digest name actual total=0 count=0
  local -A seen=()
  [[ -d $root && ! -L $root && $(realpath -e -- "$root") == "$root" ]] || pub_fail 'Packet root must be canonical'
  pub_regular "$root/SHA256SUMS"
  [[ $(pub_sha "$root/SHA256SUMS") == "$expected" && $(stat -c %s "$root/SHA256SUMS") -le 4194304 ]] || pub_fail 'Packet manifest identity/size differs'
  [[ -z $(find "$root" ! -type d ! -type f -print -quit) ]] || pub_fail 'Packet contains links or special files'
  while IFS= read -r line || [[ -n $line ]]; do
    [[ $line =~ ^([0-9a-f]{64})\ \ (.+)$ ]] || pub_fail 'Invalid packet manifest line'
    digest=${BASH_REMATCH[1]}; name=${BASH_REMATCH[2]}; pub_relative "$name"
    [[ $name != SHA256SUMS && -z ${seen[$name]+x} ]] || pub_fail 'Duplicate/self manifest member'
    case "$name" in correction-source|correction-source/*|publication-tooling|publication-tooling/*|independent-audit.json|publication-request.json) pub_fail 'Reserved additive publication path in packet';; esac
    seen[$name]=1; pub_regular "$root/$name"
    actual=$(stat -c %s "$root/$name"); [[ $actual -le 4194304 ]] || pub_fail 'Packet member exceeds original4MiB limit'
    total=$((total+actual)); count=$((count+1))
    [[ $total -le 33554432 && $(pub_sha "$root/$name") == "$digest" ]] || pub_fail 'Packet byte identity/32MiB payload bound differs'
  done < "$root/SHA256SUMS"
  [[ $count -gt 0 && $(find "$root" -type f | wc -l) -eq $((count+1)) ]] || pub_fail 'Missing or extra packet files'
  for name in report.json index.html inputs-manifest.json build_packet.py README.txt; do [[ -n ${seen[$name]+x} ]] || pub_fail 'Required generated packet member missing'; done
}
pub_validate() {
  # request path, exact request SHA, frozen tooling ledger SHA
  local request=$1 request_sha=$2 tools_sha=$3
  [[ $request_sha =~ ^[0-9a-f]{64}$ && $tools_sha =~ ^[0-9a-f]{64}$ ]] || pub_fail 'Exact SHA256 arguments required'
  pub_regular "$request"; [[ $(stat -c %s "$request") -le 1048576 && $(pub_sha "$request") == "$request_sha" ]] || pub_fail 'Request identity/size differs'
  [[ $(pub_sha "$PUB_TOOLS/source.sha256") == "$tools_sha" ]] || pub_fail 'Publication tooling changed'
  (cd "$PUB_TOOLS" && sha256sum -c source.sha256 --quiet)
  [[ $(pub_sha "$PUB_TOOLS/correction-source/SHA256SUMS") == "$PUB_CORRECTION_SHA" ]] || pub_fail 'Correction source ledger changed'
  (cd "$PUB_TOOLS/correction-source" && sha256sum -c SHA256SUMS --quiet)
  [[ $(pub_sha "$PUB_TOOLS/correction-source/provenance/source-snapshot.json") == "$PUB_SNAPSHOT_SHA" ]] || pub_fail 'Snapshot file changed'
  [[ $(jq -cS -j '.files' "$PUB_TOOLS/correction-source/provenance/source-snapshot.json" | sha256sum | cut -d' ' -f1) == "$PUB_CANONICAL_SHA" ]] || pub_fail 'Canonical ordered-file identity changed'
  jq -e --arg tools "$tools_sha" '
    (keys|sort)==(["schema","expected_remote_parent","packet","packet_sha256sums_sha256","report_sha256","inputs_manifest_sha256","audit","audit_sha256","publication_source_manifest_sha256"]|sort)
    and .schema=="candidate07-additive-git-publication-request-v1"
    and (.expected_remote_parent|type=="string" and test("^[0-9a-f]{40}$"))
    and ([.packet_sha256sums_sha256,.report_sha256,.inputs_manifest_sha256,.audit_sha256,.publication_source_manifest_sha256]|all(type=="string" and test("^[0-9a-f]{64}$")))
    and .publication_source_manifest_sha256==$tools and (.packet|type=="string") and (.audit|type=="string")' "$request" >/dev/null
  PUB_PACKET=$(jq -r .packet "$request"); PUB_AUDIT=$(jq -r .audit "$request")
  PUB_PARENT=$(jq -r .expected_remote_parent "$request")
  PUB_PACKET_SHA=$(jq -r .packet_sha256sums_sha256 "$request")
  PUB_AUDIT_SHA=$(jq -r .audit_sha256 "$request")
  pub_verify_packet "$PUB_PACKET" "$PUB_PACKET_SHA"
  pub_regular "$PUB_AUDIT"; [[ $(stat -c %s "$PUB_AUDIT") -le 4194304 && $(pub_sha "$PUB_AUDIT") == "$PUB_AUDIT_SHA" ]] || pub_fail 'Actual independent audit identity differs'
  [[ $(pub_sha "$PUB_PACKET/report.json") == "$(jq -r .report_sha256 "$request")" && $(pub_sha "$PUB_PACKET/inputs-manifest.json") == "$(jq -r .inputs_manifest_sha256 "$request")" ]] || pub_fail 'Actual packet report/input identity differs'
  jq -e --slurpfile r "$request" --arg corr "$PUB_CORRECTION_SHA" --arg snapshot "$PUB_SNAPSHOT_SHA" --arg canonical "$PUB_CANONICAL_SHA" '
    .schema=="candidate07-sequence03-independent-packet-review-v1" and .approved_for_publication==true and .blocking_findings==[]
    and .packet==$r[0].packet and .packet_sha256sums_sha256==$r[0].packet_sha256sums_sha256
    and .report_sha256==$r[0].report_sha256 and .inputs_manifest_sha256==$r[0].inputs_manifest_sha256
    and .publication_source_manifest_sha256==$r[0].publication_source_manifest_sha256
    and .correction_source_manifest_sha256==$corr and .candidate07_snapshot_file_sha256==$snapshot
    and .candidate07_canonical_source_identity==$canonical
    and .release_authority==false and .covariance_authority==false and .scientific_release_authority==false' "$PUB_AUDIT" >/dev/null
  # This is an outcome-agnostic completeness/scope check, not numerical re-audit.
  jq -e '.schema=="candidate07-sequence03-publication-v1" and (.status=="audited_diagnostic_checks_passed" or .status=="diagnostic_failures_or_incomplete_evidence")
    and .release_authority==false and .covariance_authority==false and .accuracy_claim==false
    and .frozen_benchmarks_unchanged==true
    and ([.outcomes[].stage]==["native-tests","native-fail-fast-tests","correction-tests","synthetic-refinement-log_drag_ou","synthetic-refinement-pulses","flight-refinement","eccentric-24h-refinement","objective-log_drag_ou","objective-pulses","nuisance-replay","nuisance-replay-candidate1-point012","cold-pulses","cold-density"])
    and (.saved_audits|keys)==["export","rank","scientific","selected"]' "$PUB_PACKET/report.json" >/dev/null
  local snapshot_link
  snapshot_link=$(jq -er '.source_receipt_links["candidate/source-snapshot.json"]' "$PUB_PACKET/report.json")
  pub_relative "$snapshot_link"; pub_regular "$PUB_PACKET/$snapshot_link"
  [[ $(pub_sha "$PUB_PACKET/$snapshot_link") == "$PUB_SNAPSHOT_SHA" ]] || pub_fail 'Packet carries a different candidate source snapshot'
}
pub_clean_git() { env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_OBJECT_DIRECTORY -u GIT_ALTERNATE_OBJECT_DIRECTORIES -u GIT_COMMON_DIR -u GIT_NAMESPACE -u GIT_CONFIG_COUNT -u GIT_CONFIG_PARAMETERS git -c core.hooksPath=/dev/null "$@"; }
pub_git() { pub_clean_git --git-dir="$PUB_OUT/git01" "$@"; }
pub_remote_head() {
  local file=$1
  pub_clean_git ls-remote --exit-code --refs "$PUB_REMOTE" "$PUB_REF" > "$file"
  [[ $(wc -l < "$file") -eq 1 ]] || pub_fail 'Remote branch missing or ambiguous'
  [[ $(cut -f1 "$file") == "$PUB_PARENT" && $(cut -f2 "$file") == "$PUB_REF" ]] || pub_fail 'Remote parent moved; prepare a separately reviewed request, never overwrite it'
}
