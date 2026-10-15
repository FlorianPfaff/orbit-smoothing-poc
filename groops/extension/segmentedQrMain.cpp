// SPDX-License-Identifier: GPL-3.0-or-later
// Standalone native adapter. Input coefficients and output steps use native units.
#include "segmentedQr.h"
#include <iomanip>
#include <iostream>
#include <sstream>
using namespace OrbitPoc::SegmentedQr;
namespace {
constexpr std::size_t bound=10000000;
template<class T>T read(){T value{};require(bool(std::cin>>value),"invalid_input","Truncated or malformed input");return value;}
std::size_t size(){auto n=read<unsigned long long>();require(n<=bound,"invalid_input","Input count exceeds protocol bound");return static_cast<std::size_t>(n);}
std::vector<Term> terms(){std::vector<Term> out;const auto count=size();out.reserve(count);for(std::size_t i=0;i<count;i++){auto id=size();out.push_back({id,read<double>()});}return out;}
std::string escaped(const std::string &v){std::string out="\"";for(char c:v){if(c=='"'||c=='\\')out+='\\';if(c=='\n')out+="\\n";else if(static_cast<unsigned char>(c)<32)out+='?';else out+=c;}return out+'"';}
template<class T>void vector(const std::vector<T> &values){std::cout<<'[';for(std::size_t i=0;i<values.size();i++){if(i)std::cout<<',';std::cout<<values[i];}std::cout<<']';}
void matrix(const Matrix &m){std::cout<<'[';for(std::size_t i=0;i<m.rows;i++){if(i)std::cout<<',';std::cout<<'[';for(std::size_t j=0;j<m.cols;j++){if(j)std::cout<<',';std::cout<<m(i,j);}std::cout<<']';}std::cout<<']';}
void rankJson(const Rank &r){std::cout<<"{\"rows\":"<<r.rows<<",\"columns\":"<<r.columns<<",\"status\":"<<escaped(r.status)<<",\"threshold\":"<<r.threshold<<",\"singular_values\":";vector(r.singularValues);std::cout<<'}';}
}
int main(){
  try {
    const auto protocol=read<std::string>();
    require(protocol=="SEGMENTED_QR_V1"||protocol=="SEGMENTED_QR_BLOCKS_V1","invalid_input","Unknown protocol");
    const auto nv=size(),ne=size(),na=size(),ng=size(),nq=size();Problem p;
    p.blockQueries=protocol=="SEGMENTED_QR_BLOCKS_V1";const auto nb=p.blockQueries?size():0;
    for(std::size_t i=0;i<nv;i++){auto id=size(),kind=size();require(kind<=1,"invalid_input","Unknown variable kind");double scale=read<double>();auto stage=size();p.variables.push_back({id,kind==1,scale,stage});}
    std::vector<std::pair<std::size_t,std::vector<Row>*>> ledgers={{ne,&p.equalities},{na,&p.stochastic}};
    for(auto countAndRows:ledgers)for(std::size_t i=0;i<countAndRows.first;i++){
      Row row;row.id=size();row.stage=size();row.rhs=read<double>();row.terms=terms();countAndRows.second->push_back(std::move(row));
    }
    for(std::size_t i=0;i<ng;i++){PivotGroup g;g.stage=size();auto d=size(),f=size();for(std::size_t j=0;j<d;j++)g.deterministic.push_back(size());for(std::size_t j=0;j<f;j++)g.stochastic.push_back(size());p.groups.push_back(std::move(g));}
    for(std::size_t i=0;i<nq;i++)p.queries.push_back(terms());
    for(std::size_t i=0;i<nb;i++)p.queryBlocks.push_back(size());
    std::string trailing;require(!(std::cin>>trailing),"invalid_input","Trailing input tokens");
    auto r=solve(p);std::cout<<std::setprecision(17)<<"{\"schema\":\"orbit-poc-segmented-qr-v1\",\"status\":\"complete\",\"step\":";vector(r.step);
    std::cout<<",\"covariance\":";matrix(r.covariance);
    std::cout<<",\"covariance_blocks\":[";std::size_t queryStart=0;
    for(std::size_t k=0;k<r.covarianceBlocks.size();k++) {
      if(k)std::cout<<',';
      const auto &block=r.covarianceBlocks[k];
      std::cout<<"{\"query_start\":"<<queryStart<<",\"query_count\":"<<block.rows<<",\"covariance\":";matrix(block);std::cout<<'}';queryStart+=block.rows;
    }
    std::cout<<"],\"max_covariance_query_block\":"<<r.maxCovarianceQueryBlock
             <<",\"covariance_scratch_shape\":["<<p.variables.size()<<','<<r.maxCovarianceQueryBlock<<']';
    std::cout<<",\"residual_energy\":"<<r.residualEnergy<<",\"stochastic_objective\":"<<0.5*r.residualEnergy<<",\"orthogonal_residual_energy\":"<<r.orthogonalResidualEnergy<<",\"input_constant_energy\":"<<r.inputConstantEnergy<<",\"equality_max_residual\":"<<r.equalityMaxResidual<<",\"equality_max_backward_error\":"<<r.equalityMaxBackwardError<<",\"max_front_rows\":"<<r.maxFrontRows<<",\"max_front_columns\":"<<r.maxFrontColumns;
    std::cout<<",\"step_coordinate_system\":\"native\",\"conditional_coordinate_system\":\"scaled\"";
    std::cout<<",\"rank_scope\":\"local_front_checks;original_chart_certificate_external\",\"column_scales\":[";
    for(std::size_t i=0;i<p.variables.size();i++){if(i)std::cout<<',';std::cout<<p.variables[i].scale;}
    std::cout<<"],\"original_columns\":[";bool first=true;for(const auto &v:p.variables)if(v.original){if(!first)std::cout<<',';std::cout<<v.id;first=false;}
    std::cout<<"],\"conditionals\":[";
    for(std::size_t k=0;k<r.conditionals.size();k++){
      const auto &c=r.conditionals[k];if(k)std::cout<<',';std::cout<<"{\"kind\":"<<escaped(c.deterministic?"deterministic":"stochastic")<<",\"stage\":"<<c.stage<<",\"pivot_ids\":";vector(c.pivots);
      std::cout<<",\"separator_ids\":";vector(c.separators);std::cout<<",\"row_ids\":";vector(c.origins);std::cout<<",\"R\":";matrix(c.R);std::cout<<",\"S\":";matrix(c.S);std::cout<<",\"rhs\":";vector(c.rhs);std::cout<<",\"rank\":";rankJson(c.rank);std::cout<<'}';
    }
    std::cout<<"],\"row_provenance\":[";
    for(std::size_t k=0;k<r.rowProvenance.size();k++) {
      const auto &v=r.rowProvenance[k];if(k)std::cout<<',';
      std::cout<<"{\"ledger\":"<<escaped(v.equality?"equality":"stochastic")<<",\"stage\":"<<v.stage<<",\"row_ids\":";vector(v.rows);
      std::cout<<",\"source_row_ids\":";vector(v.sources);std::cout<<",\"constant_energy\":"<<v.constantEnergy<<",\"compression_residual_energy\":"<<v.compressionResidualEnergy<<'}';
    }
    std::cout<<"]}\n";return 0;
  } catch(const Error &error){std::cout<<"{\"schema\":\"orbit-poc-segmented-qr-v1\",\"status\":\"failed\",\"reason\":"<<escaped(error.code)<<",\"message\":"<<escaped(error.what())<<"}\n";return 1;}
    catch(const std::exception &error){std::cout<<"{\"schema\":\"orbit-poc-segmented-qr-v1\",\"status\":\"failed\",\"reason\":\"runtime_failure\",\"message\":"<<escaped(error.what())<<"}\n";return 1;}
}
