"""Check complete pinned runtime trees in the final namespace before execution."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse,hashlib,json,os,sys,time
parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--receipt',required=True);parser.add_argument('command',nargs=argparse.REMAINDER)
a=parser.parse_args();start=time.monotonic()
def checksum(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as stream:
  for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def verify_reference(reference):
 if not isinstance(reference,dict) or not isinstance(reference.get('path'),str) or not isinstance(reference.get('sha256'),str):raise ValueError('Invalid pinned artifact reference')
 path=Path(reference['path'])
 if checksum(path)!=reference['sha256']:raise ValueError('Pinned artifact changed: '+str(path))
 return path
def read_reference(reference):return json.loads(verify_reference(reference).read_text())
def names(root):
 result=set()
 for parent,dirs,files in os.walk(root,followlinks=False):
  dirs[:]=[name for name in dirs if name!='__pycache__']
  for name in dirs[:]:
   path=Path(parent)/name
   if path.is_symlink():result.add(path.relative_to(root).as_posix());dirs.remove(name)
  for name in files:
   if not name.endswith(('.pyc','.pyo')):result.add((Path(parent)/name).relative_to(root).as_posix())
 return result
def check(item):
 root,row=item;path=root/row['relative_path']
 if 'directory_symlink' in row:
  if not path.is_symlink() or os.readlink(path)!=row['directory_symlink']:raise ValueError('Directory alias differs: '+str(path))
  return
 if bool(path.is_symlink()) != ('symlink' in row):raise ValueError('File alias kind differs: '+str(path))
 if 'symlink' in row and os.readlink(path)!=row['symlink']:raise ValueError('File alias target differs: '+str(path))
 if path.stat().st_size!=row['bytes'] or checksum(path)!=row['sha256']:raise ValueError('Runtime bytes differ: '+str(path))
bytecode=Path(os.environ.get('PYTHONPYCACHEPREFIX',''))
if os.environ.get('PYTHONDONTWRITEBYTECODE')!='1' or not os.environ.get('PYTHONPYCACHEPREFIX') or not bytecode.is_dir() or any(bytecode.iterdir()) or not os.statvfs(bytecode).f_flag & os.ST_RDONLY:
 raise ValueError('Runtime verification requires an empty read-only PYTHONPYCACHEPREFIX and PYTHONDONTWRITEBYTECODE=1')
config=json.loads(Path(a.config).read_text());context=read_reference(config['execution_context']);verified=[]
launch_artifacts={}
for key in ('wrapper','bubblewrap','runtime_startup_verifier','run_to_report_controller','run_to_report_entrypoint'):
 if key not in context:raise ValueError('Missing pinned launch artifact: '+key)
 path=verify_reference(context[key])
 launch_artifacts[key]={'path':str(path.absolute()),'sha256':context[key]['sha256']}
if Path(launch_artifacts['runtime_startup_verifier']['path']).resolve()!=Path(__file__).resolve():raise ValueError('Executing verifier differs from the pinned verifier path')
for key in ('runtime_manifest','new_python_runtime_manifest'):
 manifest=read_reference(context[key])
 for tree in manifest['trees']:
  root=Path(tree['root']);expected={row['relative_path'] for row in tree['files']}
  if len(expected)!=len(tree['files']) or names(root)!=expected:raise ValueError('Runtime tree membership differs: '+str(root))
  if not os.statvfs(root).f_flag & os.ST_RDONLY:raise ValueError('Runtime tree is not mounted read-only: '+str(root))
  with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(check,((root,row) for row in tree['files'])))
  verified.append({'root':str(root),'entries':len(expected),'read_only':True})
  print('Verified runtime tree',root,len(expected),flush=True)
receipt=Path(a.receipt);receipt.parent.mkdir(parents=True,exist_ok=True)
record={'status':'verified','scope':'Pinned launch artifacts plus complete frozen runtime membership, bytes and alias targets checked inside read-only common namespace immediately before execution','configuration':{'path':str(Path(a.config).absolute()),'sha256':checksum(a.config)},'execution_context':config['execution_context'],'trees':verified,'launch_artifacts':launch_artifacts,'bytecode_cache_policy':'Empty read-only prefix; cached bytecode outside the prefix is not loaded and no cache writes occur','bytecode_cache_prefix':str(bytecode),'elapsed_seconds':time.monotonic()-start,'verifier':{'path':str(Path(__file__).absolute()),'sha256':checksum(__file__)}}
receipt.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
command=a.command[1:] if a.command[:1]==['--'] else a.command
if command:os.execvpe(command[0],command,os.environ)
