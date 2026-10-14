"""Instrument actual native weighted GNSS/prior rows for independent validation."""
from pathlib import Path
import sys

MARKER = "ORBIT_POC_LINEAR_TRACE_V1"


def patch(path, substitutions):
    text = path.read_text()
    if MARKER in text:
        return
    for old, new in substitutions:
        if text.count(old) != 1:
            raise ValueError(f"Linear trace patch anchor mismatch: {path.name}: {old[:100]}")
        text = text.replace(old, new, 1)
    path.write_text('// ' + MARKER + '\n#include "misc/orbitPoc/linearTrace.h"\n' + text)


def apply(source):
    source = Path(source) / "source"
    design = source / "gnss/gnssDesignMatrix.cpp"
    anchor = "    for(UInt ii=0; ii<A.indexUsedBlock.size(); ii++)"
    # This exact loop appears in other methods: scope to the named function.
    text = design.read_text()
    if MARKER not in text:
        start = text.index("void GnssDesignMatrix::accumulateNormals(")
        prefix, body = text[:start], text[start:]
        position = body.index(anchor)
        export = '''    if(orbitPocLinearTrace().enabled())
      for(UInt r=0;r<l.rows();r++)
      {
        std::vector<UInt> indices; std::vector<Double> values;
        for(UInt block : A.indexUsedBlock)
          for(UInt part=0;part<A.indexUsedParameter[block].size();part++)
            for(UInt c=0;c<A.countUsedParameter[block][part];c++)
            {
              const UInt column=A.indexUsedParameter[block][part]+c;
              indices.push_back(normals.blockIndex(block)+column);
              values.push_back(A.A(A.row+r,A.blockIndices[block]+column));
            }
        orbitPocLinearTrace().addRow(l(r,0),indices,values);
      }

'''
        design.write_text('// '+MARKER+'\n#include "misc/orbitPoc/linearTrace.h"\n'+prefix+body[:position]+export+body[position:])
    processing = source / "gnss/gnssProcessingStep/gnssProcessingStep.cpp"
    # Also upgrade previously applied V1 traces without changing inactive runs.
    old_begin = "    orbitPocLinearTrace().begin(normalEquationInfo, gnss->aprioriParameter(normalEquationInfo), solveEpochParameters);"
    existing = processing.read_text()
    if "\n" + old_begin + "\n" in existing:
        processing.write_text(existing.replace("\n" + old_begin + "\n",
            "\n    if(orbitPocLinearTrace().enabled())\n  " + old_begin + "\n", 1))
    patch(processing, [
        ("    normals.initEmpty(normalEquationInfo.blockIndices(), normalEquationInfo.comm,",
         "    if(orbitPocLinearTrace().enabled())\n      orbitPocLinearTrace().begin(normalEquationInfo, gnss->aprioriParameter(normalEquationInfo), solveEpochParameters);\n    normals.initEmpty(normalEquationInfo.blockIndices(), normalEquationInfo.comm,"),
        ("    n.clear();\n    n.shrink_to_fit();\n    Parallel::broadCast(x, 0, normalEquationInfo.comm);",
         "    orbitPocLinearTrace().delta(x);\n    n.clear();\n    n.shrink_to_fit();\n    Parallel::broadCast(x, 0, normalEquationInfo.comm);")])
    constraints = source / "gnss/gnssParametrization/gnssParametrizationConstraints.h"
    patch(constraints, [("        const UInt idBlock    = normals.index2block(index);",
        "        orbitPocLinearTrace().addRow((bias-x0.at(index))/sigma,{index},{1./sigma});\n        const UInt idBlock    = normals.index2block(index);")])
    covariance = source / "gnss/gnssProcessingStep/gnssProcessingStepComputeCovarianceMatrix.h"
    patch(covariance, [("    state.normals.cholesky(TRUE/*timing*/);",
        "    orbitPocLinearTrace().fullStructure(state.normals);\n    state.normals.cholesky(TRUE/*timing*/);"),
        ("    state.normals.cholesky2SparseInverse();",
         "    state.normals.cholesky2SparseInverse();\n    orbitPocLinearTrace().covariance(state.normals);")])


if __name__ == "__main__":
    apply(sys.argv[1])
