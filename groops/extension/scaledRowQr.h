// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_SCALED_ROW_QR_H
#define ORBIT_POC_SCALED_ROW_QR_H
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <memory>
#include <unistd.h>
#include "base/import.h"
#include "gnss/gnssNormalEquationInfo.h"
#include "parallel/matrixDistributed.h"
#include "external/fortran.h"
#include "misc/orbitPoc/artifactReceipt.h"
#include "misc/orbitPoc/twofoldGeometry.h"

extern "C" void FORTRANCALL(orbitpoctriangularqr,ORBITPOCTRIANGULARQR)(
  const F77Int &m,const F77Int &n,const F77Int &nb,F77Double a[],const F77Int &lda,
  F77Double b[],const F77Int &ldb,F77Double t[],const F77Int &ldt,
  F77Double z[],F77Double y[],F77Double work[],F77Int &info);

// Original weighted rows only: no A'A, ridge or normal-equation fallback.
namespace orbitPocQr
{
// Objective arithmetic uses original weighted residuals, never residuals
// reconstructed from an observation-dependent orthogonal elimination basis.
// Neumaier compensation retains small contributions in both positive costs and
// signed paired reductions; each product is formed in extended precision.
class ObjectiveSum
{
  long double sum=0,correction=0;
public:
  void add(long double value)
  {
    const long double next=sum+value;
    correction+=(std::fabs(sum)>=std::fabs(value))?(sum-next)+value:(value-next)+sum;
    sum=next;
  }
  long double value()const{return sum+correction;}
};
inline std::string env(const char *name,const std::string &fallback="")
{const char *p=std::getenv(name); return p ? p : fallback;}
inline Bool enabled() {return !env("ORBIT_POC_NUMERICS_QR_PREFIX").empty();}
inline void triangularMerge(Matrix &r,Vector &z,Matrix &rows,Vector &target)
{
  if(!rows.rows()||!r.columns())return;
  if(r.rows()!=r.columns()||r.columns()!=rows.columns()||z.rows()!=r.rows()||target.rows()!=rows.rows())
    throw(Exception("Invalid triangular QR merge dimensions"));
  if(rows.rows()>std::numeric_limits<F77Int>::max()||r.rows()>std::numeric_limits<F77Int>::max())
    throw(Exception("Triangular QR merge exceeds native LAPACK integer dimensions"));
  const F77Int m=rows.rows(),n=r.columns(),nb=std::min<F77Int>(32,n),lda=r.ld(),ldb=rows.ld(),ldt=nb;
  Matrix t(nb,n);Vector work(static_cast<UInt>(nb)*n);F77Int info=0;
  FORTRANCALL(orbitpoctriangularqr,ORBITPOCTRIANGULARQR)(m,n,nb,r.field(),lda,rows.field(),ldb,t.field(),ldt,z.field(),target.field(),work.field(),info);
  if(info)throw(Exception("LAPACK triangular QR merge failed with code "+std::to_string(info)));
}
inline std::FILE *temporarySpool(const std::string &directory)
{
  if(directory.empty())return std::tmpfile();
  for(unsigned char value:directory)if(value<32)throw(Exception("Invalid QR spool directory"));
  std::string pattern=directory+"/orbit-poc-qr-XXXXXX";
  std::vector<char> name(pattern.begin(),pattern.end());name.push_back('\0');
  const int descriptor=mkstemp(name.data());
  if(descriptor<0)throw(Exception("Cannot create secure QR row spool in "+directory));
  std::FILE *stream=fdopen(descriptor,"w+b");
  if(!stream){close(descriptor);std::remove(name.data());throw(Exception("Cannot open QR row spool"));}
  if(std::remove(name.data())!=0){std::fclose(stream);throw(Exception("Cannot unlink QR row spool"));}
  return stream;
}
inline Bool dynamic(const ParameterName &p)
{return p.type=="logDensity" || (p.type.find("position0.")==0 || p.type.find(".position0.")!=std::string::npos) || (p.type.find("velocity0.")==0 || p.type.find(".velocity0.")!=std::string::npos) || p.type.find("stochasticPulse.")==0;}
inline std::string unit(const ParameterName &p)
{
  if(p.type.find("stochasticPulse.")==0) return "um/s";
  if((p.type.find("position0.")==0 || p.type.find(".position0.")!=std::string::npos)) return "m";
  if((p.type.find("velocity0.")==0 || p.type.find(".velocity0.")!=std::string::npos)) return "m";
  if(p.type=="logDensity") return "1";
  if(p.type=="VTEC" || p.type.find("VTECGradient.")==0) return "TECU";
  if(p.type=="clock" || p.type.find("clockError")==0 || p.type.find("codeBias")==0 || p.type.find("tecBias")==0 || p.type=="testBias")return "m";
  if(p.type.find("phaseBiasTrend")==0)return "cycle/channel";
  if(p.type.find("ambiguity")==0 || p.type.find("phaseBias")==0) return "cycle";
  throw(Exception("Unsupported QR parameter unit: "+p.str()));
}
inline std::string coordinateConvention(const ParameterName &p)
{
  if(p.type.find("velocity0.")==0||p.type.find(".velocity0.")!=std::string::npos)return "initial_velocity_times_arc_scale;SI_map=initial_design_artifact";
  if(p.type.find("stochasticPulse.")==0)return "inertial_velocity;SI_multiplier=1e-6";
  if(p.type.find("phaseBias")==0||p.type.find("ambiguity")==0)return "native_signal_basis;range_map=recorded_wavelength_basis";
  if(p.type.find("codeBias")==0||p.type.find("tecBias")==0)return "native_bias_basis;range_map=recorded_datum_basis";
  return "direct_native_coordinate";
}
inline const Vector &fullCoordinates(Vector &accumulated,const_MatrixSliceRef basis,const Vector &physical)
{
  if(!accumulated.rows())accumulated=leastSquares(Matrix(basis),Vector(physical));
  if(accumulated.rows()!=basis.columns())throw(Exception("Accumulated bias coordinate basis changed"));
  return accumulated;
}
inline void accumulateCoordinates(Vector &accumulated,const_MatrixSliceRef update)
{
  if(!accumulated.rows()||accumulated.rows()!=update.rows()||update.columns()!=1)
    throw(Exception("Bias coordinates must be initialized before nuisance updates"));
  axpy(1.,update,accumulated);
}
struct Rank
{
  UInt rank=0, count=0; Double threshold=0, largest=0, smallest=0; std::string status="full";
  std::vector<Double> singularValues;
};
inline Rank rank(const_MatrixSliceRef rows,UInt originalRows=0)
{
  Rank out; out.count=rows.columns();
  if(!out.count) return out;
  if(!rows.rows()) {out.status="deficient";return out;}
  Matrix a(rows),u,v; Vector s=singularValueDecomposition(a,u,v,FALSE);
  for(UInt i=0;i<s.rows();i++)out.singularValues.push_back(s(i));
  out.largest=s(0); out.smallest=(s.rows()<out.count ? 0 : s(s.rows()-1));
  out.threshold=std::numeric_limits<Double>::epsilon()*std::max({originalRows,rows.rows(),rows.columns()})*out.largest;
  for(UInt i=0;i<s.rows();i++) if(s(i)>out.threshold) out.rank++;
  if(out.rank<out.count) out.status="deficient";
  else if(out.smallest<=10*out.threshold) out.status="unresolved";
  return out;
}
inline void requireRank(const_MatrixSliceRef rows,const std::string &context)
{const auto r=rank(rows); if(r.status!="full") throw(Exception("v3.1 QR "+context+" rank "+r.status));}
inline Matrix upper(const_MatrixSliceRef a,UInt n)
{Matrix r(n,Matrix::TRIANGULAR); for(UInt j=0;j<n;j++) for(UInt i=0;i<=j;i++) r(i,j)=a(i,j); return r;}
// Null/range bases for datum design rows; pad with zero rows to obtain the full
// right basis even for underdetermined designs. These are exact gauge changes.
inline Matrix basis(const_MatrixSliceRef rows,Bool range)
{
  const UInt n=rows.columns(); if(!n) return Matrix(0,0);
  Matrix a(std::max(rows.rows(),n),n); if(rows.rows()) copy(rows,a.row(0,rows.rows()));
  Matrix u,vt; Vector s=singularValueDecomposition(a,u,vt,TRUE);
  const Double tol=std::numeric_limits<Double>::epsilon()*std::max(a.rows(),n)*(s.rows()?s(0):0);
  UInt r=0; while(r<n && s(r)>10*tol) r++;
  if(r<n && s(r)>tol) throw(Exception("Unresolved datum rank in original-row SVD"));
  Matrix result(n,range?r:n-r);
  for(UInt j=0;j<result.columns();j++) for(UInt i=0;i<n;i++) result(i,j)=vt(range?j:r+j,i);
  // Deterministic signs; gauge coordinates are recorded by the caller.
  for(UInt j=0;j<result.columns();j++)
  {UInt pivot=0;for(UInt i=1;i<n;i++) if(std::fabs(result(i,j))>std::fabs(result(pivot,j))) pivot=i; if(result(pivot,j)<0) result.column(j)*=-1.;}
  return result;
}
inline Matrix concatenate(const std::vector<Matrix> &blocks,UInt columns)
{UInt m=0;for(const auto &a:blocks)m+=a.rows(); Matrix rows(m,columns);UInt p=0;for(const auto&a:blocks){copy(a,rows.row(p,a.rows()));p+=a.rows();}return rows;}
// Orthogonally remove a possibly gauge-deficient nuisance block. The SVD basis
// identifies its column space; no implicit penalty is added for its nullspace.
inline Matrix project(const_MatrixSliceRef rows,const std::vector<UInt> &local,const std::vector<UInt> &keep)
{
  Matrix b(rows.rows(),local.size()), a(rows.rows(),keep.size());
  for(UInt j=0;j<local.size();j++)copy(rows.column(local[j]),b.column(j));
  for(UInt j=0;j<keep.size();j++)copy(rows.column(keep[j]),a.column(j));
  if(!b.size())return a;
  Matrix u,vt;Vector s=singularValueDecomposition(b,u,vt,TRUE);
  const Double t=std::numeric_limits<Double>::epsilon()*std::max(b.rows(),b.columns())*s(0);UInt r=0;
  while(r<s.rows() && s(r)>10*t)r++;
  if(r<s.rows() && s(r)>t)throw(Exception("Unresolved datum nuisance rank"));
  if(r) a-=u.column(0,r)*(u.column(0,r).trans()*a);
  const Double floor=10*std::numeric_limits<Double>::epsilon()*std::max(rows.rows(),rows.columns())*norm(rows);
  for(UInt j=0;j<a.columns();j++)if(norm(a.column(j))<=floor)a.column(j).setNull();
  return a;
}
inline void recordDatum(const std::string &kind,const_MatrixSliceRef a)
{
  if(!enabled())return;
  static UInt sequence=0;const std::string file=env("ORBIT_POC_NUMERICS_QR_PREFIX")+".datum."+std::to_string(++sequence)+"."+kind+".tsv";
  std::ofstream out(file);if(!out)throw(Exception("Cannot record datum basis"));out<<std::setprecision(17);
  for(UInt i=0;i<a.rows();i++){for(UInt j=0;j<a.columns();j++){if(j)out<<'\t';out<<a(i,j);}out<<'\n';}
}
inline Vector selectDatum(const_MatrixSliceRef rows,UInt receivers,UInt transmitters)
{
  // Preserve the legacy priority: receiver biases, transmitter biases, then
  // ambiguities. Within each latter block choose the largest remaining norm,
  // breaking equal-norm ties in reverse index order, as the native pivot does.
  // Gauge nullspaces are expected here, but a singular value in the unresolved
  // band is not evidence of an exact gauge. Certify the rank before selecting
  // the preferred columns, and require that preference selection spans it.
  const auto certificate=rank(rows);
  for(Double value:certificate.singularValues)
    if(value>certificate.threshold&&value<=10*certificate.threshold)
      throw(Exception("Unresolved ambiguity datum rank in original-row SVD"));
  Matrix q(rows.rows(),rows.columns());UInt count=0;Vector selected(rows.columns());
  const Double tolerance=certificate.threshold;
  auto residual=[&](UInt j){Vector v(rows.column(j));for(UInt repeat=0;repeat<2;repeat++)for(UInt k=0;k<count;k++)axpy(-inner(q.column(k),v),q.column(k),v);return v;};
  for(UInt j=0;j<receivers;j++){Vector v=residual(j);const Double n=norm(v);if(n<=tolerance)throw(Exception("Deficient receiver-bias datum rows"));copy(v*(1./n),q.column(count++));selected(j)=1.;}
  for(const auto &bounds:std::vector<std::pair<UInt,UInt>>{{receivers,receivers+transmitters},{receivers+transmitters,rows.columns()}})
    while(TRUE)
    {
      UInt best=NULLINDEX;Double largest=0;Vector v;
      for(UInt j=bounds.second;j>bounds.first;j--)if(!selected(j-1)){Vector candidate=residual(j-1);const Double n=norm(candidate);if(n>largest){largest=n;best=j-1;v=candidate;}}
      if(count==certificate.rank||best==NULLINDEX||largest<=tolerance)break;
      selected(best)=1.;copy(v*(1./largest),q.column(count++));
    }
  if(count!=certificate.rank)throw(Exception("Preferred ambiguity datum does not span the certified row space"));
  Matrix chosen(rows.rows(),count);UInt column=0;
  for(UInt j=0;j<selected.rows();j++)if(selected(j))copy(rows.column(j),chosen.column(column++));
  requireRank(chosen,"selected ambiguity datum");
  return selected;
}
inline void writeMatrix(const std::string &name,const_MatrixSliceRef a)
{
  std::ofstream f(name,std::ios::binary);if(!f)throw(Exception("Cannot write native QR factor"));
  const std::uint64_t dims[2]={a.rows(),a.columns()}; f.write(reinterpret_cast<const char*>(dims),sizeof(dims));
  for(UInt i=0;i<a.rows();i++)for(UInt j=0;j<a.columns();j++){const double v=a(i,j);f.write(reinterpret_cast<const char*>(&v),sizeof(v));}
  if(!f)throw(Exception("Cannot finish native QR factor"));
}
}

