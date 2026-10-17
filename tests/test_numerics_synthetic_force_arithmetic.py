"""Actual opt-in force decomposition and independent Decimal residual oracle.

Only standalone arithmetic/force-header compilation and fabricated patcher
fixtures run here. Actual GROOPS closure, derivatives and objective gates remain
required; these tests cannot establish that the physical repeat floor is fixed.
"""
from decimal import Decimal as D, localcontext
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT/'groops/extension'
OLD_FORCE = '''      force.at(k) = rotEarth.at(k).inverseRotate(forces->acceleration(satellite, orbit.at(k).time, orbit.at(k).position, orbit.at(k).velocity,
                                         starCamera.at(k).rotary, rotEarth.at(k), earthRotation, ephemerides));'''
OLD_SUBTRACT = '''        g(3*i+0) -= epoch.acceleration.x();
        g(3*i+1) -= epoch.acceleration.y();
        g(3*i+2) -= epoch.acceleration.z();'''


def patcher():
    spec=importlib.util.spec_from_file_location('force_arithmetic_patcher',EXT/'native_synthetic_force.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def prestage(root):
    files={
        'classes/miscAccelerations/miscAccelerations.h':'''#pragma once
#include "base/import.h"
class MiscAccelerations {public:
  /// Constructor.
};
class MiscAccelerationsBase {public:
virtual ~MiscAccelerationsBase() {}
virtual Vector3d acceleration(SatelliteModelPtr,const Time &,const Vector3d &,const Vector3d &,const Rotary3d &,const Rotary3d &,EphemeridesPtr){return {};}
};
''',
        'classes/miscAccelerations/miscAccelerations.cpp':'// prior derivative dispatch\n',
        'classes/forces/forces.h':'class Forces { public:\n  /// Constructor.\n};\n',
        'classes/forces/forces.cpp':'// prior derivative dispatch\n',
        'programs/preprocessing/preprocessingVariationalEquation.cpp':OLD_FORCE+'\n'+OLD_SUBTRACT+'\n',
    }
    for name in ('miscAccelerationsSyntheticGravity.h','miscAccelerationsSyntheticDrag.h','miscAccelerationsLogDensity.h'):
        files['classes/miscAccelerations/'+name]=(EXT/name).read_text()
    for name,text in files.items():
        path=root/'source'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    (root/'source/misc/orbitPoc').mkdir(parents=True)


def snapshot(root):
    return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_patcher_preserves_other_profiles_and_is_idempotent(tmp_path):
    prestage(tmp_path);patcher().apply(tmp_path);first=snapshot(tmp_path);patcher().apply(tmp_path)
    assert snapshot(tmp_path)==first
    text=(tmp_path/'source/programs/preprocessing/preprocessingVariationalEquation.cpp').read_text()
    assert text.count('if(orbitPocDerivativeProfile=="synthetic_complete_v1")')==2
    assert text.count(OLD_FORCE)==text.count(OLD_SUBTRACT)==1
    assert 'else\n'+OLD_FORCE in text and 'else\n        {\n'+OLD_SUBTRACT in text
    assert 'epoch.position.z()},GM)' in text
    assert text.count('syntheticReferenceResidual(')==1


def test_dispatch_is_actual_configured_components_and_fails_closed(tmp_path):
    prestage(tmp_path);patcher().apply(tmp_path);root=tmp_path/'source'
    base=(root/'classes/miscAccelerations/miscAccelerations.h').read_text()
    assert 'OrbitPoc::SyntheticForceParts &parts) {return FALSE;}' in base
    forces=(root/'classes/forces/forces.cpp').read_text()
    assert 'orbitPocHasGravity || orbitPocHasTides || !miscAccelerations ||' in forces
    assert 'requires explicitly supported synthetic force arithmetic' in forces
    aggregate=(root/'classes/miscAccelerations/miscAccelerations.cpp').read_text()
    assert 'satellite->changeState(time,position,velocity,positionSun,rotSat,rotEarth)' in aggregate
    assert 'value.validate();sum.add(value)' in aggregate
    wrapper=(root/'classes/miscAccelerations/miscAccelerationsLogDensity.h').read_text()
    assert 'nominalDrag->orbitPocSyntheticForceParts(' in wrapper
    assert 'parts.scale(series->multiplier(time));parts.validate();' in wrapper
    gravity=(root/'classes/miscAccelerations/miscAccelerationsSyntheticGravity.h').read_text()
    assert 'parts.centralGM=GM' in gravity and 'orbitPocGravityParts(position,radius,j2)' in gravity
    assert 'rotSat,Rotary3d(),ephemerides)' in gravity
    assert 'configured_crf_parts_stable_reference_v1' in (EXT/'stagedVariationalBody.h').read_text()


@pytest.fixture(scope='module')
def arithmetic(tmp_path_factory):
    compiler=shutil.which('c++')
    if compiler is None:pytest.skip('C++ compiler required for standalone arithmetic')
    directory=tmp_path_factory.mktemp('synthetic-force-arithmetic');exe=directory/'probe'
    subprocess.run([compiler,'-std=c++17','-O2','-fno-fast-math','-ffp-contract=off','-I',str(EXT),
                    str(ROOT/'tests/fixtures/synthetic_force_arithmetic.cpp'),'-o',str(exe)],check=True,capture_output=True,text=True)
    def run(rows,mode='residual',success=True):
        result=subprocess.run([str(exe),mode],input=''.join(' '.join(format(float(x),'.17g') for x in row)+'\n' for row in rows),
                              capture_output=True,text=True,timeout=5)
        if success:
            assert result.returncode==0,result.stderr
            return [[D(x) for x in line.split()] for line in result.stdout.splitlines()]
        assert result.returncode==2
        return result.stderr
    return run


def decimal_residual(row):
    with localcontext() as ctx:
        ctx.prec=100
        vals=[D.from_float(float(x)) for x in row];p,r=vals[:3],vals[3:6];gm,ref=vals[6:8]
        rp=sum(x*x for x in p).sqrt();rr=sum(x*x for x in r).sqrt()
        return [-gm*p[i]/rp**3+ref*r[i]/rr**3+vals[8+i] for i in range(3)]


def test_stable_residual_matches_decimal_for_equal_and_unequal_GM(arithmetic):
    rows=[]
    for radius in ([6878137.,200000.,-400000.],[7500000.,-1200000.,900000.]):
        for delta in (0.,1e-9,1e-6,1.,1000.):
            for gm in (398600441800000.,398600441500000.):
                for ref in (398600441500000.,398600441800000.):
                    for noncentral in ([0.,0.,0.],[.005,-.002,1.25e-6]):
                        p=[radius[0]+delta,radius[1]-.3*delta,radius[2]+.7*delta]
                        rows.append([*p,*radius,gm,ref,*noncentral])
    for row,actual in zip(rows,arithmetic(rows)):
        for observed,expected in zip(actual,decimal_residual(row)):
            assert abs(observed-expected)<=D('3e-18')*max(abs(expected),D('1e-20'))


def test_exact_coincident_equal_GM_and_required_unequal_term(arithmetic):
    p=[6878137.,200000.,-400000.]
    rows=[[*p,*p,398600441800000.,ref,0.,0.,0.] for ref in (398600441800000.,398600441500000.)]
    equal,unequal=arithmetic(rows)
    assert equal==[0,0,0]
    assert max(abs(x) for x in unequal)>D('1e-9')
    for x,y in zip(unequal,decimal_residual(rows[1])):assert abs(x-y)<D('2e-26')


def test_recursive_scaled_component_accumulation(arithmetic):
    rows=[[398600441800000.,weight,outer,.005,-.002,.001,-8.,.1,.3,-2e-7,4e-7,-8e-8]
          for weight in (.75,1.2,2.) for outer in (.9,1.1)]
    with localcontext() as ctx:
        ctx.prec=100
        for row,actual in zip(rows,arithmetic(rows,'composition')):
            gm,w,o,*v=[D.from_float(float(x)) for x in row];nc,full,drag=v[:3],v[3:6],v[6:]
            expected=[gm*o]+[(x+w*d)*o for x,d in zip(full,drag)]+[(x+w*d)*o for x,d in zip(nc,drag)]
            for x,y in zip(actual,expected):assert abs(x-y)<=D('4e-19')*max(abs(y),D('1e-20'))


@pytest.mark.parametrize('reference,gm', [([0.,0.,0.],398600441500000.),([6878137.,0.,0.],0.)])
def test_invalid_reference_is_rejected(arithmetic,reference,gm):
    assert 'invalid synthetic reference' in arithmetic([[6878137.,0.,0.,*reference,398600441800000.,gm,0.,0.,0.]],success=False)


def test_actual_configured_headers_preserve_legacy_force_bits(tmp_path):
    compiler=shutil.which('c++')
    if compiler is None:pytest.skip('C++ compiler required for actual force header fixture')
    prestage(tmp_path);patcher().apply(tmp_path);root=tmp_path/'source';stub=root/'base/import.h';stub.parent.mkdir()
    stub.write_text(r'''#pragma once
#include <cmath>
#include <map>
#include <string>
#include <stdexcept>
using Double=double;using Bool=bool;constexpr bool TRUE=true,FALSE=false;
struct Time{};using SatelliteModelPtr=void*;using EphemeridesPtr=void*;
struct Vector3d{double data[3]{};Vector3d()=default;Vector3d(double x,double y,double z):data{x,y,z}{}
double x()const{return data[0];}double y()const{return data[1];}double z()const{return data[2];}
double operator[](unsigned i)const{return data[i];}double r()const{return std::sqrt(x()*x()+y()*y()+z()*z());}};
inline Vector3d operator*(double s,const Vector3d&p){return {s*p.x(),s*p.y(),s*p.z()};}
inline Vector3d operator+(const Vector3d&a,const Vector3d&b){return {a.x()+b.x(),a.y()+b.y(),a.z()+b.z()};}
inline Vector3d operator-(const Vector3d&a,const Vector3d&b){return {a.x()-b.x(),a.y()-b.y(),a.z()-b.z()};}
struct Rotary3d{double angle=0;Rotary3d()=default;explicit Rotary3d(double a):angle(a){}
Vector3d rotate(const Vector3d&p)const{if(angle==0)return p;return {std::cos(angle)*p.x()-std::sin(angle)*p.y(),std::sin(angle)*p.x()+std::cos(angle)*p.y(),p.z()};}};
struct Config{enum Appearance{DEFAULT,MUSTSET};std::map<std::string,double>values;};
inline void readConfig(Config&c,const std::string&n,double&v,Config::Appearance,const std::string&d,const std::string&){v=c.values.count(n)?c.values[n]:std::stod(d);}
inline bool isCreateSchema(Config&){return false;}
using Exception=std::runtime_error;
''')
    exe=tmp_path/'instances'
    subprocess.run([compiler,'-std=c++17','-O2','-fno-fast-math','-ffp-contract=off','-I',str(root),'-I',str(root/'classes/miscAccelerations'),
                    str(ROOT/'tests/fixtures/synthetic_force_instances.cpp'),'-o',str(exe)],check=True,capture_output=True,text=True)
    rows=[]
    for gm in (398600441800000.,398600441500000.):
        for j2 in (.00108262668,.0009):
            for angle in (0.,.31,2.7):
                rows.append([6878137.,200000.,-400000.,-500.,7300.,1500.,gm,j2,6378111.,angle,.031,7e-13,480000.,53000.,6378123.,7.28e-5])
    result=subprocess.run([str(exe)],input=''.join(' '.join(map(str,row))+'\n' for row in rows),check=True,capture_output=True,text=True,timeout=5)
    assert len(result.stdout.splitlines())==len(rows)
    with localcontext() as context:
        context.prec=100
        for row,line in zip(rows,result.stdout.splitlines()):
            x,y,z,vx,vy,vz,gm,j2,radius,_,ballistic,rho,altitude,height,earth,omega=[D.from_float(float(v)) for v in row]
            r=(x*x+y*y+z*z).sqrt();a=D('1.5')*j2*gm*radius*radius/r**5;z2=z*z/r**2
            j2_force=[a*x*(5*z2-1),a*y*(5*z2-1),a*z*(5*z2-3)]
            u=[vx+omega*y,vy-omega*x,vz];speed=sum(v*v for v in u).sqrt()
            density=rho*(-(r-earth-altitude)/height).exp()
            drag=[-D('.5')*ballistic*density*speed*v for v in u]
            actual=[D(v) for v in line.split()];assert actual[0]==gm
            for observed,expected in zip(actual[1:],j2_force+drag):
                assert abs(observed-expected)<D('3e-14')*abs(expected)+D('1e-22')
