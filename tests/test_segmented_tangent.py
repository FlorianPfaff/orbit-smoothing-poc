"""The v4 local equalities reproduce both distinct native tangent operators.

These compile the real header and compare with independently assembled dense
integral/variation-of-constants designs. No native orbit fit is launched.
"""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest
from scipy.linalg import solve

ROOT = Path(__file__).resolve().parents[1]

CPP = r'''
#include "segmentedTangent.h"
#include "segmentedNativeExport.h"
#include <iomanip>
#include <iostream>
#include <string>
using namespace OrbitPoc;
using namespace OrbitPoc::SegmentedTangent;
void array(const std::vector<double>&x){std::cout<<'[';for(unsigned i=0;i<x.size();i++){if(i)std::cout<<',';std::cout<<x[i];}std::cout<<']';}
std::vector<double> dense(const std::vector<Row>&rows,unsigned cols,bool parameter=false)
{std::vector<double>a(rows.size()*cols);for(unsigned i=0;i<rows.size();i++)for(auto t:parameter?rows[i].parameter:rows[i].auxiliary)a[i*cols+t.column]+=t.value;return a;}
int main(int argc,char**argv)
{
 std::cout<<std::setprecision(17);std::string mode=argc>1?argv[1]:"operator";
 if(mode=="serialization")
 {
   {OrbitPoc::SegmentedExport::Capture c;OrbitPoc::SegmentedExport::exact(7);
    OrbitPoc::SegmentedExport::twofold(8,std::vector<orbitPocQr::TwofoldGeometry>{{.5L,1e-30L},{-.125L,-1e-31L}});
    std::cout<<"{\"weights\":";OrbitPoc::SegmentedExport::weights(std::cout,c.values);
    std::cout<<",\"escaped\":";OrbitPoc::SegmentedExport::string(std::cout,"a\"b\\c\n");
    struct Epoch{int mjdInt()const{return 60000;}double mjdMod()const{return .25;}};
    std::cout<<",\"query\":";OrbitPoc::SegmentedExport::stateQuery(std::cout,"nominal_observation",2,0,19,33,12,Epoch{},c.values,{{9,1.L,0.L}});
    std::cout<<"}\n";}
   return OrbitPoc::SegmentedExport::capturedStencil?1:0;
 }
 const unsigned n=17,m=6*n;const double dt=10.;
 std::vector<double> extra;Channel main;main.weights=eventQuadrature(n,dt,3,{40,80},{},&extra);
 for(unsigned i=0;i<n;i++)
 {Sample s;for(unsigned j=0;j<3;j++){s.jacobian.position[3*j+j]=-1e-5*(j+1);s.jacobian.velocity[3*j+j]=-1e-3*(j+1);}
 s.jacobian.position[1]=3e-6;s.position={{i,1}};s.velocity={{i,1}};main.samples.push_back(s);}
 std::vector<Channel>channels{main};
 if(mode=="flight")
 {Channel drag;drag.weights=eventQuadrature(n,dt,3,{40,80},{35,125},&extra,2.);drag.samples=main.samples;
 for(auto&s:drag.samples){for(double&x:s.jacobian.position)x*=.02;for(double&x:s.jacobian.velocity)x*=.03;}
 for(double t:extra){unsigned a=std::min(n-2,unsigned(t/dt));double w=t/dt-a;Sample s=drag.samples[a];s.position={{a,1-w},{a+1,w}};s.velocity=s.position;drag.samples.push_back(s);}channels.push_back(drag);}
 if(mode=="invalid")
 {
   unsigned caught=0;auto expect=[&](auto f){try{f();}catch(const std::exception&){caught++;}};
   expect([&]{tangentRows(1,dt,channels,{});});expect([&]{tangentRows(n,0,channels,std::vector<double>(m));});
   auto bad=channels;bad[0].samples[0].position[0].column=n;expect([&]{tangentRows(n,dt,bad,std::vector<double>(m));});
   bad=channels;bad[0].samples[0].jacobian.velocity[0]=NAN;expect([&]{tangentRows(n,dt,bad,std::vector<double>(m));});
   expect([&]{variationRows(n,5,main.weights,{},{});});
   expect([&]{variationRows(n,8,main.weights,{{{6,0,1}}},{});});
   expect([&]{variationRows(n,8,main.weights,{},{{0,0,{}}});});
   expect([&]{observationRow({},{{0,1}},{});});
   std::cout<<"{\"caught\":"<<caught<<"}\n";return caught==8?0:1;
 }
 if(mode=="variation")
 {
   const unsigned p=11;std::vector<std::vector<Forcing>>f(n);
   for(unsigned i=0;i<n;i++)for(unsigned j=0;j<6;j++)for(unsigned col=0;col<2;col++)
     f[i].push_back({j,col,1e-5*(i+1)*(j+1)*(col?-.3:1.)});
   Pulse pulse{8,2,{}};pulse.map[0]=2e-5;pulse.map[9]=pulse.map[13]=pulse.map[17]=1e-6;
   const auto rows=variationRows(n,p,main.weights,f,{pulse});
   std::vector<double>D(m*p),alpha(6*(p-6));
   for(unsigned epoch=0;epoch<n;epoch++)
   {
     if(epoch)for(auto w:main.weights[epoch-1])for(auto term:f[w.index])alpha[(p-6)*term.component+term.parameter]+=w.integral*term.value;
     for(unsigned c=0;c<6;c++)
     {for(unsigned j=0;j<p-6;j++)D[(6*epoch+c)*p+j]=alpha[(p-6)*c+j];D[(6*epoch+c)*p+p-6+c]=1;
      if(epoch>=pulse.epoch)for(unsigned j=0;j<3;j++)D[(6*epoch+c)*p+pulse.parameter+j]+=pulse.map[3*c+j];}
   }
   std::vector<Matrix6>phi(n);for(unsigned i=0;i<n;i++)for(unsigned c=0;c<6;c++){phi[i][6*c+c]=c<3?1:1/160.;if(c<3)phi[i][6*c+c+3]=i/16.;}
   auto obs=observationRow(phi,{{7,-.05},{8,.6},{9,.45}},{{.2,-.7,.4,0,0,0}});
   std::vector<double>o(m);for(auto t:obs)o[t.column]=t.value;
   std::cout<<"{\"n\":"<<n<<",\"p\":"<<p<<",\"E\":";array(dense(rows,m));std::cout<<",\"P\":";array(dense(rows,p,true));
   std::cout<<",\"reference\":";array(D);std::cout<<",\"observation\":";array(o);std::cout<<"}\n";return 0;
 }
 std::vector<double>rhs(m);for(unsigned i=0;i<m;i++)rhs[i]=std::sin(.01*i)+.03*std::cos(.05*i);
 auto rows=tangentRows(n,dt,channels,rhs);std::vector<double>G(m*m),b(m);
 for(unsigned i=0;i<m;i++)b[i]=rows[i].target;
 for(unsigned col=0;col<m;col++)
 {
   std::vector<double>x(m);x[col]=1;std::vector<double>integrated(6*n);
   for(auto&channel:channels)
   {
     std::vector<long double>a(3*channel.samples.size());
     for(unsigned k=0;k<channel.samples.size();k++)for(unsigned r=0;r<3;r++)for(unsigned c=0;c<3;c++)
     {const auto&s=channel.samples[k];double p=0,v=0;for(auto w:s.position)p+=w.value*x[6*w.column+c];for(auto w:s.velocity)v+=w.value*x[6*w.column+c+3];a[3*k+r]+=static_cast<long double>(s.jacobian.position[3*r+c])*p+static_cast<long double>(s.jacobian.velocity[3*r+c])*v;}
     auto y=tangentIntegrate(channel.weights,dt,a);for(unsigned i=0;i<y.size();i++)integrated[i]+=y[i];
   }
   for(unsigned i=0;i<n;i++)for(unsigned c=0;c<6;c++)G[(6*i+c)*m+col]=x[6*i+c]-integrated[(c<3?0:3*n)+3*i+c%3];
 }
 std::cout<<"{\"n\":"<<n<<",\"E\":";array(dense(rows,m));std::cout<<",\"b\":";array(b);
 std::cout<<",\"G\":";array(G);std::cout<<",\"rhs\":";array(rhs);std::cout<<"}\n";
}
'''