class OrbitPocRowQr
{
  struct Row {Double rhs;std::vector<UInt> ids;std::vector<Double> values;};
  struct Conditional {std::vector<UInt> ids;Matrix r,b;Vector z,scales;};
  struct FileCloser {void operator()(FILE *file) const {if(file)std::fclose(file);}};
  std::unique_ptr<FILE,FileCloser> spool;
  struct GroupConditional {Matrix original,householder;Vector tau,z,raw;Double removedEnergy;};
  std::map<std::tuple<UInt,UInt,UInt>,GroupConditional> groupConditionals;
  std::vector<Row> epochRows;
  std::vector<Double> objectiveResiduals,referenceResiduals;
  std::map<std::tuple<UInt,UInt,UInt>,Vector> observationResiduals,referenceObservationResiduals;
  using PreciseResiduals=std::vector<orbitPocQr::TwofoldGeometry>;
  std::map<std::tuple<UInt,UInt,UInt>,PreciseResiduals> preciseObservationResiduals,referencePreciseObservationResiduals;
  std::vector<Conditional> conditionals;
  std::vector<ParameterName> names;
  std::vector<Double> norms;
  Vector scales,z;
  Matrix R;
  UInt total=0,localCount=0,retained=0,reducedRows=0,sourceRows=0,sequence=0,currentEpoch=NULLINDEX;
  std::vector<UInt> epochIds;
  Double constant=0,sourceRhs2=0,groupRemovedEnergy=0;
  std::string stem,previousStem,spoolDirectory,contextName="weighted_observation";
  std::ofstream provenance;
  orbitPocQr::Rank diagnosis;
  Bool finished=FALSE,keepIntermediateFactors=TRUE,compressRows=FALSE;
  Bool costOnly=FALSE,expectedCostPending=FALSE;
  Double expectedCost=0;
  std::uint64_t support=14695981039346656037ULL;
  mutable Double nuisanceGradient=std::numeric_limits<Double>::quiet_NaN();
  mutable Double nuisanceReduction=std::numeric_limits<Double>::quiet_NaN();
  void supportValue(std::uint64_t value){for(UInt i=0;i<8;i++){support^=(value>>(8*i))&255;support*=1099511628211ULL;}}
  void put(const_MatrixSliceRef a,const_MatrixSliceRef b)
  {
    std::vector<Double> packed(a.columns()+1);
    for(UInt i=0;i<a.rows();i++)
    {packed[0]=b(i,0);
      for(UInt j=0;j<a.columns();j++){const Double v=a(i,j);if(v!=0)norms[j+localCount]=std::hypot(norms[j+localCount],v);packed[j+1]=v;}
      if(std::fwrite(packed.data(),sizeof(Double),packed.size(),spool.get())!=packed.size())throw(Exception("QR spool write failed"));
      reducedRows++;}
  }
public:
  Bool enabled() const {return orbitPocQr::enabled();}
  const std::string &artifactStem() const{return stem;}
  void prepareCostOnly()
  {
    costOnly=TRUE;provenance.close();spool.reset();referenceResiduals=objectiveResiduals;
    referenceObservationResiduals=observationResiduals;
    referencePreciseObservationResiduals=preciseObservationResiduals;
  }
  // Capture all original observation rows, including a group STEC prior, even
  // if no group nuisance is active. Called before any observation QR rotation.
  // Standalone row fixtures provide exact binary64 data. The native GNSS
  // equation instead calls the explicit expansion overload below, after all
  // corrections and weights, and verifies its completion before this boundary.
  void retainObservationResiduals(UInt receiver,UInt transmitter,UInt epoch,const_MatrixSliceRef target)
  {
    if((stem.empty()&&!costOnly)||finished)return;
    if(target.columns()!=1)throw(Exception("Original objective requires a residual vector"));
    PreciseResiduals precise(target.rows());
    for(UInt i=0;i<target.rows();i++)precise[i]=orbitPocQr::TwofoldGeometry(target(i,0));
    retainObservationResiduals(receiver,transmitter,epoch,target,precise);
  }
  void retainObservationResiduals(UInt receiver,UInt transmitter,UInt epoch,const_MatrixSliceRef target,const PreciseResiduals &precise)
  {
    if((stem.empty()&&!costOnly)||finished)return;
    if(target.columns()!=1)throw(Exception("Original objective requires a residual vector"));
    if(precise.size()!=target.rows())throw(Exception("Precise original observation row count differs"));
    const auto key=std::make_tuple(receiver,transmitter,epoch);
    if(observationResiduals.count(key)||preciseObservationResiduals.count(key))throw(Exception("Duplicate original observation objective block"));
    for(UInt i=0;i<target.rows();i++)
    {
      if(!std::isfinite(target(i,0))||!std::isfinite(precise[i].high)||!std::isfinite(precise[i].low))
        throw(Exception("Nonfinite original observation residual"));
      if(static_cast<Double>(precise[i].rounded())!=target(i,0))
        throw(Exception("Precise original observation and QR target disagree"));
    }
    observationResiduals.emplace(key,Vector(target));
    preciseObservationResiduals.emplace(key,precise);
  }
  Double actualObjectiveReduction()const
  {
    if(!costOnly||referenceResiduals.size()!=objectiveResiduals.size()||referenceObservationResiduals.size()!=observationResiduals.size())
      throw(Exception("Cost-only original objective support changed"));
    orbitPocQr::ObjectiveSum reduction;
    auto add=[&](Double before,Double after){reduction.add(.5L*(static_cast<long double>(before)-after)*(static_cast<long double>(before)+after));};
    for(UInt i=0;i<referenceResiduals.size();i++)add(referenceResiduals[i],objectiveResiduals[i]);
    if(preciseObservationResiduals.size()!=observationResiduals.size()||referencePreciseObservationResiduals.size()!=referenceObservationResiduals.size())
      throw(Exception("Missing precise original observation ledger"));
    for(const auto &entry:preciseObservationResiduals)
    {
      const auto reference=referencePreciseObservationResiduals.find(entry.first);
      if(reference==referencePreciseObservationResiduals.end()||reference->second.size()!=entry.second.size())throw(Exception("Cost-only original observation support changed"));
      for(UInt i=0;i<entry.second.size();i++)
      {
        const auto &before=reference->second[i],&after=entry.second[i];
        const auto value=orbitPocQr::TwofoldGeometry(.5L)*(before-after)*(before+after);
        reduction.add(value.high);reduction.add(value.low);
      }
    }
    return static_cast<Double>(reduction.value());
  }
  // Compatibility diagnostic on rounded rows; never used for acceptance or
  // direct objective arithmetic. Factor provenance records this distinction.
  std::array<Double,7> largestRawResidualChange()const
  {
    std::array<Double,7> result{};Double maximum=0;
    for(const auto &entry:observationResiduals)
    {
      const auto &before=referenceObservationResiduals.at(entry.first),&after=entry.second;
      for(UInt i=0;i<before.rows();i++)
      {
        const Double contribution=static_cast<Double>(.5L*(static_cast<long double>(before(i))-after(i))*(static_cast<long double>(before(i))+after(i)));
        if(std::fabs(contribution)>maximum)
        {maximum=std::fabs(contribution);result={Double(std::get<0>(entry.first)),Double(std::get<1>(entry.first)),Double(std::get<2>(entry.first)),Double(i),before(i),after(i),contribution};}
      }
    }
    return result;
  }
  Bool isCostOnly()const{return costOnly;}
  std::uint64_t supportSignature()const{return support;}
  UInt weightedRowCount()const{return sourceRows;}
  void expectObjective(Double value){expectedCost=value;expectedCostPending=TRUE;}
  void context(const std::string &value){contextName=value;}
  void retainGroup(UInt receiver,UInt transmitter,UInt epoch,const_MatrixSliceRef original,const_MatrixSliceRef factor,const Vector &tau,const_MatrixSliceRef target)
  {
    if((stem.empty()&&!costOnly)||finished)return;
    Vector transformed(target);QTransMult(factor,tau,transformed);
    const Double removed=quadsum(transformed.row(0,tau.rows()));
    const auto key=std::make_tuple(receiver,transmitter,epoch);const auto previous=groupConditionals.find(key);
    if(previous==groupConditionals.end()){supportValue(receiver);supportValue(transmitter);supportValue(epoch);supportValue(original.rows());supportValue(original.columns());}
    if(previous!=groupConditionals.end())groupRemovedEnergy-=previous->second.removedEnergy;
    groupConditionals[key]={Matrix(original),Matrix(factor),tau,Vector(transformed.row(0,tau.rows())),Vector(target),removed};groupRemovedEnergy+=removed;
  }
  Vector recoverGroup(UInt receiver,UInt transmitter,UInt epoch,const_MatrixSliceRef original,const Vector &residual)const
  {
    const auto it=groupConditionals.find({receiver,transmitter,epoch});
    if(it==groupConditionals.end())throw(Exception("Missing retained ionosphere conditional factor"));
    const auto &c=it->second;
    if(original.rows()!=c.original.rows()||original.columns()!=c.original.columns()||norm(original-c.original)>1e-14*std::max(1.,norm(original)))
      throw(Exception("Ionosphere support/weights changed during QR recovery"));
    Vector v=residual;QTransMult(c.householder,c.tau,v);Vector x(v.row(0,c.tau.rows()));
    const Matrix r=orbitPocQr::upper(c.householder,c.tau.rows());triangularSolve(1.,r,x);return x;
  }
  UInt originalObjectiveRowCount()const
  {
    UInt count=objectiveResiduals.size();
    for(const auto &entry:observationResiduals)count+=entry.second.rows();
    return count;
  }
  Double rawCost()const
  {
    orbitPocQr::ObjectiveSum cost;
    for(Double residual:objectiveResiduals)cost.add(.5L*residual*residual);
    if(preciseObservationResiduals.size()!=observationResiduals.size())throw(Exception("Missing precise original observation ledger"));
    for(const auto &entry:preciseObservationResiduals)for(const auto &residual:entry.second)
    {
      const auto value=orbitPocQr::TwofoldGeometry(.5L)*residual*residual;
      cost.add(value.high);cost.add(value.low);
    }
    return static_cast<Double>(cost.value());
  }
  Double lastNuisanceGradient()const{return nuisanceGradient;}
  Double lastNuisanceReduction()const{return nuisanceReduction;}
  void recordBiasCoordinates(const Vector &full)const
  {
    if(costOnly)return;
    if(full.rows()!=names.size())throw(Exception("Full-bias coordinate count mismatch"));
    std::ofstream out(stem+".bias_coordinates.tsv");out<<std::setprecision(17)<<"index\tname\tfull_native_coordinate\n";
    for(UInt i=0;i<names.size();i++)if(names[i].type.find("codeBias")==0||names[i].type.find("tecBias")==0)
      out<<i<<'\t'<<names[i].str()<<'\t'<<full(i)<<'\n';
    if(!out)throw(Exception("Cannot record full accumulated bias coordinates"));
    std::ofstream nuisance(stem+".nuisance_coordinates.tsv");nuisance<<std::setprecision(17)<<"index\tname\tfull_native_coordinate\n";
    for(UInt i=0;i<names.size();i++)if(!orbitPocQr::dynamic(names[i]))nuisance<<i<<'\t'<<names[i].str()<<'\t'<<full(i)<<'\n';
    if(!nuisance)throw(Exception("Cannot record full nuisance coordinates"));
  }
  void addPulseReference(const std::vector<ParameterName> &parameters,Vector &x) const
  {
    const auto path=orbitPocQr::env("ORBIT_POC_NUMERICS_PULSE_REFERENCE");if(path.empty())return;
    std::ifstream in(path);if(!in)throw(Exception("Cannot read full pulse reference"));
    for(UInt i=0;i<parameters.size();i++)if(parameters[i].type.find("stochasticPulse.")==0)
    {Double value;if(!(in>>value)||!std::isfinite(value))throw(Exception("Invalid full pulse reference"));x(i)+=value;}
    Double extra;if(in>>extra)throw(Exception("Full pulse reference count mismatch"));
  }
  void writeProfileCost(const Vector &profiled) const
  {
    const Double denominator=std::max(1.,std::sqrt(sourceRhs2+groupRemovedEnergy));
    auto conditionalGradient=[](const_MatrixSliceRef r,const Vector &target)
    {
      Double maximum=0;
      for(UInt j=0;j<r.columns();j++)
      {long double product=0;Double length=0;for(UInt i=0;i<r.rows();i++){product+=static_cast<long double>(r(i,j))*target(i);length=std::hypot(length,r(i,j));}
        if(length>0)maximum=std::max(maximum,static_cast<Double>(std::fabs(product)/length));}
      return maximum;
    };
    Double clockEnergy=0,clockGradient=0,groupGradient=0,retainedGradient=0;
    for(const auto &c:conditionals){clockEnergy+=quadsum(c.z);clockGradient=std::max(clockGradient,conditionalGradient(c.r,c.z));}
    for(const auto &entry:groupConditionals)
    {const auto &c=entry.second;const Matrix r=orbitPocQr::upper(c.householder,c.tau.rows());groupGradient=std::max(groupGradient,conditionalGradient(r,c.z));}
    Vector y(retained);for(UInt j=0;j<retained;j++)y(j)=profiled(j+localCount)/scales(j);
    const Vector prediction=R*y;
    long double retainedReduction=0;
    for(UInt i=0;i<prediction.rows();i++)retainedReduction+=static_cast<long double>(prediction(i))*(static_cast<long double>(z(i))-.5L*prediction(i));
    for(UInt j=0;j<retained;j++)if(!orbitPocQr::dynamic(names[j+localCount]))
      retainedGradient=std::max(retainedGradient,conditionalGradient(R.column(j),z));
    nuisanceGradient=std::max({retainedGradient,clockGradient,groupGradient})/denominator;
    nuisanceReduction=static_cast<Double>(retainedReduction+.5L*(static_cast<long double>(clockEnergy)+groupRemovedEnergy));
    std::ofstream f(stem+".profile.json");f<<std::setprecision(17)<<"{\"direct_cost\":"<<rawCost()<<",\"linearized_profile_cost\":"<<.5*residual2(profiled)<<",\"profile_cost\":"<<.5*residual2(profiled)<<",\"rhs2\":"<<(sourceRhs2+groupRemovedEnergy)<<",\"group_eliminated_target_energy\":"<<groupRemovedEnergy<<",\"epoch_nuisance_eliminated_target_energy\":"<<clockEnergy<<",\"clock_eliminated_target_energy\":"<<clockEnergy<<",\"retained_nuisance_predicted_reduction\":"<<static_cast<Double>(retainedReduction)<<",\"nuisance_predicted_reduction\":"<<nuisanceReduction<<",\"nuisance_gradient_scaled\":"<<nuisanceGradient<<",\"retained_nuisance_gradient_scaled\":"<<retainedGradient/denominator<<",\"epoch_nuisance_conditional_gradient_scaled\":"<<clockGradient/denominator<<",\"clock_conditional_gradient_scaled\":"<<clockGradient/denominator<<",\"group_conditional_gradient_scaled\":"<<groupGradient/denominator<<",\"profile_residual2\":"<<residual2(profiled)<<"}\n";
    if(!f)throw(Exception("Cannot record nuisance stationarity diagnostics"));
  }

