"""Exact-zero codec regression, separate from actual fixed-trajectory gates."""
from pathlib import Path
import json
import os
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def fixture(tmp_path_factory):
    output = tmp_path_factory.mktemp('warm-zero')/'fixture'
    subprocess.run(['/usr/bin/g++', '-std=c++17', '-O1', '-I', str(ROOT/'groops/extension'),
                    str(ROOT/'tests/nuisance_warm_zero_fixture.cpp'), '-o', str(output)], check=True)
    return output


def run(fixture, operation, root, category='all', mode='receiver_clock_signal_float_v1', before='8000000000000000', after='0', donor=None):
    root.mkdir()
    command = [str(fixture), operation, str(root), category, mode, before, after]
    if donor is not None:
        command.append(str(donor))
    environment = {k:v for k,v in os.environ.items() if not k.startswith('ORBIT_POC_')}
    subprocess.run(command, check=True, env=environment, capture_output=True, text=True)


def test_codec_zeros_canonical_nonzeros_exact_without_mutation(fixture):
    subprocess.run([str(fixture), 'codec'], check=True)


@pytest.mark.parametrize('category', ['coordinate', 'chart', 'invariant', 'all'])
@pytest.mark.parametrize('mode', ['receiver_clock_signal_float_v1', 'receiver_clock_v1'])
@pytest.mark.parametrize('signs', [('8000000000000000','0'), ('0','8000000000000000')])
def test_zero_export_import_refresh_accepts_both_signs(fixture, tmp_path, category, mode, signs):
    source = tmp_path/'source';target = tmp_path/'target'
    run(fixture, 'export', source, category, mode, *signs)
    run(fixture, 'import', target, category, mode, *reversed(signs), donor=source/'output')
    for root in (source,target):
        receipt = json.loads((root/'output.json').read_text())
        assert receipt['eligibility'] == {'nuisance_converged':True,'nuisance_floor_limited':False,
                                         'fresh_undamped':True,'rank_status':'full'}
        assert receipt['invariants'] == {'target_cold_ionosphere_unchanged':True,
                                        'target_clock_prior_anchors_unchanged':True}
    a=json.loads((source/'output.json').read_text());b=json.loads((target/'output.json').read_text())
    assert a['chart_sha256']==b['chart_sha256']
    assert a['cold_origin_sha256']==b['cold_origin_sha256']
    assert a['imported']['used'] is False and b['imported']['used'] is True


@pytest.mark.parametrize('category', ['coordinate', 'chart', 'invariant'])
@pytest.mark.parametrize('before,after', [('0','1'), ('0','8000000000000001'),
                                         ('1','2'), ('8000000000000001','8000000000000002'),
                                         ('3ff0000000000000','3ff0000000000001'),
                                         ('bff0000000000000','bff0000000000001')])
def test_nonzero_one_ulp_refresh_changes_reject(fixture,tmp_path,category,before,after):
    run(fixture,'reject_refresh',tmp_path/'case',category,before=before,after=after)


@pytest.mark.parametrize('category', ['coordinate', 'chart'])
@pytest.mark.parametrize('value', ['1','8000000000000001'])
def test_nonzero_changed_cold_origin_or_chart_reject_before_import(fixture,tmp_path,category,value):
    source=tmp_path/'source'
    run(fixture,'export',source,category)
    run(fixture,'reject_import',tmp_path/'target',category,before=value,donor=source/'output')


@pytest.mark.parametrize('category', ['coordinate', 'chart', 'invariant'])
@pytest.mark.parametrize('value', ['7ff0000000000000','fff0000000000000','7ff8000000000001'])
def test_nonfinite_still_rejects_without_state_mutation(fixture,tmp_path,category,value):
    run(fixture,'reject_nonfinite',tmp_path/'case',category,before=value)
