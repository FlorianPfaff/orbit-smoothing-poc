"""Exact pidfd lifetime for one childless read-only timing observer sidecar."""
from pathlib import Path
import os,signal,subprocess,time,json,stat

def identity(pid):
 fields=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
 return {'pid':pid,'start_ticks':int(fields[19]),'parent':int(fields[1]),'state':fields[0]}

class OwnedObserver:
 def __init__(self,argv,*,cwd,env,log):
  if not hasattr(os,'pidfd_open') or not hasattr(signal,'pidfd_send_signal'):raise RuntimeError('Pinned control Python pidfd APIs required')
  self.child=None;self.fd=None;self.initial=None;self.cleanup_receipt=None
  self.child=subprocess.Popen(argv,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
  try:
   before=identity(self.child.pid);self.fd=os.pidfd_open(self.child.pid);after=identity(self.child.pid)
   if before['start_ticks']!=after['start_ticks']:raise RuntimeError('Observer changed identity while opening pidfd')
   self.initial=after
  except BaseException:
   # Before the child is reaped, this Popen retains ownership of its numericPID.
   # No descendant or process-name signal is authorized by this failure path.
   if self.child.poll() is None:self.child.terminate()
   try:self.child.wait(timeout=5)
   except subprocess.TimeoutExpired:
    self.child.kill();self.child.wait(timeout=5)
   if self.fd is not None:os.close(self.fd);self.fd=None
   raise

 def poll(self):return self.child.poll()
 def stop(self,stop_file,*,grace_seconds=10):
  # As in the pinned workload supervisor, another ordinary interrupt must not
  # interrupt cleanup of the already-owned child. Restore caller handlers.
  previous={number:signal.getsignal(number) for number in (signal.SIGINT,signal.SIGTERM)}
  for number in previous:signal.signal(number,signal.SIG_IGN)
  try:return self._stop(stop_file,grace_seconds=grace_seconds)
  finally:
   for number,handler in previous.items():signal.signal(number,handler)

 def _stop(self,stop_file,*,grace_seconds=10):
  if self.cleanup_receipt is not None:return self.cleanup_receipt
  if self.fd is None:raise RuntimeError('Observer ownership handle missing')
  stop=Path(stop_file);forced=False;signals=[];started=time.monotonic();errors=[]
  try:
   if self.child.poll() is None:
    try:
     try:
      descriptor=os.open(stop,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
     except FileExistsError:
      if not stat.S_ISREG(stop.lstat().st_mode):raise RuntimeError('Existing observer stop path is not a regular file')
     else:
      with os.fdopen(descriptor,'w') as stream:stream.write('Owned controller completed or stopped its benchmark scope.\n');stream.flush();os.fsync(stream.fileno())
    except BaseException as ex:errors.append(repr(ex))
   try:self.child.wait(timeout=0 if errors else grace_seconds)
   except subprocess.TimeoutExpired:
    forced=True
    for number in (signal.SIGTERM,signal.SIGKILL):
     try:signal.pidfd_send_signal(self.fd,number);signals.append(int(number))
     except ProcessLookupError:pass
     try:self.child.wait(timeout=5);break
     except subprocess.TimeoutExpired:continue
    if self.child.poll() is None:raise RuntimeError('Owned observer did not terminate')
  finally:
   if self.child.poll() is not None:os.close(self.fd);self.fd=None
  self.cleanup_receipt={'verified':True,'identity':self.initial,'returncode':self.child.returncode,'forced':forced,'signals':signals,'stop_errors':errors,'elapsed_seconds':time.monotonic()-started,'ownership':'Direct child captured by a held pidfd; only this child is signalled.','scope':'Observer code is separately pinned and creates no children. Workload namespace cleanup has its own independent receipt.'}
  return self.cleanup_receipt
