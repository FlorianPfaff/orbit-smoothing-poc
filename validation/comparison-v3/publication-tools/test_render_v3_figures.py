"""Scratch semantic checks; no actual evaluation data are read."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('figures',Path(__file__).with_name('render_v3_figures.py'))
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


class FigureTests(unittest.TestCase):
    def test_fixed_orientation_reverses_bounds_and_preserves_denominators(self):
        value=r.oriented({'method_a':r.PULSES,'method_b':r.DENSITY,'valid_seed_pairs':47,
            'bootstrap_unit':'paired independent seed',
            'planned_seed_pairs':50,'failed_or_missing_seed_pairs':3,
            'mean_difference_a_minus_b':2.,'bootstrap_95_interval':[-1.,5.]})
        self.assertEqual(value['mean'],-2.)
        self.assertEqual(value['interval'],[-5.,1.])
        self.assertEqual((value['valid'],value['planned'],value['missing']),(47,50,3))

    def test_unavailable_is_not_converted_to_zero(self):
        _,report=r.fixture()
        value=r.comparison(report['paired_metrics'],'leo300/quiet/normal','whole_arc.position_rmse_m')
        self.assertIsNone(value['mean']);self.assertIsNone(value['interval'])
        coverage=r.coverage_row(report['fixed_epoch_coverage'],r.PULSES,13)
        self.assertIsNone(coverage['estimate']);self.assertIsNone(coverage['interval'])
        self.assertEqual(coverage['failed_or_unavailable_seeds'],50)

    def test_bad_denominators_and_published_bundle_are_rejected(self):
        _,report=r.fixture();row=report['paired_metrics'][2].copy();row['planned_seed_pairs']=49
        with self.assertRaisesRegex(ValueError,'denominator'):r.oriented(row)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'publication.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'immutable'):r.render_bundle(root)

    def test_fixture_has_all_fixed_primary_and_secondary_metrics(self):
        _,report=r.fixture()
        for orbit in r.ORBITS:
            for atmo,coverage in r.SCENARIOS:
                for metric in ('whole_arc.position_rmse_m','gap.position_rmse_m'):
                    r.comparison(report['paired_metrics'],'/'.join((orbit,atmo,coverage)),metric)

    def test_epoch_bootstrap_and_inconsistent_coverage_are_rejected(self):
        _,report=r.fixture()
        paired=report['paired_metrics'][1].copy();paired['bootstrap_unit']='trajectory epoch'
        with self.assertRaisesRegex(ValueError,'independent seeds'):r.oriented(paired)
        row=report['fixed_epoch_coverage'][0]
        row['estimate']=.93
        with self.assertRaisesRegex(ValueError,'disagrees'):r.coverage_row(report['fixed_epoch_coverage'],r.DENSITY,11)
        row['estimate']=row['successes']/row['trials'];row['confidence']=.90
        with self.assertRaisesRegex(ValueError,'confidence level'):r.coverage_row(report['fixed_epoch_coverage'],r.DENSITY,11)


if __name__=='__main__':unittest.main()
