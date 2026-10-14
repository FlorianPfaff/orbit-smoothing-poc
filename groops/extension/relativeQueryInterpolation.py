"""Numerics-only explicit sub-Time offsets for the existing GNSS polynomials."""
from pathlib import Path


def replace_one(text, old, new, label):
    if text.count(old) != 1:
        raise ValueError(f"Relative query patch anchor mismatch: {label}")
    return text.replace(old, new, 1)


def apply(source):
    marker = "ORBIT_POC_RELATIVE_QUERY_INTERPOLATION_V31"
    path = source / "base/polynomial.h"
    text = path.read_text()
    if marker not in text:
        anchor = "  Matrix interpolate(const std::vector<Time> &timesNew, const_MatrixSliceRef A, UInt rowsPerEpoch, UInt derivative, Bool adjoint=FALSE) const;"
        text = replace_one(text, anchor, anchor + "\n  // " + marker + "\n  Matrix interpolateOffset(const std::vector<Time> &timesNew, const_MatrixSliceRef A, const std::vector<long double> &offsetSeconds, UInt rowsPerEpoch=1, UInt derivative=0, Bool adjoint=FALSE) const;", "Polynomial declaration")
        path.write_text(text)
    path = source / "base/polynomial.cpp"
    text = path.read_text()
    if marker not in text:
        signature = "Matrix Polynomial::interpolate(const std::vector<Time> &timesNew, const_MatrixSliceRef A, UInt rowsPerEpoch, UInt derivative, Bool adjoint) const"
        text = replace_one(text, signature, signature + "\n{return interpolateOffset(timesNew,A,{},rowsPerEpoch,derivative,adjoint);}\n\n// " + marker + "\nMatrix Polynomial::interpolateOffset(const std::vector<Time> &timesNew, const_MatrixSliceRef A, const std::vector<long double> &offsetSeconds, UInt rowsPerEpoch, UInt derivative, Bool adjoint) const", "Polynomial definition")
        anchor = "    const Bool continuousQuery=orbitPocPrefix&&*orbitPocPrefix;"
        text = replace_one(text, anchor, anchor + r'''
    if(!offsetSeconds.empty()&&offsetSeconds.size()!=timesNew.size())throw(Exception("Relative polynomial query shape mismatch"));
    for(long double value:offsetSeconds)if(!std::isfinite(value)||std::fabs(value)>1e-8L)throw(Exception("Relative polynomial query exceeds sub-Time remainder"));
    const Bool shifted=std::any_of(offsetSeconds.begin(),offsetSeconds.end(),[](long double value){return value!=0;});
    if(shifted&&(!continuousQuery||isLeastSquares))throw(Exception("Relative query requires the QR interpolation polynomial"));
    auto offsetAt=[&](UInt index){return offsetSeconds.empty()?0.L:offsetSeconds.at(index);};''', "query validation")
        text = replace_one(text, "if(!derivative && !isLeastSquares && sameTimes)", "if(!shifted && !derivative && !isLeastSquares && sameTimes)", "grid shortcut")
        text = replace_one(text, "if(!adjoint && !derivative && (idxFirstRight < times.size())", "if(offsetAt(i)==0 && !adjoint && !derivative && (idxFirstRight < times.size())", "point shortcut")
        text = replace_one(text, "(static_cast<long double>(times.at(idx+k).mjdMod())-query.mjdMod())*86400.L)/sampling;", "(static_cast<long double>(times.at(idx+k).mjdMod())-query.mjdMod())*86400.L-offsetAt(i))/sampling;", "local query offset")
        path.write_text(text)
    path = source / "misc/orbitPoc/piecewisePolynomial.h"
    text = path.read_text()
    if marker in text:
        text=text[:text.index("  // "+marker)]+"};\n#endif\n"
    if marker not in text:
        start = text.index("  Matrix interpolate(")
        end = text.rindex("\n};")
        method = text[start:end]
        method = replace_one(method, "Matrix interpolate(const std::vector<Time> &timesNew, const_MatrixSliceRef A,\n                     UInt rowsPerEpoch=1, Bool valuesJump=FALSE) const", "Matrix interpolateOffset(const std::vector<Time> &timesNew, const_MatrixSliceRef A,\n                     const std::vector<long double> &offsetSeconds, UInt rowsPerEpoch=1, Bool valuesJump=FALSE) const", "piecewise declaration")
        method = replace_one(method, "    if(segments.empty()", r'''    const char *prefix=std::getenv("ORBIT_POC_NUMERICS_QR_PREFIX");
    if(!prefix||!*prefix)return interpolate(timesNew,A,rowsPerEpoch,valuesJump);
    if(!offsetSeconds.empty()&&offsetSeconds.size()!=timesNew.size())throw(Exception("Piecewise relative query shape mismatch"));
    auto offsetAt=[&](UInt index){return offsetSeconds.empty()?0.L:offsetSeconds.at(index);};
    auto difference=[](const Time &a,const Time &b){return (static_cast<long double>(a.mjdInt())-b.mjdInt())*86400.L+(static_cast<long double>(a.mjdMod())-b.mjdMod())*86400.L;};
    auto segmentAt=[&](UInt i){return std::upper_bound(splitTimes.begin(),splitTimes.end(),timesNew.at(i),[&](const Time &query,const Time &boundary){return difference(query,boundary)+offsetAt(i)<0;})-splitTimes.begin();};
    if(segments.empty()''', "piecewise validation")
        method = replace_one(method, "std::upper_bound(splitTimes.begin(),splitTimes.end(),timesNew.front())-splitTimes.begin()", "segmentAt(0)", "piecewise scalar side")
        method = replace_one(method, "std::upper_bound(splitTimes.begin(),splitTimes.end(),timesNew.at(i))-splitTimes.begin()", "segmentAt(i)", "piecewise batch side")
        method = replace_one(method, "return timesNew.at(a)<timesNew.at(b);", "return difference(timesNew.at(a),timesNew.at(b))+offsetAt(a)-offsetAt(b)<0;", "piecewise exact sorting")
        method = replace_one(method, "return polynomial.interpolate(timesNew,A.row(rowsPerEpoch*part.first,rowsPerEpoch*count),rowsPerEpoch);", "return polynomial.interpolateOffset(timesNew,A.row(rowsPerEpoch*part.first,rowsPerEpoch*count),offsetSeconds,rowsPerEpoch);", "piecewise scalar")
        method = replace_one(method, "      std::vector<Time> queries;\n      for(UInt index:order) queries.push_back(timesNew.at(index));", "      std::vector<Time> queries;std::vector<long double> offsets;\n      for(UInt index:order){queries.push_back(timesNew.at(index));offsets.push_back(offsetAt(index));}", "piecewise order")
        method = replace_one(method, "const Matrix values=polynomial.interpolate(queries,A.row(rowsPerEpoch*part.first,rowsPerEpoch*count),rowsPerEpoch);", "const Matrix values=polynomial.interpolateOffset(queries,A.row(rowsPerEpoch*part.first,rowsPerEpoch*count),offsets,rowsPerEpoch);", "piecewise batch")
        text = text[:end] + "\n  // " + marker + "\n" + method + text[end:]
        path.write_text(text)
    path = source / "gnss/gnssReceiver.h"
    text = path.read_text()
    if marker not in text:
        anchor = "  Time timeCorrected(UInt idEpoch) const"
        text = replace_one(text, anchor, "  // " + marker + r'''
  long double timeRemainder(UInt idEpoch) const
  {
    const char *prefix=std::getenv("ORBIT_POC_NUMERICS_QR_PREFIX");
    return prefix&&*prefix ? orbitPocQr::timeRemainder(times.at(idEpoch),clockError(idEpoch),timeCorrected(idEpoch)) : 0.L;
  }
''' + anchor, "receiver remainder")
        path.write_text(text)
    path = source / "gnss/gnssTransmitter.h"
    text = path.read_text()
    if marker not in text:
        anchor = "  Vector3d velocity(const Time &time) const;"
        text = replace_one(text, anchor, anchor + "\n  // " + marker + r'''
  Vector3d positionOffset(UInt idEpoch,const Time &time,long double remainder) const
  {return Vector3d(polynomial.interpolateOffset({time},pos,{remainder}))+crf2srf.at(idEpoch).inverseTransform(offset.at(idEpoch));}
  Vector3d velocityOffset(const Time &time,long double remainder) const
  {return Vector3d(polynomial.interpolateOffset({time},vel,{remainder}));}
''', "transmitter remainder")
        path.write_text(text)
    path = source / "gnss/gnssParametrization/gnssParametrizationLeoDynamicOrbits.cpp"
    text = path.read_text()
    if marker not in text:
        for which in ("back()", "at(arcNo)"):
            anchor = "std::vector<Time> times;\n" + ("            " if which == "back()" else "          ") + "for(UInt idEpoch=para->startEpoch." + which
            text = replace_one(text, anchor, "std::vector<Time> times;std::vector<long double> queryRemainders;\n" + ("            " if which == "back()" else "          ") + "for(UInt idEpoch=para->startEpoch." + which, "LEO query declarations " + which)
        old = "times.push_back(para->recv->timeCorrected(idEpoch));"
        if text.count(old)!=2: raise ValueError("LEO query collection changed")
        text = text.replace(old,"{times.push_back(para->recv->timeCorrected(idEpoch));queryRemainders.push_back(para->recv->timeRemainder(idEpoch));}")
        for which in ("back()", "at(arcNo)"):
            for quantity, jump in (("pos", ""), ("vel", ", TRUE/*velocity jumps*/")):
                anchor = f"para->polynomial.{which}.interpolate(times, para->{quantity}.{which}, 3{jump})"
                text = replace_one(text, anchor, f"para->polynomial.{which}.interpolateOffset(times, para->{quantity}.{which}, queryRemainders, 3{jump})", "LEO query " + which + quantity)
        anchor = "para->polynomial.at(arcNo).interpolate({eqn.timeRecv}, para->PosDesign.at(arcNo), 3)"
        text = replace_one(text, anchor, "para->polynomial.at(arcNo).interpolateOffset({eqn.timeRecv}, para->PosDesign.at(arcNo), {eqn.receiver->timeRemainder(eqn.idEpoch)}, 3)", "LEO design query")
        path.write_text("// " + marker + "\n" + text)
    path = source / "gnss/gnssObservation.cpp"
    text = path.read_text()
    if marker not in text:
        start = text.index("    posTrans = transmitter.position(idEpoch, timeRecv-seconds2time(20200e3/LIGHT_VELOCITY));")
        end = text.index("\n\n    // line of sight",start)
        legacy = text[start:end]
        replacement = r'''    // ORBIT_POC_RELATIVE_QUERY_INTERPOLATION_V31
    if(orbitPocQr::enabled())
    {
      auto query=[&](long double travel)
      {
        const long double duration=static_cast<long double>(receiver.clockError(idEpoch))+travel;
        timeTrans=orbitPocQr::stableReceiverTime(receiver.times.at(idEpoch),duration);
        return orbitPocQr::timeRemainder(receiver.times.at(idEpoch),duration,timeTrans);
      };
      long double remainder=query(20200e3L/LIGHT_VELOCITY);
      posTrans=transmitter.positionOffset(idEpoch,timeTrans,remainder);
      Vector3d posOld;
      for(UInt i=0;(i<10)&&((posTrans-posOld).r()>0.0001);i++)
      {
        remainder=query((posTrans-posRecv).r()/LIGHT_VELOCITY);
        posOld=posTrans;posTrans=transmitter.positionOffset(idEpoch,timeTrans,remainder);
      }
      velTrans=transmitter.velocityOffset(timeTrans,remainder);
    }
    else
    {
''' + legacy + "\n    }"
        text = text[:start]+replacement+text[end:]
        path.write_text(text)
