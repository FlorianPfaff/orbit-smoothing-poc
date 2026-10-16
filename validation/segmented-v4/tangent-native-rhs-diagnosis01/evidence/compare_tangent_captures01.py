from pathlib import Path
import struct,hashlib,json,math,datetime
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff')
items=[(B/'tangent-telemetry-02/run/replay/captured-system.bin','b1fd97fe4f004a87d459455f0625d609b8d5f9140d63a5dcdb7448e093bc5fd2'),(B/'tangent-telemetry-04/run/replay/captured-system.bin','b1020102aefcae66220d7af34e12d17b47b8992d1d45c092fbe09a66027214f3')]
data=[]
for p,h in items:
 b=p.read_bytes();assert hashlib.sha256(b).hexdigest()==h;assert b[:16]==b'OPCTANGENT001\n\0\0';schema,n,intervals,terms,rhscount=struct.unpack_from('<5Q',b,16);assert schema==1 and intervals==n-1 and rhscount==6*n
 rhsstart=len(b)-8*rhscount;values=struct.unpack_from('<'+str(rhscount)+'d',b,rhsstart);data.append((b,n,rhsstart,values))
a,b=data;assert(a[1],a[2],len(a[0]))==(b[1],b[2],len(b[0]));offset=3*a[1]
def stats(x,y,scale):
 d=[scale*(v-u)for u,v in zip(x,y)];return {'changed_values':sum(u!=v for u,v in zip(x,y)),'maximum_absolute_difference':max(map(abs,d)),'difference_l2':math.sqrt(math.fsum(v*v for v in d)),'old_l2':math.sqrt(math.fsum((scale*v)**2 for v in x)),'new_l2':math.sqrt(math.fsum((scale*v)**2 for v in y))}
out={'schema':'orbit-poc-captured-system-exact-comparison-v1','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'inputs':[{'path':str(p),'sha256':h}for p,h in items],'epochs':a[1],'operator_prefix_bytes':a[2],'operator_prefix_byte_identical':a[0][:a[2]]==b[0][:b[2]],'header_jacobians_quadrature_old_sha256':hashlib.sha256(a[0][:a[2]]).hexdigest(),'header_jacobians_quadrature_new_sha256':hashlib.sha256(b[0][:b[2]]).hexdigest(),'position_rhs':stats(a[3][:offset],b[3][:offset],1.),'scaled_velocity_rhs':stats(a[3][offset:],b[3][offset:],1000.),'scientific_runs':0}
print(json.dumps(out,indent=2))
