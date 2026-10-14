#!/usr/bin/env python3
"""Keep integer-second offsets separate from large MJD configuration doubles."""
from pathlib import Path
import argparse

def apply(source):
    path=Path(source)/'source/classes/timeSeries/timeSeriesUniformSampling.h'
    text=path.read_text()
    if 'offsetSeconds' in text:return
    before='    if(isCreateSchema(config)) return;'
    after='''    Double offsetSeconds;
    readConfig(config,"offsetSeconds",offsetSeconds,Config::DEFAULT,"0","exact seconds added to both endpoints; avoids large-MJD rounding");
    if(isCreateSchema(config)) return;
    timeStart += seconds2time(offsetSeconds);
    timeEnd += seconds2time(offsetSeconds);'''
    if text.count(before)!=1:raise ValueError('Pinned uniform sampling anchor changed')
    path.write_text(text.replace(before,after,1))
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source',type=Path);apply(parser.parse_args().source)
