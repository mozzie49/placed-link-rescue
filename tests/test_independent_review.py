"""Independent compatibility/safety regressions for the deliberately narrow v0 subset."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, DictionaryObject, FloatObject, NameObject,
                           NumberObject, TextStringObject)
from make_fixtures import create

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/placed-link-rescue/scripts/placed_link_rescue.py'
spec = importlib.util.spec_from_file_location('review_rescue', SCRIPT)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

class IndependentReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.TemporaryDirectory()
        create(Path(cls.base.name) / 'base')

    @classmethod
    def tearDownClass(cls):
        cls.base.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name) / 'fixture'
        shutil.copytree(Path(self.base.name) / 'base', self.directory)
        self.map = self.directory / 'reviewed-map.json'
        self.out = self.directory / 'output'

    def tearDown(self):
        self.temp.cleanup()

    def edit_pdf(self, fn, source=False):
        name = 'advertisements.pdf' if source else 'magazine-export.pdf'
        path = self.directory / name
        # Fresh original each time, including table-driven refusal cases.
        writer = PdfWriter(clone_from=PdfReader(Path(self.base.name) / 'base' / name))
        fn(writer)
        with path.open('wb') as handle:
            writer.write(handle)
        data = json.loads(self.map.read_text())
        record = data['sources']['ads'] if source else data['target']
        record['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.map.write_text(json.dumps(data))
        return path

    def refuse(self, match):
        with self.assertRaisesRegex(r.RescueError, match):
            r.repair(self.map, self.out)
        self.assertFalse(self.out.exists())

    def test_source_hash_change_is_refused(self):
        path = self.directory / 'advertisements.pdf'
        path.write_bytes(path.read_bytes() + b'\n')
        self.refuse('hash mismatch: ads')

    def test_indirect_source_uri_retains_exact_destination(self):
        def mutate(writer):
            action = writer.pages[0]['/Annots'][0].get_object()['/A']
            action[NameObject('/URI')] = writer._add_object(action['/URI'])
        self.edit_pdf(mutate, source=True)
        receipt = r.repair(self.map, self.out)
        self.assertEqual(receipt['added'], 3)
        self.assertIn('https://example.org/still?edition=fall&ref=print', [item['uri'] for item in receipt['links']])

    def test_indirect_target_annotations_are_preserved(self):
        def mutate(writer):
            writer.pages[0][NameObject('/Annots')] = writer._add_object(writer.pages[0]['/Annots'])
            annot = writer.pages[0]['/Annots'][0].get_object()
            annot[NameObject('/Dest')] = ArrayObject([writer.pages[1].indirect_reference, NameObject('/XYZ'), NumberObject(0), NumberObject(576), NumberObject(0)])
        self.edit_pdf(mutate)
        receipt = r.repair(self.map, self.out)
        self.assertTrue(receipt['verification']['existing_annotations_unchanged'])
        reader = PdfReader(self.out / 'digital.pdf')
        self.assertEqual(reader.get_page_number(reader.pages[0]['/Annots'][0].get_object()['/Dest'][0].get_object()), 1)
        import fitz
        with fitz.open(self.out / 'digital.pdf') as independent:
            link = independent[0].get_links()[0]
            self.assertEqual(link['kind'], fitz.LINK_GOTO)
            self.assertEqual(link['page'], 1)

    def test_fractional_rotation_is_not_silently_truncated(self):
        for value in (0.5, -0.5, 360.5):
            with self.subTest(value=value):
                self.edit_pdf(lambda writer: writer.pages[1].__setitem__(NameObject('/Rotate'), FloatObject(value)))
                self.refuse('rotation|Rotate|Rotated')

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO check')
    def test_fifo_map_is_refused_without_blocking(self):
        fifo = self.directory / 'pipe.json'
        os.mkfifo(fifo)
        result = subprocess.run([sys.executable, str(SCRIPT), 'repair', '--map', str(fifo), '--output-dir', str(self.out)], capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)['status'], 'refused')
        self.assertFalse(self.out.exists())

    def test_unknown_and_active_link_actions_are_refused(self):
        for action in ('/Launch', '/GoToR', '/GoToE', '/SubmitForm', '/ImportData', '/RichMediaExecute', '/JavaScript', '/Unknown'):
            with self.subTest(action=action):
                def mutate(writer):
                    annot = writer.pages[0]['/Annots'][0].get_object()
                    annot[NameObject('/A')] = DictionaryObject({NameObject('/S'): NameObject(action)})
                self.edit_pdf(mutate, source=True)
                self.refuse('Unsupported PDF action')

    def test_external_stream_file_references_are_refused(self):
        def mutate(writer):
            page = writer.pages[0]
            stream = page['/Contents'].get_object()
            stream[NameObject('/F')] = TextStringObject('/etc/passwd')
        self.edit_pdf(mutate, source=True)
        self.refuse('Unsupported PDF feature: /F')

    def test_unsafe_source_uri_schemes_are_not_restored(self):
        def mutate(writer):
            action = writer.pages[0]['/Annots'][0].get_object()['/A']
            action[NameObject('/URI')] = TextStringObject('javascript:alert(1)')
        self.edit_pdf(mutate, source=True)
        receipt = r.repair(self.map, self.out)
        self.assertEqual(receipt['added'], 2)
        skipped = receipt['skipped_source_annotations']
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]['kind'], 'unsupported-uri-scheme')
        self.assertEqual(skipped[0]['uri'], 'javascript:alert(1)')
        raw_output = (self.out / 'digital.pdf').read_bytes()
        self.assertNotIn(b'javascript', raw_output)

    def test_target_unsafe_uri_is_not_silently_preserved(self):
        def mutate(writer):
            action = writer.pages[4]['/Annots'][0].get_object()['/A']
            action[NameObject('/URI')] = TextStringObject('file:///etc/passwd')
        self.edit_pdf(mutate)
        self.refuse('Unsupported preserved URI')

    def test_embedded_files_and_signature_dictionary_are_refused(self):
        for key, value in [('/AF', ArrayObject()), ('/ByteRange', ArrayObject()), ('/AcroForm', DictionaryObject())]:
            with self.subTest(key=key):
                self.edit_pdf(lambda writer: writer.root_object.__setitem__(NameObject(key), value))
                self.refuse('Unsupported PDF feature')

    def test_duplicate_source_annotation_is_reported_separately(self):
        def mutate(writer):
            annotations = writer.pages[0]['/Annots']
            annotations.append(annotations[0])
        self.edit_pdf(mutate, source=True)
        receipt = r.repair(self.map, self.out)
        self.assertEqual(receipt['added'], 3)
        self.assertEqual(receipt['already_present'], 0)
        self.assertEqual(receipt['source_duplicates'], 1)
        duplicates = [item for item in receipt['links'] if item['status'] == 'source-duplicate']
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]['source_page'], 1)
        self.assertEqual(duplicates[0]['annotation'], 1)
        actual, _ = r.links(PdfReader(self.out / 'digital.pdf').pages[3])
        self.assertEqual(len(actual), 1)

    def test_explicit_goto_action_is_preserved(self):
        def mutate(writer):
            annot = writer.pages[0]['/Annots'][0].get_object()
            annot.pop('/Dest')
            annot[NameObject('/A')] = writer._add_object(DictionaryObject({
                NameObject('/S'): NameObject('/GoTo'),
                NameObject('/D'): ArrayObject([writer.pages[1].indirect_reference,
                    NameObject('/XYZ'), NumberObject(10), NumberObject(560), NumberObject(0)])
            }))
        self.edit_pdf(mutate)
        receipt = r.repair(self.map, self.out)
        self.assertTrue(receipt['verification']['existing_annotations_unchanged'])
        import fitz
        with fitz.open(self.directory / 'magazine-export.pdf') as before, fitz.open(self.out / 'digital.pdf') as after:
            a = before[0].get_links()[0]
            b = after[0].get_links()[0]
            self.assertEqual({k: v for k, v in a.items() if k != 'xref'}, {k: v for k, v in b.items() if k != 'xref'})
            self.assertEqual(b['kind'], fitz.LINK_GOTO)
            self.assertEqual(b['page'], 1)

    def test_overlapping_source_hotspots_are_refused(self):
        def mutate(writer):
            original = writer.pages[0]['/Annots'][0].get_object()
            duplicate = DictionaryObject(dict(original))
            duplicate[NameObject('/Rect')] = ArrayObject([NumberObject(x) for x in (32, 83, 281, 113)])
            writer.pages[0]['/Annots'].append(writer._add_object(duplicate))
        self.edit_pdf(mutate, source=True)
        self.refuse('Conflicting/overlapping')

    def test_geometry_box_differences_are_refused(self):
        self.edit_pdf(lambda writer: writer.pages[1].__setitem__(NameObject('/TrimBox'), ArrayObject([NumberObject(x) for x in (5, 5, 427, 571)])))
        self.refuse('identical geometry')

    def test_limits_refuse_before_rendering(self):
        with patch.object(r, 'MAX_FILE_BYTES', 8), patch.object(r, 'render', side_effect=AssertionError('renderer called')):
            self.refuse('PDF exceeds')
        with patch.object(r, 'MAX_TOTAL_BYTES', 8), patch.object(r, 'render', side_effect=AssertionError('renderer called')):
            self.refuse('Inputs exceed total')
        with patch.object(r, 'MAX_NODES', 1), patch.object(r, 'render', side_effect=AssertionError('renderer called')):
            self.refuse('safety bounds')

    def test_unavailable_or_failed_renderer_leaves_no_bundle(self):
        with patch.object(r.shutil, 'which', return_value=None):
            self.refuse('Poppler')
        self.assertFalse(any(self.directory.glob('.placed-link-rescue-*')))
        with patch.object(r.subprocess, 'run', side_effect=subprocess.TimeoutExpired('pdftoppm', 45)):
            self.refuse('timed out')
        self.assertFalse(any(self.directory.glob('.placed-link-rescue-*')))

    def test_runtime_version_failure_keeps_verified_result(self):
        actual_run = subprocess.run
        for case in ('timeout', 'empty'):
            with self.subTest(case=case):
                def invoke(command, *args, **kwargs):
                    if '-v' in command:
                        if case == 'timeout':
                            raise subprocess.TimeoutExpired(command, 5)
                        return subprocess.CompletedProcess(command, 0, stdout='', stderr='')
                    return actual_run(command, *args, **kwargs)
                destination = self.directory / ('version-' + case)
                with patch.object(r.subprocess, 'run', side_effect=invoke):
                    receipt = r.repair(self.map, destination)
                self.assertEqual(receipt['runtime']['Poppler'], 'unavailable')
                self.assertTrue(receipt['verification']['target_rendering_unchanged'])
                self.assertEqual(receipt['added'], 3)
                self.assertEqual(len(PdfReader(destination / 'digital.pdf').pages), 5)

    def test_existing_output_symlink_is_never_followed(self):
        self.out.symlink_to(self.directory, target_is_directory=True)
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.directory.iterdir() if p.is_file()}
        with self.assertRaisesRegex(r.RescueError, 'already exists'):
            r.repair(self.map, self.out)
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.directory.iterdir() if p.is_file()}
        self.assertEqual(before, after)
        self.assertTrue(self.out.is_symlink())

if __name__ == '__main__':
    unittest.main()
