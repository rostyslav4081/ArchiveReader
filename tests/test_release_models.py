import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


class ReleaseModelTests(unittest.TestCase):
    def fixture(self, root):
        spec = importlib.util.spec_from_file_location('release_models', Path(__file__).resolve().parents[1] / 'scripts/package_release_models.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.__file__ = str(root / 'scripts/package_release_models.py')
        metadata = root / 'docs/release-models'
        metadata.mkdir(parents=True)
        item = {'group': 'PolishWords', 'folder': 'example', 'repository': 'example/model', 'revision': 'fixed-revision', 'files': {'model.safetensors': hashlib.sha256(b'weights').hexdigest()}, 'license': 'MIT'}
        (metadata / 'manifest.json').write_text(json.dumps([item]), 'utf-8')
        (metadata / 'README.md').write_text('Installation and limitations', 'utf-8')
        model = root / 'model-work-PolishWords/models/example'
        model.mkdir(parents=True)
        output = root / 'assets'
        return module, model, output

    def test_verified_weights_are_packaged_with_provenance_and_checksums(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            module, model, output = self.fixture(root)
            (model / 'model.safetensors').write_bytes(b'weights')
            with patch('sys.argv', ['package', '--group', 'PolishWords', '--output', str(output)]), patch.object(module.urllib.request, 'urlopen', side_effect=AssertionError('No download needed')):
                module.main()
            archive = next(output.glob('*.zip'))
            with zipfile.ZipFile(archive) as package:
                self.assertEqual(package.read('models/example/model.safetensors'), b'weights')
                self.assertIn('model-licenses/ATTRIBUTION.json', package.namelist())
            self.assertIn(module.sha256(archive), (output / 'PolishWords-SHA256SUMS.txt').read_text())

    def test_mismatching_download_cannot_create_a_release_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            module, model, output = self.fixture(Path(temp))
            with patch('sys.argv', ['package', '--group', 'PolishWords', '--output', str(output)]), patch.object(module.urllib.request, 'urlopen', return_value=io.BytesIO(b'wrong weights')):
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    module.main()
            self.assertFalse(list(output.glob('*.zip')))
            self.assertFalse((model / 'model.safetensors').exists())
