"""Exact single NumPy initialization exception; no process launches in this file."""
FORBIDDEN={'subprocess.Popen','os.system','os.fork','os.forkpty','os.posix_spawn','os.exec','os.kill','os.killpg'}
EXPECTED=('lscpu',['lscpu'],None,None)


class StartupProbeGuard:
    def __init__(self,expected_environment,environment,origin,verify_runtime):
        self.expected_environment=dict(expected_environment)
        self.environment=environment
        self.origin=origin
        self.verify_runtime=verify_runtime
        self.active=False
        self.opened=False
        self.allowed=0
        self.events=[]

    def begin(self):
        if self.opened or self.active:raise RuntimeError('Startup probe scope cannot reopen')
        if self.environment()!=self.expected_environment:raise RuntimeError('Startup environment differs')
        self.opened=True
        self.active=True

    def close(self):
        self.active=False

    def audit(self,event,args):
        if event not in FORBIDDEN:return
        record={'event':event,'scope_active':self.active,'permitted':False}
        if event=='subprocess.Popen' and len(args)==4:
            record.update(observed_executable=repr(args[0]),observed_argv=repr(args[1]),observed_cwd=repr(args[2]),
                          explicit_environment_is_none=args[3] is None)
        self.events.append(record)
        if (event!='subprocess.Popen' or not self.active or self.allowed!=0 or args!=EXPECTED
                or self.environment()!=self.expected_environment or self.origin() is not True):
            raise RuntimeError('Child process or signal forbidden: '+event)
        self.verify_runtime()
        self.allowed+=1
        record.update(permitted=True,executable=args[0],argv=list(args[1]),cwd=args[2],explicit_environment=args[3],
                      inherited_environment=dict(self.expected_environment),
                      observation='Python subprocess.Popen audit event before process creation; no PID/exit/output claim')
