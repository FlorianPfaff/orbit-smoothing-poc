from pathlib import Path
import subprocess,json,hashlib,shlex
r=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/engineering-02');b=r/'build'
commands=subprocess.check_output(['/usr/bin/ninja','-C',str(b),'-t','commands','groops'],text=True).splitlines()
selected=[x for x in commands if 'preprocessingVariationalEquation.cpp.o' in x]
deps=subprocess.check_output(['/usr/bin/ninja','-C',str(b),'-t','deps'],text=True)
matched=[block for block in deps.split('\n\n') if 'stagedVariationalBody.h' in block]
print(json.dumps({'selected_commands':selected,'commands_count':len(commands),'header_dependency_blocks':matched,'build_manifest':{'path':str(b/'build-manifest.json'),'sha256':hashlib.sha256((b/'build-manifest.json').read_bytes()).hexdigest()},'ninja':{'path':'/usr/bin/ninja','sha256':hashlib.sha256(Path('/usr/bin/ninja').read_bytes()).hexdigest()}}))
