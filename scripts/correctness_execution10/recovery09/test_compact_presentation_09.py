"""Presentation limits do not alter scientific classifications or raw summaries."""
from pathlib import Path
import importlib.util,json,gzip
import pytest
HERE=Path(__file__).parent

def module(name):
    spec=importlib.util.spec_from_file_location(name,HERE/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
r=module('render_correctness_report_09');c=module('collect_correctness_publication_09')

def test_large_repeated_detail_is_linked_without_changing_payload():
    value={'status':'failed','files':{str(i):'a'*64 for i in range(2000)}}
    before=json.dumps(value,sort_keys=True)
    page=r.detail('Exact source evidence',value,'summary.json.gz')
    assert len(page)<1000 and 'summary.json.gz' in page and 'repeated payload only' in page
    assert json.dumps(value,sort_keys=True)==before

def test_small_failure_detail_and_escaping_are_retained():
    page=r.detail('Failure <script>',{'status':'failed','error':'<script>','value':1})
    assert '&lt;script&gt;' in page and 'failed' in page and '&quot;value&quot;: 1' in page


def test_large_report_uses_existing_stored_and_expanded_bounds(tmp_path):
    p=tmp_path/'summary.json';raw=json.dumps({'status':'failed','payload':'x'*(c.MAX_FILE+1)}).encode();p.write_bytes(raw)
    assert len(raw)>c.MAX_FILE and c.read_full_summary(p)==raw
    assert len(gzip.compress(raw,mtime=0))<c.MAX_FILE
    with pytest.raises(ValueError,match='oversized'):c.read(p)


def test_expanded_report_bound_is_not_raised(tmp_path):
    p=tmp_path/'summary.json'
    with p.open('wb') as f:f.truncate(c.MAX_EXPANDED_REPORT+1)
    with pytest.raises(ValueError,match='oversized'):c.read_full_summary(p)


def test_missing_summary_fails_closed(tmp_path):
    with pytest.raises(ValueError,match='Missing'):c.read_full_summary(tmp_path/'absent')


def test_compressed_stored_limit_is_checked(tmp_path,monkeypatch):
    p=tmp_path/'summary.json';p.write_text('{}')
    monkeypatch.setattr(c.gzip,'compress',lambda *a,**k:b'x'*(c.MAX_FILE+1))
    with pytest.raises(ValueError,match='Compressed report'):c.read_full_summary(p)
