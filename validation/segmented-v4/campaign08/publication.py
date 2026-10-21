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


def event_html(event):
    parts = ['<section class="block"><h2>' + escape(event["title"]) + '</h2><p>' + escape(event["detail"]) + '</p>']
    if "finished_at" in event:
        parts += ['<p class="small">Finished ' + escape(event["finished_at"]) + '; outer owned execution ' + format(event["elapsed_seconds"], '.3f') + ' seconds.</p>']
    if "workload_elapsed_seconds" in event:
        parts += ['<p class="small">Wrapper workload: ' + format(event["workload_elapsed_seconds"], '.3f') + ' seconds; return code ' + str(event["returncode"]) + '. These are setup durations, not per-fit timings.</p>']
    if "test_environment_event" in event:
        parts += ['<p>' + escape(event["test_environment_event"]) + '</p>']
    fields = (("review", "Review receipt"), ("request", "Exact request"),
              ("execution", "Execution and cleanup"), ("result", "Recorded result / receipt"),
              ("log", "Original log"), ("manifest", "Capture manifest"),
              ("acceptance", "Independent acceptance"), ("observer_summary", "Observer summary"), ("cleanup", "Fresh independent cleanup"))
    parts += ['<p>' + ' · '.join(link(event[k], label) for k, label in fields if k in event) + '</p></section>']
    return parts


