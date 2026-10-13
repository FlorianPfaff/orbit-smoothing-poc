import numpy as np
from dataclasses import replace
from orbit_poc.config import ModelSpec, MU, EARTH_RADIUS, OMEGA
from orbit_poc.dynamics import (scales, transition, batch_transition_jacobian,
    observe, batch_observe_jacobian, process_covariances, propagate, rtn_basis)

def state(spec):
    r=EARTH_RADIUS+500000.
    return np.r_[r,0.,0.,0.,np.sqrt(MU/r)*np.cos(.8),np.sqrt(MU/r)*np.sin(.8),np.zeros(spec.dimension-6)]/scales(spec)

def test_autodiff_transition_matches_scaled_central_differences():
    for name in ('white','colored','density'):
        spec=ModelSpec(model=name)
        z=state(spec)
        actual=np.asarray(batch_transition_jacobian(z[None,:],np.array([60.]),spec))[0]
        eps=1e-5
        columns=[]
        for j in range(spec.dimension):
            dz=np.eye(spec.dimension)[j]*eps
            columns.append((np.asarray(transition(z+dz,60.,spec))-np.asarray(transition(z-dz,60.,spec)))/(2*eps))
        numeric=np.array(columns).T
        assert np.linalg.norm(actual-numeric)/np.linalg.norm(actual) < 1e-4

def test_measurements_and_jacobians():
    spec=ModelSpec()
    z=state(spec)
    p=np.array([EARTH_RADIUS,0.,0.]); v=np.cross([0.,0.,OMEGA],p)
    y=np.asarray(observe(z,p,v))
    np.testing.assert_allclose(y,[500000.,0.],atol=1e-8)
    h=np.asarray(batch_observe_jacobian(z[None,:],p[None,:],v[None,:]))[0]
    eps=1e-6
    numeric=np.array([(np.asarray(observe(z+eps*e,p,v))-np.asarray(observe(z-eps*e,p,v)))/(2*eps) for e in np.eye(spec.dimension)]).T
    # Scale each observable by its measurement noise before comparing.
    wh=np.array([10.,.01])[:,None]
    assert np.linalg.norm((h-numeric)/wh)/np.linalg.norm(h/wh) < 1e-4

def test_joint_covariance_positive_with_orbit_force_cross_terms():
    for name in ('white','colored','density'):
        spec=ModelSpec(model=name)
        z=state(spec)
        q=process_covariances(np.array([z,z]),np.array([0.,60.]),spec)[0]
        np.linalg.cholesky(q)
        np.testing.assert_allclose(q,q.T,atol=1e-30)
        if name!='white':
            assert np.linalg.norm(q[:6,6:]) > 0
            if name=='density':
                expected=spec.sigma**2*(1-np.exp(-120/spec.tau))
                np.testing.assert_allclose(q[6,6],expected,rtol=1e-8)

def test_integrator_refinement_at_tracking_precision():
    spec=ModelSpec()
    ts=np.arange(0.,21600.1,60.)
    coarse=np.asarray(propagate(state(spec),ts,spec))*scales(spec)
    fine=np.asarray(propagate(state(spec),ts,replace(spec,substep=spec.substep/2)))*scales(spec)
    assert np.max(np.linalg.norm(coarse[:,:3]-fine[:,:3],axis=1)) < .1
    assert np.max(np.linalg.norm(coarse[:,3:6]-fine[:,3:6],axis=1)) < 1e-4

def test_rtn_basis_is_right_handed_orthonormal():
    z=state(ModelSpec())*scales(ModelSpec())
    b=np.asarray(rtn_basis(z[:3],z[3:6]))
    np.testing.assert_allclose(b.T@b,np.eye(3),atol=1e-14)
    np.testing.assert_allclose(np.linalg.det(b),1.,atol=1e-14)
