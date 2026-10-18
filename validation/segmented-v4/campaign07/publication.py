#!/usr/bin/env python3
"""Render or verify this evidence publication; never import/run campaign controls."""
from pathlib import Path
import argparse
import ast
import hashlib
from html import escape
from html.parser import HTMLParser
import json

ROOT = Path(__file__).resolve().parent
MANIFEST = "publication-manifest.json"


def read(name):
    return json.loads((ROOT / name).read_text())


def pin(path):
    data = path.read_bytes()
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def write_json(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def safe(name):
    path = ROOT / name
    if Path(name).is_absolute() or ".." in Path(name).parts or path.is_symlink():
        raise ValueError("Unsafe publication path: " + name)
    if not path.is_file() or ROOT not in path.resolve().parents:
        raise ValueError("Missing publication file: " + name)
    return path


def link(path, label=None):
    return '<a href="' + escape(path, quote=True) + '">' + escape(label or path) + '</a>'


def render():
    s = read("summary.json")
    p = s["preparation_publication"]
    prov = read("provenance.json")["copied_files"]
    ext = read("external-evidence.json")["artifacts"]
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>Segmented v4 · campaign07 provenance</title>',
             '''<style>
*{box-sizing:border-box}body{margin:0;background:#eef2f6;color:#172330;font:16px/1.6 system-ui,sans-serif}
main{max-width:1100px;margin:auto;padding:40px 24px 64px}header{background:#142d45;color:#fff;padding:30px;border-radius:12px}
h1{font-size:2rem;line-height:1.2;margin:8px 0 16px}h2{font-size:1.3rem;line-height:1.35;margin:0 0 16px}h3{font-size:1.05rem}
p{margin:12px 0}a{color:#125a87;text-underline-offset:3px}header a{color:#a9e0ff}.eyebrow{letter-spacing:.1em;text-transform:uppercase;font-size:.8rem;color:#b7d7ed}
.stamp{color:#c1d5e4;font-size:.9rem}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:20px 0}.card{background:#fff;border:1px solid #d5dfe9;border-radius:10px;padding:18px}
.number{display:block;font-size:2rem;font-weight:700;line-height:1.2}.label{color:#526779;font-size:.9rem}.block{background:#fff;border:1px solid #d5dfe9;border-radius:10px;padding:25px;margin-top:20px}
.notice{border-left:5px solid #bf7b24;background:#fff8e9;padding:15px 20px;margin-top:20px}.small{font-size:.87rem;color:#526779}.scroll{overflow:auto}
table{width:100%;border-collapse:collapse;font-size:.9rem}th{text-align:left;background:#eff5f9}td,th{vertical-align:top;padding:12px;border-bottom:1px solid #dce4eb}
code{font-size:.8rem;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#142d45;color:#fff;padding:16px;border-radius:6px}
details{margin-top:16px}summary{cursor:pointer;font-weight:600}ul{padding-left:22px}footer{margin-top:24px;color:#526779;font-size:.85rem}
@media(max-width:650px){main{padding:20px 12px}.cards{grid-template-columns:1fr}header,.block{padding:20px}h1{font-size:1.65rem}}
</style><main>''',
             '<header><div class="eyebrow">Segmented v4 / campaign07</div>',
             '<h1>Campaign controls and provenance</h1>',
             '<p>' + escape(s["scope"]) + '</p>',
             '<p class="stamp">Evidence cutoff: <time>' + escape(s["evidence_cutoff"]) + '</time><br>Status: ' + escape(s["status"]) + '</p>',
             '<p>' + link("summary.json", "Machine-readable summary") + ' · ' + link(p["relative_report"], "Audited input preparation") + '</p></header>',
             '<div class="cards"><div class="card"><span class="number">' + str(p["prepared_cases"]) + '</span><span class="label">prepared cases</span></div>',
             '<div class="card"><span class="number">' + str(p["planned_fit_attempts"]) + '</span><span class="label">frozen planned fits</span></div>',
             '<div class="card"><span class="number">' + str(s["observed_fit_attempts"]["count"]) + '</span><span class="label">fit attempts in the cited snapshot</span></div></div>',
             '<p class="small">' + escape(s["observed_fit_attempts"]["scope"]) + ' ' + link(s["observed_fit_attempts"]["evidence"], "Snapshot source") + '.</p>',
             '<div class="notice"><strong>Evidence boundary.</strong> ' + escape(s.get("boundary", "No campaign launch, successful inner probe or fit outcome is asserted by this snapshot.")) + ' Release ready: ' + str(s["release_ready"]).lower() + '.</div>']
    for milestone in ("terminal_milestone", "metadata_milestone", "assembly_milestone", "launch_milestone"):
        if milestone in s:
            m = s[milestone]
            parts += ['<section class="block"><h2>' + escape(m["title"]) + '</h2><p>' + escape(m["detail"]) + '</p><ul>']
            parts += ['<li>' + link(x["path"], x["label"]) + '</li>' for x in m["evidence"]]
            parts += ['</ul></section>']
    parts += ['<section class="block"><h2>Reviewed controls</h2><div class="scroll"><table><thead><tr><th>Control</th><th>Recorded evidence</th></tr></thead><tbody>']
    for row in s["control_reviews"]:
        count = str(row["tests_passed"]) + ' independent tests passed. ' if "tests_passed" in row else ''
        parts += ['<tr><td>' + link(row["evidence"], row["label"]) + '</td><td>' + escape(count + row["detail"]) + '</td></tr>']
    parts += ['</tbody></table></div><p class="small">Test counts describe their cited control suites and are not added together as independent scientific evidence.</p></section>',
              '<section class="block"><h2>Preserved metadata failures</h2><p>All setup failures retain their execution records, logs, independent review and external artifact identities. None is a scientific fit outcome.</p>']
    for f in s["preserved_failures"]:
        parts += ['<h3>' + escape(f["id"]) + ' · ' + format(f["elapsed_seconds"], '.3f') + ' seconds</h3><p>' + escape(f["detail"]) + '</p><p>' + link(f["evidence"], "Independent review") + ' · ' + link(f["execution"], "Execution record") + ' · ' + link(f["log"], "Original log") + '</p>']
    a = s["actual_metadata"]
    parts += ['</section>']
    for event in s.get("control_events", []):
        parts += ['<section class="block"><h2>' + escape(event["title"]) + '</h2><p>' + escape(event["detail"]) + '</p><ul>']
        parts += ['<li>' + link(x["path"], x["label"]) + '</li>' for x in event["evidence"]]
        parts += ['</ul></section>']
    if "control_correction" in s or "pending_correction" in s:
        candidate = s.get("control_correction", s.get("pending_correction"))
        parts += ['<section class="block"><h2>' + escape(candidate.get("title", "Correction candidate awaiting review")) + '</h2><p>' + escape(candidate["detail"]) + '</p><ul>']
        parts += ['<li>' + link(x["path"], x["label"]) + '</li>' for x in candidate["evidence"]]
        parts += ['</ul></section>']
    parts += ['<section class="block"><h2>Actual metadata packet</h2><p>Status: <strong>' + escape(a["status"]) + '</strong>. ' + escape(a.get("output_root_label", "Fresh output root")) + ':</p><p><code>' + escape(a["fresh_output_root"]) + '</code></p><ul>']
    for name in ("request", "plan", "readonly_view", "parent_topology", "installation", "derivation"):
        parts += ['<li>' + link(a[name], name.replace('_', ' ').capitalize()) + '</li>']
    for key, label in (("terminal_audit", "Terminal independent audit"),
                       ("sealed_result", "Sealed result"),
                       ("invocation", "Exact invocation metadata"),
                       ("correspondence", "Conditional correspondence result")):
        if key in a:
            parts += ['<li>' + link(a[key], label) + '</li>']
    parts += ['</ul><p>Manifest identity: <code>' + escape(p["manifest_hash"]) + '</code></p>',
              '<p class="small">Prepared source: ' + str(p["source_files_verified"]) + ' files; aggregate SHA-256 <code>' + escape(p["full_405_source_sha256"]) + '</code>. Preparation publication commit <code>' + escape(p["commit"]) + '</code>.</p></section>',
              '<section class="block"><h2>Exact control bytes</h2><p>The copies below retain reviewed bytes and original path semantics. They are evidence copies; remote execution requires the complete pinned context and approved packet.</p><details><summary>Inspect copied Python controls and fixtures</summary><div class="scroll"><table><thead><tr><th>File</th><th>SHA-256 / bytes</th></tr></thead><tbody>']
    for row in prov:
        if row["path"].startswith("controls/") and row["path"].endswith(".py"):
            parts += ['<tr><td>' + link(row["path"]) + '</td><td><code>' + row["sha256"] + '</code><br>' + str(row["bytes"]) + ' bytes</td></tr>']
    parts += ['</tbody></table></div></details><p>' + link("provenance.json", "Complete byte-copy provenance") + ' · ' + link("external-evidence.json", str(len(ext)) + " external artifact pins") + '</p></section>',
              '<section class="block"><h2>Reproduce the publication checks</h2><p>From this folder, verify the closed file inventory, SHA-256 identities, copy provenance, JSON, Python syntax and local report links:</p><pre>python3 -B publication.py verify</pre><p>Add <code>--source-copies</code> to compare exact copies with the original local control workspace. This verifier does not start a namespace or import or execute campaign controls.</p><p>' + link(MANIFEST, "Publication inventory") + ' excludes only itself. Anchor its identity in the reviewed Git commit when transferring the bundle. Bulk inputs, collision ledgers and runtime inventories remain external; remote-only pins are attributed to the named evidence record.</p></section>',
              '<section class="block"><h2>Interpretation limits</h2><ul>']
    parts += ['<li>' + escape(x) + '</li>' for x in s["limits"]]
    parts += ['</ul></section>']
    if "related_campaign_status" in s:
        related = s["related_campaign_status"]
        parts += ['<section class="block"><h2>Separate original150 status</h2><p>' + escape(related["detail"]) + '</p><p class="small">Observed: ' + escape(related["observed_at"]) + ' · ' + link(related["evidence"], "Dated extract and source pin") + '</p></section>']
    if s.get("prior_publications"):
        parts += ['<section class="block"><h2>Earlier published snapshot</h2><p>The previous dated status and all earlier evidence remain recoverable from the recorded Git commit.</p><ul>']
        for earlier in s["prior_publications"]:
            parts += ['<li>' + escape(earlier["evidence_cutoff"]) + ' · <code>' + escape(earlier["commit"]) + '</code><br>Publication manifest SHA-256: <code>' + escape(earlier["manifest_sha256"]) + '</code></li>']
        parts += ['</ul></section>']
    parts += ['<footer>Static evidence publication. Counts and statuses are tied to the cited capture, not refreshed from the running host.</footer></main></html>']
    (ROOT / "index.html").write_text('\n'.join(parts) + '\n')


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in ("href", "src"):
                self.targets.append(value)