def render():
    s = read("summary.json")
    prov = read("provenance.json")["copied_files"]
    ext = read("external-evidence.json")["artifacts"]
    b, source, prior = s["build01"], s["source_provenance"], s["prior_campaign"]
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>Segmented v4 · campaign08 recovery provenance</title>',
             """<style>
*{box-sizing:border-box}body{margin:0;background:#eef2f6;color:#172330;font:16px/1.6 system-ui,sans-serif}
main{max-width:1100px;margin:auto;padding:40px 24px 64px}header{background:#142d45;color:#fff;padding:30px;border-radius:12px}
h1{font-size:2rem;line-height:1.2;margin:8px 0 16px}h2{font-size:1.3rem;line-height:1.35;margin:0 0 16px}p{margin:12px 0}
a{color:#125a87;text-underline-offset:3px}header a{color:#a9e0ff}.eyebrow{letter-spacing:.1em;text-transform:uppercase;font-size:.8rem;color:#b7d7ed}
.stamp{color:#c1d5e4;font-size:.9rem}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:20px 0}.card{background:#fff;border:1px solid #d5dfe9;border-radius:10px;padding:18px}
.number{display:block;font-size:2rem;font-weight:700;line-height:1.2}.label{color:#526779;font-size:.9rem}.block{background:#fff;border:1px solid #d5dfe9;border-radius:10px;padding:25px;margin-top:20px}
.notice{border-left:5px solid #bf7b24;background:#fff8e9;padding:15px 20px;margin-top:20px}.small{font-size:.87rem;color:#526779}.scroll{overflow:auto}
table{width:100%;border-collapse:collapse;font-size:.9rem}th{text-align:left;background:#eff5f9}td,th{vertical-align:top;padding:12px;border-bottom:1px solid #dce4eb}
code{font-size:.8rem;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#142d45;color:#fff;padding:16px;border-radius:6px}
details{margin-top:16px}summary{cursor:pointer;font-weight:600}ul{padding-left:22px}footer{margin-top:24px;color:#526779;font-size:.85rem}
@media(max-width:650px){main{padding:20px 12px}.cards{grid-template-columns:1fr}header,.block{padding:20px}h1{font-size:1.65rem}}
</style><main>""",
             '<header><div class="eyebrow">Segmented v4 / campaign08</div>',
             '<h1>' + ('Terminal failure and provenance' if "terminal08" in s else 'Recovery controls and provenance') + '</h1><p>' + escape(s["scope"]) + '</p>',
             '<p class="stamp">Evidence cutoff: <time>' + escape(s.get("evidence_cutoff", s["snapshot_created_at"])) + '</time><br>Status: ' + escape(s["status"]) + '</p>',
             '<p>' + link("summary.json", "Machine-readable summary") + ' · ' + link(prior["relative_report"], "Preserved campaign07 terminal report") + '</p></header>',
             '<div class="cards"><div class="card"><span class="number">' + str(s["planned_fit_attempts"]) + '</span><span class="label">frozen planned fits</span></div>',
             '<div class="card"><span class="number">' + str(s["fit_attempts_observed"]) + '</span><span class="label">fit attempts in cited evidence</span></div>',
             '<div class="card"><span class="number">' + ('Stopped' if "terminal08" in s else ('Accepted' if s["actual_binary_build_accepted"] else 'Pending')) + '</span><span class="label">' + ('terminal controller state' if "terminal08" in s else 'control build acceptance') + '</span></div></div>',
             '<div class="notice"><strong>Evidence boundary.</strong> ' + escape(s["limits"][0]) + '</div>']
    if "terminal08" in s:
        parts += event_html(s["terminal08"])
    parts += ['<section class="block"><h2>Preserved campaign07 failure</h2><p>' + escape(prior["detail"]) + '</p>',
             '<p class="small">Finished ' + escape(prior["finished_at"]) + '. Published commit <code>' + escape(prior["publication_commit"]) + '</code>.</p></section>',
             '<section class="block"><h2>Reviewed recovery controls</h2><div class="scroll"><table><thead><tr><th>Control</th><th>Recorded evidence</th></tr></thead><tbody>']
    for row in s["control_reviews"]:
        parts += ['<tr><td>' + link(row["evidence"], row["label"]) + '</td><td>' + escape(str(row["tests_passed"]) + ' independent tests passed. ' + row["detail"]) + '</td></tr>']
    parts += ['</tbody></table></div><p class="small">Counts describe separate control suites and are not scientific validation results.</p>',
              '<p>Fresh host control: <code>' + escape(s["fresh_control"]["path"]) + '</code>. Device ' + str(s["fresh_control"]["device"]) + ', inode ' + str(s["fresh_control"]["inode"]) + '. ' + link(s["fresh_control_evidence"], "Dated identity capture") + '.</p></section>',
              '<section class="block"><h2>Build01 stopped before fixture validation</h2><p>' + escape(b["detail"]) + '</p>',
              '<p>' + link(b["execution"], "Execution and cleanup") + ' · ' + link(b["failure"], "Preserved failure") + ' · ' + link(b["log"], "Original traceback") + '</p>',
              '<p>Compiled executable SHA-256: <code>' + escape(b["binary_sha256"]) + '</code>.</p>',
              '<p class="small">The external capture contains ' + str(b["external_capture"]["files_verified"]) + ' files / ' + format(b["external_capture"]["bytes_verified"], ',') + ' bytes rehashed locally. Its full manifest, source tree and binary remain outside Git, pinned in the external evidence index.</p></section>',
              '<section class="block"><h2>Source change and provenance limits</h2><p>' + escape(source["detail"]) + '</p>',
              '<p>' + link(source["evidence"], "Source research and ordered patch replay") + ' · ' + link(source["patch"], "Exact cap-only patch") + ' · ' + link("evidence/source/receipt.json", "Source packet receipt") + '</p><ul>']
    parts += ['<li>' + escape(x) + '</li>' for x in source["limits"]]
    parts += ['</ul></section>']
    for key in ("validation02", "validation03", "build_acceptance", "production_transport", "recovery08", "launch08", "prior_reviewed_snapshot"):
        if key not in s:
            continue
        parts += event_html(s[key])
    if "related_campaign_status" in s:
        related = s["related_campaign_status"]
        parts += ['<section class="block"><h2>Separate original150 status</h2><p>' + escape(related["detail"]) + '</p><p class="small">Observed: ' + escape(related["observed_at"]) + '. The full read-only capture is pinned in ' + link("external-evidence.json", "external evidence") + '.</p></section>']
    if s.get("historical_control_reviews"):
        parts += ['<section class="block"><h2>Preserved earlier control versions</h2><p>These accepted reviews describe historical controls. The transport correction supersedes them for campaign08.</p><ul>']
        parts += ['<li>' + link(row["evidence"], row["label"]) + ': ' + escape(row["detail"]) + '</li>' for row in s["historical_control_reviews"]]
        parts += ['</ul></section>']
    parts += ['<section class="block"><h2>Frozen taskset ELF compatibility</h2><p>' + escape(s["elf_compatibility"]["detail"]) + '</p><p>' + link(s["elf_compatibility"]["evidence"], "Measured ELF-version summary") + '</p></section>',
              '<section class="block"><h2>Unchanged scientific context</h2><p>These original artifact identities remain fixed across the control recovery.</p><div class="scroll"><table><thead><tr><th>Artifact</th><th>SHA-256 / manifest identity</th></tr></thead><tbody>']
    for key, value in s["unchanged_artifact_pins"].items():
        parts += ['<tr><td>' + escape(key.replace('_', ' ')) + '</td><td><code>' + escape(value) + '</code></td></tr>']
    parts += ['</tbody></table></div></section><section class="block"><h2>Exact control bytes and external artifacts</h2>',
              '<p>Copies retain their original bytes and path semantics. They are review evidence; execution requires the complete separately accepted context.</p>',
              '<details><summary>Inspect copied Python controls and fixtures</summary><div class="scroll"><table><thead><tr><th>File</th><th>SHA-256 / bytes</th></tr></thead><tbody>']
    for row in prov:
        if row["path"].startswith("controls/") and row["path"].endswith(".py"):
            parts += ['<tr><td>' + link(row["path"]) + '</td><td><code>' + row["sha256"] + '</code><br>' + str(row["bytes"]) + ' bytes</td></tr>']
    parts += ['</tbody></table></div></details><p>' + link("provenance.json", str(len(prov)) + " exact copied files") + ' · ' + link("external-evidence.json", str(len(ext)) + " external artifact pins") + '</p>',
              '<p class="small">Bulk source archives, executable bytes, input inventories, row data and full host observations remain outside this bundle. Remote-only identities are attributed to their evidence record; locally rehashed artifacts are explicitly marked.</p></section>',
              '<section class="block"><h2>Reproduce publication checks</h2><p>From this folder:</p><pre>python3 -B publication.py verify</pre>',
              '<p>Add <code>--source-copies</code> to compare the evidence copies with the original local controls. Checks cover the closed byte inventory, hashes, copy provenance, JSON, Python syntax and report links. They never import or execute campaign controls.</p>',
              '<p>' + link(MANIFEST, "Publication inventory") + ' excludes only itself. Its reviewed Git commit anchors the bundle.</p></section>',
              '<section class="block"><h2>Interpretation limits</h2><ul>']
    parts += ['<li>' + escape(x) + '</li>' for x in s["limits"]]
    parts += ['</ul></section><footer>Static evidence publication. Status is tied to the cited records and does not refresh from the remote host.</footer></main></html>']
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
        write_json(MANIFEST, {"schema": "orbit-poc-campaign08-publication-inventory-v1",
                             "scope": "Closed publication inventory; excludes this manifest itself.",
                             "files": rows})
    verify(args.source_copies)


if __name__ == "__main__":
    main()
