// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_SEGMENTED_QR_H
#define ORBIT_POC_SEGMENTED_QR_H

// Equality and stochastic rows remain separate throughout elimination. This
// kernel never forms normal equations or replaces an equality with a weight.
// LAPACK uses its ordinary LP64 Fortran interface, as does the native build.
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <limits>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

extern "C" {
void dgeqrf_(const int*,const int*,double*,const int*,double*,double*,const int*,int*);
void dormqr_(const char*,const char*,const int*,const int*,const int*,const double*,const int*,const double*,double*,const int*,double*,const int*,int*);
void dgesvd_(const char*,const char*,const int*,const int*,double*,const int*,double*,double*,const int*,double*,const int*,double*,const int*,int*);
void dtrtrs_(const char*,const char*,const char*,const int*,const int*,const double*,const int*,double*,const int*,int*);
}

namespace OrbitPoc { namespace SegmentedQr {
using Id=std::size_t;
struct Error:std::runtime_error {
  std::string code;
  Error(const std::string &code_,const std::string &message):std::runtime_error(message),code(code_){}
};
inline void require(bool ok,const std::string &code,const std::string &message)
{if(!ok)throw Error(code,message);}
inline void finite(double x)
{require(std::isfinite(x),"nonfinite_input","Nonfinite coefficient or result");}
inline double product(double a,double b) {
  const double value=a*b;finite(value);
  require(value!=0.||a==0.||b==0.,"arithmetic_underflow","A nonzero coordinate coefficient underflowed");return value;
}
inline double quotient(double a,double b) {
  const double value=a/b;finite(value);
  require(value!=0.||a==0.,"arithmetic_underflow","A nonzero equality coefficient underflowed");return value;
}
inline int lapackSize(std::size_t n)
{require(n<=static_cast<std::size_t>(std::numeric_limits<int>::max()),"size_overflow","LAPACK integer overflow");return static_cast<int>(n);}
struct Matrix {
  std::size_t rows=0,cols=0;
  std::vector<double> data; // column major
  Matrix()=default;
  Matrix(std::size_t r,std::size_t c):rows(r),cols(c) {
    require(!c||r<=std::numeric_limits<std::size_t>::max()/c,"size_overflow","Matrix allocation overflow");
    data.resize(r*c,0.);
  }
  double &operator()(std::size_t i,std::size_t j){return data.at(i+rows*j);}
  double operator()(std::size_t i,std::size_t j)const{return data.at(i+rows*j);}
};
struct Term {Id id;double coefficient;};
struct Variable {Id id;bool original;double scale;std::size_t lastUseStage;};
struct Row {
  Id id=0;std::size_t stage=0;double rhs=0.;std::vector<Term> terms;
  std::vector<Id> origins; // populated by the kernel; input must leave empty
};
struct PivotGroup {std::size_t stage=0;std::vector<Id> deterministic,stochastic;};
struct Problem {
  std::vector<Variable> variables;
  std::vector<Row> equalities,stochastic;
  std::vector<PivotGroup> groups;
  std::vector<std::vector<Term>> queries;
  bool blockQueries=false;
  std::vector<std::size_t> queryBlocks;
};
struct Rank {
  std::size_t rows=0,columns=0;
  std::vector<double> singularValues;
  double threshold=0.;
  std::string status="full";
};
struct Conditional {
  bool deterministic=false;
  std::size_t stage=0;
  std::vector<Id> pivots,separators,origins;
  Matrix R,S;
  std::vector<double> rhs;
  Rank rank;
};
struct RowProvenance {
  bool equality=false;
  std::size_t stage=0;
  std::vector<Id> rows,sources;
  double constantEnergy=0.,compressionResidualEnergy=0.;
};
struct Result {
  std::vector<double> step;
  Matrix covariance;
  std::vector<Matrix> covarianceBlocks;
  std::size_t maxCovarianceQueryBlock=0;
  std::vector<Conditional> conditionals;
  std::vector<RowProvenance> rowProvenance;
  double residualEnergy=0.,orthogonalResidualEnergy=0.,inputConstantEnergy=0.;
  double equalityMaxResidual=0.,equalityMaxBackwardError=0.;
  std::size_t maxFrontRows=0,maxFrontColumns=0;
};

inline Rank rank(const Matrix &input) {
  Rank out;out.rows=input.rows;out.columns=input.cols;
  if(!input.cols)return out;
  if(input.rows<input.cols){out.status="deficient";return out;}
  Matrix a=input;
  const int m=lapackSize(a.rows),n=lapackSize(a.cols),lda=std::max(1,m),one=1;
  out.singularValues.resize(n);
  double dummy=0.,workspace=0.;int info=0,lwork=-1;const char job='N';
  dgesvd_(&job,&job,&m,&n,a.data.data(),&lda,out.singularValues.data(),&dummy,&one,&dummy,&one,&workspace,&lwork,&info);
  require(!info,"lapack_failure","SVD workspace query failed");
  require(std::isfinite(workspace)&&workspace>=1&&workspace<std::numeric_limits<int>::max(),"size_overflow","Invalid SVD workspace");
  lwork=static_cast<int>(std::ceil(workspace));std::vector<double> work(lwork);
  dgesvd_(&job,&job,&m,&n,a.data.data(),&lda,out.singularValues.data(),&dummy,&one,&dummy,&one,work.data(),&lwork,&info);
  require(!info,"lapack_failure","SVD failed to converge");
  for(double value:out.singularValues)finite(value);
  out.threshold=std::numeric_limits<double>::epsilon()*std::max(input.rows,input.cols)*out.singularValues.front();
  if(out.singularValues.back()<=out.threshold)out.status="deficient";
  else if(out.singularValues.back()<=10*out.threshold)out.status="unresolved";
  return out;
}
inline void fullRank(const Rank &r,bool equality) {
  require(r.status=="full",equality?"constraint_rank_inconsistent":"stochastic_front_rank_"+r.status,
          std::string(equality?"Equality":"Stochastic")+" pivot block is "+r.status+"; no directions were removed");
}
struct Qr {Matrix triangular,transformed;Rank rank;};
inline Qr eliminate(const Matrix &leading,const Matrix &rest,bool equality,bool checkRank=true) {
  require(leading.rows==rest.rows,"shape_error","QR row mismatch");
  Qr out;
  if(checkRank){out.rank=rank(leading);fullRank(out.rank,equality);}
  require(leading.rows>=leading.cols,"shape_error","Householder front has fewer rows than pivot columns");
  out.triangular=leading;out.transformed=rest;
  if(!leading.cols)return out;
  const int m=lapackSize(leading.rows),n=lapackSize(leading.cols),lda=std::max(1,m);
  std::vector<double> tau(n);double workspace=0.;int info=0,lwork=-1;
  dgeqrf_(&m,&n,out.triangular.data.data(),&lda,tau.data(),&workspace,&lwork,&info);
  require(!info,"lapack_failure","Householder QR workspace query failed");
  require(std::isfinite(workspace)&&workspace>=1&&workspace<std::numeric_limits<int>::max(),"size_overflow","Invalid QR workspace");
  lwork=static_cast<int>(std::ceil(workspace));std::vector<double> work(lwork);
  dgeqrf_(&m,&n,out.triangular.data.data(),&lda,tau.data(),work.data(),&lwork,&info);
  require(!info,"lapack_failure","Householder QR failed");
  if(rest.cols) {
    const char side='L',trans='T';const int nrhs=lapackSize(rest.cols);lwork=-1;
    dormqr_(&side,&trans,&m,&nrhs,&n,out.triangular.data.data(),&lda,tau.data(),out.transformed.data.data(),&lda,&workspace,&lwork,&info);
    require(!info,"lapack_failure","Householder application workspace query failed");
    require(std::isfinite(workspace)&&workspace>=1&&workspace<std::numeric_limits<int>::max(),"size_overflow","Invalid Householder workspace");
    lwork=static_cast<int>(std::ceil(workspace));work.resize(lwork);
    dormqr_(&side,&trans,&m,&nrhs,&n,out.triangular.data.data(),&lda,tau.data(),out.transformed.data.data(),&lda,work.data(),&lwork,&info);
    require(!info,"lapack_failure","Householder application failed");
  }
  for(double value:out.transformed.data)finite(value);
  return out;
}
inline Matrix triangularSolve(const Matrix &R,Matrix rhs,bool transpose=false) {
  require(R.rows==R.cols&&rhs.rows==R.rows,"shape_error","Triangular solve shape mismatch");
  if(!R.rows||!rhs.cols)return rhs;
  const int n=lapackSize(R.rows),nrhs=lapackSize(rhs.cols),lda=std::max(1,n);
  const char uplo='U',trans=transpose?'T':'N',diag='N';int info=0;
  dtrtrs_(&uplo,&trans,&diag,&n,&nrhs,R.data.data(),&lda,rhs.data.data(),&lda,&info);
  require(!info,"triangular_solve_failure","Singular or invalid conditional");
  for(double value:rhs.data)finite(value);
  return rhs;
}
inline Conditional conditional(const Qr &qr,const std::vector<Id> &pivots,
                               const std::vector<Id> &separator,const std::vector<Id> &origins,
                               std::size_t stage,bool deterministic) {
  Conditional c;c.deterministic=deterministic;c.stage=stage;c.pivots=pivots;c.separators=separator;c.origins=origins;c.rank=qr.rank;
  const std::size_t p=pivots.size();c.R=Matrix(p,p);c.S=Matrix(p,separator.size());c.rhs.resize(p);
  for(std::size_t i=0;i<p;i++) {
    for(std::size_t j=i;j<p;j++)c.R(i,j)=qr.triangular(i,j);
    for(std::size_t j=0;j<separator.size();j++)c.S(i,j)=qr.transformed(i,j);
    c.rhs[i]=qr.transformed(i,separator.size());
  }
  return c;
}
inline std::vector<Id> origins(const std::vector<Row> &a,const std::vector<Row> &b={}) {
  std::set<Id> ids;
  for(const auto *rows:{&a,&b})for(const auto &row:*rows)for(Id id:row.origins)ids.insert(id);
  return {ids.begin(),ids.end()};
}
inline Matrix rowsMatrix(const std::vector<Row> &rows,const std::vector<Id> &columns) {
  Matrix result(rows.size(),columns.size()+1);std::map<Id,std::size_t> index;
  for(std::size_t j=0;j<columns.size();j++)index[columns[j]]=j;
  for(std::size_t i=0;i<rows.size();i++) {
    for(const auto &term:rows[i].terms) {
      auto it=index.find(term.id);require(it!=index.end(),"internal_error","Missing front column");
      result(i,it->second)=term.coefficient;
    }
    result(i,columns.size())=rows[i].rhs;
  }
  return result;
}
inline Matrix slice(const Matrix &matrix,std::size_t row,std::size_t rows,std::size_t column,std::size_t columns) {
  require(row+rows<=matrix.rows&&column+columns<=matrix.cols,"shape_error","Matrix slice outside bounds");
  Matrix out(rows,columns);
  for(std::size_t j=0;j<columns;j++)for(std::size_t i=0;i<rows;i++)out(i,j)=matrix(row+i,column+j);
  return out;
}
inline std::vector<Row> takeRows(std::vector<Row> &rows,const std::set<Id> &pivots) {
  std::vector<Row> selected,remaining;
  for(auto &row:rows) {
    bool touches=false;for(const auto &term:row.terms)if(term.coefficient!=0.&&pivots.count(term.id)){touches=true;break;}
    (touches?selected:remaining).push_back(std::move(row));
  }
  rows=std::move(remaining);return selected;
}
inline void appendRows(std::vector<Row> &destination,const Matrix &matrix,const std::vector<Id> &columns,
                       const std::vector<Id> &originIds,std::size_t stage,Id &nextId,
                       bool equality,long double &energy,std::vector<RowProvenance> &provenance) {
  require(matrix.cols==columns.size()+1,"shape_error","Reduced row shape mismatch");
  RowProvenance record;record.equality=equality;record.stage=stage;record.sources=originIds;
  long double constantEnergy=0.;
  for(std::size_t i=0;i<matrix.rows;i++) {
    Row row;row.id=nextId++;row.stage=stage;row.rhs=matrix(i,columns.size());row.origins={row.id};record.rows.push_back(row.id);
    for(std::size_t j=0;j<columns.size();j++) {
      finite(matrix(i,j));if(matrix(i,j)!=0.)row.terms.push_back({columns[j],matrix(i,j)});
    }
    finite(row.rhs);
    if(row.terms.empty()) {
      // A redundant equality changes structural rank even if its RHS is zero.
      require(!equality,"constraint_rank_inconsistent","Equality ledger contains an unexplained zero row");
      constantEnergy+=static_cast<long double>(row.rhs)*row.rhs;
    } else destination.push_back(std::move(row));
  }
  energy+=constantEnergy;record.constantEnergy=static_cast<double>(constantEnergy);
  if(!record.rows.empty())provenance.push_back(std::move(record));
}
// Compress a separator factor without deciding its rank. A separator may be
// rank deficient until later observations/priors arrive. Keep all n triangular
// rows (including small diagonals); only structurally zero lower-Q rows become
// residual energy. This avoids forwarding a growing stack of past observations.
inline Matrix compressStochastic(const Matrix &matrix,long double &energy) {
  require(matrix.cols>0,"shape_error","Missing stochastic RHS");
  const std::size_t n=matrix.cols-1,m=matrix.rows;
  if(m<=n||!n)return matrix;
  auto q=eliminate(slice(matrix,0,m,0,n),slice(matrix,0,m,n,1),false,false);
  Matrix result(n,n+1);
  for(std::size_t i=0;i<n;i++) {
    for(std::size_t j=i;j<n;j++)result(i,j)=q.triangular(i,j);
    result(i,n)=q.transformed(i,0);
  }
  for(std::size_t i=n;i<m;i++)energy+=static_cast<long double>(q.transformed(i,0))*q.transformed(i,0);
  return result;
}
inline void appendStochasticRows(std::vector<Row> &destination,const Matrix &matrix,
                                 const std::vector<Id> &columns,const std::vector<Id> &originIds,
                                 std::size_t stage,Id &nextId,long double &energy,
                                 std::vector<RowProvenance> &provenance) {
  const long double before=energy;
  const auto compressed=compressStochastic(matrix,energy);
  const double compressionEnergy=static_cast<double>(energy-before);
  const auto count=provenance.size();
  appendRows(destination,compressed,columns,originIds,stage,nextId,false,energy,provenance);
  if(provenance.size()>count) {
    provenance.back().compressionResidualEnergy=compressionEnergy;
    provenance.back().constantEnergy+=compressionEnergy;
  }
}
inline void validateTerms(const std::vector<Term> &terms,std::size_t n) {
  std::set<Id> ids;
  for(const auto &term:terms){require(term.id<n&&ids.insert(term.id).second,"invalid_columns","Out-of-range or duplicate column ID");finite(term.coefficient);}
}
inline void validate(const Problem &p) {
  const std::size_t n=p.variables.size();require(n>0,"invalid_problem","Empty variable registry");
  std::size_t auxiliary=0;
  for(std::size_t i=0;i<n;i++) {
    const auto &v=p.variables[i];require(v.id==i,"invalid_columns","Variable IDs must be contiguous and ordered");
    finite(v.scale);require(v.scale>0.,"invalid_scale","Column scales must be positive");auxiliary+=!v.original;
  }
  require(p.equalities.size()==auxiliary,"constraint_rank_inconsistent","Equality count must equal auxiliary dimension of the original chart");
  std::set<Id> rowIds,pivotIds;std::size_t previousStage=0,deterministic=0;
  for(const auto *ledger:{&p.equalities,&p.stochastic})for(const auto &row:*ledger) {
    require(row.origins.empty(),"invalid_provenance","Input provenance is the unique input row ID");
    require(rowIds.insert(row.id).second,"invalid_rows","Row IDs must be unique across both ledgers");finite(row.rhs);validateTerms(row.terms,n);
    for(const auto &term:row.terms)if(term.coefficient!=0.)
      require(row.stage<=p.variables[term.id].lastUseStage,"chronology_violation","Factor exceeds variable's declared last-use stage");
  }
  for(const auto &group:p.groups) {
    require(!group.deterministic.empty()||!group.stochastic.empty(),"invalid_schedule","Empty pivot group");
    require(group.stage>=previousStage,"chronology_violation","Elimination stages must be chronological");previousStage=group.stage;
    deterministic+=group.deterministic.size();
    for(const auto *ids:{&group.deterministic,&group.stochastic})for(Id id:*ids) {
      require(id<n&&pivotIds.insert(id).second,"invalid_schedule","Invalid or repeated pivot ID");
      require(group.stage>=p.variables[id].lastUseStage,"chronology_violation","Variable eliminated before its final native stencil use");
    }
  }
  require(pivotIds.size()==n,"invalid_schedule","Every variable must be eliminated exactly once");
  require(deterministic==p.equalities.size(),"constraint_rank_inconsistent","Deterministic pivot count must equal equality rank");
  for(const auto &query:p.queries)validateTerms(query,n);
  if(p.blockQueries) {
    std::size_t total=0;
    for(auto count:p.queryBlocks) {
      require(count>0&&count<=p.queries.size()-total,"invalid_query_blocks","Query blocks must be positive and within the query ledger");total+=count;
    }
    require(total==p.queries.size(),"invalid_query_blocks","Query blocks must cover every query row exactly once");
  } else require(p.queryBlocks.empty(),"invalid_query_blocks","Flat query mode cannot contain block sizes");
}

inline Matrix selectedCovariance(const std::vector<Variable> &variables,
                                 const std::vector<Conditional> &conditionals,
                                 const std::vector<std::vector<Term>> &queries,
                                 std::size_t first,std::size_t count) {
  require(first<=queries.size()&&count<=queries.size()-first,"invalid_query_blocks","Selected query slice outside ledger");
  // Only selected query covariance is formed. Deterministic conditionals add
  // no innovation variance; every stochastic conditional contributes unit noise.
  const std::size_t n=variables.size();
  Matrix adjoint(n,count),covariance(count,count);
  for(std::size_t q=0;q<count;q++)for(const auto &term:queries[first+q])adjoint(term.id,q)=product(term.coefficient,variables[term.id].scale);
  for(const auto &c:conditionals) {
    Matrix z(c.pivots.size(),count);
    for(std::size_t i=0;i<c.pivots.size();i++)for(std::size_t q=0;q<count;q++)z(i,q)=adjoint(c.pivots[i],q);
    z=triangularSolve(c.R,z,true);
    if(!c.deterministic)for(std::size_t i=0;i<count;i++)for(std::size_t j=0;j<=i;j++) {
      long double value=covariance(i,j);for(std::size_t k=0;k<c.pivots.size();k++)value+=static_cast<long double>(z(k,i))*z(k,j);
      covariance(i,j)=covariance(j,i)=static_cast<double>(value);finite(covariance(i,j));
    }
    for(std::size_t j=0;j<c.separators.size();j++)for(std::size_t q=0;q<count;q++) {
      long double value=adjoint(c.separators[j],q);for(std::size_t i=0;i<c.pivots.size();i++)value-=static_cast<long double>(c.S(i,j))*z(i,q);
      adjoint(c.separators[j],q)=static_cast<double>(value);finite(adjoint(c.separators[j],q));
    }
    for(Id id:c.pivots)for(std::size_t q=0;q<count;q++)adjoint(id,q)=0.;
  }
  return covariance;
}

// Column scales are numerical coordinates only: x_native = scale*x_scaled.
// Original/auxiliary kind does not determine pivot role. The caller supplies a
// structurally valid schedule and the independent original-chart rank certificate.
inline Result solve(const Problem &p) {
  validate(p);Result out;const std::size_t n=p.variables.size();
  auto E=p.equalities,A=p.stochastic;Id nextId=0;long double removedEnergy=0.;
  for(auto *ledger:{&E,&A})for(auto &row:*ledger) {
    require(row.id<std::numeric_limits<Id>::max()/2,"invalid_rows","Row ID exceeds supported range");nextId=std::max(nextId,row.id+1);row.origins={row.id};
    for(auto &term:row.terms){term.coefficient=product(term.coefficient,p.variables[term.id].scale);}
    row.terms.erase(std::remove_if(row.terms.begin(),row.terms.end(),[](const Term &v){return v.coefficient==0.;}),row.terms.end());
    if(ledger==&E) {
      double norm=0.;for(const auto &term:row.terms)norm=std::max(norm,std::abs(term.coefficient));
      require(norm>0.,"constraint_rank_inconsistent","Zero equality row");
      // Homogeneous row scaling is exact equality preconditioning, never noise.
      for(auto &term:row.terms)term.coefficient=quotient(term.coefficient,norm);
      row.rhs=quotient(row.rhs,norm);
    }
  }
  // Constant stochastic rows contain residual energy even if no front sees them.
  A.erase(std::remove_if(A.begin(),A.end(),[&](const Row &row){if(!row.terms.empty())return false;removedEnergy+=static_cast<long double>(row.rhs)*row.rhs;return true;}),A.end());
  out.inputConstantEnergy=static_cast<double>(removedEnergy);
  for(const auto &group:p.groups) {
    std::set<Id> pivots(group.deterministic.begin(),group.deterministic.end());pivots.insert(group.stochastic.begin(),group.stochastic.end());
    auto e=takeRows(E,pivots),a=takeRows(A,pivots);std::set<Id> separatorSet;
    for(const auto *rows:{&e,&a})for(const auto &row:*rows)for(const auto &term:row.terms)if(!pivots.count(term.id))separatorSet.insert(term.id);
    std::vector<Id> separator(separatorSet.begin(),separatorSet.end()),rest=group.stochastic;
    rest.insert(rest.end(),separator.begin(),separator.end());
    std::vector<Id> columns=group.deterministic;columns.insert(columns.end(),rest.begin(),rest.end());
    Matrix em=rowsMatrix(e,columns),am=rowsMatrix(a,columns);
    out.maxFrontRows=std::max(out.maxFrontRows,e.size()+a.size());out.maxFrontColumns=std::max(out.maxFrontColumns,columns.size());
    const std::size_t d=group.deterministic.size(),f=group.stochastic.size();
    Matrix reducedA=am,reducedE=em;
    auto allOrigins=origins(e,a);
    if(d) {
      auto q=eliminate(slice(em,0,em.rows,0,d),slice(em,0,em.rows,d,rest.size()+1),true);
      auto c=conditional(q,group.deterministic,rest,origins(e),group.stage,true);
      Matrix target(d,rest.size()+1);
      for(std::size_t i=0;i<d;i++){for(std::size_t j=0;j<rest.size();j++)target(i,j)=c.S(i,j);target(i,rest.size())=c.rhs[i];}
      target=triangularSolve(c.R,target);
      reducedA=Matrix(am.rows,rest.size()+1);
      for(std::size_t i=0;i<am.rows;i++)for(std::size_t j=0;j<rest.size()+1;j++) {
        long double value=am(i,d+j);
        for(std::size_t k=0;k<d;k++)value-=static_cast<long double>(am(i,k))*target(k,j);
        reducedA(i,j)=static_cast<double>(value);finite(reducedA(i,j));
      }
      reducedE=slice(q.transformed,d,em.rows-d,0,rest.size()+1);
      out.conditionals.push_back(std::move(c));
    }
    // An exact row touching a stochastic pivot cannot be turned into noise.
    for(std::size_t i=0;i<reducedE.rows;i++)for(std::size_t j=0;j<f;j++)
      require(reducedE(i,j)==0.,"unsupported_pivot_schedule","Remaining exact constraint touches a stochastic pivot; retain or reorder it");
    appendRows(E,slice(reducedE,0,reducedE.rows,f,separator.size()+1),separator,origins(e),group.stage,nextId,true,removedEnergy,out.rowProvenance);
    if(f) {
      auto q=eliminate(slice(reducedA,0,reducedA.rows,0,f),slice(reducedA,0,reducedA.rows,f,separator.size()+1),false);
      out.conditionals.push_back(conditional(q,group.stochastic,separator,allOrigins,group.stage,false));
      appendStochasticRows(A,slice(q.transformed,f,reducedA.rows-f,0,separator.size()+1),separator,allOrigins,group.stage,nextId,removedEnergy,out.rowProvenance);
    } else appendStochasticRows(A,reducedA,separator,allOrigins,group.stage,nextId,removedEnergy,out.rowProvenance);
  }
  require(E.empty(),"constraint_rank_inconsistent","Uneliminated equality rows");
  require(A.empty(),"invalid_schedule","Uneliminated stochastic rows");
  std::vector<double> scaled(n,0.);
  for(auto it=out.conditionals.rbegin();it!=out.conditionals.rend();++it) {
    const auto &c=*it;Matrix rhs(c.pivots.size(),1);
    for(std::size_t i=0;i<c.pivots.size();i++) {
      long double value=c.rhs[i];for(std::size_t j=0;j<c.separators.size();j++)value-=static_cast<long double>(c.S(i,j))*scaled[c.separators[j]];
      rhs(i,0)=static_cast<double>(value);
    }
    rhs=triangularSolve(c.R,rhs);for(std::size_t i=0;i<c.pivots.size();i++)scaled[c.pivots[i]]=rhs(i,0);
  }
  out.step.resize(n);for(std::size_t i=0;i<n;i++){out.step[i]=product(scaled[i],p.variables[i].scale);}
  if(p.blockQueries) {
    std::size_t first=0;
    for(auto count:p.queryBlocks) {
      out.covarianceBlocks.push_back(selectedCovariance(p.variables,out.conditionals,p.queries,first,count));
      out.maxCovarianceQueryBlock=std::max(out.maxCovarianceQueryBlock,count);first+=count;
    }
  } else {
    out.covariance=selectedCovariance(p.variables,out.conditionals,p.queries,0,p.queries.size());
    out.maxCovarianceQueryBlock=p.queries.size();
  }
  long double directEnergy=0.;
  for(const auto &row:p.stochastic) {
    long double residual=row.rhs;for(const auto &term:row.terms)residual-=static_cast<long double>(term.coefficient)*out.step[term.id];
    directEnergy+=residual*residual;
  }
  for(const auto &row:p.equalities) {
    long double residual=row.rhs,scale=std::abs(static_cast<long double>(row.rhs));
    for(const auto &term:row.terms){const long double value=static_cast<long double>(term.coefficient)*out.step[term.id];residual-=value;scale+=std::abs(value);}
    out.equalityMaxResidual=std::max(out.equalityMaxResidual,static_cast<double>(std::abs(residual)));
    const double backward=scale?static_cast<double>(std::abs(residual)/scale):0.;
    out.equalityMaxBackwardError=std::max(out.equalityMaxBackwardError,backward);
  }
  require(out.equalityMaxBackwardError<=64.*std::numeric_limits<double>::epsilon()*std::max<std::size_t>(1,out.maxFrontColumns),
          "constraint_residual_inconsistent","Recovered solution violates exact constraints beyond arithmetic backward error");
  out.residualEnergy=static_cast<double>(directEnergy);out.orthogonalResidualEnergy=static_cast<double>(removedEnergy);finite(out.residualEnergy);finite(out.orthogonalResidualEnergy);
  return out;
}
}} // namespace OrbitPoc::SegmentedQr
#endif