def verify(source_copies=False):
    rows = read(MANIFEST)["files"]
    expected = {row["path"] for row in rows}
    actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()}
    if len(expected) != len(rows) or actual != expected | {MANIFEST}:
        raise ValueError("Publication inventory does not exactly match files")
    for row in rows:
        if pin(safe(row["path"])) != row:
            raise ValueError("Changed bytes: " + row["path"])
    copied = read("provenance.json")["copied_files"]
    for row in copied:
        current = pin(safe(row["path"]))
        if any(current[k] != row[k] for k in ("bytes", "sha256")):
            raise ValueError("Changed evidence copy: " + row["path"])
        if source_copies:
            data = Path(row["source_path"]).read_bytes()
            if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("Changed original source: " + row["source_path"])
    for path in ROOT.rglob('*.json'):
        json.loads(path.read_bytes())
    for path in ROOT.rglob('*.py'):
        ast.parse(path.read_bytes(), filename=str(path))
    links = Links()
    links.feed((ROOT / "index.html").read_text())
    for target in links.targets:
        if '://' not in target and not (ROOT / target.split('#')[0]).is_file():
            raise ValueError("Broken report link: " + target)
    print(json.dumps({"status": "verified_publication_bytes_and_links",
                      "inventory_files": len(rows), "copied_files": len(copied),
                      "bytes_excluding_manifest": sum(r["bytes"] for r in rows),
                      "source_copies_rechecked": source_copies,
                      "campaign_controls_executed": False}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["refresh", "verify"])
    parser.add_argument("--source-copies", action="store_true")
    args = parser.parse_args()
    if args.action == "refresh":
        render()
        rows = [pin(p) for p in sorted(ROOT.rglob('*')) if p.is_file() and p.name != MANIFEST]
        write_json(MANIFEST, {"schema": "orbit-poc-campaign07-publication-inventory-v1",
                             "scope": "Closed publication inventory; excludes this manifest itself.",
                             "files": rows})
    verify(args.source_copies)


if __name__ == "__main__":
    main()
