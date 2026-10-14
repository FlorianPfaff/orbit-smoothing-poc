#!/usr/bin/env python3
"""One-sided quadrature for unchanged UTC-indexed atmospheric forces."""
from pathlib import Path
import argparse,shutil

def replace(text,before,after):
    if text.count(before)!=1:raise ValueError('Atmospheric patch anchor changed: '+before[:120])
    return text.replace(before,after,1)

def apply(source):
    root=Path(source)/'source';here=Path(__file__).parent
    for name in ('eventQuadrature.h','atmosphereEvents.h','atmosphereLocalEvents.h','atmosphereExtraSamples.h'):
        target=root/'misc/orbitPoc'/name
        if not target.exists() or target.read_bytes()!=(here/name).read_bytes():shutil.copyfile(here/name,target)
    h=root/'classes/parametrizationAcceleration/parametrizationAcceleration.h'
    text=h.read_text()
    if 'integrationDiscontinuities' not in text:
        text=replace(text,'  std::vector<Time> integrationBoundaries() const;','  std::vector<Time> integrationBoundaries() const;\n  std::vector<Time> integrationDiscontinuities(const Time &start,const Time &end) const;')
        text=replace(text,'virtual std::vector<Time> integrationBoundaries() const {return {};}','virtual std::vector<Time> integrationBoundaries() const {return {};}\nvirtual std::vector<Time> integrationDiscontinuities(const Time &,const Time &) const {return {};}')
        h.write_text(text)
        cpp=h.with_suffix('.cpp')
        cpp.write_text(cpp.read_text()+'''
std::vector<Time> ParametrizationAcceleration::integrationDiscontinuities(const Time &start,const Time &end) const
{
  std::vector<Time> result;
  for(auto item:parameter)
  {const auto times=item->integrationDiscontinuities(start,end);result.insert(result.end(),times.begin(),times.end());}
  std::sort(result.begin(),result.end());result.erase(std::unique(result.begin(),result.end()),result.end());return result;
}
''')
    cpp=root/'programs/preprocessing/preprocessingVariationalEquation.cpp';text=cpp.read_text()
    if 'orbitPocAtmosphericForce' not in text:
        text=replace(text,'#include "misc/orbitPoc/integrationWindows.h"','#include "misc/orbitPoc/integrationWindows.h"\n#include "misc/orbitPoc/atmosphereEvents.h"\n#include "classes/miscAccelerations/miscAccelerations.h"')
        text=replace(text,'  ForcesPtr                      forces;','  ForcesPtr                      forces;\n  MiscAccelerationsPtr orbitPocAtmosphericForce;\n  OrbitPoc::Quadrature orbitPocAtmosphericWeights;\n  Matrix atmosphereIntegral(const_MatrixSliceRef g,Bool velocity) const;')
        anchor='    readConfig(config, "forces",                      forces,                 Config::MUSTSET,   "", "");'
        text=replace(text,anchor,anchor+'\n    readConfig(config,"orbitPocAtmosphericForce",orbitPocAtmosphericForce,Config::OPTIONAL,"","identical atmospheric component for exact one-sided UTC-event quadrature");')
        anchor='    orbitPocWindows = integrationBoundaries ? orbitPocIntegrationWindows(times,integrationBoundaries->times(),integrationDegree) : std::vector<UInt>();'
        text=replace(text,anchor,anchor+'''\n    if(orbitPocAtmosphericForce)
      orbitPocAtmosphericWeights=orbitPocEventQuadrature(times,integrationBoundaries ? integrationBoundaries->times() : std::vector<Time>(),orbitPocAtmosphereEvents(times.front(),times.back()),integrationDegree);
    Vector orbitPocDrag(3*epochCount);''')
        anchor='      // accelerometer\n'
        text=replace(text,anchor,'''      if(orbitPocAtmosphericForce)
      {
        const auto drag=rotEarth.at(k).inverseRotate(orbitPocAtmosphericForce->acceleration(satellite,orbit.at(k).time,
            orbit.at(k).position,orbit.at(k).velocity,starCamera.at(k).rotary,rotEarth.at(k),ephemerides));
        copy(drag.vector(),orbitPocDrag.row(3*k,3));
      }
'''+anchor)
        text=replace(text,'    Matrix pos0  = integrate2Position(deltaT, g);','    Matrix pos0 = orbitPocAtmosphericForce ? integrate2Position(deltaT,g-orbitPocDrag)+atmosphereIntegral(orbitPocDrag,FALSE) : integrate2Position(deltaT,g);')
        text=replace(text,'    Matrix vel0 = integrate2Velocity(deltaT, acc0);','    Matrix vel0 = orbitPocAtmosphericForce ? integrate2Velocity(deltaT,acc0-orbitPocDrag)+atmosphereIntegral(orbitPocDrag,TRUE) : integrate2Velocity(deltaT,acc0);')
        text+='''
// Atmospheric integrals preserve step discontinuities in archived driver data.
Matrix PreprocessingVariationalEquation::atmosphereIntegral(const_MatrixSliceRef g,Bool velocity) const
{
  Matrix result(g.rows(),g.columns()),position(3,g.columns()),speed(3,g.columns());
  for(UInt i=0;i<orbitPocAtmosphericWeights.size();i++)
  {
    Matrix integral(3,g.columns()),moment(3,g.columns()); Double dt=0;
    for(const auto &term:orbitPocAtmosphericWeights.at(i))
    {axpy(term.integral,g.row(3*term.index,3),integral);axpy(term.moment,g.row(3*term.index,3),moment);dt+=term.integral;}
    axpy(dt,speed,position);axpy(dt,integral,position);axpy(-1.,moment,position);speed+=integral;
    copy(velocity ? speed : position,result.row(3*(i+1),3));
  }
  return result;
}
'''
        cpp.write_text(text)
    h=root/'misc/observation/variationalEquation.h';text=h.read_text()
    if 'orbitPocEventWeights' not in text:
        text=replace(text,'  std::vector<UInt> orbitPocWindows;','  OrbitPoc::Quadrature orbitPocEventWeights;\n  std::map<UInt,Matrix> orbitPocEventCache;\n  std::vector<UInt> orbitPocWindows;')
        text=replace(text,'#include "files/fileSatelliteModel.h"','#include "files/fileSatelliteModel.h"\n#include "misc/orbitPoc/atmosphereEvents.h"\n#include <map>')
        h.write_text(text)
        cpp=h.with_suffix('.cpp');text=cpp.read_text()
        anchor='    orbitPocWindows = boundaries.empty() ? std::vector<UInt>() : orbitPocIntegrationWindows(arc_.times,boundaries,integrationDegree);'
        text=replace(text,anchor,anchor+'''\n    const auto events=parameterAcceleration ? parameterAcceleration->integrationDiscontinuities(arc_.times.front(),arc_.times.back()) : std::vector<Time>();
    orbitPocEventWeights=events.empty() ? OrbitPoc::Quadrature() : orbitPocEventQuadrature(arc_.times,boundaries,events,integrationDegree);''')
        anchor='    idIntegrand  = Integrand.size();'
        text=replace(text,anchor,anchor+'\n    orbitPocEventCache.clear();')
        anchor='    if(!orbitPocWindows.empty())\n    {'
        text=replace(text,anchor,'''    if(!orbitPocEventWeights.empty())
    {
      while(idEpochAlpha<idEpoch)
      {
        const auto &weights=orbitPocEventWeights.at(idEpochAlpha);
        for(const auto &term:weights)
        {
          auto item=orbitPocEventCache.find(term.index);
          if(item==orbitPocEventCache.end()) item=orbitPocEventCache.emplace(term.index,computeIntegrand(term.index)).first;
          axpy(term.integral,item->second,Alpha);
        }
        const UInt first=weights.front().index;
        while(!orbitPocEventCache.empty() && orbitPocEventCache.begin()->first<first) orbitPocEventCache.erase(orbitPocEventCache.begin());
        idEpochAlpha++;
      }
      return;
    }

'''+anchor)
        cpp.write_text(text)

    # Upgrade V1 hourly-only weights to the complete unchanged JB local-time model.
    cpp=root/'programs/preprocessing/preprocessingVariationalEquation.cpp';text=cpp.read_text()
    if 'orbitPocLocalMidnightEvents' not in text:
        text=replace(text,'#include "misc/orbitPoc/atmosphereEvents.h"','#include "misc/orbitPoc/atmosphereEvents.h"\n#include "misc/orbitPoc/atmosphereLocalEvents.h"')
        text=replace(text,'  MiscAccelerationsPtr orbitPocAtmosphericForce;','  MiscAccelerationsPtr orbitPocAtmosphericForce;\n  Bool orbitPocAtmosphericHasDensityKnots=FALSE;')
        anchor='    readConfig(config,"orbitPocAtmosphericForce",orbitPocAtmosphericForce,Config::OPTIONAL,"","identical atmospheric component for exact one-sided UTC-event quadrature");'
        text=replace(text,anchor,anchor+'\n    readConfig(config,"orbitPocAtmosphericHasDensityKnots",orbitPocAtmosphericHasDensityKnots,Config::DEFAULT,"0","use declared continuous knots for the log-density multiplier");')
        before='    if(orbitPocAtmosphericForce)\n      orbitPocAtmosphericWeights=orbitPocEventQuadrature(times,integrationBoundaries ? integrationBoundaries->times() : std::vector<Time>(),orbitPocAtmosphereEvents(times.front(),times.back()),integrationDegree);'
        text=replace(text,before,'')
        anchor='    // computeGravityGradient'
        block="""    if(orbitPocAtmosphericForce)
    {
      Matrix positions(3*epochCount,1);
      for(UInt i=0;i<epochCount;i++) copy(orbit.at(i).position.vector(),positions.row(3*i,3));
      auto events=orbitPocAtmosphereEvents(times.front(),times.back());
      const auto local=orbitPocLocalMidnightEvents(times,positions,rotEarth);
      events.insert(events.end(),local.begin(),local.end());
      orbitPocAtmosphericWeights=orbitPocEventQuadrature(times,
        (orbitPocAtmosphericHasDensityKnots && integrationBoundaries) ? integrationBoundaries->times() : std::vector<Time>(),events,integrationDegree);
    }

"""
        text=replace(text,anchor,block+anchor);cpp.write_text(text)
    cpp=root/'misc/observation/variationalEquation.cpp';text=cpp.read_text()
    if 'orbitPocLocalMidnightEvents' not in text:
        text=replace(text,'#include "misc/orbitPoc/integrationWindows.h"','#include "misc/orbitPoc/integrationWindows.h"\n#include "misc/orbitPoc/atmosphereLocalEvents.h"')
        before='    const auto events=parameterAcceleration ? parameterAcceleration->integrationDiscontinuities(arc_.times.front(),arc_.times.back()) : std::vector<Time>();'
        after="""    auto events=parameterAcceleration ? parameterAcceleration->integrationDiscontinuities(arc_.times.front(),arc_.times.back()) : std::vector<Time>();
    if(!events.empty())
    {const auto local=orbitPocLocalMidnightEvents(arc_.times,arc_.pos0,arc_.rotEarth);events.insert(events.end(),local.begin(),local.end());}"""
        text=replace(text,before,after);cpp.write_text(text)

    # Auxiliary native evaluations keep full polynomial degree when a true
    # atmospheric event lies less than one stencil width from a density knot.
    cpp=root/'programs/preprocessing/preprocessingVariationalEquation.cpp';text=cpp.read_text()
    if 'orbitPocAtmosphericExtraTimes' not in text:
        text=replace(text,'#include "misc/orbitPoc/atmosphereEvents.h"','#include "misc/orbitPoc/atmosphereEvents.h"\n#include "misc/orbitPoc/atmosphereExtraSamples.h"')
        text=replace(text,'  OrbitPoc::Quadrature orbitPocAtmosphericWeights;','  OrbitPoc::Quadrature orbitPocAtmosphericWeights;\n  std::vector<Time> orbitPocAtmosphericExtraTimes;')
        text=replace(text,'events,integrationDegree);','events,integrationDegree,&orbitPocAtmosphericExtraTimes);\n      orbitPocDrag=Vector(3*(epochCount+orbitPocAtmosphericExtraTimes.size()));')
        anchor='    if(parameterAcceleration)\n    {\n      parameterAcceleration->setIntervalArc'
        extra="""    if(orbitPocAtmosphericForce && !orbitPocAtmosphericExtraTimes.empty())
    {
      VariationalEquationArc reference;reference.times=times;reference.rotEarth=rotEarth;
      reference.pos0=Matrix(3*epochCount,1);reference.vel0=Matrix(3*epochCount,1);
      for(UInt i=0;i<epochCount;i++)
      {copy(orbit.at(i).position.vector(),reference.pos0.row(3*i,3));copy(orbit.at(i).velocity.vector(),reference.vel0.row(3*i,3));reference.rotSat.push_back(starCamera.at(i).rotary);}
      const auto knots=integrationBoundaries ? integrationBoundaries->times() : std::vector<Time>();
      const auto extra=orbitPocAtmosphereExtraSamples(reference,orbitPocAtmosphericExtraTimes,knots,knots);
      for(UInt i=0;i<extra.times.size();i++)
      {
        const auto earth=earthRotation->rotaryMatrix(extra.times.at(i));
        const Vector3d p(extra.pos0(3*i,0),extra.pos0(3*i+1,0),extra.pos0(3*i+2,0));
        const Vector3d v(extra.vel0(3*i,0),extra.vel0(3*i+1,0),extra.vel0(3*i+2,0));
        const auto drag=earth.inverseRotate(orbitPocAtmosphericForce->acceleration(satellite,extra.times.at(i),p,v,extra.rotSat.at(i),earth,ephemerides));
        copy(drag.vector(),orbitPocDrag.row(3*(epochCount+i),3));
      }
    }

"""
        # The unique block inside computeArc follows force/accelerometer assembly.
        text=replace(text,anchor,extra+anchor)
        text=text.replace('g-orbitPocDrag)','g-orbitPocDrag.row(0,g.rows()))').replace('acc0-orbitPocDrag)','acc0-orbitPocDrag.row(0,acc0.rows()))')
        text=replace(text,'Matrix result(g.rows(),g.columns()),position','Matrix result(3*(orbitPocAtmosphericWeights.size()+1),g.columns()),position')
        cpp.write_text(text)
    h=root/'misc/observation/variationalEquation.h';text=h.read_text()
    if 'orbitPocExtraArc' not in text:
        text=replace(text,'  OrbitPoc::Quadrature orbitPocEventWeights;','  VariationalEquationArc orbitPocExtraArc;\n  OrbitPoc::Quadrature orbitPocEventWeights;');h.write_text(text)
        cpp=h.with_suffix('.cpp');text=cpp.read_text()
        text=replace(text,'#include "misc/orbitPoc/atmosphereLocalEvents.h"','#include "misc/orbitPoc/atmosphereLocalEvents.h"\n#include "misc/orbitPoc/atmosphereExtraSamples.h"')
        before='    orbitPocEventWeights=events.empty() ? OrbitPoc::Quadrature() : orbitPocEventQuadrature(arc_.times,boundaries,events,integrationDegree);'
        after="""    std::vector<Time> extraTimes;
    orbitPocEventWeights=events.empty() ? OrbitPoc::Quadrature() : orbitPocEventQuadrature(arc_.times,boundaries,events,integrationDegree,&extraTimes);
    orbitPocExtraArc=orbitPocAtmosphereExtraSamples(arc_,extraTimes,boundaries,timePulse);"""
        text=replace(text,before,after)
        before='        const UInt first=weights.front().index;\n        while(!orbitPocEventCache.empty() && orbitPocEventCache.begin()->first<first) orbitPocEventCache.erase(orbitPocEventCache.begin());'
        after='        if(orbitPocEventCache.size()>64) orbitPocEventCache.clear(); // auxiliary indices are not chronological'
        text=replace(text,before,after)
        index=text.index('Matrix VariationalEquation::computeIntegrand(UInt idEpoch)')
        prefix,body=text[:index],text[index:]
        body=body.replace('arc_.','data.')
        body=replace(body,'    Vector3d pos  =','    const auto &data=(idEpoch<arc_.times.size()) ? arc_ : orbitPocExtraArc;\n    if(idEpoch>=arc_.times.size()) idEpoch-=arc_.times.size();\n    Vector3d pos  =')
        cpp.write_text(prefix+body)

    # A separately refined force mesh avoids dependence on the output-state
    # sampling. Both the force and its integrated parameter sensitivity use it.
    h=root/'classes/parametrizationAcceleration/parametrizationAcceleration.h';text=h.read_text()
    if 'integrationAtmosphereStep' not in text:
        text=replace(text,'  std::vector<Time> integrationDiscontinuities(const Time &start,const Time &end) const;','  std::vector<Time> integrationDiscontinuities(const Time &start,const Time &end) const;\n  Double integrationAtmosphereStep() const;')
        text=replace(text,'virtual std::vector<Time> integrationDiscontinuities(const Time &,const Time &) const {return {};}','virtual std::vector<Time> integrationDiscontinuities(const Time &,const Time &) const {return {};}\nvirtual Double integrationAtmosphereStep() const {return 1.;}')
        h.write_text(text)
        cpp=h.with_suffix('.cpp');cpp.write_text(cpp.read_text()+"""
Double ParametrizationAcceleration::integrationAtmosphereStep() const
{
  Double step=1.;
  for(auto item:parameter) step=std::min(step,item->integrationAtmosphereStep());
  return step;
}
""")
    cpp=root/'programs/preprocessing/preprocessingVariationalEquation.cpp';text=cpp.read_text()
    if 'orbitPocAtmosphericQuadratureStep' not in text:
        text=replace(text,'  Bool orbitPocAtmosphericHasDensityKnots=FALSE;','  Bool orbitPocAtmosphericHasDensityKnots=FALSE;\n  Double orbitPocAtmosphericQuadratureStep=1.;')
        anchor='    readConfig(config,"orbitPocAtmosphericHasDensityKnots",orbitPocAtmosphericHasDensityKnots,Config::DEFAULT,"0","use declared continuous knots for the log-density multiplier");'
        text=replace(text,anchor,anchor+'\n    readConfig(config,"orbitPocAtmosphericQuadratureStep",orbitPocAtmosphericQuadratureStep,Config::DEFAULT,"1","atmospheric force quadrature cadence in seconds; refined independently of the state grid");\n    if(!(orbitPocAtmosphericQuadratureStep>0.)) throw(Exception("positive atmospheric quadrature cadence required"));')
        text=replace(text,'events,integrationDegree,&orbitPocAtmosphericExtraTimes);','events,integrationDegree,&orbitPocAtmosphericExtraTimes,orbitPocAtmosphericQuadratureStep);');cpp.write_text(text)
        cpp=root/'misc/observation/variationalEquation.cpp';text=cpp.read_text()
        text=replace(text,'events,integrationDegree,&extraTimes);','events,integrationDegree,&extraTimes,parameterAcceleration->integrationAtmosphereStep());');cpp.write_text(text)

    cpp=root/'programs/preprocessing/preprocessingVariationalEquation.cpp';text=cpp.read_text()
    if 'ORBIT_POC_ATMOSPHERE_TRACE' not in text:
        text=replace(text,'#include "misc/orbitPoc/atmosphereExtraSamples.h"','#include "misc/orbitPoc/atmosphereExtraSamples.h"\n#include <fstream>')
        anchor='      for(UInt i=0;i<extra.times.size();i++)\n      {'
        text=replace(text,anchor,"""      std::ofstream trace;
      if(const char *path=std::getenv("ORBIT_POC_ATMOSPHERE_TRACE"))
      {trace.open(path);trace.precision(17);}
"""+anchor)
        anchor='        copy(drag.vector(),orbitPocDrag.row(3*(epochCount+i),3));'
        text=replace(text,anchor,anchor+"""
        if(trace.is_open())
        {
          trace<<(extra.times.at(i)-times.front()).seconds();
          for(UInt j=0;j<3;j++) trace<<' '<<p.vector()(j);
          for(UInt j=0;j<3;j++) trace<<' '<<v.vector()(j);
          const Vector q=extra.rotSat.at(i).quaternion();
          for(UInt j=0;j<4;j++) trace<<' '<<q(j);
          for(UInt j=0;j<3;j++) trace<<' '<<drag.vector()(j);
          trace<<'\\n';
        }
""")
        cpp.write_text(text)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source',type=Path);apply(parser.parse_args().source)
