#!/usr/bin/env python3
"""Render and verify dated status publication only; never execute campaign controls."""
from pathlib import Path
from html import escape
from html.parser import HTMLParser
import argparse,ast,hashlib,json
ROOT=Path(__file__).resolve().parent
def read(name):return json.loads((ROOT/name).read_bytes())
def pin(p):return {'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def save(name,value):(ROOT/name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
def link(path,label):return '<a href="'+escape(path,quote=True)+'">'+escape(label)+'</a>'
def render():
 s=read('summary.json');a=s['first_attempt'];b=s['active_attempt'];n=b['native_process']
 parts=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
 '<title>Segmented v4 · campaign09 status01</title>',
 '<style>*{box-sizing:border-box}body{margin:0;background:#eef2f6;color:#172330;font:16px/1.6 system-ui,sans-serif}main{max-width:1050px;margin:auto;padding:36px 22px 60px}header{background:#142d45;color:#fff;border-radius:12px;padding:28px}h1{font-size:2rem;line-height:1.2}h2{font-size:1.3rem}a{color:#125a87}header a{color:#a9e0ff}.block{background:white;border:1px solid #d5dfe9;border-radius:10px;padding:24px;margin-top:20px}.notice{background:#fff8e9;border-left:5px solid #bf7b24;padding:16px 20px;margin-top:20px}.stamp,footer{font-size:.9rem}table{border-collapse:collapse;width:100%}th,td{vertical-align:top;text-align:left;padding:12px;border-bottom:1px solid #dce4eb}th{background:#eff5f9}code{overflow-wrap:anywhere;font-size:.85rem}pre{white-space:pre-wrap;background:#142d45;color:white;padding:16px;border-radius:6px}.scroll{overflow:auto}footer{margin-top:22px;color:#526779}@media(max-width:650px){main{padding:20px 12px}header,.block{padding:20px}}</style><main>',
 '<header><p>Segmented v4 / campaign09 / status01</p><h1>First timeout reported; second attempt active</h1>',
 '<p>This dated process-status update preserves the original first-native handoff report. It adds no scientific validation of a fit.</p>',
 '<p class="stamp">Evidence cutoff: '+escape(s['cutoff'])+'</p><p>'+link('../campaign09/index.html','Original handoff at 01:41:13 UTC')+' · '+link('summary.json','Exact audited status summary')+'</p></header>',
 '<div class="notice">68 planned · 2 started · 1 terminal (reported timeout) · 1 active · 66 unstarted · 0 reported successful completions. Release ready: false.</div>',
 '<section class="block"><h2>Observed attempt status</h2><div class="scroll"><table><thead><tr><th>Frozen order / attempt</th><th>Observed status</th></tr></thead><tbody>',
 '<tr><td>0<br><code>'+escape(a['attempt_id'])+'</code></td><td>Terminal record present; classification <strong>timeout</strong>. The full result, cleanup and numerical diagnostics were not independently audited in this status review.</td></tr>',
 '<tr><td>1<br><code>'+escape(b['attempt_id'])+'</code></td><td>Supervisor running; no terminal record. One native GROOPS process observed at <code>point-002-repeat/profile.xml</code>.</td></tr></tbody></table></div>',
 '<p>The audit checked all 68 ordered identities against the frozen manifest. Attempts 2–67 remain unstarted in this snapshot.</p></section>',
 '<section class="block"><h2>Second native process and scope</h2><p>PID '+str(n['pid'])+', start ticks '+str(n['start_ticks'])+', is attributed to the owned campaign ancestry and checked private namespace. Its executable path, device/inode/size and expected frozen digest match the previously sealed segmented runtime. CPU affinity is 24, the four numerical thread settings are one, and HOME is private. The driver remains live, the three required locks have owned holders, and the latest captured observer sample is clear.</p>',
 '<p>The native process was in <code>D</code> (uninterruptible sleep) at this one non-atomic observation. That state alone establishes neither a hang nor convergence. No native executable bytes or growing logs were rehashed during fitting.</p>',
 '<p>'+link('evidence/status-independent-review01.json','Independent status audit')+' · '+link('controls/audit_campaign09_status06.py','Exact offline reconstruction source')+'</p></section>',
 '<section class="block"><h2>Earlier report remains frozen</h2><p>The original 370-file, 2,458,296-byte campaign09 report retains its 01:41:13.968477 UTC cutoff and 1-started / 0-terminal status. Its independent publication review is copied here without changing that closed inventory. This later report advances only the observed process and terminal counts.</p><p>'+link('evidence/prior-publication-independent-review01.json','Original publication acceptance receipt')+' · '+link('../campaign09/publication-manifest.json','Original frozen inventory')+'</p></section>',
 '<section class="block"><h2>Evidence and reproduction</h2><ul>']
 for path,label in [('summary.json','Exact compact snapshot projection'),('evidence/status-independent-review01.json','Narrow follow-on acceptance'),('evidence/live06/request.json','Read-only capture request'),('evidence/live06/process.json','Actual capture completion receipt'),('evidence/live06/stderr.log','Exact capture stderr'),('provenance.json','Exact source-copy provenance'),('external-evidence.json','External raw snapshot and result pins'),('publication-manifest.json','Closed publication inventory')]:parts.append('<li>'+link(path,label)+'</li>')
 parts+=['</ul><pre>python3 -B publication.py verify --source-copies</pre><p>This verifies publication bytes, exact source copies, JSON, Python syntax and local links. It runs no campaign control, native workload or remote query. The full snapshot and scientific data remain external; the original offline projection source is retained.</p></section>',
 '<section class="block"><h2>Scope limits</h2><ul>']
 parts+=['<li>'+escape(x)+'</li>' for x in s['limitations']]
 parts+=['<li>Reported terminal classification is not an independently accepted scientific outcome. This update authorizes no covariance, accuracy, speed or release claim; timing remains shared-host timing.</li></ul></section><footer>Static dated evidence; this page does not poll a host or refresh campaign status.</footer></main></html>']
 (ROOT/'index.html').write_text('\n'.join(parts)+'\n')
