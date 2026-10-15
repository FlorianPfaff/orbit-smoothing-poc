"""Carry polynomial coordinate roundoff into the opt-in GNSS range equation."""
from relativeQueryInterpolation import replace_one


def require_install_state(source):
    # Old markers must never silently skip the representation upgrade. Use a
    # fresh pinned upstream tree; preserve candidate1 and all of its receipts.
    old = "ORBIT_POC_PRECISE_POSITION_REMAINDER_V31"
    new = old + "_PAIR2"
    for relative in ("base/polynomial.h", "base/polynomial.cpp", "misc/orbitPoc/piecewisePolynomial.h",
                     "gnss/gnssReceiver.h", "gnss/gnssTransmitter.h",
                     "gnss/gnssParametrization/gnssParametrizationLeoDynamicOrbits.cpp", "gnss/gnssObservation.cpp"):
        path = source / relative
        if path.is_file():
            text = path.read_text()
            if old in text and new not in text:
                raise ValueError("high_low_geometry_v2 requires a fresh pinned upstream install; preserve the old generated tree")
    observation = source / "gnss/gnssObservation.cpp"
    if observation.is_file():
        text = observation.read_text()
        if new in text and "ORBIT_POC_TWOFOLD_LIGHT_TIME_V31" not in text:
            raise ValueError("twofold light time requires a fresh pinned upstream install; preserve the old generated tree")