@pytest.fixture(scope="module")
def kernel(tmp_path_factory):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.fail("C++ compiler is required for the segmented tangent gate")
    directory = tmp_path_factory.mktemp("segmented-tangent")
    source = directory / "probe.cpp"
    source.write_text(CPP)
    executable = directory / "probe"
    result = subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                             "-I", str(ROOT / "groops/extension"), str(source), "-o", str(executable)],
                            text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return executable


def run(kernel, mode):
    result = subprocess.run([str(kernel), mode], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("mode", ["operator", "flight"])
def test_local_rows_match_global_native_integral_operator(kernel, mode):
    data = run(kernel, mode)
    m = 6 * data["n"]
    e, g = np.array(data["E"]).reshape(m, m), np.array(data["G"]).reshape(m, m)
    dense = solve(g, data["rhs"])
    local = solve(e, data["b"])
    assert np.linalg.norm(local-dense)/np.linalg.norm(dense) < 2e-12
    assert np.linalg.norm(g @ local - data["rhs"])/np.linalg.norm(data["rhs"]) < 2e-12
    # Computational cut at node 8 does not discard stencil dependencies.
    assert np.count_nonzero(e[6*7:6*8, 6*8:])


def test_force_design_keeps_actual_variation_of_constants_discretization(kernel):
    data = run(kernel, "variation")
    m, p = 6*data["n"], data["p"]
    e, parameters = np.array(data["E"]).reshape(m, m), np.array(data["P"]).reshape(m, p)
    design = solve(e, -parameters)
    reference = np.array(data["reference"]).reshape(m, p)
    np.testing.assert_allclose(design, reference, rtol=3e-15, atol=2e-16)
    np.testing.assert_array_equal(design[:6, -6:], np.eye(6))
    np.testing.assert_array_equal(design[:6*8, 2:5], 0.)
    np.testing.assert_array_equal(design[6*8+3:6*8+6, 2:5], np.eye(3)*1e-6)


def test_local_measurement_keeps_halo_and_native_initial_scaling(kernel):
    data = run(kernel, "variation")
    n = data["n"]
    expected = np.zeros(6*n)
    for epoch, weight in [(7, -.05), (8, .6), (9, .45)]:
        expected[6*epoch:6*epoch+3] = weight*np.array([.2, -.7, .4])
        expected[6*epoch+3:6*epoch+6] = weight*np.array([.2, -.7, .4])*epoch/16
    np.testing.assert_allclose(data["observation"], expected, rtol=2e-15, atol=1e-17)


def test_invalid_operator_and_forcing_fail_closed(kernel):
    assert run(kernel, "invalid")["caught"] == 8


def test_native_export_is_valid_json_and_preserves_expansion_components(kernel):
    data = run(kernel, "serialization")
    assert data["escaped"] == 'a"b\\c\n'
    assert [row[0] for row in data["weights"]] == [7, 8, 9]
    assert [row[1] for row in data["weights"]] == [1., .5, -.125]
    assert float.fromhex(data["weights"][1][3]) == pytest.approx(1e-30, rel=1e-15)
    assert float.fromhex(data["weights"][2][3]) == pytest.approx(-1e-31, rel=1e-15)


def test_cartesian_query_transport_separates_position_and_postpulse_velocity(kernel):
    data = run(kernel, "serialization")
    query = data["query"]
    assert query["kind"] == "state" and query["set"] == "nominal_observation"
    assert (query["receiver"], query["arc"], query["index"], query["native_first"], query["native_count"]) == (2, 0, 19, 33, 12)
    assert query["time"] == [60000, .25]
    assert query["position_halo"] == data["weights"]
    assert query["velocity_halo"] == [[9, 1, "0x8p-3", "0x0p+0"]]


def test_export_installer_keeps_distinct_operators_and_native_halowork():
    path = ROOT / "groops/extension/native_segmented.py"
    spec = importlib.util.spec_from_file_location("native_segmented", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "computeIntegrand(index,&raw)" in module.VARIATION_EXPORT
    assert "stochasticPulse[i]" in module.VARIATION_EXPORT
    assert "stateInterpolation.orbitPocStencil" in module.TANGENT_EXPORT
    assert "polynomial.interpolateOffset" in module.STENCIL
    assert "Matrix(count,0)" in module.STENCIL
    assert "coeffIntegral.at(coefficient)" in module.VARIATION_EXPORT
    assert "initial_parameter_offset" in module.VARIATION_EXPORT
    assert "unchanged_whole_arc" in module.TANGENT_EXPORT


def test_covariance_query_hook_never_requires_dense_covariance():
    spec = importlib.util.spec_from_file_location("native_segmented_queries", ROOT / "groops/extension/native_segmented.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hook = module.COVARIANCE_QUERIES
    assert "stateCovariance" not in hook and "parameterCovariance" not in hook
    assert "PosDesign" not in hook and "VelDesign" not in hook
    assert '"nominal_observation"' in hook and "covered[i]=TRUE" in hook
    assert "orbitPocStencil(gnss->times[i],0.L,TRUE)" in hook
    assert 'identity={{i,1.L,0.L}}' in hook
    assert "equation.times.size()>1000||queries.size()>1000||count>200" in module.QUERY_GATE


def test_segmented_build_flag_requires_numerics(tmp_path):
    result = subprocess.run(["python3", str(ROOT/"scripts/build_groops.py"),
                             "--source-dir", str(tmp_path/"unused"), "--build-dir", str(tmp_path/"build"),
                             "--segmented"], capture_output=True, text=True, timeout=20)
    assert result.returncode == 2
    assert "--segmented requires --numerics" in result.stderr
    assert not (tmp_path/"unused").exists()
