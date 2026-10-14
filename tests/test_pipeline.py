"""Integration tests for STEP conversion and incremental publishing behavior."""
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PipelineTest(unittest.TestCase):
    def test_conversion_and_catalog_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns('__pycache__', '.git'))

            # Keep this test deterministic even when users add large community models.
            for step in (root / 'originais').rglob('*'):
                if step.suffix.lower() in ('.step', '.stp') and step.name != 'portico-exemplo.step':
                    step.unlink()

            def run():
                return subprocess.run(
                    [sys.executable, str(root / 'scripts/converter.py')],
                    capture_output=True,
                    text=True,
                    timeout=240,
                )

            def catalog():
                return json.loads((root / 'catalogo.json').read_text())

            (root / 'catalogo.json').unlink(missing_ok=True)
            first = run()
            self.assertEqual(first.returncode, 0, first.stderr)
            model = catalog()['models'][0]
            self.assertEqual(model['mesh_instances'], 3)
            self.assertEqual(model['materials'], 2)
            self.assertEqual(model['triangles'], 36)

            glb = root / model['file']
            raw = glb.read_bytes()
            size = struct.unpack_from('<I', raw, 12)[0]
            document = json.loads(raw[20:20 + size])
            self.assertEqual([len(m['primitives']) for m in document['meshes']], [1, 1, 1])

            q = math.sqrt(0.5)
            for scene in document['scenes']:
                scene_root = document['nodes'][scene['nodes'][0]]
                self.assertEqual(scene_root['name'], 'STEP Z-up to glTF Y-up')
                for actual, expected in zip(scene_root['rotation'], [-q, 0.0, 0.0, q]):
                    self.assertAlmostEqual(actual, expected)
                self.assertNotIn('scale', scene_root)

            # RWGltf converts STEP length units to meters directly: sample width is 3.2 m.
            position_ids = [
                p['attributes']['POSITION']
                for mesh in document['meshes']
                for p in mesh['primitives']
            ]
            lo = min(document['accessors'][i]['min'][0] for i in position_ids)
            hi = max(document['accessors'][i]['max'][0] for i in position_ids)
            self.assertAlmostEqual(hi - lo, 3.2)

            before = hashlib.sha256(raw).hexdigest()
            stamp = glb.stat().st_mtime_ns
            second = run()
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn('0 convertidos', second.stdout)
            self.assertEqual(stamp, glb.stat().st_mtime_ns)

            # Metadata-only edit should change the label, not geometry.
            meta = root / 'originais/portico-exemplo.json'
            data = json.loads(meta.read_text())
            data['name'] = 'Nome atualizado'
            meta.write_text(json.dumps(data))
            self.assertEqual(run().returncode, 0)
            self.assertEqual(catalog()['models'][0]['name'], 'Nome atualizado')
            self.assertEqual(before, hashlib.sha256(glb.read_bytes()).hexdigest())

            # A corrupt incoming STEP must not replace the published catalog.
            published = (root / 'catalogo.json').read_bytes()
            invalid = root / 'originais/invalido.step'
            invalid.write_text('not a STEP')
            failed = run()
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(published, (root / 'catalogo.json').read_bytes())
            invalid.unlink()

            # Repeated filenames in different directories must coexist.
            another = root / 'originais/outro'
            another.mkdir()
            shutil.copyfile(root / 'originais/portico-exemplo.step', another / 'portico-exemplo.step')
            duplicate = run()
            self.assertEqual(duplicate.returncode, 0, duplicate.stderr)
            entries = catalog()['models']
            self.assertEqual(len(entries), 2)
            self.assertNotEqual(entries[0]['file'], entries[1]['file'])

            # Regression: STEP assemblies may legally reuse subassembly names.
            import cadquery as cq
            part = cq.Workplane().box(10, 10, 10)
            sub1 = cq.Assembly(name='sub1').add(part, name='cube')
            sub2 = cq.Assembly(name='sub2').add(part, name='cube')
            assy = cq.Assembly(name='root')
            assy.add(sub1, name='sub1')
            assy.add(sub2, name='sub2', loc=cq.Location((20, 0, 0)))
            patterned = root / 'originais/patterned.step'
            assy.export(str(patterned))
            text = patterned.read_text()
            patterned.write_text(text.replace("'sub1'", "'pattern'").replace("'sub2'", "'pattern'"))
            patterned_run = run()
            self.assertEqual(patterned_run.returncode, 0, patterned_run.stderr)
            self.assertTrue(any(m['source'].endswith('patterned.step') for m in catalog()['models']))

            # Source deletion removes only the corresponding generated files.
            for step in (root / 'originais').rglob('*'):
                if step.suffix.lower() in ('.step', '.stp'):
                    step.unlink()
            self.assertEqual(run().returncode, 0)
            self.assertEqual(catalog()['models'], [])
            self.assertFalse(list((root / 'modelos').glob('*.glb')))


if __name__ == '__main__':
    unittest.main()
