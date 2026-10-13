"""Shared 64-bit dynamics, measurement functions, and frozen joint process noise.

States are internally scaled by fixed units for conditioning. Input/output public
measurement values remain metres and metres/second. No truth is accessed here.
"""
from functools import lru_cache
import math
import numpy as np
import jax
jax.config.update("jax_enable_x64", True)
import jax.numpy as jnp
from .config import MU, EARTH_RADIUS, J2, OMEGA, MASS, AREA, CD, RHO_500, SCALE_HEIGHT

def scales(spec):
    return np.array([1e6]*3 + [1e3]*3 + ([1e-6]*3 if spec.model == "colored" else [1.] if spec.model == "density" else []))

def rtn_basis(r, v):
    radial = r / jnp.linalg.norm(r)
    normal = jnp.cross(r, v)
    normal = normal / jnp.linalg.norm(normal)
    transverse = jnp.cross(normal, radial)
    return jnp.stack([radial, transverse, normal], axis=1)

def acceleration(r, v, log_density=0.0):
    radius = jnp.linalg.norm(r)
    central = -MU * r / radius**3
    z2 = (r[2] / radius)**2
    j2term = 1.5*J2*MU*EARTH_RADIUS**2/radius**5 * r * jnp.array([5*z2-1,5*z2-1,5*z2-3])
    relative_v = v - jnp.cross(jnp.array([0.,0.,OMEGA]), r)
    rho = RHO_500 * jnp.exp(-(radius-EARTH_RADIUS-500000.)/SCALE_HEIGHT + log_density)
    drag = -0.5*CD*AREA/MASS*rho*jnp.linalg.norm(relative_v)*relative_v
    return central+j2term+drag

@lru_cache(maxsize=128)
def _kernels(spec):
    # NumPy constants are safe when this factory is first reached inside a
    # JAX scan trace; capturing a newly created tracer in a cache is not.
    units = scales(spec)
    dim = spec.dimension
    # The supported dataset interval is at most 60 s, so a static loop permits
    # reverse autodiff in NUTS while respecting the maximum requested substep.
    nsub = int(math.ceil(60. / spec.substep))
    def rhs(z):
        physical = z*units
        r,v = physical[:3],physical[3:6]
        acc = acceleration(r,v,physical[6] if spec.model == "density" else 0.)
        if spec.model == "colored":
            acc = acc + rtn_basis(r,v) @ physical[6:9]
        if spec.model == "white":
            derivative = jnp.concatenate([v,acc])
        else:
            derivative = jnp.concatenate([v,acc,-physical[6:]/spec.tau])
        return derivative/units
    rhs_jac = jax.jacfwd(rhs)
    def step(z,dt):
        h = dt/nsub
        def body(_, y):
            a=rhs(y); b=rhs(y+h*a/2); c=rhs(y+h*b/2); d=rhs(y+h*c)
            return y+h*(a+2*b+2*c+d)/6
        return jax.lax.fori_loop(0,nsub,body,z)
    noise = np.zeros((dim,dim))
    noise[3:6,3:6] = np.eye(3)*spec.q_acc
    if spec.model == "colored":
        noise[6:9,6:9] = np.eye(3)*(2*spec.accel_sigma**2/spec.tau)
    elif spec.model == "density":
        noise[6,6] = 2*spec.sigma**2/spec.tau
    noise = noise/np.outer(units,units)
    def cov_step(z,dt):
        h=dt/nsub
        def aug_rhs(y,q):
            f=rhs_jac(y)
            return rhs(y), f@q+q@f.T+noise
        def body(_,carry):
            y,q=carry
            a,b=aug_rhs(y,q)
            c,d=aug_rhs(y+h*a/2,q+h*b/2)
            e,f=aug_rhs(y+h*c/2,q+h*d/2)
            g,k=aug_rhs(y+h*e,q+h*f)
            return y+h*(a+2*c+2*e+g)/6, q+h*(b+2*d+2*f+k)/6
        _,q = jax.lax.fori_loop(0,nsub,body,(z,jnp.zeros((dim,dim))))
        return (q+q.T)/2
    return (jax.jit(step),jax.jit(jax.vmap(step)),
            jax.jit(jax.vmap(jax.jacfwd(step,argnums=0))),
            jax.jit(jax.vmap(cov_step)),jax.jit(rhs),jax.jit(rhs_jac))

def transition(z,dt,spec):
    return _kernels(spec)[0](z,dt)

def batch_transition(z,dt,spec):
    return _kernels(spec)[1](jnp.asarray(z),jnp.broadcast_to(jnp.asarray(dt),(len(z),)))

def batch_transition_jacobian(z,dt,spec):
    return _kernels(spec)[2](jnp.asarray(z),jnp.broadcast_to(jnp.asarray(dt),(len(z),)))

def observe(z,station_pos,station_vel):
    r=z[:3]*1e6; v=z[3:6]*1e3
    delta=r-station_pos
    distance=jnp.linalg.norm(delta)
    rate=jnp.dot(delta,v-station_vel)/distance
    return jnp.array([distance,rate])

batch_observe = jax.jit(jax.vmap(observe))
batch_observe_jacobian = jax.jit(jax.vmap(jax.jacfwd(observe,argnums=0)))

def process_covariances(reference_z,times,spec):
    reference_z=np.asarray(reference_z)
    dt=np.diff(times)
    if np.any(dt <= 0) or np.any(dt > 60.000001):
        raise ValueError("Process intervals must be in (0,60] seconds")
    q=np.asarray(_kernels(spec)[3](reference_z[:-1],dt)).copy()
    # Stabilize in correlation units, avoiding an absolute floor that would
    # dominate physically small orbital diffusion after state scaling.
    d=np.sqrt(np.maximum(np.diagonal(q,axis1=1,axis2=2),1e-300))
    correlation=q/(d[:,:,None]*d[:,None,:])
    smallest=np.linalg.eigvalsh(correlation)[:,0]
    shift=np.maximum(0.,1e-12-smallest)
    q += np.eye(spec.dimension)[None,:,:]*(shift[:,None,None]*d[:,:,None]**2)
    np.linalg.cholesky(q)
    return q

def propagate(initial_state,times,spec):
    """Return normalized states; includes no stochastic innovations."""
    times=jnp.asarray(times)
    def scan(z,dt):
        nxt=transition(z,dt,spec)
        return nxt,nxt
    _,tail=jax.lax.scan(scan,jnp.asarray(initial_state),jnp.diff(times))
    return jnp.concatenate([jnp.asarray(initial_state)[None,:],tail],axis=0)