def apply(source):
    require_install_state(source)
    marker="ORBIT_POC_PRECISE_POSITION_REMAINDER_V31_PAIR2"
    path=source/"base/polynomial.h";text=path.read_text()
    if marker not in text:
        anchor="UInt derivative=0, Bool adjoint=FALSE) const;"
        text=replace_one(text,anchor,"UInt derivative=0, Bool adjoint=FALSE, std::vector<long double> *preciseValues=nullptr, std::vector<long double> *coordinateRemainders=nullptr) const; // "+marker,"precise Polynomial declaration")
        path.write_text(text)
    path=source/"base/polynomial.cpp";text=path.read_text()
    if marker not in text:
        anchor="const std::vector<long double> &offsetSeconds, UInt rowsPerEpoch, UInt derivative, Bool adjoint) const"
        text=replace_one(text,anchor,"const std::vector<long double> &offsetSeconds, UInt rowsPerEpoch, UInt derivative, Bool adjoint, std::vector<long double> *preciseValues, std::vector<long double> *coordinateRemainders) const","precise Polynomial definition")
        anchor="    if(!shifted && !derivative && !isLeastSquares && sameTimes) // exact grid identity remains exact\n      return A;"
        text=replace_one(text,anchor,r'''    // ORBIT_POC_PRECISE_POSITION_REMAINDER_V31_PAIR2
    if((preciseValues||coordinateRemainders) && (adjoint||isLeastSquares||!continuousQuery))throw(Exception("Precise coordinate output requires forward QR interpolation"));
    if(preciseValues)preciseValues->assign(rowsPerEpoch*timesNew.size()*A.columns(),0.L);
    // Compatibility output remains the absolute long-double value. The new
    // low output satisfies value = returned_double + coordinateRemainders.
    if(coordinateRemainders)coordinateRemainders->assign(rowsPerEpoch*timesNew.size()*A.columns(),0.L);
    if(!shifted && !derivative && !isLeastSquares && sameTimes) // exact grid identity remains exact
    {
      if(preciseValues)for(UInt row=0;row<A.rows();row++)for(UInt col=0;col<A.columns();col++)preciseValues->at(row*A.columns()+col)=A(row,col);
      return A;
    }''',"precise exact grid")
        anchor="          copy(A.row(rowsPerEpoch*idxFirstRight, rowsPerEpoch), B.row(rowsPerEpoch*i, rowsPerEpoch));"
        text=replace_one(text,anchor,anchor+"\n          if(preciseValues)for(UInt row=0;row<rowsPerEpoch;row++)for(UInt col=0;col<A.columns();col++)preciseValues->at((rowsPerEpoch*i+row)*A.columns()+col)=A(rowsPerEpoch*idxFirstRight+row,col);","precise exact row")
        anchor="B(rowsPerEpoch*i+row,col)=static_cast<Double>(value);}"
        text=replace_one(text,anchor,"B(rowsPerEpoch*i+row,col)=static_cast<Double>(value);if(preciseValues)preciseValues->at((rowsPerEpoch*i+row)*A.columns()+col)=value;if(coordinateRemainders)coordinateRemainders->at((rowsPerEpoch*i+row)*A.columns()+col)=(center-static_cast<long double>(B(rowsPerEpoch*i+row,col)))+localOffset;}","precise interpolation sum")
        path.write_text(text)
    path=source/"misc/orbitPoc/piecewisePolynomial.h";text=path.read_text()
    if marker not in text:
        anchor="const std::vector<long double> &offsetSeconds, UInt rowsPerEpoch=1, Bool valuesJump=FALSE) const"
        text=replace_one(text,anchor,"const std::vector<long double> &offsetSeconds, UInt rowsPerEpoch=1, Bool valuesJump=FALSE, std::vector<long double> *preciseValues=nullptr, std::vector<long double> *coordinateRemainders=nullptr) const","precise piecewise declaration")
        anchor="    if(!prefix||!*prefix)return interpolate(timesNew,A,rowsPerEpoch,valuesJump);"
        text=replace_one(text,anchor,r'''    // ORBIT_POC_PRECISE_POSITION_REMAINDER_V31_PAIR2
    if(!prefix||!*prefix)
    {
      const Matrix values=interpolate(timesNew,A,rowsPerEpoch,valuesJump);
      if(preciseValues){preciseValues->resize(values.rows()*values.columns());for(UInt row=0;row<values.rows();row++)for(UInt col=0;col<values.columns();col++)preciseValues->at(row*values.columns()+col)=values(row,col);}
      if(coordinateRemainders)coordinateRemainders->assign(values.rows()*values.columns(),0.L);
      return values;
    }
    if(preciseValues)preciseValues->assign(rowsPerEpoch*timesNew.size()*A.columns(),0.L);
    if(coordinateRemainders)coordinateRemainders->assign(rowsPerEpoch*timesNew.size()*A.columns(),0.L);''',"precise piecewise legacy")
        text=replace_one(text,"offsetSeconds,rowsPerEpoch);","offsetSeconds,rowsPerEpoch,0,FALSE,preciseValues,coordinateRemainders);","precise piecewise scalar")
        text=replace_one(text,"const Matrix values=polynomial.interpolateOffset(queries,A.row(rowsPerEpoch*part.first,rowsPerEpoch*count),offsets,rowsPerEpoch);","std::vector<long double> exact,low;\n      const Matrix values=polynomial.interpolateOffset(queries,A.row(rowsPerEpoch*part.first,rowsPerEpoch*count),offsets,rowsPerEpoch,0,FALSE,preciseValues?&exact:nullptr,coordinateRemainders?&low:nullptr);\n      if(preciseValues)for(UInt i=0;i<order.size();i++)for(UInt row=0;row<rowsPerEpoch;row++)for(UInt col=0;col<A.columns();col++)preciseValues->at((rowsPerEpoch*order.at(i)+row)*A.columns()+col)=exact.at((rowsPerEpoch*i+row)*A.columns()+col);\n      if(coordinateRemainders)for(UInt i=0;i<order.size();i++)for(UInt row=0;row<rowsPerEpoch;row++)for(UInt col=0;col<A.columns();col++)coordinateRemainders->at((rowsPerEpoch*order.at(i)+row)*A.columns()+col)=low.at((rowsPerEpoch*i+row)*A.columns()+col);","precise piecewise batch")
        path.write_text(text)
    path=source/"gnss/gnssReceiver.h";text=path.read_text()
    if marker not in text:
        anchor="  std::vector<Vector3d>     pos, vel;"
        text=replace_one(text,anchor,"  // "+marker+"\n  std::vector<Vector3d> orbitPocPositionRemainder;\n"+anchor,"receiver precise storage")
        anchor="  Vector3d position(UInt idEpoch) const {return pos.at(idEpoch) + global2local.at(idEpoch).inverseTransform(offset.at(idEpoch));}"
        text=replace_one(text,anchor,anchor+r'''
  Vector3d positionRemainder(UInt idEpoch) const
  {
    const Vector3d base=pos.at(idEpoch),low=orbitPocPositionRemainder.size()>idEpoch?orbitPocPositionRemainder.at(idEpoch):Vector3d();
    const Vector3d antenna=global2local.at(idEpoch).inverseTransform(offset.at(idEpoch)),rounded=position(idEpoch);
    return Vector3d(static_cast<Double>(((static_cast<long double>(base.x())-rounded.x())+antenna.x())+low.x()),
                    static_cast<Double>(((static_cast<long double>(base.y())-rounded.y())+antenna.y())+low.y()),
                    static_cast<Double>(((static_cast<long double>(base.z())-rounded.z())+antenna.z())+low.z()));
  }
''',"receiver antenna addition")
        path.write_text(text)
    path=source/"gnss/gnssTransmitter.h";text=path.read_text()
    if marker not in text:
        start=text.index("  Vector3d positionOffset(");end=text.index("  Vector3d velocityOffset(",start)
        text=text[:start]+r'''  // ORBIT_POC_PRECISE_POSITION_REMAINDER_V31_PAIR2
  Vector3d positionOffset(UInt idEpoch,const Time &time,long double remainder,Vector3d *coordinateRemainder=nullptr) const
  {
    std::vector<long double> low;
    const Vector3d base(polynomial.interpolateOffset({time},pos,{remainder},1,0,FALSE,nullptr,coordinateRemainder?&low:nullptr));
    const Vector3d antenna=crf2srf.at(idEpoch).inverseTransform(offset.at(idEpoch)),rounded=base+antenna;
    if(coordinateRemainder)*coordinateRemainder=Vector3d(static_cast<Double>(((static_cast<long double>(base.x())-rounded.x())+antenna.x())+low.at(0)),static_cast<Double>(((static_cast<long double>(base.y())-rounded.y())+antenna.y())+low.at(1)),static_cast<Double>(((static_cast<long double>(base.z())-rounded.z())+antenna.z())+low.at(2)));
    return rounded;
  }
'''+text[end:]
        path.write_text(text)
    path=source/"gnss/gnssParametrization/gnssParametrizationLeoDynamicOrbits.cpp";text=path.read_text()
    if marker not in text:
        for which in ("back()","at(arcNo)"):
            anchor=f"const Vector pos = para->polynomial.{which}.interpolateOffset(times, para->pos.{which}, queryRemainders, 3);"
            text=replace_one(text,anchor,f"std::vector<long double> coordinateLow;\n          const Vector pos = para->polynomial.{which}.interpolateOffset(times, para->pos.{which}, queryRemainders, 3, FALSE, nullptr, &coordinateLow);\n          para->recv->orbitPocPositionRemainder.resize(para->recv->times.size());","LEO precise query "+which)
        anchor="para->recv->pos.at(idEpoch) = Vector3d(pos.row(3*i, 3));"
        if text.count(anchor)!=2:raise ValueError("LEO precise cache anchor mismatch")
        text=text.replace(anchor,anchor+"\n              para->recv->orbitPocPositionRemainder.at(idEpoch)=Vector3d(static_cast<Double>(coordinateLow.at(3*i)),static_cast<Double>(coordinateLow.at(3*i+1)),static_cast<Double>(coordinateLow.at(3*i+2)));")
        path.write_text("// "+marker+"\n"+text)
    path=source/"gnss/gnssObservation.cpp";text=path.read_text()
    if marker not in text:
        anchor="Vector3d &k, Vector3d &kRecv, Vector3d &kTrans)"
        text=replace_one(text,anchor,"Vector3d &k, Vector3d &kRecv, Vector3d &kTrans, Vector3d *receiverRemainder=nullptr, Vector3d *transmitterRemainder=nullptr)","geometry remainder output")
        anchor="    if(orbitPocQr::enabled())\n    {\n      auto query="
        text=replace_one(text,anchor,"    if(orbitPocQr::enabled())\n    {\n      if(receiver.isEarthFixed())throw(Exception(\"v3.1 precise range geometry supports inertial LEO receivers only\"));\n      const Vector3d recvLow=receiver.positionRemainder(idEpoch);Vector3d transLow;\n      if(receiverRemainder)*receiverRemainder=recvLow;\n      auto query=","geometry restriction")
        text=replace_one(text,"auto query=[&](long double travel)\n      {\n        const long double duration=static_cast<long double>(receiver.clockError(idEpoch))+travel;",
                        "// ORBIT_POC_TWOFOLD_LIGHT_TIME_V31\n      auto query=[&](const orbitPocQr::TwofoldGeometry &travel)\n      {\n        const auto duration=orbitPocQr::TwofoldGeometry(receiver.clockError(idEpoch))+travel;",
                        "twofold light-time duration")
        start=text.index("      long double remainder=query(20200e3L/LIGHT_VELOCITY);");end=text.index("\n    }\n    else",start)
        text=text[:start]+r'''      long double remainder=query(orbitPocQr::TwofoldGeometry(20200e3L)/orbitPocQr::TwofoldGeometry(LIGHT_VELOCITY));
      posTrans=transmitter.positionOffset(idEpoch,timeTrans,remainder,&transLow);
      for(UInt i=0;i<10;i++)
      {
        remainder=query(orbitPocQr::preciseDistanceExpansion(posTrans,transLow,posRecv,recvLow)/orbitPocQr::TwofoldGeometry(LIGHT_VELOCITY));
        const Vector3d old=posTrans,oldLow=transLow;
        posTrans=transmitter.positionOffset(idEpoch,timeTrans,remainder,&transLow);
        if(orbitPocQr::preciseDistance(posTrans,transLow,old,oldLow)<1e-10L)break;
        if(i==9)throw(Exception("Precise GNSS light-time iteration did not close"));
      }
      velTrans=transmitter.velocityOffset(timeTrans,remainder);
      if(transmitterRemainder)*transmitterRemainder=transLow;'''+text[end:]
        anchor="    Vector3d k, kRecvAnt, kTrans;"
        text=replace_one(text,anchor,anchor+"\n    Vector3d receiverPositionRemainder,transmitterPositionRemainder;","range low locals")
        anchor="                         k, kRecvAnt, kTrans);"
        text=replace_one(text,anchor,"                         k, kRecvAnt, kTrans, &receiverPositionRemainder, &transmitterPositionRemainder);","range low arguments")
        anchor="transmitter->clockError(idEpoch),transmitter->scaleFactor(idEpoch)) : l(i)-r12;"
        text=replace_one(text,anchor,"transmitter->clockError(idEpoch),transmitter->scaleFactor(idEpoch),receiverPositionRemainder,transmitterPositionRemainder) : l(i)-r12;","range low reconstruction")
        path.write_text("// "+marker+"\n"+text)
    path=source/"base/polynomial.cpp";text=path.read_text()
    if "ORBIT_POC_ANCHORED_LAGRANGE_V31" not in text:
        anchor="long double value=0;for(UInt k=0;k<count;k++)value+=weights[k]*A(rowsPerEpoch*(idx+k)+row,col);"
        replacement="/* ORBIT_POC_ANCHORED_LAGRANGE_V31 */const char *auditMode=std::getenv(\"ORBIT_POC_NUMERICS_ARITHMETIC_AUDIT_MODE\");const UInt anchorNode=auditMode&&std::string(auditMode)==\"1\"?0:(auditMode&&std::string(auditMode)==\"2\"?count-1:count/2);const long double reference=A(rowsPerEpoch*(idx+anchorNode)+row,col);long double localOffset=0.L;for(UInt k=0;k<count;k++)localOffset+=weights[k]*(static_cast<long double>(A(rowsPerEpoch*(idx+k)+row,col))-reference);const long double center=derivative?0.L:reference;const long double value=center+localOffset;"
        text=replace_one(text,anchor,replacement,"anchored polynomial accumulation")
        path.write_text(text)

    path=source/"base/polynomial.cpp";text=path.read_text()
    if "ORBIT_POC_NUMERICS_ARITHMETIC_AUDIT_MODE" not in text:
        old="const long double reference=A(rowsPerEpoch*(idx+count/2)+row,col);"
        new='const char *auditMode=std::getenv("ORBIT_POC_NUMERICS_ARITHMETIC_AUDIT_MODE");const UInt anchorNode=auditMode&&std::string(auditMode)=="1"?0:(auditMode&&std::string(auditMode)=="2"?count-1:count/2);const long double reference=A(rowsPerEpoch*(idx+anchorNode)+row,col);'
        text=replace_one(text,old,new,"equivalent-arithmetic polynomial audit")
        path.write_text(text)
