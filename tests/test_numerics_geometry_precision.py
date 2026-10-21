"""Versioned high/low geometry: installer and independent arithmetic checks.

Patcher tests are lightweight. The standalone native arithmetic test compiles
only the actual expansion helper, not GROOPS. Neither certifies a native fit.
"""
from decimal import Decimal as D, localcontext
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
EXT=ROOT/'groops/extension'


def module(name,monkeypatch):
    monkeypatch.syspath_prepend(str(EXT))
    spec=importlib.util.spec_from_file_location('geometry_test_'+name,EXT/(name+'.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def prestage(root):
    files={
        'base/polynomial.h':'UInt derivative=0, Bool adjoint=FALSE) const;\n',
        'base/polynomial.cpp':'''const std::vector<long double> &offsetSeconds, UInt rowsPerEpoch, UInt derivative, Bool adjoint) const
    if(!shifted && !derivative && !isLeastSquares && sameTimes) // exact grid identity remains exact
      return A;
          copy(A.row(rowsPerEpoch*idxFirstRight, rowsPerEpoch), B.row(rowsPerEpoch*i, rowsPerEpoch));
{long double value=0;for(UInt k=0;k<count;k++)value+=weights[k]*A(rowsPerEpoch*(idx+k)+row,col);B(rowsPerEpoch*i+row,col)=static_cast<Double>(value);}
''',
        'misc/orbitPoc/piecewisePolynomial.h':'''const std::vector<long double> &offsetSeconds, UInt rowsPerEpoch=1, Bool valuesJump=FALSE) const
    if(!prefix||!*prefix)return interpolate(timesNew,A,rowsPerEpoch,valuesJump);
return polynomial.interpolateOffset(timesNew,A,offsetSeconds,rowsPerEpoch);
const Matrix values=polynomial.interpolateOffset(queries,A.row(rowsPerEpoch*part.first,rowsPerEpoch*count),offsets,rowsPerEpoch);
''',
        'gnss/gnssReceiver.h':'''  std::vector<Vector3d>     pos, vel;
  Vector3d position(UInt idEpoch) const {return pos.at(idEpoch) + global2local.at(idEpoch).inverseTransform(offset.at(idEpoch));}
''',
        'gnss/gnssTransmitter.h':'''  Vector3d positionOffset(UInt id,const Time &t,long double remainder) const {return {};}
  Vector3d velocityOffset() const {return {};}
''',
        'gnss/gnssParametrization/gnssParametrizationLeoDynamicOrbits.cpp':'''const Vector pos = para->polynomial.back().interpolateOffset(times, para->pos.back(), queryRemainders, 3);
para->recv->pos.at(idEpoch) = Vector3d(pos.row(3*i, 3));
const Vector pos = para->polynomial.at(arcNo).interpolateOffset(times, para->pos.at(arcNo), queryRemainders, 3);
para->recv->pos.at(idEpoch) = Vector3d(pos.row(3*i, 3));
''',
        'gnss/gnssObservation.cpp':'''Vector3d &k, Vector3d &kRecv, Vector3d &kTrans)
    if(orbitPocQr::enabled())
    {
      auto query=0;
      long double remainder=query(20200e3L/LIGHT_VELOCITY);
    }
    else {}
    Vector3d k, kRecvAnt, kTrans;
                         k, kRecvAnt, kTrans);
transmitter->clockError(idEpoch),transmitter->scaleFactor(idEpoch)) : l(i)-r12;
''',
    }
    for name,text in files.items():
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    return files


def snapshot(root):
    return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_installer_is_idempotent_and_preserves_compatibility_output(tmp_path,monkeypatch):
    installer=module('positionRemainder',monkeypatch);prestage(tmp_path)
    installer.apply(tmp_path);first=snapshot(tmp_path);installer.apply(tmp_path)
    assert snapshot(tmp_path)==first
    header=(tmp_path/'base/polynomial.h').read_text()
    assert '*preciseValues=nullptr, std::vector<long double> *coordinateRemainders=nullptr' in header
    body=(tmp_path/'base/polynomial.cpp').read_text()
    assert 'ORBIT_POC_PRECISE_POSITION_REMAINDER_V31_PAIR2' in body
    assert 'preciseValues->at(row*A.columns()+col)=A(row,col)' in body
    assert 'coordinateRemainders->assign(rowsPerEpoch*timesNew.size()*A.columns(),0.L)' in body
    assert 'const long double center=derivative?0.L:reference' in body
    assert '(center-static_cast<long double>(B(rowsPerEpoch*i+row,col)))+localOffset' in body
    assert 'auditMode' in body


def test_piecewise_exact_legacy_batch_and_both_receiver_caches(tmp_path,monkeypatch):
    installer=module('positionRemainder',monkeypatch);prestage(tmp_path);installer.apply(tmp_path)
    piecewise=(tmp_path/'misc/orbitPoc/piecewisePolynomial.h').read_text()
    assert 'coordinateRemainders->assign(values.rows()*values.columns(),0.L)' in piecewise
    assert 'preciseValues?&exact:nullptr,coordinateRemainders?&low:nullptr' in piecewise
    assert 'low.at((rowsPerEpoch*i+row)*A.columns()+col)' in piecewise
    receiver=(tmp_path/'gnss/gnssParametrization/gnssParametrizationLeoDynamicOrbits.cpp').read_text()
    assert receiver.count('queryRemainders, 3, FALSE, nullptr, &coordinateLow)')==2
    assert 'coordinateLow.at(3*i)-pos(3*i)' not in receiver
    transmitter=(tmp_path/'gnss/gnssTransmitter.h').read_text()
    assert 'FALSE,nullptr,coordinateRemainder?&low:nullptr' in transmitter
    assert '(static_cast<long double>(base.x())-rounded.x())+antenna.x()' in transmitter


@pytest.mark.parametrize('relative',['base/polynomial.h','base/polynomial.cpp','gnss/gnssObservation.cpp'])
def test_old_marker_refused_before_any_installation_write(tmp_path,monkeypatch,relative):
    installer=module('positionRemainder',monkeypatch);prestage(tmp_path)
    (tmp_path/relative).write_text('// ORBIT_POC_PRECISE_POSITION_REMAINDER_V31\n'+(tmp_path/relative).read_text())
    before=snapshot(tmp_path)
    with pytest.raises(ValueError,match='fresh pinned upstream'):installer.apply(tmp_path)
    assert snapshot(tmp_path)==before


def test_qr_stage_installer_preflights_before_copy_or_patch(tmp_path,monkeypatch):
    root=tmp_path/'disposable';source=root/'source';prestage(source)
    path=source/'base/polynomial.h';path.write_text('// ORBIT_POC_PRECISE_POSITION_REMAINDER_V31\n'+path.read_text())
    before=snapshot(root)
    with pytest.raises(ValueError,match='fresh pinned upstream'):module('native_row_qr',monkeypatch).apply(root)
    assert snapshot(root)==before


def test_full_extension_entry_refuses_old_tree_before_any_write(tmp_path,monkeypatch):
    root=tmp_path/'disposable';source=root/'source';prestage(source)
    path=source/'base/polynomial.h'
    path.write_text('// ORBIT_POC_PRECISE_POSITION_REMAINDER_V31\n'+path.read_text())
    installer=module('apply_extension',monkeypatch)
    before=snapshot(root)
    def check_commit(argv,**kwargs):
        assert argv==['git','-C',str(root.resolve()),'rev-parse','HEAD']
        return installer.COMMIT+'\n'
    def write_forbidden(*args,**kwargs):
        raise AssertionError('Full installer attempted a write/patch before rejecting the old tree')
    monkeypatch.setattr(installer.subprocess,'check_output',check_commit)
    monkeypatch.setattr(installer.subprocess,'run',write_forbidden)
    monkeypatch.setattr(installer,'copy_changed',write_forbidden)
    monkeypatch.setattr(Path,'mkdir',write_forbidden)
    with pytest.raises(ValueError,match='fresh pinned upstream'):
        installer.apply(root,numerics=True)
    assert snapshot(root)==before


def test_full_extension_legacy_entry_does_not_apply_numerics_guard(tmp_path,monkeypatch):
    root=tmp_path/'disposable';source=root/'source';prestage(source)
    path=source/'base/polynomial.h'
    path.write_text('// ORBIT_POC_PRECISE_POSITION_REMAINDER_V31\n'+path.read_text())
    installer=module('apply_extension',monkeypatch)
    monkeypatch.setattr(installer.subprocess,'check_output',lambda *args,**kwargs:installer.COMMIT+'\n')
    class LegacyEntryReached(Exception):pass
    def mkdir_sentinel(*args,**kwargs):raise LegacyEntryReached
    monkeypatch.setattr(Path,'mkdir',mkdir_sentinel)
    with pytest.raises(LegacyEntryReached):installer.apply(root,numerics=False)


def test_new_header_copy_and_factor_version_are_explicit(monkeypatch):
    patcher=(EXT/'native_row_qr.py').read_text();factor=(EXT/'scaledRowQr.h').read_text()
    assert 'with_name("twofoldGeometry.h")' in patcher
    assert 'high_low_geometry_v2' in factor
    helper=(EXT/'twofoldGeometry.h').read_text()
    assert 'geometryPrecisionVersion="high_low_geometry_v2"' in helper
    assert 'FE_TONEAREST' in helper and '__FAST_MATH__' in helper
    assert 'std::fma(a.high,b.high,-p)' in helper
    exporter=(EXT/'orbitPocPredictSignals.cpp').read_text()
    assert 'queryRemainders,3,FALSE,nullptr,&coordinateLow' in exporter


def test_native_twofold_helper_against_independent_decimal(tmp_path):
    compiler=shutil.which('c++')
    if compiler is None:pytest.skip('C++ compiler is required for this arithmetic fixture')
    executable=tmp_path/'probe'
    subprocess.run([compiler,'-std=c++17','-O2','-fno-fast-math','-ffp-contract=off','-I',str(EXT),
        str(ROOT/'tests/fixtures/twofold_geometry_probe.cpp'),'-o',str(executable)],check=True,capture_output=True,text=True)
    with localcontext() as context:
        context.prec=100
        f=lambda value:D.from_float(float(value))
        rh=list(map(f,[6871000.125,-1200300.375,2450060.5]));th=list(map(f,[15400000.75,21300000.125,11600000.5]))
        rl=list(map(f,['1.37e-10','-4.2e-11','8.91e-11']));tl=list(map(f,['-3.4e-10','1.21e-10','3.2e-11']))
        velocity=list(map(f,[-1234.5,2781.25,992.125]));c=f(299792458);gm=f(3.986004418e14)
        def prediction(low):
            r=[a+b for a,b in zip(rh,low)];t=[a+b for a,b in zip(th,tl)]
            rho=sum((a-b)**2 for a,b in zip(r,t)).sqrt();r1=sum(a*a for a in t).sqrt();r2=sum(a*a for a in r).sqrt()
            return (rho+2*gm/c**2*((r1+r2+rho)/(r1+r2-rho)).ln()+2*sum(a*b for a,b in zip(t,velocity))/c+c*(f(3.812e-6)-f(4.3e-8)))*f(1.000000000001)
        measured=f(prediction(rl)+50);shifted=list(rl);shifted[0]=f(rl[0]+D('2.025e-14'))
        result=subprocess.run([str(executable),str(measured)],check=True,capture_output=True,text=True,timeout=5)
        rows={line.split()[0]:list(map(D,line.split()[1:])) for line in result.stdout.splitlines()}
        for name,low in [('nominal',rl),('shifted',shifted)]:
            high,low_part,rounded=rows[name];truth=measured-prediction(low)
            assert abs(high+low_part-truth)<D('1e-18')
            assert abs(rounded-truth)<D('4e-15')
