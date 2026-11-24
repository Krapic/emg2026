"""Run the offline report on the bundled laboratory recordings and reference model."""

import contextlib
import importlib.util
import io
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / 'grip_data/models/5a7118ac2e564532a642e958fdc0eb69.json'

spec = importlib.util.spec_from_file_location('analiza', ROOT / 'scripts/analiza.py')
analiza = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analiza)


def report(*arguments):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        status = analiza.main(list(arguments))
    return status, output.getvalue()


@unittest.skipUnless(MODEL.is_file(), 'Priložene snimke i model nisu u grip_data.')
class BundledDataTests(unittest.TestCase):
    def test_reference_model_reproduces_documented_validation(self):
        status, text = report('evaluate', str(MODEL))
        self.assertEqual(status, 0)
        self.assertIn('P01_validacija (validacija): 5900 redaka, MAE 3.57 N, RMSE 4.17 N', text)

    def test_validation_without_grip_is_flagged(self):
        status, text = report()
        self.assertEqual(status, 0)
        self.assertIn('! P01_validacija: praćeno je 0 od 4 zadanih razina stiska.', text)
        self.assertIn('validacija P01_validacija: stisak je u samo 0 % redaka', text)
        self.assertNotIn('! P01_mvc', text)

    def test_phases_show_target_and_held_force(self):
        status, text = report('check', 'P01_ucenje')
        self.assertEqual(status, 0)
        self.assertEqual(text.count('nije praćeno'), 4)

    def test_unknown_recording_is_an_error(self):
        status, text = report('check', 'nepostojeca')
        self.assertEqual(status, 1)
        self.assertIn('GREŠKA: Nema snimke', text)


if __name__ == '__main__':
    unittest.main()
