"""Render one explicitly late-iteration diagnostic with existing Matplotlib; no fit/gate work."""
import argparse,base64,csv,hashlib,io,json,math,subprocess
from pathlib import Path

def digest(raw):return hashlib.sha256(raw).hexdigest()
def encode(value):return (json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
def require(v,m):
 if not v:raise ValueError(m)

PLOT=r'''
import base64,hashlib,io,json,os,tempfile
from pathlib import Path
cfg=json.loads(base64.b64decode(CONFIG_BASE64))
with tempfile.TemporaryDirectory(prefix='orbit08-publication-mpl-') as cache:
 os.environ['MPLCONFIGDIR']=cache
 import matplotlib
 matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 import numpy as np
 import sys
 actual_python=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
 assert actual_python=='6759dcc6aa5a3fe3377349092f92f6700f1f79017294c1d0085009eb8802cb1e'
 plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'svg.hashsalt':cfg['inputs_sha256']})
 rows=cfg['rows'];x=[r['generation'] for r in rows];updates=[r['undamped_maximum_update_m']*1e9 for r in rows];alpha=[r['accepted_alpha'] for r in rows]
 fig,axes=plt.subplots(2,1,figsize=(10.5,6.3),sharex=True,gridspec_kw={'height_ratios':[1.2,1]})
 ax=axes[0];ax.plot(x,updates,color='#245786',marker='o',markersize=3,linewidth=1.35,label='Recorded undamped correction')
 ax.axhline(10,color='#ad3a37',linestyle='--',linewidth=1.3,label='Unchanged strict threshold: 10 nm')
 ax.set_yscale('log');ax.set_ylabel('Maximum nuisance correction (nm)');ax.grid(alpha=.22,which='both');ax.legend(loc='best',frameon=False)
 ax.annotate(f'Generation 52: {updates[-1]:.3f} nm',xy=(x[-1],updates[-1]),xytext=(-160,22),textcoords='offset points',arrowprops={'arrowstyle':'-','color':'#555'},fontsize=9)
 ax=axes[1];ax.plot(x,alpha,color='#266b57',marker='o',markersize=3,linewidth=1.2)
 ax.scatter([r['generation'] for r in rows if not r['accepted']],[r['accepted_alpha'] for r in rows if not r['accepted']],color='#ad3a37',marker='x',s=42,zorder=4,label='No trial accepted')
 ax.set_yscale('symlog',linthresh=1e-6);ax.set_ylabel('Accepted line-search alpha');ax.set_xlabel('Nuisance generation (late view: 4–52)');ax.grid(alpha=.22,which='both');ax.set_xlim(3.5,52.5);ax.legend(loc='best',frameon=False)
 fig.suptitle('Execution 08 · failed density point006 · late-iteration diagnostics',fontsize=14,x=.07,ha='left')
 fig.text(.07,.018,'One failed nuisance profile. Generations 1–3 are outside this view; the complete 1–52 history is preserved.\nNative recorded values only; no new convergence, covariance, trajectory-accuracy or release claim.',fontsize=9,color='#454545')
 fig.subplots_adjust(top=.88,bottom=.16,left=.12,right=.97,hspace=.25)
 outputs={}
 for ext in ('svg','png'):
  stream=io.BytesIO();meta={'Date':None,'Title':'Execution08 failed density point006, late generations4–52'} if ext=='svg' else {'Software':'Matplotlib '+matplotlib.__version__}
  fig.savefig(stream,format=ext,dpi=170,metadata=meta);value=stream.getvalue();outputs[ext]={'bytes':len(value),'sha256':hashlib.sha256(value).hexdigest(),'base64':base64.b64encode(value).decode()}
 plt.close(fig)
 print(json.dumps({'outputs':outputs,'versions':{'python':sys.version,'python_sha256':actual_python,'matplotlib':matplotlib.__version__,'numpy':np.__version__},'inputs_sha256':cfg['inputs_sha256']}))
'''

def render(transfer_path,transfer_sha256,output):
 raw=transfer_path.read_bytes();require(digest(raw)==transfer_sha256,'Transfer manifest changed');transfer=json.loads(raw)
 require(transfer['execution_attempt']=='08' and transfer['validation_status']=='failed' and transfer['local_match_verified'] is True,'Closed failed execution08 required')
 require(not output.exists() and output.is_absolute(),'New absolute plot output required')
 root=Path(transfer['local_root']);point='validation-07/objective-log_drag_ou/point-006-direction-1.0-1-repeat';records={r['relative']:r for r in transfer['files']};rows=[];inputs=[]
 for n in range(4,53):
  name=point+'/qr.'+str(n)+'.nuisance_line_search.json';r=records[name];value=(root/name).read_bytes()
  require(r['encoding']=='identity' and len(value)==r['bytes'] and digest(value)==r['sha256']==r['original_sha256'],'Plot input byte identity changed')
  source=json.loads(value);require(source['schema']=='orbit-poc-native-nuisance-line-search-v1','Unexpected line-search schema')
  update=source['undamped_maximum_update_m'];alpha=source['alpha'];accepted=source['accepted'];prediction=source['full_step_prediction']
  require(all(type(v) in (int,float) and math.isfinite(v) for v in (update,alpha,prediction)) and update>0 and 0<=alpha<=1 and type(accepted) is bool,'Invalid recorded plot values')
  rows.append({'generation':n,'undamped_maximum_update_m':update,'accepted_alpha':alpha,'accepted':accepted,'full_step_prediction':prediction,'trial_count':len(source['trials'])})
  inputs.append({'relative':name,'sha256':digest(value),'bytes':len(value)})
 cfg={'rows':rows,'inputs':inputs,'inputs_sha256':digest(encode(inputs)),'transfer_manifest_sha256':transfer_sha256,'late_iteration_view':[4,52],'strict_threshold_m':1e-8,'threshold_changed':False}
 payload=base64.b64encode(encode(cfg)).decode();script='CONFIG_BASE64='+repr(payload)+'\n'+PLOT
 result=subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','ConnectTimeout=10','gpuserver4090','/home/florianpfaff/codex-runs/orbit-poc-20261013/env/bin/python','-'],input=script.encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
 require(result.returncode==0,'Read-only Matplotlib rendering failed: '+result.stderr.decode()[:2000]);response=json.loads(result.stdout);require(response['inputs_sha256']==cfg['inputs_sha256'],'Rendered input attribution differs')
 files={'inputs.json':encode(cfg)};fieldnames=list(rows[0]);stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=fieldnames);writer.writeheader();writer.writerows(rows);files['late-iterations.csv']=stream.getvalue().encode()
 for ext,record in response['outputs'].items():
  value=base64.b64decode(record['base64'],validate=True);require(len(value)==record['bytes'] and digest(value)==record['sha256'] and len(value)<=16*1024*1024,'Plot output identity/size differs');files['late-iterations.'+ext]=value
 metadata={'schema':'orbit-poc-execution08-late-iteration-plot-v1','scope':'Descriptive plot of one failed objective point; generations4–52 only. Complete1–52 appendix remains primary. No gate changes or acceptance claim.','plot_helper_sha256':digest(Path(__file__).read_bytes()),'render_script_sha256':digest(script.encode()),'versions':response['versions'],'inputs_sha256':cfg['inputs_sha256'],'transfer_manifest_sha256':transfer_sha256,'files':{n:{'sha256':digest(v),'bytes':len(v)} for n,v in files.items()},'scientific_gate_substitution':False}
 output.mkdir(parents=True)
 for name,value in files.items():(output/name).write_bytes(value)
 (output/'manifest.json').write_bytes(encode(metadata));return metadata
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--manifest-sha256',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(render(a.manifest,a.manifest_sha256,a.output),indent=2))
