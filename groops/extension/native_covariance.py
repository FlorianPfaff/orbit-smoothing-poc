"""Patch native LEO output with full-inverse marginal Cartesian covariance.

Only gnssParametrizationLeoDynamicOrbits.h/.cpp are changed. Registration and the
global covariance processing step are deliberately owned by the native build.
The existing computeCovarianceMatrix step must run after the final parameter
update and before writeResults. Its selected inverse must contain every required
orbit-parameter block. Unsupported MPI and missing inverse blocks fail explicitly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

MARKER = "ORBIT_COMPARISON_MARGINAL_COVARIANCE_V1"
PARAMETER_MARKER = "ORBIT_COMPARISON_PARAMETER_COVARIANCE_V1"
OBSERVATION_MARKER = "ORBIT_COMPARISON_OBSERVATION_COVARIANCE_V1"
SOURCE_SUBDIR = Path("source/gnss/gnssParametrization")


def _replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Expected exactly one upstream anchor, found {text.count(old)}: {old[:100]!r}")
    return text.replace(old, new, 1)


def _parameter_covariance_patch(header, cpp):
    """Upgrade V1 state-only exports without changing their numerical result."""
    if PARAMETER_MARKER in header or PARAMETER_MARKER in cpp:
        if PARAMETER_MARKER not in header or PARAMETER_MARKER not in cpp:
            raise ValueError("Partial native parameter-covariance patch")
        return header, cpp
    header = _replace_once(header, "    std::vector<Matrix>            stateCovariance; // " + MARKER,
        "    std::vector<Matrix>            stateCovariance; // " + MARKER +
        "\n    Matrix                         parameterCovariance; // " + PARAMETER_MARKER)
    header = _replace_once(header, "fileNameVariational, fileNameCovariance;",
                           "fileNameVariational, fileNameCovariance, fileNameParameterCovariance;")
    config = '    readConfig(config, "outputfileCovariance",        fileNameCovariance,          Config::OPTIONAL, "",     "MJD and 36 row-major marginalized Cartesian covariance entries in SI; serial only");'
    cpp = _replace_once(cpp, config, config + '\n    readConfig(config, "outputfileParameterCovariance", fileNameParameterCovariance, Config::OPTIONAL, "", "Full nuisance-marginalized dynamic parameter covariance in native parameter order");')
    cpp = _replace_once(cpp, "if(!fileNameCovariance.empty() && Parallel::size(comm) != 1)",
                        "if((!fileNameCovariance.empty() || !fileNameParameterCovariance.empty()) && Parallel::size(comm) != 1)")
    cpp = _replace_once(cpp, "if(fileNameCovariance.empty() || !isEnabled(normalEquationInfo, name))",
                        "if((fileNameCovariance.empty() && fileNameParameterCovariance.empty()) || !isEnabled(normalEquationInfo, name))")
    cpp = _replace_once(cpp, "        para->stateCovariance.clear(); // invalidate covariance after any parameter update",
                        "        para->stateCovariance.clear(); // invalidate covariance after any parameter update\n        para->parameterCovariance = Matrix();")
    cpp = _replace_once(cpp, "        para->stateCovariance.clear();\n        for(UInt arcNo=0;",
                        "        para->parameterCovariance = parameterCovariance; // " + PARAMETER_MARKER +
                        "\n        if(fileNameCovariance.empty()) continue;\n        para->stateCovariance.clear();\n        for(UInt arcNo=0;")
    write = r'''
    // ORBIT_COMPARISON_PARAMETER_COVARIANCE_V1: exact native parameter ordering.
    if(!fileNameParameterCovariance.empty())
    {
      VariableList fileNameVariableList;
      for(auto para : parameters)
        if(para && para->index && para->recv->isMyRank())
        {
          if(para->parameterCovariance.rows() != para->x.rows())
            throw(Exception("Run computeCovarianceMatrix after final parameter update before parameter covariance output"));
          fileNameVariableList.setVariable("station", para->recv->name());
          writeFileMatrix(fileNameParameterCovariance(fileNameVariableList).appendBaseName(suffix), para->parameterCovariance);
        }
    }

'''
    cpp = _replace_once(cpp, "    if(!fileNameParameter.empty())", write + "    if(!fileNameParameter.empty())")
    return header, cpp


def _observation_covariance_patch(header, cpp):
    """Propagate full-inverse designs at nominal GNSS epochs, including gaps.

    UTC dynamics knots and GPS measurement epochs need not coincide. Interpolate
    the variational designs before applying covariance; never interpolate the
    already propagated marginal blocks or borrow a neighboring epoch.
    """
    if OBSERVATION_MARKER in header or OBSERVATION_MARKER in cpp:
        if OBSERVATION_MARKER not in header or OBSERVATION_MARKER not in cpp:
            raise ValueError("Partial native observation covariance patch")
        return header, cpp
    header = _replace_once(header, "fileNameCovariance, fileNameParameterCovariance;",
        "fileNameCovariance, fileNameParameterCovariance, fileNameCovarianceObservationEpochs; // " + OBSERVATION_MARKER)
    anchor = '    readConfig(config, "outputfileParameterCovariance", fileNameParameterCovariance, Config::OPTIONAL, "", "Full nuisance-marginalized dynamic parameter covariance in native parameter order");'
    cpp = _replace_once(cpp, anchor, anchor + '\n    readConfig(config, "outputfileCovarianceObservationEpochs", fileNameCovarianceObservationEpochs, Config::OPTIONAL, "", "MJD and 36 marginalized Cartesian SI covariance entries at every nominal GNSS epoch, including masked epochs");')
    cpp = _replace_once(cpp,
        "if((!fileNameCovariance.empty() || !fileNameParameterCovariance.empty()) && Parallel::size(comm) != 1)",
        "if((!fileNameCovariance.empty() || !fileNameParameterCovariance.empty() || !fileNameCovarianceObservationEpochs.empty()) && Parallel::size(comm) != 1)")
    cpp = _replace_once(cpp,
        "if((fileNameCovariance.empty() && fileNameParameterCovariance.empty()) || !isEnabled(normalEquationInfo, name))",
        "if((fileNameCovariance.empty() && fileNameParameterCovariance.empty() && fileNameCovarianceObservationEpochs.empty()) || !isEnabled(normalEquationInfo, name))")
    write = r'''
    // ORBIT_COMPARISON_OBSERVATION_COVARIANCE_V1: evaluate designs, then J P J^T.
    if(!fileNameCovarianceObservationEpochs.empty())
    {
      VariableList fileNameVariableList;
      for(auto para : parameters)
        if(para && para->index && para->recv->isMyRank())
        {
          const UInt count = para->x.rows();
          if(para->parameterCovariance.rows() != count)
            throw(Exception("Run computeCovarianceMatrix after final update before observation covariance output"));
          Matrix output(gnss->times.size(), 37);
          std::vector<Bool> covered(gnss->times.size(), FALSE);
          for(UInt arcNo=0; arcNo<para->times.size(); arcNo++)
          {
            std::vector<Time> query;
            std::vector<UInt> indices;
            for(UInt i=0; i<gnss->times.size(); i++)
              if(!covered.at(i) && gnss->times.at(i) >= para->times.at(arcNo).front() &&
                                  gnss->times.at(i) <= para->times.at(arcNo).back())
              {
                query.push_back(gnss->times.at(i));
                indices.push_back(i);
                covered.at(i) = TRUE;
              }
            if(query.empty()) continue;
            const Matrix pos = para->polynomial.at(arcNo).interpolate(query, para->PosDesign.at(arcNo), 3);
            const Matrix vel = para->polynomial.at(arcNo).interpolate(query, para->VelDesign.at(arcNo), 3, TRUE/*velocity jumps*/);
            const Matrix posCov = pos * para->parameterCovariance;
            const Matrix velCov = vel * para->parameterCovariance;
            for(UInt epoch=0; epoch<query.size(); epoch++)
            {
              Matrix design(6, count), weighted(6, count);
              copy(pos.row(3*epoch, 3), design.row(0, 3));
              copy(vel.row(3*epoch, 3), design.row(3, 3));
              copy(posCov.row(3*epoch, 3), weighted.row(0, 3));
              copy(velCov.row(3*epoch, 3), weighted.row(3, 3));
              const Matrix stateCovariance = weighted * design.trans();
              output(indices.at(epoch), 0) = query.at(epoch).mjd();
              for(UInt i=0; i<6; i++)
                for(UInt j=0; j<6; j++)
                {
                  const Double value = 0.5*(stateCovariance(i,j)+stateCovariance(j,i));
                  if(!std::isfinite(value) || ((i == j) && (value <= 0)))
                    throw(Exception("Invalid native Cartesian covariance at GNSS epoch"));
                  output(indices.at(epoch), 1+6*i+j) = value;
                }
            }
          }
          for(Bool valid : covered)
            if(!valid)
              throw(Exception("A nominal GNSS covariance epoch lies outside every variational arc"));
          fileNameVariableList.setVariable("station", para->recv->name());
          writeFileMatrix(fileNameCovarianceObservationEpochs(fileNameVariableList).appendBaseName(suffix), output);
        }
    }

'''
    cpp = _replace_once(cpp, "    if(!fileNameParameter.empty())", write + "    if(!fileNameParameter.empty())")
    return header, cpp


UPDATE = r'''
// ORBIT_COMPARISON_MARGINAL_COVARIANCE_V1
void GnssParametrizationLeoDynamicOrbits::updateCovariance(const GnssNormalEquationInfo &normalEquationInfo, const MatrixDistributed &covariance)
{
  try
  {
    if(fileNameCovariance.empty() || !isEnabled(normalEquationInfo, name))
      return;
    if(Parallel::size(normalEquationInfo.comm) != 1)
      throw(Exception("Native LEO covariance extension supports serial execution only"));

    for(auto para : parameters)
      if(para && para->index && para->recv->isMyRank())
      {
        const UInt count = para->x.rows();
        const UInt first = normalEquationInfo.index(para->index);
        if(first+count > covariance.parameterCount())
          throw(Exception("Orbit parameter range exceeds full inverse dimension"));
        Matrix parameterCovariance(count, count);
        // These entries are extracted AFTER inversion of the full native normal
        // matrix. Clocks, float ambiguities and other fitted blocks have already
        // been marginalized. Never invert an orbit-only normal submatrix here.
        for(UInt i=0; i<count; i++)
          for(UInt j=i; j<count; j++)
          {
            const UInt blockI = covariance.index2block(first+i);
            const UInt blockJ = covariance.index2block(first+j);
            if(!covariance.isBlockUsed(blockI, blockJ) || !covariance.isMyRank(blockI, blockJ))
              throw(Exception("Full inverse is missing a required orbit covariance block"));
            const Matrix &block = covariance.N(blockI, blockJ);
            const UInt row = first+i-covariance.blockIndex(blockI);
            const UInt col = first+j-covariance.blockIndex(blockJ);
            if(row >= block.rows() || col >= block.columns())
              throw(Exception("Full inverse orbit covariance block has incomplete storage"));
            const Double value = block(row, col);
            if(!std::isfinite(value))
              throw(Exception("Nonfinite native orbit parameter covariance"));
            parameterCovariance(i,j) = parameterCovariance(j,i) = value;
          }

        para->stateCovariance.clear();
        for(UInt arcNo=0; arcNo<para->times.size(); arcNo++)
        {
          const UInt epochs = para->times.at(arcNo).size();
          const Matrix &pos = para->PosDesign.at(arcNo);
          const Matrix &vel = para->VelDesign.at(arcNo);
          if(pos.rows() != 3*epochs || vel.rows() != 3*epochs || pos.columns() != count || vel.columns() != count)
            throw(Exception("Position/velocity variational designs do not match orbit parameters"));
          // Batched matrix products preserve all state/dynamic cross terms and
          // avoid a large separate covariance product at every epoch.
          const Matrix posCov = pos * parameterCovariance;
          const Matrix velCov = vel * parameterCovariance;
          Matrix rows(epochs, 36);
          for(UInt epoch=0; epoch<epochs; epoch++)
          {
            Matrix design(6, count), weighted(6, count);
            copy(pos.row(3*epoch, 3), design.row(0, 3));
            copy(vel.row(3*epoch, 3), design.row(3, 3));
            copy(posCov.row(3*epoch, 3), weighted.row(0, 3));
            copy(velCov.row(3*epoch, 3), weighted.row(3, 3));
            const Matrix stateCovariance = weighted * design.trans();
            for(UInt i=0; i<6; i++)
              for(UInt j=0; j<6; j++)
              {
                const Double value = 0.5*(stateCovariance(i,j)+stateCovariance(j,i));
                if(!std::isfinite(value) || ((i == j) && (value <= 0)))
                  throw(Exception("Invalid native Cartesian covariance"));
                rows(epoch, 6*i+j) = value;
              }
          }
          para->stateCovariance.push_back(rows);
        }
      }
  }
  catch(std::exception &e)
  {
    GROOPS_RETHROW(e)
  }
}

/***********************************************/

'''

WRITE = r'''
    // ORBIT_COMPARISON_MARGINAL_COVARIANCE_V1: MJD, then row-major 6x6 SI covariance.
    if(!fileNameCovariance.empty())
    {
      VariableList fileNameVariableList;
      fileNameVariableList.setVariable("station", "***");
      logStatus<<"write marginalized Cartesian covariance <"<<fileNameCovariance(fileNameVariableList).appendBaseName(suffix)<<">"<<Log::endl;
      for(auto para : parameters)
        if(para && para->index && para->recv->isMyRank())
        {
          if(para->stateCovariance.size() != para->times.size())
            throw(Exception("Run computeCovarianceMatrix after the final parameter update before covariance output"));
          UInt count = 0;
          for(const auto &times : para->times)
            count += times.size();
          Matrix output(count, 37);
          UInt row = 0;
          for(UInt arcNo=0; arcNo<para->times.size(); arcNo++)
            for(UInt epoch=0; epoch<para->times.at(arcNo).size(); epoch++, row++)
            {
              output(row, 0) = para->times.at(arcNo).at(epoch).mjd();
              for(UInt column=0; column<36; column++)
                output(row, column+1) = para->stateCovariance.at(arcNo)(epoch, column);
            }
          fileNameVariableList.setVariable("station", para->recv->name());
          writeFileMatrix(fileNameCovariance(fileNameVariableList).appendBaseName(suffix), output);
        }
    }

'''


def patch(source_root):
    source_root = Path(source_root)
    folder = source_root / SOURCE_SUBDIR
    header_path = folder / "gnssParametrizationLeoDynamicOrbits.h"
    cpp_path = folder / "gnssParametrizationLeoDynamicOrbits.cpp"
    header, cpp = header_path.read_text(), cpp_path.read_text()
    if MARKER in header or MARKER in cpp:
        if MARKER not in header or MARKER not in cpp:
            raise ValueError("Partial native covariance patch found; refusing ambiguous source state")
        upgraded_header, upgraded_cpp = _parameter_covariance_patch(header, cpp)
        upgraded_header, upgraded_cpp = _observation_covariance_patch(upgraded_header, upgraded_cpp)
        changed = upgraded_header != header or upgraded_cpp != cpp
        if changed:
            header_path.write_text(upgraded_header)
            cpp_path.write_text(upgraded_cpp)
        return {"status": "upgraded_parameter_covariance" if changed else "already_patched",
                "files": [str(header_path), str(cpp_path)], "parameter_covariance_marker": PARAMETER_MARKER}
    before = {str(p.relative_to(source_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (header_path, cpp_path)}
    header = _replace_once(header, "    std::vector<Vector>            pos, vel;",
        "    std::vector<Vector>            pos, vel;\n    std::vector<Matrix>            stateCovariance; // " + MARKER)
    header = _replace_once(header, "  FileName                       fileNameOrbit, fileNameParameter, fileNameVariational;",
        "  FileName                       fileNameOrbit, fileNameParameter, fileNameVariational, fileNameCovariance;")
    anchor = "  void   writeResults(const GnssNormalEquationInfo &normalEquationInfo, const std::string &suffix) const override;"
    header = _replace_once(header, anchor,
        "  void   updateCovariance(const GnssNormalEquationInfo &normalEquationInfo, const MatrixDistributed &covariance) override;\n" + anchor)
    config_anchor = '    readConfig(config, "outputfileParameters",        fileNameParameter,           Config::OPTIONAL, "",     "variable {station} available");'
    cpp = _replace_once(cpp, config_anchor, config_anchor + '\n    readConfig(config, "outputfileCovariance",        fileNameCovariance,          Config::OPTIONAL, "",     "MJD and 36 row-major marginalized Cartesian covariance entries in SI; serial only");')
    cpp = _replace_once(cpp, "    this->gnss = gnss;", "    this->gnss = gnss;\n    if(!fileNameCovariance.empty() && Parallel::size(comm) != 1)\n      throw(Exception(\"Native LEO covariance extension supports serial execution only\"));")
    cpp = _replace_once(cpp, "        const Vector dx = x.row(normalEquationInfo.index(para->index), para->x.rows());",
        "        para->stateCovariance.clear(); // invalidate covariance after any parameter update\n        const Vector dx = x.row(normalEquationInfo.index(para->index), para->x.rows());")
    method_anchor = "void GnssParametrizationLeoDynamicOrbits::writeResults(const GnssNormalEquationInfo &normalEquationInfo, const std::string &suffix) const"
    cpp = _replace_once(cpp, method_anchor, UPDATE + method_anchor)
    cpp = _replace_once(cpp, "    if(!fileNameParameter.empty())", WRITE + "    if(!fileNameParameter.empty())")
    # All anchors were checked before either upstream file is replaced.
    header, cpp = _parameter_covariance_patch(header, cpp)
    header, cpp = _observation_covariance_patch(header, cpp)
    header_path.write_text(header)
    cpp_path.write_text(cpp)
    return {"status": "patched", "marker": MARKER, "before_sha256": before,
            "after_sha256": {str(p.relative_to(source_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (header_path, cpp_path)},
            "covariance_scope": "orbit block of the full native inverse, propagated through stacked position/velocity designs",
            "output_columns": "MJD, then C00,C01,...,C55 in row-major order; SI position and velocity",
            "parallel_execution": "explicitly rejected"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    result = patch(args.source_root)
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
