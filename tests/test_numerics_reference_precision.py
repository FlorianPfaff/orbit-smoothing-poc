"""Compiled reference evaluation versus an independent 90-digit Decimal oracle.

These tests isolate arithmetic at fixed fitted elements. Native warm/cold
trajectory closure and objective gates remain necessary; these tests do not
certify them or change their tolerances.
"""
from decimal import Decimal as D, localcontext
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / 'groops/extension'
PI = D('3.141592653589793238462643383279502884197169399375105820974944592307816406286208998628034825342117')
CASES = [
    (398600441800000., 6878137., .0012, -.0005, .02, .5, .17),
    (398600441800000., 12000000., .4, .2, -.2, .4, 2.7),
    (398600441800000., 26560000., .02, -.01, .3, -.2, 4.3),
    (398600441800000., 42164000., .0001, -.0002, .01, -.03, 6.1),
]
TIMES = (-3600., 0., 5., 300., 3600., 43200., 86400.)

# The baseline is the pinned Equinoctial::orbit arithmetic, including its
# double a^3, narrowed eccentric longitude, double trig and double basis.
PROBE = r'''
#include <iomanip>
#include <iostream>
#include "preciseEquinoctialReference.h"
int main(int argc,char **argv) {
  std::cout<<std::setprecision(36);
  if(argc>1 && std::string(argv[1])=="force") {
    double gm,referenceGM;std::array<double,3> position,high,low,noncentral;
    while(std::cin>>gm>>referenceGM) {
      for(auto &x:position)std::cin>>x;
      for(auto &x:high)std::cin>>x;
      for(auto &x:low)std::cin>>x;
      for(auto &x:noncentral)std::cin>>x;
      OrbitPoc::SyntheticForceParts parts;parts.centralGM=gm;
      OrbitPoc::ForceTriple reference;
      for(unsigned i=0;i<3;i++) {parts.noncentral[i]=noncentral[i];reference[i]=static_cast<long double>(high[i])+low[i];}
      const auto force=OrbitPoc::preciseSyntheticReferenceResidual(parts,position,reference,referenceGM);
      for(auto x:force)std::cout<<x<<' ';
      std::cout<<'\n';
    }
    return 0;
  }
  if(argc>1) {
    double high,approximate;long double low,integral;
    while(std::cin>>high>>low>>approximate>>integral)
      std::cout<<OrbitPoc::preciseReferenceMeanResidual(high,low,approximate,integral)<<'\n';
    return 0;
  }
  double GM,a,h,k,p,q,l0,elapsed;
  while(std::cin>>GM>>a>>h>>k>>p>>q>>l0>>elapsed) {
    try {
      auto precise=OrbitPoc::preciseEquinoctialReference({GM,a,h,k,p,q,l0},elapsed);
      const long double n=std::sqrt(static_cast<long double>(GM)/std::pow(a,3));
      const long double pi=3.14159265358979323846264338328L;
      long double lambda=std::fmod(static_cast<long double>(l0)+n*elapsed,2*pi);
      if(lambda<0)lambda+=2*pi;
      long double fl=lambda,old;unsigned iterations=0;
      do {old=fl;fl-=(fl-k*std::sin(fl)+h*std::cos(fl)-lambda)/(1-k*std::cos(fl)-h*std::sin(fl));}
      while(std::fabs(fl-old)>1e-18L && iterations++<100);
      const double F=fl,b=1/(1+std::sqrt(1-h*h-k*k)),r=a*(1-h*std::sin(F)-k*std::cos(F));
      const double X=a*((1-h*h*b)*std::cos(F)+h*k*b*std::sin(F)-k);
      const double Y=a*((1-k*k*b)*std::sin(F)+h*k*b*std::cos(F)-h);
      const double XD=std::sqrt(GM*a)/r*(h*k*b*std::cos(F)-(1-h*h*b)*std::sin(F));
      const double YD=std::sqrt(GM*a)/r*(-h*k*b*std::sin(F)+(1-k*k*b)*std::cos(F));
      const double alpha=1/(1+p*p+q*q);
      const std::array<double,3> f={alpha*(1-p*p+q*q),alpha*2*p*q,-alpha*2*p};
      const std::array<double,3> g={alpha*2*p*q,alpha*(1+p*p-q*q),alpha*2*q};
      for(auto x:precise.position)std::cout<<x<<' ';
      for(auto x:precise.velocity)std::cout<<x<<' ';
      for(unsigned i=0;i<3;i++)std::cout<<X*f[i]+Y*g[i]<<' ';
      for(unsigned i=0;i<3;i++)std::cout<<XD*f[i]+YD*g[i]<<' ';
      std::cout<<'\n';
    } catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 2;}
  }
}
'''


