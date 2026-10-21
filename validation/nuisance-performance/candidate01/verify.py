#!/usr/bin/env python3
import gzip, hashlib, json
from pathlib import Path
p=Path(__file__).resolve().parent
m=json.loads((p/'manifest.json').read_text())
for e in m['files']:
 b=(p/e['path']).read_bytes()
 assert len(b)==e['bytes'] and hashlib.sha256(b).hexdigest()==e['sha256'],e['path']
 if e.get('encoding')=='gzip':
  raw=gzip.decompress(b)
  assert hashlib.sha256(raw).hexdigest()==e['source_sha256'],e['path']
print(f"Verified {len(m['files'])} published files; no native run performed.")
