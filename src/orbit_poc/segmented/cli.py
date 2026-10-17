"""Independent v4 preparation, bounded execution and inclusive reporting."""
import argparse,json
from pathlib import Path

def register(commands):
    parser=commands.add_parser('segmented',help='Frozen v4 segmented numerical benchmark')
    actions=parser.add_subparsers(dest='segmented_command',required=True)
    for name in ('prepare','validate','run','report'):
        command=actions.add_parser(name);command.add_argument('--config',type=Path,required=True);command.add_argument('--output-dir',type=Path)
        if name=='run':command.add_argument('--max-attempts',type=int)

def dispatch(args):
    from .config import load_config
    config=load_config(args.config)
    if args.segmented_command=='report':
        from .report import create_report
        result=create_report(config,args.output_dir)
    elif args.segmented_command=='validate':
        from .validation import validate
        result=validate(config,args.output_dir)
    else:
        from . import protocol
        options={'max_attempts':args.max_attempts} if args.segmented_command=='run' else {}
        result=getattr(protocol,args.segmented_command)(config,args.output_dir,**options)
    print(json.dumps(result,indent=2,allow_nan=False))
    return 1 if result['status'] in ('blocked','failed') else 0