@pytest.fixture(scope='module')
def reference_probe(tmp_path_factory):
    compiler = shutil.which('c++')
    if compiler is None:
        pytest.skip('C++ compiler required for native reference arithmetic')
    directory = tmp_path_factory.mktemp('reference-precision')
    source = directory / 'probe.cpp'
    source.write_text(PROBE)
    executable = directory / 'probe'
    subprocess.run([compiler, '-std=c++17', '-O2', '-fno-fast-math', '-ffp-contract=off',
                    '-I', str(EXT), str(source), '-o', str(executable)], check=True, capture_output=True, text=True)

    def evaluate(rows, residual=False, success=True, force=False):
        payload = ''.join(' '.join(format(x, '.17g') for x in row) + '\n' for row in rows)
        result = subprocess.run([str(executable)] + (['force'] if force else ['residual'] if residual else []),
                                input=payload, capture_output=True, text=True, timeout=10)
        if not success:
            assert result.returncode == 2
            return result.stderr
        assert result.returncode == 0, result.stderr
        return [[D(x) for x in line.split()] for line in result.stdout.splitlines()]
    return evaluate


def sincos(x):
    """Independent convergent series, with no binary floating-point trig."""
    x = (x + PI) % (2*PI) - PI
    sine, cosine, st, ct = x, D(1), x, D(1)
    for index in range(1, 200):
        st *= -x*x/D((2*index)*(2*index+1))
        ct *= -x*x/D((2*index-1)*(2*index))
        old = sine, cosine
        sine += st
        cosine += ct
        if (sine, cosine) == old:
            return sine, cosine
    raise AssertionError('Decimal trigonometric series failed')


def oracle(row):
    with localcontext() as context:
        context.prec = 90
        GM, a, h, k, p, q, l0, elapsed = map(D.from_float, row)
        n = (GM/(a*a*a)).sqrt()
        lam = (l0+n*elapsed) % (2*PI)
        F = lam
        for _ in range(100):
            s, c = sincos(F)
            correction = (F-k*s+h*c-lam)/(1-k*c-h*s)
            F -= correction
            if abs(correction) < D('1e-85'):
                break
        else:
            raise AssertionError('Decimal longitude failed')
        s, c = sincos(F)
        beta = 1/(1+(1-h*h-k*k).sqrt())
        radius = a*(1-h*s-k*c)
        X = a*((1-h*h*beta)*c+h*k*beta*s-k)
        Y = a*((1-k*k*beta)*s+h*k*beta*c-h)
        XD = (GM*a).sqrt()/radius*(h*k*beta*c-(1-h*h*beta)*s)
        YD = (GM*a).sqrt()/radius*(-h*k*beta*s+(1-k*k*beta)*c)
        alpha = 1/(1+p*p+q*q)
        f = [alpha*(1-p*p+q*q), alpha*2*p*q, -alpha*2*p]
        g = [alpha*2*p*q, alpha*(1+p*p-q*q), alpha*2*q]
        return [X*u+Y*v for u,v in zip(f,g)]+[XD*u+YD*v for u,v in zip(f,g)]


@pytest.mark.parametrize('case', CASES)
def test_reference_matches_independent_high_precision_oracle(reference_probe, case):
    rows = [(*case, time) for time in TIMES]
    values = reference_probe(rows)
    for row, actual in zip(rows, values):
        expected = oracle(row)
        assert max(abs(x-y) for x,y in zip(actual[:3], expected[:3])) < D('2e-10')
        assert max(abs(x-y) for x,y in zip(actual[3:6], expected[3:])) < D('2e-13')