  const orbitPocQr::Rank &rankInfo()const{return diagnosis;}
  void begin(const GnssNormalEquationInfo &info)
  {
    if(Parallel::size(info.comm)!=1)throw(Exception("v3.1 QR supports serial execution only"));
    names=info.parameterNames(); total=names.size();localCount=info.blockIndex(info.blockInterval());retained=total-localCount;
    for(const auto &parameter:names)(void)orbitPocQr::unit(parameter);
    for(UInt i=0;i<localCount;i++)if(names[i].type.find("clock")==std::string::npos&&names[i].type!="VTEC")throw(Exception("v3.1 local QR supports independent epoch clocks and VTEC only"));
    const auto retention=orbitPocQr::env("ORBIT_POC_NUMERICS_KEEP_INTERMEDIATE_FACTORS","1");
    if(retention!="0"&&retention!="1")throw(Exception("QR factor retention must be 0 or 1"));
    keepIntermediateFactors=(retention=="1");
    const auto compression=orbitPocQr::env("ORBIT_POC_NUMERICS_COMPRESS_ROW_PROVENANCE","0");
    if(compression!="0"&&compression!="1")throw(Exception("QR row compression must be 0 or 1"));
    compressRows=(compression=="1");
    spoolDirectory=orbitPocQr::env("ORBIT_POC_NUMERICS_SPOOL_DIRECTORY");
    // Close the previous spool before creating its replacement. Named spools
    // are unlinked immediately, so failure or process death leaves no large file.
    spool.reset();if(!costOnly){spool.reset(orbitPocQr::temporarySpool(spoolDirectory));if(!spool)throw(Exception("Cannot create QR row spool"));}
    norms.assign(total,0.);objectiveResiduals.clear();observationResiduals.clear();preciseObservationResiduals.clear();groupConditionals.clear();epochRows.clear();conditionals.clear();epochIds.clear();sourceRows=reducedRows=0;constant=sourceRhs2=groupRemovedEnergy=0;finished=FALSE;
    nuisanceGradient=nuisanceReduction=std::numeric_limits<Double>::quiet_NaN();
    support=14695981039346656037ULL;
    if(costOnly)return;
    previousStem=stem;stem=orbitPocQr::env("ORBIT_POC_NUMERICS_QR_PREFIX")+"."+std::to_string(++sequence);
    provenance.close();provenance.clear();provenance.open(stem+".rows.tsv");
    if(!provenance)throw(Exception("Cannot open original-row provenance"));
    provenance<<std::setprecision(17)<<"row\tepoch\tsource\trhs\tcolumns\n";
  }
  void beginEpoch(UInt idEpoch,UInt first,UInt count)
  {currentEpoch=idEpoch;epochIds.resize(count);std::iota(epochIds.begin(),epochIds.end(),first);}
  void addRow(Double rhs,const std::vector<UInt>&ids,const std::vector<Double>&values)
  {
    if(ids.size()!=values.size()||!std::isfinite(rhs)||finished)throw(Exception("Invalid native weighted QR row"));
    Row row{rhs,ids,values};Bool hasLocal=FALSE;
    for(UInt j=0;j<ids.size();j++)
    {if(ids[j]>=total||!std::isfinite(values[j]))throw(Exception("Invalid QR column"));
      if(ids[j]<localCount&&values[j]!=0){hasLocal=TRUE;if(std::find(epochIds.begin(),epochIds.end(),ids[j])==epochIds.end())throw(Exception("Time-coupled clocks or VTEC unsupported by v3.1 QR"));}}
    supportValue(currentEpoch);supportValue(sourceRows);for(unsigned char value:contextName)supportValue(value);
    // Group-eliminated observation rows already have their complete original
    // residual vector above. Epoch/global Gaussian constraints are separate
    // rows and are included exactly once. Unhooked standalone row fixtures
    // retain their direct-row semantics when there are no observation blocks.
    if(contextName!="weighted_observation"||observationResiduals.empty())objectiveResiduals.push_back(rhs);
    if(costOnly){sourceRows++;sourceRhs2+=rhs*rhs;return;}
    provenance<<sourceRows<<'\t'<<(currentEpoch==NULLINDEX?"global":std::to_string(currentEpoch))<<'\t'<<contextName<<'\t'<<rhs<<'\t';
    for(UInt j=0;j<ids.size();j++){if(j)provenance<<',';provenance<<ids[j];}provenance<<'\n';
    sourceRows++;sourceRhs2+=rhs*rhs;
    if(currentEpoch!=NULLINDEX)epochRows.push_back(std::move(row));
    else
    {if(hasLocal)throw(Exception("Global or time-coupled constraint on eliminated epoch nuisances unsupported"));Matrix a(1,retained);for(UInt j=0;j<ids.size();j++)if(ids[j]>=localCount)a(0,ids[j]-localCount)+=values[j];Vector b(1,rhs);put(a,b);}
  }
  void finishEpoch()
  {
    if(costOnly){epochRows.clear();epochIds.clear();currentEpoch=NULLINDEX;return;}
    const UInt m=epochRows.size(),k=epochIds.size();
    Matrix a(m,retained),b(m,k);Vector rhs(m);
    for(UInt i=0;i<m;i++){rhs(i)=epochRows[i].rhs;for(UInt j=0;j<epochRows[i].ids.size();j++)
    {const UInt id=epochRows[i].ids[j];const Double v=epochRows[i].values[j];if(id>=localCount)a(i,id-localCount)+=v;else if(v!=0)b(i,std::distance(epochIds.begin(),std::find(epochIds.begin(),epochIds.end(),id)))+=v;}}
    if(k)
    {
      // Scale the independent epoch block before rank diagnosis so clock/VTEC
      // unit conventions do not create spurious local rank classifications.
      Vector localScales(k);
      for(UInt j=0;j<k;j++){norms[epochIds[j]]=norm(b.column(j));localScales(j)=norms[epochIds[j]]>0?1./norms[epochIds[j]]:1.;b.column(j)*=localScales(j);}
      orbitPocQr::requireRank(b,"epoch clock/VTEC nuisance");const Vector tau=QR_decomposition(b);QTransMult(b,tau,a);QTransMult(b,tau,rhs);
      conditionals.push_back({epochIds,orbitPocQr::upper(b,k),Matrix(a.row(0,k)),Vector(rhs.row(0,k)),localScales});
    }
    if(m>k)put(a.row(k,m-k),rhs.row(k,m-k));
    epochRows.clear();epochIds.clear();currentEpoch=NULLINDEX;
  }
  void finish()
  {
    if(finished)return;finished=TRUE;
    if(currentEpoch!=NULLINDEX)throw(Exception("Unclosed QR epoch"));
    if(!observationResiduals.empty())
    {
      UInt eliminatedRows=0;
      for(const auto &entry:groupConditionals)
      {
        if(!observationResiduals.count(entry.first))throw(Exception("Group QR lacks its original objective block"));
        eliminatedRows+=entry.second.tau.rows();
      }
      if(originalObjectiveRowCount()!=sourceRows+eliminatedRows)
        throw(Exception("Original objective row accounting differs from the weighted QR rows"));
    }
    else if(!groupConditionals.empty())throw(Exception("Original observation objective hook is missing"));
    if(costOnly)return;
    if(expectedCostPending){expectedCostPending=FALSE;if(rawCost()!=expectedCost)throw(Exception("Accepted nuisance trial did not reproduce its isolated native objective"));}
    scales=Vector(retained);for(UInt j=0;j<retained;j++)scales(j)=norms[j+localCount]>0?1./norms[j+localCount]:1.;
    R=Matrix(retained,retained);z=Vector(retained);constant=0.;std::rewind(spool.get());
    UInt blockSize=256;const auto requested=orbitPocQr::env("ORBIT_POC_NUMERICS_QR_BLOCK_ROWS");
    if(!requested.empty()){blockSize=std::stoul(requested);if(!blockSize)throw(Exception("QR block rows must be positive"));}
    std::vector<Double> packed(retained+1);
    for(UInt done=0;done<reducedRows;)
    {
      const UInt take=std::min(blockSize,reducedRows-done);
      Matrix a(take,retained);Vector b(take);
      for(UInt i=0;i<take;i++)
      {if(std::fread(packed.data(),sizeof(Double),packed.size(),spool.get())!=packed.size())throw(Exception("QR spool truncated"));b(i)=packed[0];
        for(UInt j=0;j<retained;j++)a(i,j)=packed[j+1]*scales(j);}
      // DTPQRT uses the upper-triangular structure instead of refactoring an
      // entire n-by-n factor for every block. DTPMQRT applies its Q' to [z;b].
      orbitPocQr::triangularMerge(R,z,a,b);
      constant+=quadsum(b);done+=take;
    }
    provenance.flush();if(!provenance)throw(Exception("Original-row provenance write failed"));
    provenance.close();
    if(compressRows)orbitPocQr::compressRowProvenance(stem+".rows.tsv");
    diagnosis=orbitPocQr::rank(R,reducedRows);
    std::ofstream singular(stem+".singular_values.txt");singular<<std::setprecision(17);
    for(Double value:diagnosis.singularValues)singular<<value<<'\n';
    if(!singular)throw(Exception("Cannot record undamped QR singular values"));
    std::ofstream parameters(stem+".parameters.tsv");parameters<<std::setprecision(17)<<"index\tname\tdynamic\tunit\tscale\tcoordinate_convention\n";
    for(UInt i=0;i<total;i++)parameters<<i<<'\t'<<names[i].str()<<'\t'<<orbitPocQr::dynamic(names[i])<<'\t'<<orbitPocQr::unit(names[i])<<'\t'<<(i<localCount?(norms[i]>0?1./norms[i]:1.):scales(i-localCount))<<'\t'<<orbitPocQr::coordinateConvention(names[i])<<'\n';
    orbitPocQr::writeMatrix(stem+".R.bin",R);orbitPocQr::writeMatrix(stem+".z.bin",z);
    orbitPocQr::writeMatrix(stem+".rhs.bin",z);
    std::ofstream meta(stem+".factor.json");meta<<std::setprecision(17)<<"{\"schema\":\"orbit-poc-qr-factor-v1\",\"binary_format\":\"uint64 rows, uint64 columns, row-major float64; little-endian\",\"rows\":"<<R.rows()<<",\"columns\":"<<R.columns()<<",\"orthogonal_energy\":"<<constant<<",\"retained_global_indices\":[";
    for(UInt j=0;j<retained;j++){if(j)meta<<',';meta<<j+localCount;}meta<<"],\"scales\":[";
    for(UInt j=0;j<retained;j++){if(j)meta<<',';meta<<scales(j);}meta<<"],\"dynamic\":[";
    for(UInt j=0;j<retained;j++){if(j)meta<<',';meta<<(orbitPocQr::dynamic(names[j+localCount])?"true":"false");}
    meta<<"],\"local_global_indices\":[";for(UInt i=0;i<localCount;i++){if(i)meta<<',';meta<<i;}
    meta<<"],\"local_scales\":[";for(UInt i=0;i<localCount;i++){if(i)meta<<',';meta<<(norms[i]>0?1./norms[i]:1.);}
    meta<<"],\"local_elimination\":\"independent_epoch_clock_vtec_qr\",\"merge_kernel\":\"LAPACK_DTPQRT_DTPMQRT\",\"keep_intermediate_factors\":"<<(keepIntermediateFactors?"true":"false")
        <<",\"spool_policy\":\""<<(spoolDirectory.empty()?"system_tmpfile":"unlinked_mkstemp")
        <<"\",\"spool_directory\":"<<std::quoted(spoolDirectory)
        <<",\"row_provenance_policy\":\""<<(compressRows?"verified_row_compression_v1":"raw_tsv")<<"\""
        <<",\"objective_residual_basis\":\"original_weighted_rows_v1\",\"objective_accumulation\":\"compensated_long_double\",\"original_objective_rows\":"<<originalObjectiveRowCount()
        <<",\"observation_residual_arithmetic\":\"complete_weighted_twofold_v1\",\"separate_constraint_residual_arithmetic\":\"native_binary64_targets\",\"largest_raw_residual_change_basis\":\"rounded_binary64_diagnostic_only\""
        <<",\"gnss_measurement_arithmetic\":\"relative_query_clock_range_v1\",\"native_time_metadata_precision\":\"double_day_fraction\",\"cartesian_coordinate_precision\":\"float64\",\"corrected_range_coordinates\":\"long_double_polynomial_high_low\",\"range_geometry_precision\":\"high_low_geometry_v2\",\"query_interpolation_precision\":\"twofold_query_weights_v1\",\"light_time_precision\":\"twofold_duration_to_relative_query_v1\",\"receiver_frame\":\"inertial_leo_only\",\"light_time_position_tolerance_m\":1e-10,\"row_compression_level\":"<<(compressRows?6:0)
        <<",\"row_spool_bytes\":"<<static_cast<std::uint64_t>(reducedRows)*(retained+1)*sizeof(Double)<<"}\n";
    meta.close();parameters.close();singular.close();
    if(!meta||!parameters||!singular)throw(Exception("Cannot finish QR factor metadata"));
    spool.reset(); // Reduced rows are no longer needed once the factor exists.
    // A successor must be fully written before any previous large artifacts are
    // removed. All numerical/rank/objective and parameter receipts are retained.
    if(!keepIntermediateFactors&&!previousStem.empty())
    {
      std::vector<orbitPocQr::ArtifactReceipt> removed;
      std::vector<std::pair<std::string,std::string>> disposable{{".R.bin","superseded_triangular_factor"},{".z.bin","superseded_transformed_target"},{".rhs.bin","superseded_transformed_target_alias"}};
      if(!compressRows)disposable.push_back({".rows.tsv","superseded_row_provenance"});
      for(const auto &item:disposable)removed.push_back(orbitPocQr::inspectArtifact(previousStem+item.first,item.second));
      const auto receipt=previousStem+".retention.json";
      orbitPocQr::writeRetentionReceipt(receipt,removed,FALSE);
      for(const auto &artifact:removed)if(std::remove(artifact.path.c_str())!=0)throw(Exception("Cannot remove superseded QR artifact"));
      orbitPocQr::writeRetentionReceipt(receipt,removed,TRUE);
    }
  }
  Vector recover(const Vector &retainedNative)const
  {
    Vector x(total);copy(retainedNative,x.row(localCount,retained));
    for(const auto &c:conditionals)
    {Vector v=c.z-c.b*retainedNative;triangularSolve(1.,c.r,v);for(UInt i=0;i<c.ids.size();i++)x(c.ids[i])=c.scales(i)*v(i);}
    return x;
  }
  Vector solve(Double lambda=0,Bool nuisanceOnly=FALSE)
  {
    finish();if(lambda<0||!std::isfinite(lambda))throw(Exception("Invalid LM lambda"));
    if(diagnosis.status!="full") {writeDiagnostics(Vector(total),Vector(total),lambda);throw(Exception("v3.1 retained QR rank "+diagnosis.status));}
    std::vector<UInt> selected,dyn;
    for(UInt j=0;j<retained;j++){if(orbitPocQr::dynamic(names[j+localCount]))dyn.push_back(j);if(!nuisanceOnly||!orbitPocQr::dynamic(names[j+localCount]))selected.push_back(j);}
    Matrix a(R.rows()+((lambda&&!nuisanceOnly)?dyn.size():0),selected.size());Vector b(a.rows());copy(z,b.row(0,z.rows()));
    for(UInt j=0;j<selected.size();j++)copy(R.column(selected[j]),a.slice(0,j,R.rows(),1));
    if(lambda&&!nuisanceOnly)for(UInt j=0;j<dyn.size();j++)a(R.rows()+j,dyn[j])=std::sqrt(lambda);
    Vector scaled(retained);
    if(selected.size())
    {if(lambda || nuisanceOnly){const Vector tau=QR_decomposition(a);QTransMult(a,tau,b);}
      Vector v(b.row(0,selected.size()));const Matrix r=orbitPocQr::upper(a,selected.size());triangularSolve(1.,r,v);for(UInt j=0;j<selected.size();j++)scaled(selected[j])=v(j);}
    Vector native(retained);for(UInt j=0;j<retained;j++)native(j)=scales(j)*scaled(j);
    return recover(native);
  }
  Double residual2(const Vector &x)const
  {Vector y(retained);for(UInt j=0;j<retained;j++)y(j)=x(j+localCount)/scales(j);return constant+quadsum(z-R*y);}
  void writeDiagnostics(const Vector &undamped,const Vector &step,Double lambda)const
  {
    Vector gradient=R.trans()*z;Double g=0;for(UInt i=0;i<gradient.rows();i++)g=std::max(g,std::fabs(gradient(i)));
    std::ofstream f(stem+".diagnostics.json");f<<std::setprecision(17);
    f<<"{\"schema\":\"orbit-poc-native-qr-v1\",\"rank_status\":\""<<diagnosis.status<<"\",\"rank\":"<<diagnosis.rank<<",\"retained_parameters\":"<<retained<<",\"local_parameters\":"<<localCount<<",\"source_rows\":"<<sourceRows<<",\"reduced_rows\":"<<reducedRows<<",\"rank_threshold\":"<<diagnosis.threshold<<",\"sigma_max\":"<<diagnosis.largest<<",\"sigma_min\":"<<diagnosis.smallest<<",\"rhs2\":"<<(sourceRhs2+groupRemovedEnergy)<<",\"projected_rhs2\":"<<sourceRhs2<<",\"constant_residual2\":"<<constant<<",\"residual2\":"<<residual2(step)<<",\"gradient_scaled\":"<<g/std::max(1.,std::sqrt(sourceRhs2+groupRemovedEnergy))<<",\"lambda\":"<<lambda<<"}\n";
    std::ofstream d(stem+".delta.tsv");d<<std::setprecision(17)<<"index\tundamped\tstep\n";for(UInt i=0;i<total;i++)d<<i<<'\t'<<undamped(i)<<'\t'<<step(i)<<'\n';
  }
  Matrix covariance(const std::vector<UInt>&indices)
  {
    if(orbitPocQr::env("ORBIT_POC_NUMERICS_NUISANCE_FLOOR_LIMITED")=="1")throw(Exception("No covariance for empirically floor-limited nuisance profile"));
    finish();if(diagnosis.status!="full")throw(Exception("No covariance for "+diagnosis.status+" QR rank"));
    const Matrix r=orbitPocQr::upper(R,retained);Matrix y(retained,indices.size());
    for(UInt j=0;j<indices.size();j++){if(indices[j]<localCount||indices[j]>=total)throw(Exception("Selected QR covariance must use retained parameters"));y(indices[j]-localCount,j)=scales(indices[j]-localCount);}
    triangularSolve(1.,r.trans(),y);return y.trans()*y;
  }
  void covariance(MatrixDistributed &out)
  {
    const Vector undamped=solve();const Vector profiled=solve(0,TRUE);
    writeDiagnostics(undamped,Vector(total),0.);writeProfileCost(profiled);
    // Only blocks containing dynamic parameters are requested by the orbit
    // exporter. Solve all columns in those blocks together; nuisance uncertainty
    // remains present in R. Never invert an orbit-only normal submatrix.
    std::vector<UInt> blocks,indices;
    for(UInt b=0;b<out.blockCount();b++)
    {Bool use=FALSE;for(UInt i=out.blockIndex(b);i<out.blockIndex(b)+out.blockSize(b);i++)use|=orbitPocQr::dynamic(names[i]);if(use){blocks.push_back(b);for(UInt i=0;i<out.blockSize(b);i++)indices.push_back(out.blockIndex(b)+i);}}
    Matrix c=covariance(indices);UInt ii=0;
    for(UInt bi:blocks){UInt jj=ii;for(UInt bj:blocks)if(bj>=bi){out.setBlock(bi,bj);out.N(bi,bj)=Matrix(c.slice(ii,jj,out.blockSize(bi),out.blockSize(bj)));jj+=out.blockSize(bj);}ii+=out.blockSize(bi);}
  }
};
inline OrbitPocRowQr &orbitPocRowQr(){static OrbitPocRowQr qr;return qr;}
#endif
