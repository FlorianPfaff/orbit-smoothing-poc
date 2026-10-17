"""Pure exact-dyadic decoder/lift tests; no compiler or orbit propagation."""
from pathlib import Path
from fractions import Fraction as F
import copy,importlib.util,json,sys,unittest
D=Path(__file__).resolve().parents[1]
P=D/'src/orbit_poc/segmented/tangent_export.py'
spec=importlib.util.spec_from_file_location('draft_tangent_export',P);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
def exact(i):return dict(mode='exact',derivative=0,anchor=None,terms=[[i,'0x1p+0','0x0p+0']])
def anchored(anchor=0):return dict(mode='anchored_twofold',derivative=0,anchor=anchor,terms=[[0,'0x1p-1','0x1p-70'],[1,'0x1p-1','0x0p+0']])
def basic(schema=m.V2,drag=False):
 meta=dict(kind='metadata',schema=schema,profile='flight_gravity_drag_v1'if drag else'synthetic_complete_v1',epochs=2,dt=5.,initial_velocity_scale=.2,maximum_tangent_relative_residual=1e-12,nominal_force_history='unchanged_whole_arc',new_process_priors=False,forcing_design='separate_native_variation_of_constants_export')
 if schema==m.V2:meta['interpolation_semantics']=m.SEMANTICS
 rows=[meta]
 for channel,count in [('main',2)]+([('drag',3)]if drag else[]):
  for i in range(count):
   row=dict(kind='sample',channel=channel,index=i,time=[60000,.0 if i==0 else .001],Ar=[.125]+[0.]*8,Av=[.03125]+[0.]*8)
   if schema==m.V2:row.update(position_stencil=exact(i)if i<2 else anchored(1),velocity_stencil=exact(i)if i<2 else anchored(0))
   else:row.update(position_halo=[[i,1.,'0x1p+0','0x0p+0']],velocity_halo=[[i,1.,'0x1p+0','0x0p+0']])
   rows.append(row)
  rows.append(dict(kind='quadrature',channel=channel,interval=0,terms=[[0,2.5,4.],[1,2.5,8.5]]if channel=='main'else[[2,1.,2.]]))
 return rows+[dict(kind='complete')]
