"""The candidate must be explicit and reproduce the pinned installed source."""
from pathlib import Path
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "wide_tangent_installer", ROOT / "groops/extension/native_tangent_wide.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class WideTangentInstall(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "source"
        shutil.copytree(ROOT / "tests/fixtures/wide_tangent_baseline", self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_exact_sources_and_repeat(self):
        result = installer.apply(self.root)
        self.assertEqual(result["changed_files"], 7)
        self.assertTrue(result["candidate_only"])
        self.assertFalse(result["compiled"])
        for name, digest in result["source_hashes"].items():
            self.assertEqual(installer.sha((self.root / name).read_bytes()), digest)
            self.assertEqual((self.root / name).read_bytes(),
                             (installer.PAYLOAD / "proposed" / name).read_bytes())
        self.assertEqual(installer.apply(self.root)["changed_files"], 0)

    def test_bad_baseline_rejected_before_any_write(self):
        path = self.root / "programs/preprocessing/preprocessingVariationalEquation.cpp"
        path.write_bytes(path.read_bytes() + b"\n// different source\n")
        before = {str(p.relative_to(self.root)): p.read_bytes()
                  for p in self.root.rglob("*") if p.is_file()}
        with self.assertRaises(ValueError):
            installer.apply(self.root)
        self.assertEqual(before, {str(p.relative_to(self.root)): p.read_bytes()
                                 for p in self.root.rglob("*") if p.is_file()})

    def test_unknown_new_file_rejected(self):
        (self.root / "misc/orbitPoc/wideInterpolationExport.h").write_text("different")
        with self.assertRaises(ValueError):
            installer.apply(self.root)

    def test_symlink_target_rejected(self):
        path = self.root / "base/polynomial.cpp"
        other = path.with_name("original.cpp")
        path.rename(other)
        path.symlink_to(other)
        with self.assertRaises(ValueError):
            installer.apply(self.root)

    def test_noncanonical_target_rejected(self):
        with self.assertRaises(ValueError):
            installer.apply(self.root / "base/..")

    def test_changed_payload_rejected_before_writes(self):
        payload = Path(self.temporary.name) / "payload"
        shutil.copytree(installer.PAYLOAD, payload)
        path = payload / "proposed/misc/orbitPoc/wideSixStateTangent.h"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(ValueError):
            installer.apply(self.root, payload_root=payload)
        self.assertFalse((self.root / "misc/orbitPoc/wideSixStateTangent.h").exists())

    def test_unknown_manifest_option_rejected(self):
        payload = Path(self.temporary.name) / "payload"
        shutil.copytree(installer.PAYLOAD, payload)
        path = payload / "manifest.json"
        value = json.loads(path.read_text())
        value["relax_tolerance"] = True
        path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            installer.apply(self.root, payload_root=payload)

    def test_explicit_option_requires_segmented_before_source_access(self):
        absent = Path(self.temporary.name) / "absent"
        process = subprocess.run(
            [sys.executable, str(ROOT / "scripts/build_groops.py"),
             "--source-dir", str(absent), "--build-dir", str(absent / "build"),
             "--wide-tangent-candidate"], capture_output=True, text=True)
        self.assertEqual(process.returncode, 2)
        self.assertIn("--wide-tangent-candidate requires --segmented", process.stderr)
        self.assertFalse(absent.exists())


if __name__ == "__main__":
    unittest.main()
