// SPDX-License-Identifier: GPL-3.0-or-later
// Included inside PreprocessingVariationalEquation::computeArc, after the
// unchanged force/Enke evaluation. The legacy branch below remains untouched.
if(orbitPocDerivativeProfile!="legacy_v3")
{
  if(parameterAcceleration || accelerometer.size())
    throw(Exception("staged Jacobians do not support fitted force parametrizations or measured accelerometer forces"));
  const Bool synthetic=orbitPocDerivativeProfile=="synthetic_complete_v1";
  if(!synthetic && !orbitPocAtmosphericForce)
    throw(Exception("flight_gravity_drag_v1 requires the matching orbitPocAtmosphericForce"));
  using OrbitPoc::ForceJacobian;
  const UInt offset=3*epochCount;
  std::vector<ForceJacobian> mainJac(epochCount),dragJac(epochCount+orbitPocAtmosphericExtraTimes.size());
  Double maximumFdDifference=0,maximumPositionAbsoluteDifference=0,maximumVelocityAbsoluteDifference=0;
  Double maximumPositionUnflooredRelativeDifference=0,maximumVelocityUnflooredRelativeDifference=0;
  UInt fdEvaluations=0,fdRefinements=0,positionFloorAppliedColumns=0,velocityFloorAppliedColumns=0;
  Double minimumPositionStep=std::numeric_limits<Double>::infinity(),maximumPositionStep=0;
  Double minimumVelocityStep=std::numeric_limits<Double>::infinity(),maximumVelocityStep=0;
  auto vector3=[](const Vector3d &v){return OrbitPoc::Vec3{v.x(),v.y(),v.z()};};
  auto dragDerivative=[&](const Time &time,const Vector3d &p,const Vector3d &v,const Rotary3d &sat,const Rotary3d &earth)
  {
    auto force=[&](const OrbitPoc::Vec3 &position,const OrbitPoc::Vec3 &velocity)
    {
      return vector3(earth.inverseRotate(orbitPocAtmosphericForce->acceleration(satellite,time,
          Vector3d(position[0],position[1],position[2]),Vector3d(velocity[0],velocity[1],velocity[2]),sat,earth,ephemerides)));
    };
    OrbitPoc::RefinedForceJacobian derivative;
    try {// JB2008/HWM native subroutines contain finite-precision intermediates.
    // 1000 m starts above their spatial roundoff floor; the unchanged half-step
    // agreement criterion controls truncation error. A dimensioned near-zero
    // position-column bound (2e-18 s^-2) avoids meaningless relative rejection.
    derivative=OrbitPoc::refinedForceJacobian(force,vector3(p),vector3(v),1000.,1e-3,2e-3,4,1e-15,1e-17);}
    catch(const std::exception &error)
    {
      std::ostringstream context;context.precision(17);
      context<<error.what()<<", GPS MJD="<<time.mjd()<<", position="<<p.x()<<","<<p.y()<<","<<p.z()
             <<", velocity="<<v.x()<<","<<v.y()<<","<<v.z();
      throw(Exception(context.str()));
    }
    maximumFdDifference=std::max(maximumFdDifference,derivative.maximumRelativeDifference);
    maximumPositionAbsoluteDifference=std::max(maximumPositionAbsoluteDifference,derivative.maximumPositionAbsoluteDifference);
    maximumVelocityAbsoluteDifference=std::max(maximumVelocityAbsoluteDifference,derivative.maximumVelocityAbsoluteDifference);
    maximumPositionUnflooredRelativeDifference=std::max(maximumPositionUnflooredRelativeDifference,derivative.maximumPositionUnflooredRelativeDifference);
    maximumVelocityUnflooredRelativeDifference=std::max(maximumVelocityUnflooredRelativeDifference,derivative.maximumVelocityUnflooredRelativeDifference);
    positionFloorAppliedColumns+=derivative.positionFloorAppliedColumns;
    velocityFloorAppliedColumns+=derivative.velocityFloorAppliedColumns;
    minimumPositionStep=std::min(minimumPositionStep,derivative.minimumPositionStep);
    maximumPositionStep=std::max(maximumPositionStep,derivative.maximumPositionStep);
    minimumVelocityStep=std::min(minimumVelocityStep,derivative.minimumVelocityStep);
    maximumVelocityStep=std::max(maximumVelocityStep,derivative.maximumVelocityStep);
    fdEvaluations+=derivative.evaluations;fdRefinements=std::max(fdRefinements,UInt(derivative.maximumRefinements));
    return derivative.jacobian;
  };
  for(UInt i=0;i<epochCount;i++)
  {
    if(synthetic)
    {
      Matrix position(3,3),velocity(3,3);
      forces->orbitPocSyntheticJacobian(satellite,times.at(i),orbit.at(i).position,orbit.at(i).velocity,
          starCamera.at(i).rotary,rotEarth.at(i),ephemerides,position,velocity);
      for(UInt r=0;r<3;r++)for(UInt c=0;c<3;c++)
      {mainJac[i].position[3*r+c]=position(r,c);mainJac[i].velocity[3*r+c]=velocity(r,c);}
    }
    else
    {
      // This is the actual forward gravity object, including its configured
      // truncation. It is independent of the old low-degree gradientfield.
      const Matrix gravity=forces->orbitPocForwardGravityGradient(times.at(i),orbit.at(i).position,rotEarth.at(i)).matrix();
      for(UInt r=0;r<3;r++)for(UInt c=0;c<3;c++)mainJac[i].position[3*r+c]=gravity(r,c);
      dragJac[i]=dragDerivative(times.at(i),orbit.at(i).position,orbit.at(i).velocity,starCamera.at(i).rotary,rotEarth.at(i));
    }
  }
  const auto boundaries=integrationBoundaries ? integrationBoundaries->times() : std::vector<Time>();
  OrbitPocPiecewisePolynomial stateInterpolation(times,7,boundaries,boundaries);
  if(!synthetic && !orbitPocAtmosphericExtraTimes.empty())
  {
    VariationalEquationArc reference;reference.times=times;reference.rotEarth=rotEarth;
    reference.pos0=Matrix(offset,1);reference.vel0=Matrix(offset,1);
    for(UInt i=0;i<epochCount;i++)
    {copy(orbit.at(i).position.vector(),reference.pos0.row(3*i,3));copy(orbit.at(i).velocity.vector(),reference.vel0.row(3*i,3));reference.rotSat.push_back(starCamera.at(i).rotary);}
    const auto extra=orbitPocAtmosphereExtraSamples(reference,orbitPocAtmosphericExtraTimes,boundaries,boundaries);
    for(UInt i=0;i<extra.times.size();i++)
      dragJac[epochCount+i]=dragDerivative(extra.times[i],Vector3d(extra.pos0(3*i,0),extra.pos0(3*i+1,0),extra.pos0(3*i+2,0)),
          Vector3d(extra.vel0(3*i,0),extra.vel0(3*i+1,0),extra.vel0(3*i+2,0)),extra.rotSat[i],earthRotation->rotaryMatrix(extra.times[i]));
  }
  std::vector<ForceJacobian> preconditionJac=mainJac;
  if(!synthetic)for(UInt i=0;i<epochCount;i++)for(UInt j=0;j<9;j++)
  {preconditionJac[i].position[j]+=dragJac[i].position[j];preconditionJac[i].velocity[j]+=dragJac[i].velocity[j];}
  // Preserve the exact native polynomial coefficients and boundary windows,
  // but avoid a day-long subtraction of two large accumulated moments.
  OrbitPoc::Quadrature mainWeights(epochCount-1);
  UInt coefficientIndex=0,evaluationPoint=0;
  for(UInt i=0;i+1<epochCount;i++)
  {
    if(!orbitPocWindows.empty())coefficientIndex=evaluationPoint=i-orbitPocWindows.at(i);
    for(UInt k=0;k<coeff_g.at(coefficientIndex).rows();k++)
      mainWeights[i].push_back({i+k-evaluationPoint,deltaT*coeff_g.at(coefficientIndex)(k),
                               deltaT*deltaT*coeff_tg.at(coefficientIndex)(k)});
    if(i<integrationDegree/2){coefficientIndex++;evaluationPoint++;}
    if(i>=epochCount-1-integrationDegree/2-1){coefficientIndex++;evaluationPoint++;}
  }
  auto samples=[](const_MatrixSliceRef matrix)
  {
    if(matrix.columns()!=1)throw(Exception("staged force integral requires one column"));
    std::vector<long double> result(matrix.rows());
    for(UInt i=0;i<matrix.rows();i++)result[i]=matrix(i,0);
    return result;
  };
  // Rebuild interpolation metadata with every whole-arc linearization. The
  // same physical sample times and native position/velocity stencils are used.
  std::vector<OrbitPoc::WideInterpolation::Stencil> extraPositionStencil,extraVelocityStencil;
  if(!synthetic && !orbitPocAtmosphericExtraTimes.empty())
  {
    extraPositionStencil=stateInterpolation.orbitPocWideStateStencils(orbitPocAtmosphericExtraTimes,FALSE);
    extraVelocityStencil=stateInterpolation.orbitPocWideStateStencils(orbitPocAtmosphericExtraTimes,TRUE);
  }
  auto integratedJacobianWide=[&](const OrbitPoc::WideTangentVector &state)
  {
    if(state.size()!=2*offset)throw(Exception("wide tangent state dimension mismatch"));
    std::vector<long double> acceleration(offset);
    for(UInt i=0;i<epochCount;i++)for(UInt r=0;r<3;r++)for(UInt c=0;c<3;c++)
      acceleration[3*i+r]+=static_cast<long double>(mainJac[i].position[3*r+c])*state[3*i+c]
                          +static_cast<long double>(mainJac[i].velocity[3*r+c])*state[offset+3*i+c];
    auto result=OrbitPoc::wideTangentIntegrate(mainWeights,deltaT,acceleration);
    if(!synthetic)
    {
      std::vector<long double> drag(3*dragJac.size());
      for(UInt i=0;i<epochCount;i++)for(UInt r=0;r<3;r++)for(UInt c=0;c<3;c++)
        drag[3*i+r]+=static_cast<long double>(dragJac[i].position[3*r+c])*state[3*i+c]
                   +static_cast<long double>(dragJac[i].velocity[3*r+c])*state[offset+3*i+c];
      for(UInt i=0;i<orbitPocAtmosphericExtraTimes.size();i++)
      {
        std::array<long double,3> extraP{},extraV{};
        for(UInt c=0;c<3;c++)
        {
          extraP[c]=OrbitPoc::WideInterpolation::evaluate(extraPositionStencil[i],
              [&](std::size_t epoch){return state.at(3*epoch+c);});
          extraV[c]=OrbitPoc::WideInterpolation::evaluate(extraVelocityStencil[i],
              [&](std::size_t epoch){return state.at(offset+3*epoch+c);});
        }
        for(UInt r=0;r<3;r++)for(UInt c=0;c<3;c++)
          drag[3*(epochCount+i)+r]+=static_cast<long double>(dragJac[epochCount+i].position[3*r+c])*extraP[c]
                                 +static_cast<long double>(dragJac[epochCount+i].velocity[3*r+c])*extraV[c];
      }
      const auto integratedDrag=OrbitPoc::wideTangentIntegrate(orbitPocAtmosphericWeights,deltaT,drag);
      for(UInt i=0;i<result.size();i++)result[i]+=integratedDrag[i];
    }
    return result;
  };
  UInt maximumTangentIterations=0;Double maximumTangentResidual=0;
  auto solveCoupled=[&](const_MatrixSliceRef p,const_MatrixSliceRef v,const char *role)
  {
    Matrix outP(offset,p.columns()),outV(offset,p.columns());
    for(UInt c=0;c<p.columns();c++)
    {
      OrbitPoc::TangentVector rhs(2*offset);for(UInt i=0;i<offset;i++){rhs[i]=p(i,c);rhs[offset+i]=v(i,c);}
      OrbitPoc::TangentSolveResult result;
      try {result=OrbitPoc::solveSixStateTangentWide(preconditionJac,deltaT,integratedJacobianWide,rhs);}
      catch(const std::exception &error)
      {
        std::ostringstream context;context.precision(17);
        context<<error.what()<<", solve_role="<<role<<", column="<<c<<", duration_seconds="<<T;
        throw(Exception(context.str()));
      }
      maximumTangentIterations=std::max(maximumTangentIterations,UInt(result.iterations));
      maximumTangentResidual=std::max(maximumTangentResidual,result.relativeResidual);
      for(UInt i=0;i<offset;i++){outP(i,c)=result.state[i];outV(i,c)=result.state[offset+i];}
    }
    return std::make_pair(std::move(outP),std::move(outV));
  };
  Matrix pBasis(offset,6),vBasis(offset,6);
  for(UInt i=0;i<epochCount;i++)for(UInt j=0;j<3;j++)
  {pBasis(3*i+j,j)=1;pBasis(3*i+j,3+j)=i*deltaT/T;vBasis(3*i+j,3+j)=1/T;}
  auto integratedForce=OrbitPoc::tangentIntegrate(mainWeights,deltaT,
      samples(orbitPocAtmosphericForce ? Matrix(g-orbitPocDrag.row(0,g.rows())) : Matrix(g)));
  if(orbitPocAtmosphericForce)
  {
    const auto integratedDrag=OrbitPoc::tangentIntegrate(orbitPocAtmosphericWeights,deltaT,samples(orbitPocDrag));
    for(UInt i=0;i<integratedForce.size();i++)integratedForce[i]+=integratedDrag[i];
  }
  Matrix approximateVelocity(offset,1);for(UInt i=0;i<epochCount;i++)copy(orbit.at(i).velocity.vector(),approximateVelocity.row(3*i,3));
  // Keep the mean solve in residual coordinates. Forming a full absolute
  // position first and then subtracting posApprox discards sub-nanometre
  // residual information before the coupled solve. The same cancellation
  // occurs if the final homogeneous fit recovers its RHS from a rounded orbit.
  // BEGIN ORBIT_POC_MEAN_RESIDUAL_ARITHMETIC (also compiled by the focused test)
  auto meanResidual=[](Double reference,Double approximate,Double integral)
  {
    return static_cast<Double>((static_cast<long double>(reference)-approximate)
                               +static_cast<long double>(integral));
  };
  auto restoreMean=[](Double approximate,Double correction)
  {
    return static_cast<Double>(static_cast<long double>(approximate)
                               +static_cast<long double>(correction));
  };
  // END ORBIT_POC_MEAN_RESIDUAL_ARITHMETIC
  Matrix residualPosition(offset,1),residualVelocity(offset,1);
  for(UInt i=0;i<offset;i++)
  {
    if(synthetic)
    {
      // Preserve the precise reference's low part until the residual has a
      // small magnitude. The coupled solve and archive remain native doubles.
      residualPosition(i,0)=OrbitPoc::preciseReferenceMeanResidual(posRef(i),orbitPocReferencePositionLow[i],posApprox(i),integratedForce[i]);
      residualVelocity(i,0)=OrbitPoc::preciseReferenceMeanResidual(velRef(i),orbitPocReferenceVelocityLow[i],approximateVelocity(i,0),integratedForce[offset+i]);
    }
    else
    {
      residualPosition(i,0)=meanResidual(posRef(i),posApprox(i),integratedForce[i]);
      residualVelocity(i,0)=meanResidual(velRef(i),approximateVelocity(i,0),integratedForce[offset+i]);
    }
  }
  const Vector initial=leastSquares(Matrix(pBasis),-1.*residualPosition);
  matMult(1,pBasis,initial,residualPosition);matMult(1,vBasis,initial,residualVelocity);
  auto correction=solveCoupled(residualPosition,residualVelocity,"physical_correction");
  auto tangent=solveCoupled(pBasis,vBasis,"state_transition");
  const Vector initialCorrection=leastSquares(Matrix(tangent.first),-1.*correction.first);
  matMult(1,tangent.first,initialCorrection,correction.first);
  matMult(1,tangent.second,initialCorrection,correction.second);
  Matrix position(offset,1),velocity(offset,1);
  for(UInt i=0;i<offset;i++)
  {
    position(i,0)=restoreMean(posApprox(i),correction.first(i,0));
    velocity(i,0)=restoreMean(approximateVelocity(i,0),correction.second(i,0));
  }
  VariationalEquationArc arc;arc.times=times;arc.pos0=position;arc.vel0=velocity;
  arc.PosState=tangent.first;arc.VelState=tangent.second;arc.rotEarth=rotEarth;
  for(UInt i=0;i<epochCount;i++)arc.rotSat.push_back(starCamera.at(i).rotary);
  maxPosDiff=std::max(maxPosDiff,maxabs(arc.pos0-posApprox));
  logInfo<<"  six-state Jacobian "<<orbitPocDerivativeProfile<<", tangent residual "<<maximumTangentResidual
         <<", FD refinement "<<maximumFdDifference<<Log::endl;
  if(!orbitPocDerivativeDiagnostics.empty())
  {
    if(orbitFile.arcCount()!=1)throw(Exception("derivative diagnostics currently require exactly one arc"));
    std::ofstream out(orbitPocDerivativeDiagnostics.str());if(!out)throw(Exception("cannot write derivative diagnostics"));out.precision(17);
    out<<"{\"schema\":\"orbit-poc-derivatives-3.1\",\"profile\":\""<<orbitPocDerivativeProfile
       <<"\",\"coordinates\":\"CRF SI\",\"gravity_source\":\"actual_forward_force\",\"maximum_tangent_relative_residual\":"<<maximumTangentResidual
       <<",\"tangent_internal_arithmetic\":\"wide_returned_binary64_guard_v1\",\"tangent_integral_accumulation\":\"long_double_local_moments\",\"tangent_accumulator_binary_digits\":"<<std::numeric_limits<long double>::digits
       <<",\"mean_solve_coordinates\":\"residual_then_single_absolute_restore_v1\""
       <<",\"reference_kinematics\":\""<<(synthetic ? "fitted_equinoctial_long_double_low_parts_v1" : "unchanged_flight_reference")<<"\""
       <<",\"maximum_reference_position_precision_difference_m\":"<<orbitPocReferencePositionDifference
       <<",\"maximum_reference_velocity_precision_difference_m_s\":"<<orbitPocReferenceVelocityDifference
       <<",\"remaining_mean_precision_limit\":\"native_double_RHS_absolute_archive_and_initial_reanchoring\""
       <<",\"synthetic_force_arithmetic\":\""<<(synthetic ? "configured_crf_parts_stable_reference_v1" : "unchanged_flight_forward")<<"\""
       <<",\"reference_GM_m3_s2\":"<<GM
       <<",\"maximum_tangent_iterations\":"<<maximumTangentIterations<<",\"drag_fd_evaluations\":"<<fdEvaluations
       <<",\"drag_fd_maximum_refinements\":"<<fdRefinements<<",\"drag_fd_maximum_relative_difference\":"<<maximumFdDifference
       <<",\"drag_fd_position_derivative_floor_s_minus2\":"<<(synthetic ? 0 : 1e-15)
       <<",\"drag_fd_velocity_derivative_floor_s_minus1\":"<<(synthetic ? 0 : 1e-17)
       <<",\"drag_fd_position_absolute_tolerance_s_minus2\":"<<(synthetic ? 0 : 2e-18)
       <<",\"drag_fd_velocity_absolute_tolerance_s_minus1\":"<<(synthetic ? 0 : 2e-20)
       <<",\"drag_fd_position_floor_applied_columns\":"<<positionFloorAppliedColumns
       <<",\"drag_fd_velocity_floor_applied_columns\":"<<velocityFloorAppliedColumns
       <<",\"drag_fd_maximum_position_absolute_difference_s_minus2\":"<<maximumPositionAbsoluteDifference
       <<",\"drag_fd_maximum_velocity_absolute_difference_s_minus1\":"<<maximumVelocityAbsoluteDifference
       <<",\"drag_fd_maximum_position_unfloored_relative_difference\":"<<maximumPositionUnflooredRelativeDifference
       <<",\"drag_fd_maximum_velocity_unfloored_relative_difference\":"<<maximumVelocityUnflooredRelativeDifference
       <<",\"drag_fd_initial_position_step_m\":"<<(synthetic ? 0 : 1000)
       <<",\"drag_fd_position_step_range_m\":["<<(synthetic ? 0 : minimumPositionStep)<<","<<maximumPositionStep<<"]"
       <<",\"drag_fd_initial_velocity_step_m_s\":"<<(synthetic ? 0 : 1e-3)
       <<",\"drag_fd_velocity_step_range_m_s\":["<<(synthetic ? 0 : minimumVelocityStep)<<","<<maximumVelocityStep<<"]"
       <<",\"initial_velocity_parameter_scale\":"<<1/T<<",\"pulse_units\":\"micrometres_per_second\",\"omitted_terms\":";
    out<<(synthetic ? "[]" : "[\"thermal_history_sensitivities\",\"non_gravity_non_drag_force_gradients\",\"atmospheric_event_time_derivatives\"]");
    out<<"}\n";if(!out)throw(Exception("failed to write derivative diagnostics"));
  }

  // ORBIT_POC_SEGMENTED_TANGENT_EXPORT_V4
  // V2 deliberately omits legacy flattened halos. Only a typed consumer may
  // accept mode/anchor/high+low semantics from the ACTUAL batch traversal.
  if(!orbitPocSegmentedTangentExport.empty())
  {
    if(orbitFile.arcCount()!=1)throw(Exception("segmented tangent export requires one arc"));
    if(extraPositionStencil.size()!=orbitPocAtmosphericExtraTimes.size() ||
       extraVelocityStencil.size()!=orbitPocAtmosphericExtraTimes.size())
      throw(Exception("typed tangent export missing actual atmospheric batch metadata"));
    using namespace OrbitPoc::SegmentedExport;
    std::ofstream out(orbitPocSegmentedTangentExport.str());out.precision(17);
    if(!out)throw(Exception("cannot open segmented tangent export"));
    out<<"{\"kind\":\"metadata\",\"schema\":\"orbit-poc-segmented-tangent-v2\",\"profile\":";string(out,orbitPocDerivativeProfile);
    out<<",\"epochs\":"<<epochCount<<",\"dt\":"<<deltaT<<",\"initial_velocity_scale\":"<<1/T
       <<",\"maximum_tangent_relative_residual\":"<<maximumTangentResidual
       <<",\"interpolation_semantics\":\"actual_batch_mode_anchor_high_low_v1\""
       <<",\"nominal_force_history\":\"unchanged_whole_arc\",\"new_process_priors\":false,\"forcing_design\":\"separate_native_variation_of_constants_export\"}\n";
    for(UInt i=0;i<epochCount;i++)
    {
      out<<"{\"kind\":\"sample\",\"channel\":\"main\",\"index\":"<<i<<",\"time\":";time(out,times.at(i));out<<',';jacobian(out,mainJac[i]);
      const auto grid=OrbitPoc::WideInterpolationExport::identity(i);
      out<<",\"position_stencil\":";OrbitPoc::WideInterpolationExport::stencil(out,grid,epochCount);
      out<<",\"velocity_stencil\":";OrbitPoc::WideInterpolationExport::stencil(out,grid,epochCount);out<<"}\n";
    }
    quadrature(out,"main",mainWeights);
    if(!synthetic)
    {
      for(UInt i=0;i<dragJac.size();i++)
      {
        const auto timeValue=i<epochCount?times.at(i):orbitPocAtmosphericExtraTimes.at(i-epochCount);
        out<<"{\"kind\":\"sample\",\"channel\":\"drag\",\"index\":"<<i<<",\"time\":";time(out,timeValue);out<<',';jacobian(out,dragJac[i]);
        const auto grid=OrbitPoc::WideInterpolationExport::identity(i<epochCount?i:0);
        const auto &position=i<epochCount?grid:extraPositionStencil.at(i-epochCount);
        const auto &velocity=i<epochCount?grid:extraVelocityStencil.at(i-epochCount);
        out<<",\"position_stencil\":";OrbitPoc::WideInterpolationExport::stencil(out,position,epochCount);
        out<<",\"velocity_stencil\":";OrbitPoc::WideInterpolationExport::stencil(out,velocity,epochCount);out<<"}\n";
      }
      quadrature(out,"drag",orbitPocAtmosphericWeights);
    }
    out<<"{\"kind\":\"complete\"}\n";if(!out)throw(Exception("segmented tangent export failed"));
  }

  return arc;
}
