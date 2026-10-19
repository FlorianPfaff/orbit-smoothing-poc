from pathlib import Path
import sys,hashlib
p=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-07/run/preparation/prefixes/129f82a9d3590663cf57650eb1a2341bd247332e00b2ce087cb83470186ec68c/native_preparation.json')
b=p.read_bytes()
assert len(b)<2000000 and hashlib.sha256(b).hexdigest()=='d1c29a3c7019dfd3cb477f1ed3cc09181a77280d504726e90e8137a55b6180a3'
sys.stdout.buffer.write(b)