class TypedLift(unittest.TestCase):
 def test_hex_low_component_exact(self):self.assertEqual(m.hexadecimal('0x8.000000000000001p-4'),F(1,2)+F(1,2**64))
 def test_hex_negative_exact(self):self.assertEqual(m.hexadecimal('-0x1.8p+2'),-6)
 def test_hex_negative_zero_exact(self):self.assertEqual(m.hexadecimal('-0x0p+0'),0)
 def test_constant_anchored_preserved_not_normalized_guess(self):
  s=m.decode_stencil(anchored(0),m.V2,2);self.assertEqual(s.evaluate([F(1),F(1)]),1)
  raw=sum((a+b for a,b in zip(s.high,s.low)),F(0));self.assertEqual(raw,1+F(1,2**70))
 def test_actual_anchor_changes_non_normalized_map(self):
  a=m.decode_stencil(anchored(0),m.V2,2);b=m.decode_stencil(anchored(1),m.V2,2)
  self.assertEqual(a.evaluate([F(2),F(3)]),F(5,2));self.assertEqual(b.evaluate([F(2),F(3)]),F(5,2)-F(1,2**70))
 def test_low_state_survives_exact_node(self):
  x=1+F(1,2**80);self.assertEqual(m.decode_stencil(exact(0),m.V2,2).evaluate([x,0]),x)
 def test_ordinary_is_not_anchored(self):
  x=anchored();x.update(mode='ordinary',anchor=None);s=m.decode_stencil(x,m.V2,2);self.assertEqual(s.evaluate([1,1]),1+F(1,2**70))
 def test_anchor_coefficients_match_branch_exactly(self):
  for anchor in (0,1):
   s=m.decode_stencil(anchored(anchor),m.V2,2);x=[F(17,8)+F(1,2**85),F(-3,7)];self.assertEqual(sum((v*x[i]for i,v in s.coefficients()),F(0)),s.evaluate(x))
 def test_legacy_flat_schema_retained(self):
  s=m.decode_stencil([[0,.5,'0x1p-1','0x1p-70'],[1,.5,'0x1p-1','0x0p+0']],m.V1,2);self.assertEqual(s.mode,'legacy_flat');self.assertEqual(s.evaluate([1,1]),1+F(1,2**70))
 def test_both_versions_build_identical_exact_grid_rows(self):
  a=m.lift_tangent_export(basic(m.V1));b=m.lift_tangent_export(basic());self.assertEqual(a.rows,b.rows);self.assertEqual(a.initial_rhs,b.initial_rhs)
 def test_extra_drag_position_velocity_anchors_are_distinct(self):
  a=m.lift_tangent_export(basic(drag=True));p,v=a.stencils['drag',2];self.assertEqual(p.anchor,1);self.assertEqual(v.anchor,0);self.assertNotEqual(p.coefficients(),v.coefficients())
 def test_lift_uses_anchor_corrected_coefficients(self):
  a=m.lift_tangent_export(basic(drag=True));b=m.lift_tangent_export(basic());self.assertEqual(a.rows[6][0]-b.rows[6][0],-F(3,8)*(F(1,2)+F(1,2**70)))
 def test_velocity_coupling_retained(self):
  a=m.lift_tangent_export(basic(drag=True));b=m.lift_tangent_export(basic());self.assertEqual(a.rows[6][3]-b.rows[6][3],-F(3,32)*F(1,2))
 def test_explicit_rounding_ledger_retains_low_error(self):
  a=m.lift_tangent_export(basic(drag=True));entries,rhs,receipt=a.binary64();self.assertTrue(receipt['rounded_nonexact_entries']);self.assertEqual(receipt['nonzero_coefficients_discarded'],0)
  lookup={(r,c):v for r,c,v in entries};entry=next(e for e in receipt['rounded_nonexact_entries']if e['location']==('matrix',6,0));self.assertEqual(F(int(entry['error_numerator']),int(entry['error_denominator'])),F(lookup[6,0])-a.rows[6][0])
 def test_flight_missing_drag_channel_rejected(self):
  x=basic();x[0]['profile']='flight_gravity_drag_v1'
  with self.assertRaises(ValueError):m.lift_tangent_export(x)
 def test_synthetic_extra_drag_channel_rejected(self):
  x=basic(drag=True);x[0]['profile']='synthetic_complete_v1'
  with self.assertRaises(ValueError):m.lift_tangent_export(x)
 def test_unknown_schema_rejected(self):
  x=basic();x[0]['schema']='orbit-poc-segmented-tangent-v3'
  with self.assertRaises(ValueError):m.lift_tangent_export(x)
 def test_unknown_semantics_rejected(self):
  x=basic();x[0]['interpolation_semantics']='normalized_flat'
  with self.assertRaises(ValueError):m.lift_tangent_export(x)
 def test_unknown_metadata_rejected(self):
  x=basic();x[0]['ridge']=1e-9
  with self.assertRaises(ValueError):m.lift_tangent_export(x)
 def test_mixed_sample_schema_rejected(self):
  x=basic();x[1]['position_halo']=[[0,1,'0x1p+0','0x0p+0']]
  with self.assertRaises(ValueError):m.lift_tangent_export(x)
 def test_missing_terminal_rejected(self):
  with self.assertRaises(ValueError):m.lift_tangent_export(basic()[:-1])
 def test_duplicate_sample_rejected(self):
  x=basic();x.insert(1,copy.deepcopy(x[1]))
  with self.assertRaises(ValueError):m.lift_tangent_export(x)
 def test_missing_quadrature_rejected(self):
  x=basic();x=[r for r in x if r['kind']!='quadrature']
  with self.assertRaises(ValueError):m.lift_tangent_export(x)
 def test_absent_sample_dependency_rejected(self):
  x=basic();x[-2]['terms'][0][0]=9
  with self.assertRaises(ValueError):m.lift_tangent_export(x)
 def test_unknown_channel_rejected(self):
  x=basic();x[1]['channel']='radiation'
  with self.assertRaises(ValueError):m.lift_tangent_export(x)
 def test_resource_limit_fails_explicitly(self):
  with self.assertRaises(ValueError):m.lift_tangent_export(basic(),maximum_epochs=1)
 def test_native_guard_not_relaxed(self):
  x=basic();x[0]['maximum_tangent_relative_residual']=3e-12
  with self.assertRaises(ValueError):m.lift_tangent_export(x)
 def test_unknown_mode_rejected(self):
  x=anchored();x['mode']='nearest'
  with self.assertRaises(ValueError):m.decode_stencil(x,m.V2,2)
 def test_derivative_not_silently_reused(self):
  x=anchored();x['derivative']=1
  with self.assertRaises(ValueError):m.decode_stencil(x,m.V2,2)
 def test_missing_anchor_rejected(self):
  x=anchored();x['anchor']=None
  with self.assertRaises(ValueError):m.decode_stencil(x,m.V2,2)
 def test_anchor_outside_support_rejected(self):
  x=anchored();x['anchor']=2
  with self.assertRaises(ValueError):m.decode_stencil(x,m.V2,2)
 def test_ordinary_cannot_invent_anchor(self):
  x=anchored();x['mode']='ordinary'
  with self.assertRaises(ValueError):m.decode_stencil(x,m.V2,2)
 def test_exact_mode_cannot_hide_weights(self):
  x=exact(0);x['terms'][0][2]='0x1p-70'
  with self.assertRaises(ValueError):m.decode_stencil(x,m.V2,2)
 def test_repeated_nodes_rejected(self):
  x=anchored();x['terms'][1][0]=0
  with self.assertRaises(ValueError):m.decode_stencil(x,m.V2,2)
 def test_grid_index_outside_rejected(self):
  with self.assertRaises(ValueError):m.decode_stencil(exact(2),m.V2,2)
 def test_float_anchor_rejected(self):
  x=anchored();x['anchor']=0.
  with self.assertRaises(ValueError):m.decode_stencil(x,m.V2,2)
 def test_legacy_rounded_value_mismatch_rejected(self):
  with self.assertRaises(ValueError):m.decode_stencil([[0,2.,'0x1p+0','0x0p+0']],m.V1,2)
 def test_nan_hex_rejected(self):
  with self.assertRaises(ValueError):m.hexadecimal('nan')
 def test_excessive_hex_exponent_rejected(self):
  with self.assertRaises(ValueError):m.hexadecimal('0x1p+99999999')
 def test_nonfinite_jacobian_rejected(self):
  x=basic();x[1]['Ar'][0]=float('nan')
  with self.assertRaises(ValueError):m.lift_tangent_export(x)
 def test_nonzero_underflow_never_dropped(self):
  a=m.lift_tangent_export(basic());a.rows[0][0]=F(1,2**1100)
  with self.assertRaises(ValueError):a.binary64()
 def test_overflow_rejected(self):
  a=m.lift_tangent_export(basic());a.rows[0][0]=F(2**1100)
  with self.assertRaises(ValueError):a.binary64()
 def test_integer_exact_rows_no_rounding_claim(self):
  a=m.ExactTangentLift({'schema':m.V2},[{0:F(1)}],[[F(1)]],{});entries,rhs,r=a.binary64();self.assertEqual(r['rounded_nonexact_entries'],[])
 def test_final_state_and_old_queries_not_used(self):
  x=basic();x[1]['covariance']=[1.]
  with self.assertRaises(ValueError):m.lift_tangent_export(x)
if __name__=='__main__':unittest.main()
