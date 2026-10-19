#!/usr/bin/env python3
"""Render and verify this static report; never import or execute campaign controls."""
from pathlib import Path
import argparse
import ast
import hashlib
from html import escape
from html.parser import HTMLParser
import json

ROOT = Path(__file__).resolve().parent
MANIFEST = 'publication-manifest.json'

def read(name):
    return json.loads((ROOT / name).read_bytes())

def pin(path):
    data = path.read_bytes()
    return {'path': path.relative_to(ROOT).as_posix(), 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest()}

def save(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')

def link(path, label):
    return '<a href="' + escape(path, quote=True) + '">' + escape(label) + '</a>'

def render():
    s = read('summary.json')
    c = s['context']
    copies = read('provenance.json')['copied_files']
    external = read('external-evidence.json')['artifacts']
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>Segmented v4 · campaign09 provenance</title>',
             '''<style>
*{box-sizing:border-box}body{margin:0;background:#eef2f6;color:#172330;font:16px/1.6 system-ui,sans-serif}
main{max-width:1100px;margin:auto;padding:40px 24px 64px}header{background:#142d45;color:#fff;padding:30px;border-radius:12px}
h1{font-size:2rem;line-height:1.2;margin:8px 0 16px}h2{font-size:1.3rem;line-height:1.35;margin:0 0 16px}p{margin:12px 0}
a{color:#125a87;text-underline-offset:3px}header a{color:#a9e0ff}.stamp{color:#c1d5e4;font-size:.9rem}
.block{background:#fff;border:1px solid #d5dfe9;border-radius:10px;padding:25px;margin-top:20px}.notice{border-left:5px solid #bf7b24;background:#fff8e9;padding:15px 20px;margin-top:20px}
table{width:100%;border-collapse:collapse;font-size:.9rem}th{text-align:left;background:#eff5f9}td,th{vertical-align:top;padding:12px;border-bottom:1px solid #dce4eb}
code{font-size:.8rem;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#142d45;color:#fff;padding:16px;border-radius:6px}.scroll{overflow:auto}
.small{font-size:.87rem;color:#526779}footer{margin-top:24px;color:#526779;font-size:.85rem}@media(max-width:650px){main{padding:20px 12px}header,.block{padding:20px}}
</style><main>''', '<header><p>Segmented v4 / campaign09</p><h1>' + escape(s['title']) + '</h1>',
             '<p>' + escape(s['scope']) + '</p><p class="stamp">Evidence cutoff: ' + escape(s['evidence_cutoff']) + '<br>Status: ' + escape(s['status']) + '</p>',
             '<p>' + link('summary.json', 'Machine-readable summary') + ' · ' + link('../campaign08/index.html', 'Preserved campaign08 failure') + '</p></header>',
             '<div class="notice">Frozen planned fits: ' + str(s['planned_fit_attempts']) + '. Started in cited evidence: ' + str(s['fit_attempts_started']) + '. Completed: ' + str(s['fit_attempts_completed']) + '. Release ready: ' + str(s['release_ready']).lower() + '.</div>']
    for event in s['events']:
        parts += ['<section class="block"><h2>' + escape(event['title']) + '</h2><p>' + escape(event['detail']) + '</p><ul>']
        parts += ['<li>' + link(e['path'], e['label']) + '</li>' for e in event['evidence']]
        parts += ['</ul></section>']
    for event in c['events']:
        parts += ['<section class="block"><h2>' + escape(event['title']) + '</h2><p>' + escape(event['detail']) + '</p><ul>']
        parts += ['<li>' + link(e['path'], e['label']) + '</li>' for e in event['evidence']]
        parts += ['</ul></section>']
    parts += ['<section class="block"><h2>Exact control copies</h2><div class="scroll"><table><thead><tr><th>File</th><th>SHA-256 / bytes</th></tr></thead><tbody>']
    for row in copies:
        if row['path'].startswith('controls/') and row['path'].endswith('.py'):
            parts += ['<tr><td>' + link(row['path'], row['path']) + '</td><td><code>' + row['sha256'] + '</code><br>' + str(row['bytes']) + ' bytes</td></tr>']
    parts += ['</tbody></table></div><p>' + link('provenance.json', str(len(copies)) + ' exact source copies') + ' · ' + link('external-evidence.json', str(len(external)) + ' external pins') + '</p></section>',
              '<section class="block"><h2>Reproduce publication checks</h2><pre>python3 -B publication.py verify</pre><p>Add <code>--source-copies</code> to compare exact copies with the original workspace. The verifier checks the closed byte inventory, JSON, Python syntax and report links without importing or running any campaign control.</p><p>' + link(MANIFEST, 'Publication inventory') + ' excludes only itself. The reviewed Git commit anchors its identity.</p></section>',
              '<section class="block"><h2>Scope limits</h2><ul>']
    parts += ['<li>' + escape(x) + '</li>' for x in c['limits'] + s.get('limits', [])]
    parts += ['</ul></section><footer>Static evidence publication; status does not refresh from any host.</footer></main></html>']
    (ROOT / 'index.html').write_text('\n'.join(parts) + '\n')

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []
    def handle_starttag(self, tag, attrs):
        self.targets.extend(v for k, v in attrs if k in ('href', 'src'))

def verify(source_copies=False):
    rows = read(MANIFEST)['files']
    paths = {r['path'] for r in rows}
    actual = {f.relative_to(ROOT).as_posix() for f in ROOT.rglob('*') if f.is_file()}
    if len(paths) != len(rows) or actual != paths | {MANIFEST}:
        raise ValueError('Closed file inventory mismatch')
    for row in rows:
        relative = Path(row['path']); path = ROOT / relative
        if relative.is_absolute() or '..' in relative.parts or path.is_symlink() or ROOT not in path.resolve().parents or pin(path) != row:
            raise ValueError('Changed or unsafe file: ' + row['path'])
    copies = read('provenance.json')['copied_files']
    for row in copies:
        current = pin(ROOT / row['path'])
        if any(current[k] != row[k] for k in ('bytes', 'sha256')):
            raise ValueError('Copy differs: ' + row['path'])
        if source_copies:
            data = Path(row['source_path']).read_bytes()
            if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
                raise ValueError('Original differs: ' + row['source_path'])
    for path in ROOT.rglob('*.json'):
        json.loads(path.read_bytes())
    for path in ROOT.rglob('*.py'):
        ast.parse(path.read_bytes(), filename=str(path))
    parser = Links(); parser.feed((ROOT / 'index.html').read_text())
    for value in parser.targets:
        if '://' not in value and not (ROOT / value.split('#')[0]).is_file():
            raise ValueError('Broken link: ' + value)
    print(json.dumps({'status': 'verified_publication_bytes_and_links', 'inventory_files': len(rows),
                      'copied_files': len(copies), 'source_copies_rechecked': source_copies,
                      'campaign_controls_executed': False}, indent=2))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('refresh', 'verify'))
    parser.add_argument('--source-copies', action='store_true')
    args = parser.parse_args()
    if args.action == 'refresh':
        render()
        save(MANIFEST, {'schema': 'orbit-poc-campaign09-publication-inventory-v1',
                        'files': [pin(f) for f in sorted(ROOT.rglob('*')) if f.is_file() and f.name != MANIFEST]})
    verify(args.source_copies)

if __name__ == '__main__':
    main()