def test_legacy_rounding_error_is_measured_at_identical_elements(reference_probe):
    rows = [(*case, time) for case in CASES for time in TIMES]
    values = reference_probe(rows)
    new_error = max(abs(x-y) for row,actual in zip(rows, values)
                    for x,y in zip(actual[:3], oracle(row)[:3]))
    old_error = max(abs(x-y) for row,actual in zip(rows, values)
                    for x,y in zip(actual[6:9], oracle(row)[:3]))
    assert old_error > D('1e-9')
    assert new_error < old_error/D(20)


def test_reference_low_parts_survive_mean_residual(reference_probe):
    rows = [(6878137., 2.**-40, 6878137., -2.**-42),
            (-6878137., -2.**-40, -6878137., 2.**-42)]
    actual = reference_probe(rows, residual=True)
    for row, value in zip(rows, actual):
        with localcontext() as context:
            context.prec = 90
            expected = D.from_float(row[0])-D.from_float(row[2])+D.from_float(row[1])+D.from_float(row[3])
            assert value[0] == expected
        assert float(row[0]+row[1])-row[2] == 0


@pytest.mark.parametrize('gm_difference', [0., 5e8])
def test_precise_reference_force_difference_matches_decimal(reference_probe, gm_difference):
    reference_gm = 398600441800000.
    high = [6878137., 1200000., -2300000.]
    low = [2.**-35, -2.**-36, 2.**-37]
    position = [high[0]+2.**-25, high[1]-2.**-26, high[2]+2.**-27]
    noncentral = [.001, -.0002, .0003]
    row = [reference_gm+gm_difference, reference_gm, *position, *high, *low, *noncentral]
    actual = reference_probe([row], force=True)[0]
    with localcontext() as context:
        context.prec = 90
        p = list(map(D.from_float, position))
        r = [D.from_float(a)+D.from_float(b) for a,b in zip(high, low)]
        p3 = sum(x*x for x in p)**D('1.5')
        r3 = sum(x*x for x in r)**D('1.5')
        expected = [-D.from_float(row[0])*a/p3+D.from_float(reference_gm)*b/r3+D.from_float(c)
                    for a,b,c in zip(p,r,noncentral)]
        assert max(abs(a-b) for a,b in zip(actual,expected)) < D('2e-20')


@pytest.mark.parametrize('index,value', [(0, -1.), (1, 0.), (2, 1.1)])
def test_reference_rejects_nonelliptic_or_invalid_inputs(reference_probe, index, value):
    row = list((*CASES[0], 0.))
    row[index] = value
    reference_probe([row], success=False)


def test_precision_installer_is_separate_idempotent_and_preserves_fit(tmp_path):
    spec = importlib.util.spec_from_file_location('reference_installer', EXT/'native_synthetic_force.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    file = tmp_path/'source/programs/preprocessing/preprocessingVariationalEquation.cpp'
    file.parent.mkdir(parents=True)
    (tmp_path/'source/misc/orbitPoc').mkdir(parents=True)
    file.write_text('''#include "base/equinoctial.h"
    Vector velRef(3*epochCount);
    // unchanged fitted elements: referenceOrbit.a += dx(0);
        referenceOrbit.orbit(times.at(i), epoch.position, epoch.velocity, epoch.acceleration);
          const auto reduced=OrbitPoc::syntheticReferenceResidual(parts,
              {orbit.at(i).position.x(),orbit.at(i).position.y(),orbit.at(i).position.z()},
              {epoch.position.x(),epoch.position.y(),epoch.position.z()},GM);
''')
    module.apply_reference_precision(tmp_path)
    first = file.read_bytes()
    module.apply_reference_precision(tmp_path)
    assert file.read_bytes() == first
    text = first.decode()
    assert text.count('if(orbitPocDerivativeProfile=="synthetic_complete_v1")') == 1
    assert text.count('referenceOrbit.orbit(times.at(i), epoch.position, epoch.velocity, epoch.acceleration);') == 1
    assert 'referenceOrbit.a += dx(0)' in text
    assert 'static_cast<long double>(times.at(i).mjdMod())-referenceOrbit.tau.mjdMod()' in text
    assert 'orbitPocReferencePositionLow[3*i+axis]' in text
    assert 'orbitPocPreciseReference.position,GM)' in text
