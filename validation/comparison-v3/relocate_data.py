"""Reissue native input manifests from byte-identical offline public caches.

Copy the original bundle cache including .source.json sidecars to --cache, and
copy shared cache/gnss and cache/slr products with .source.json sidecars.
Legacy prepared estimation/gnss and evaluation/*.np2 files can instead seed the
shared cache when copied with their sidecars to --prepared/<date>/. Re-extraction creates all
spacecraft estimation/reference files in their separate directories. Existing
acquisition records are validated and preserved; only generated manifests receive
new absolute runtime paths. No network access or reference-content inspection.
"""
from pathlib import Path
import argparse
from orbit_poc.comparison.data import DEVELOPMENT_DATES,prepare_flight_day,write_json,reuse_auxiliary_manifest

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache',type=Path,required=True)
    p.add_argument('--prepared',type=Path,required=True)
    p.add_argument('--auxiliary',type=Path)
    args=p.parse_args();results=[]
    if args.auxiliary:
        for name in ('auxiliary_manifest.json','flight_auxiliary_manifest.json'):
            reuse_auxiliary_manifest(args.auxiliary,name,relocate=True)
    for date in DEVELOPMENT_DATES:
        result=prepare_flight_day(date,args.cache,args.prepared/date,download=False)
        results.append({'date':date,'status':result['status'],'screening':result['screening']['status'],
                        'sources':[{'url':x['url'],'sha256':x['sha256'],'bytes':x['bytes']} for x in result['sources']]})
    write_json(args.prepared/'relocation_manifest.json',{'offline':True,'source_bytes_changed':False,
        'reference_contents_inspected':False,'fixed_dates_replaced':False,'dates':results})
    print('Prepared',len(results),'fixed dates from verified offline inputs')
if __name__=='__main__':main()