class Links(HTMLParser):
 def __init__(self):super().__init__();self.paths=[]
 def handle_starttag(self,tag,attrs):self.paths.extend(v for k,v in attrs if k in ('href','src'))
def verify(source_copies):
 rows=read('publication-manifest.json')['files'];actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()};expected={r['path'] for r in rows}
 assert len(rows)==len(expected) and actual==expected|{'publication-manifest.json'},'Inventory is not closed'
 for row in rows:
  p=ROOT/row['path'];assert not p.is_symlink() and ROOT in p.resolve().parents and pin(p)==row,row['path']
 for row in read('provenance.json')['copied_files']:
  actual=pin(ROOT/row['path']);assert all(actual[k]==row[k] for k in ('bytes','sha256')),row['path']
  if source_copies:
   p=Path(row['source_path']);assert p.stat().st_size==row['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==row['sha256'],str(p)
 for p in ROOT.rglob('*.json'):json.loads(p.read_bytes())
 for p in ROOT.rglob('*.py'):ast.parse(p.read_bytes(),filename=str(p))
 links=Links();links.feed((ROOT/'index.html').read_text())
 for target in links.paths:
  if '://' not in target:assert (ROOT/target.split('#')[0]).is_file(),target
 s=read('summary.json');assert (s['started_attempts'],s['terminal_attempts'],s['active_attempts'],s['not_started_attempts'],s['reported_successful_completions'])==(2,1,1,66,0)
 assert s['cutoff']=='2026-10-19T04:37:47.350976+00:00' and not s['release_ready']
 print(json.dumps({'status':'verified_status_publication_bytes_and_links','files_including_manifest':len(rows)+1,'exact_source_copies':len(read('provenance.json')['copied_files']),'source_copies_rechecked':source_copies,'local_links':len(links.paths),'remote_calls':False,'campaign_controls_executed':False},indent=2))
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['refresh','verify']);p.add_argument('--source-copies',action='store_true');a=p.parse_args()
 if a.action=='refresh':
  render();save('publication-manifest.json',{'schema':'orbit-poc-campaign09-status01-publication-inventory-v1','files':[pin(p) for p in sorted(ROOT.rglob('*')) if p.is_file() and p.name!='publication-manifest.json']})
 verify(a.source_copies)
if __name__=='__main__':main()
