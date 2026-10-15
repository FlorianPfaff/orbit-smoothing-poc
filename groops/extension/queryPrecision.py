"""Retain sub-long-double query changes through the existing QR polynomial."""
from pathlib import Path

MARKER = "ORBIT_POC_TWOFOLD_QUERY_WEIGHTS_V31"
INCLUDE = '#include "misc/orbitPoc/twofoldInterpolation.h"\n'


def apply(source):
    path = source / "base/polynomial.cpp"
    text = path.read_text()
    if MARKER not in text:
        start_anchor = "        std::vector<long double> nodes(count), weights(count);"
        if text.count(start_anchor) != 1:
            raise ValueError("Twofold query polynomial anchor mismatch")
        start = text.index(start_anchor)
        end = text.index("        continue;", start)
        previous = text[start:end]
        for required in ("offsetAt(i)", "ORBIT_POC_ANCHORED_LAGRANGE_V31",
                         "coordinateRemainders", "if(!adjoint)", "weights[k]*A(rowsPerEpoch*i+row,col)"):
            if required not in previous:
                raise ValueError("Twofold query requires the complete prior QR polynomial stage")
        replacement = r'''        // ORBIT_POC_TWOFOLD_QUERY_WEIGHTS_V31
        // ORBIT_POC_ANCHORED_LAGRANGE_V31: anchor retained by the twofold helper.
        // Degree, selected stencil, boundary side and native output conventions
        // are unchanged. Only this opt-in polynomial's arithmetic is upgraded.
        std::vector<orbitPocQr::TwofoldGeometry> nodes(count);
        const Time &query=timesNew.at(i);
        for(UInt k=0;k<count;k++)
          nodes[k]=orbitPocQr::twofoldInterpolationNode(times.at(idx+k).mjdInt(),times.at(idx+k).mjdMod(),
            query.mjdInt(),query.mjdMod(),offsetAt(i),sampling);
        const auto weights=orbitPocQr::twofoldInterpolationWeights(nodes,derivative,sampling);
        if(!adjoint)
          for(UInt row=0;row<rowsPerEpoch;row++)for(UInt col=0;col<A.columns();col++)
          {
            const char *auditMode=std::getenv("ORBIT_POC_NUMERICS_ARITHMETIC_AUDIT_MODE");
            const UInt anchorNode=auditMode&&std::string(auditMode)=="1"?0:(auditMode&&std::string(auditMode)=="2"?count-1:count/2);
            const auto value=orbitPocQr::twofoldInterpolationValue(weights,
              [&](std::size_t k){return A(rowsPerEpoch*(idx+k)+row,col);},derivative,anchorNode);
            B(rowsPerEpoch*i+row,col)=static_cast<Double>(value.rounded());
            if(preciseValues)preciseValues->at((rowsPerEpoch*i+row)*A.columns()+col)=value.rounded();
            if(coordinateRemainders)coordinateRemainders->at((rowsPerEpoch*i+row)*A.columns()+col)=
              (value-orbitPocQr::TwofoldGeometry(B(rowsPerEpoch*i+row,col))).rounded();
          }
        else
          for(UInt k=0;k<count;k++)for(UInt row=0;row<rowsPerEpoch;row++)for(UInt col=0;col<A.columns();col++)
            B(rowsPerEpoch*(idx+k)+row,col)+=static_cast<Double>((weights[k]*orbitPocQr::TwofoldGeometry(A(rowsPerEpoch*i+row,col))).rounded());
'''
        text = INCLUDE + text[:start] + replacement + text[end:]
    # Keep this header independent of GNSS classes and range-specific helpers.
    helper = source / "misc/orbitPoc/twofoldInterpolation.h"
    helper.write_bytes(Path(__file__).with_name("twofoldInterpolation.h").read_bytes())
    path.write_text(text)
