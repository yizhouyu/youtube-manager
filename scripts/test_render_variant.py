#!/usr/bin/env python3
"""Offline regression tests for the isolated comparison renderer; no real media is touched."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).with_name('render_variant.py')
SPEC = importlib.util.spec_from_file_location('render_variant_under_test', SCRIPT)
RENDER_VARIANT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RENDER_VARIANT)


class RenderVariantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='yt-render-variant-test-')
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        self.raw = self.project / '01 - Unedited'
        self.edit = self.project / '02 - Export' / 'edit'
        self.raw.mkdir(parents=True)
        (self.raw / 'protected.txt').write_text('raw media stays untouched', encoding='utf-8')
        (self.edit / 'music').mkdir(parents=True)
        (self.edit / 'captions.srt').write_text('source captions', encoding='utf-8')
        self.variant_dir = self.root / 'alternate'
        overlay = self.variant_dir / 'edit-assets' / 'music'
        overlay.mkdir(parents=True)
        (overlay / 'generated-track.wav').write_bytes(b'generated dependency')
        self.variant = self.variant_dir / 'cut.edl.json'
        self.variant_payload = {
            'shots': [{'id': 'shot-1', 'clip': 'clip-1', 'in': 0, 'out': 1, 'enabled': True}],
            'output': {'width': 1920, 'height': 1080},
            'variant_metadata': {'editable_assets': 'edit-assets'},
        }
        self.variant.write_text(json.dumps(self.variant_payload), encoding='utf-8')
        self.output = self.project / '02 - Export' / 'manus-demo' / 'cut-v1.mov'

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, output, run_mock):
        argv = ['render_variant.py', str(self.project), str(self.variant), '--output', str(output)]
        with patch.object(sys, 'argv', argv), patch.object(RENDER_VARIANT.subprocess, 'run', side_effect=run_mock):
            RENDER_VARIANT.main()

    @staticmethod
    def fake_renderer(width=3840, height=2160):
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            if command[0] == 'ffprobe':
                return SimpleNamespace(stdout=json.dumps({'streams': [{'width': width, 'height': height}]}))
            stage = Path(command[3])
            export = stage / '02 - Export'
            (export / f'{stage.name}.mov').write_bytes(b'mock rendered master')
            (stage / '02 - Export' / 'edit' / 'captions.srt').write_text('rendered captions', encoding='utf-8')
            return SimpleNamespace(returncode=0)

        return calls, run

    def test_delivers_assets_forced_4k_and_reproducible_edl_without_touching_source(self):
        calls, fake_run = self.fake_renderer()
        original_edl = self.variant.read_bytes()
        self.invoke(self.output, fake_run)

        self.assertEqual(self.output.read_bytes(), b'mock rendered master')
        self.assertEqual((self.output.parent / 'cut-v1.assets' / 'music' / 'generated-track.wav').read_bytes(), b'generated dependency')
        delivered_edl = json.loads(self.output.with_suffix('.edl.json').read_text(encoding='utf-8'))
        self.assertEqual((delivered_edl['output']['width'], delivered_edl['output']['height']), (3840, 2160))
        self.assertEqual(delivered_edl['variant_metadata']['editable_assets'], 'cut-v1.assets')
        manifest = json.loads(self.output.with_suffix('.manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['editable_assets'], 'cut-v1.assets')
        self.assertEqual(self.variant.read_bytes(), original_edl)
        self.assertEqual((self.raw / 'protected.txt').read_text(encoding='utf-8'), 'raw media stays untouched')
        self.assertEqual(len(calls), 2, 'one render and one ffprobe validation')

    def test_refuses_existing_delivery_before_running_renderer(self):
        self.output.parent.mkdir(parents=True)
        self.output.write_bytes(b'keep existing master')
        with patch.object(sys, 'argv', ['render_variant.py', str(self.project), str(self.variant), '--output', str(self.output)]), \
             patch.object(RENDER_VARIANT.subprocess, 'run') as run:
            with self.assertRaisesRegex(SystemExit, 'Refusing to overwrite'):
                RENDER_VARIANT.main()
        run.assert_not_called()
        self.assertEqual(self.output.read_bytes(), b'keep existing master')

    def test_rejects_non_4k_render_before_publishing_any_files(self):
        calls, fake_run = self.fake_renderer(width=1920, height=1080)
        with self.assertRaisesRegex(SystemExit, 'not 4K UHD'):
            self.invoke(self.output, fake_run)
        self.assertEqual(len(calls), 2)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_suffix('.edl.json').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
