import copy
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
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (NameObject, NumberObject, ArrayObject, FloatObject,
                           DictionaryObject, TextStringObject, BooleanObject)
from make_fixtures import create
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'skills/placed-link-rescue/scripts/placed_link_rescue.py'
spec=importlib.util.spec_from_file_location('rescue',SCRIPT);r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

class RescueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base=tempfile.TemporaryDirectory();create(Path(cls.base.name)/'fixture')
    @classmethod
    def tearDownClass(cls):cls.base.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.d=Path(self.tmp.name)/'f';shutil.copytree(Path(self.base.name)/'fixture',self.d)
        self.map=self.d/'reviewed-map.json';self.out=self.d/'bundle'
    def tearDown(self):self.tmp.cleanup()
    def mapping(self):return json.loads(self.map.read_text())
    def save(self,m):self.map.write_text(json.dumps(m))
    def mutate(self,fn,source=False):
        path=self.d/('advertisements.pdf' if source else 'magazine-export.pdf')
        writer=PdfWriter(clone_from=PdfReader(path));fn(writer)
        with path.open('wb') as f:writer.write(f)
        m=self.mapping();(m['sources']['ads'] if source else m['target'])['sha256']=r.digest(path);self.save(m)
    def refused(self,pattern):
        with self.assertRaisesRegex(r.RescueError,pattern):r.repair(self.map,self.out)
        self.assertFalse(self.out.exists())
    def test_reorder_insert_preserves_content_links_toc(self):
        original=(self.d/'magazine-export.pdf').read_bytes();receipt=r.repair(self.map,self.out)
        self.assertEqual(receipt['added'],3);self.assertEqual(receipt['already_present'],0)
        self.assertEqual((self.d/'magazine-export.pdf').read_bytes(),original)
        self.assertEqual(len(PdfReader(self.out/'digital.pdf').pages),5)
        self.assertTrue(receipt['verification']['target_rendering_unchanged'])
        # Independent parser: MuPDF, optional validation dependency (not shipped runtime).
        import fitz
        with fitz.open(self.d/'magazine-export.pdf') as before,fitz.open(self.out/'digital.pdf') as after:
            def toc(doc):
                return [[*row[:3], {k:v for k,v in row[3].items() if k != 'xref'}] for row in doc.get_toc(simple=False)]
            self.assertEqual(toc(before),toc(after))
            self.assertEqual(before.resolve_names(),after.resolve_names())
            for a,b in zip(before,after):
                self.assertEqual(a.get_text(),b.get_text())
                self.assertEqual(a.get_pixmap().samples,b.get_pixmap().samples)
            self.assertEqual(str(after[0].get_links()[0]['page']),'2')
            got=[x['uri'] for p in after for x in p.get_links() if 'uri' in x]
            self.assertEqual(set(got),{'https://example.org/archive','https://example.org/still?edition=fall&ref=print','https://example.org/north/issue-7#field-notes','mailto:hello@example.org?subject=Field%20Notes'})
    def test_deterministic_same_inputs(self):
        one=r.repair(self.map,self.out);two=r.repair(self.map,self.d/'second')
        self.assertEqual(one,two)
        for name in ('digital.pdf','proof.pdf','receipt.json'):
            self.assertEqual((self.out/name).read_bytes(),(self.d/'second'/name).read_bytes())
    def test_repeat_is_byte_identical(self):
        r.repair(self.map,self.out);m=self.mapping();m['target']={'path':'bundle/digital.pdf','sha256':r.digest(self.out/'digital.pdf')};self.save(m)
        receipt=r.repair(self.map,self.d/'repeat');self.assertEqual(receipt['added'],0);self.assertEqual(receipt['already_present'],3)
        self.assertEqual((self.out/'digital.pdf').read_bytes(),(self.d/'repeat/digital.pdf').read_bytes())
    def test_raster_export_requires_explicit_review(self):
        create(self.d,True);m=self.mapping();m['review']['alignment']='exact-artwork';self.save(m)
        self.refused('Artwork mismatch')
        report=r.preview(self.map,self.d/'preview');self.assertTrue(any(not a['exact_artwork_match'] for a in report['alignment']))
        m['review']['alignment']='reviewed-identity';m['review']['note']='Reviewed synthetic construction and proof: full page raster at exact original dimensions, zero offset.';self.save(m)
        receipt=r.repair(self.map,self.out);self.assertEqual(receipt['added'],3)
        self.assertTrue(any(a['assurance']=='human-reviewed-not-automatically-proved' for a in receipt['verification']['alignment']))
    def test_hash_mismatch(self):
        m=self.mapping();m['target']['sha256']='0'*64;self.save(m);self.refused('hash mismatch')
    def test_review_required(self):
        m=self.mapping();m['review']['approved']=False;self.save(m);self.refused('not been reviewed')
    def test_reserved_source(self):
        m=self.mapping();m['sources']['target']=m['sources']['ads'];self.save(m);self.refused('Reserved')
    def test_duplicate_json_key(self):
        self.map.write_text(self.map.read_text().replace('"schema": 1','"schema": 1, "schema": 1'));self.refused('Duplicate JSON')
    def test_unknown_map_field(self):
        m=self.mapping();m['guess']=True;self.save(m);self.refused('exactly')
    def test_duplicate_target(self):
        m=self.mapping();m['placements'][1]['target_page']=2;self.save(m);self.refused('Multiple')
    def test_bool_page(self):
        m=self.mapping();m['placements'][0]['source_page']=True;self.save(m);self.refused('positive integer')
    def test_out_of_range(self):
        m=self.mapping();m['placements'][0]['source_page']=200;self.save(m);self.refused('out of range')
    def test_declared_scale_offset(self):
        for matrix in ([.5,0,0,.5,0,0],[1,0,0,1,5,0],[0,1,-1,0,0,0]):
            m=self.mapping();m['placements'][0]['transform']=matrix;self.save(m);self.refused('identity transforms')
    def test_actual_offset_exact_mode(self):
        from pypdf import Transformation
        self.mutate(lambda w:w.pages[1].add_transformation(Transformation().translate(5,0)));self.refused('Artwork mismatch')
    def test_same_geometry_wrong_page(self):
        m=self.mapping();m['placements'][0]['target_page']=3;self.save(m);self.refused('Artwork mismatch')
    def test_rotation(self):
        self.mutate(lambda w:w.pages[1].rotate(90));self.refused('Rotated')
    def test_crop(self):
        self.mutate(lambda w:w.pages[1].__setitem__(NameObject('/CropBox'),ArrayObject(map(NumberObject,[5,0,432,576]))));self.refused('Cropped')
    def test_userunit(self):
        self.mutate(lambda w:w.pages[1].__setitem__(NameObject('/UserUnit'),NumberObject(2)));self.refused('UserUnit')
    def test_overlap_conflict(self):
        from pypdf.annotations import Link
        self.mutate(lambda w:w.add_annotation(1,Link(rect=(29,101,249,131),url='https://example.org/conflict')));self.refused('Conflicting')
    def test_quadpoints(self):
        def mutate(w):w.pages[0]['/Annots'][0].get_object()[NameObject('/QuadPoints')]=ArrayObject([NumberObject(1)]*8)
        self.mutate(mutate,True);self.refused('QuadPoints')
    def test_hidden_duplicate(self):
        def mutate(w):w.pages[0]['/Annots'][0].get_object()[NameObject('/F')]=NumberObject(2)
        self.mutate(mutate,True);self.refused('Hidden')
    def test_internal_source_link_reported(self):
        from pypdf.annotations import Link
        self.mutate(lambda w:w.add_annotation(0,Link(rect=(10,150,50,175),target_page_index=1)),True)
        rec=r.repair(self.map,self.out);self.assertEqual(rec['added'],3);self.assertEqual(rec['skipped_source_annotations'][0]['kind'],'internal-link')
    def test_javascript(self):
        self.mutate(lambda w:w.add_js('app.alert("no")'));self.refused('Unsupported')
    def test_form(self):
        self.mutate(lambda w:w.root_object.__setitem__(NameObject('/AcroForm'),DictionaryObject()));self.refused('AcroForm')
    def test_signature(self):
        self.mutate(lambda w:w.root_object.__setitem__(NameObject('/Perms'),DictionaryObject()));self.refused('Perms')
    def test_encryption(self):
        self.mutate(lambda w:w.encrypt(''));self.refused('Encrypted')
    def test_outline_unsafe_untyped_action(self):
        for kind in ('/GoTo3DView','/RichMediaExecute','/Unknown','/Named'):
            with self.subTest(kind=kind):
                def mutate(w):
                    first=w.root_object['/Outlines']['/First'];first[NameObject('/A')]=DictionaryObject({NameObject('/S'):NameObject(kind)})
                self.mutate(mutate);self.refused('Unsupported PDF action')
    def test_outline_indirect_action_and_file_uri(self):
        def mutate(w):
            w.root_object['/Outlines']['/First'][NameObject('/A')]=DictionaryObject({NameObject('/S'):w._add_object(NameObject('/Named'))})
        self.mutate(mutate);self.refused('Unsupported PDF action')
    def test_outline_file_uri(self):
        def mutate(w):
            w.root_object['/Outlines']['/First'][NameObject('/A')]=DictionaryObject({NameObject('/S'):NameObject('/URI'),NameObject('/URI'):TextStringObject('file:///etc/passwd')})
        self.mutate(mutate);self.refused('Unsupported preserved URI')
    def test_action_chain(self):
        def mutate(w):w.pages[0]['/Annots'][0].get_object()['/A'][NameObject('/Next')]=DictionaryObject({NameObject('/S'):NameObject('/URI'),NameObject('/URI'):TextStringObject('https://example.org')})
        self.mutate(mutate,True);self.refused('chains')
    def test_malformed_rect(self):
        def mutate(w):w.pages[0]['/Annots'][0].get_object()[NameObject('/Rect')]=ArrayObject([NumberObject(0)]*4)
        self.mutate(mutate,True);self.refused('outside')
    def test_malformed_pdf_cli(self):
        bad=self.d/'bad.pdf';bad.write_bytes(b'%PDF-1.7\ntruncated')
        result=subprocess.run([sys.executable,str(SCRIPT),'inspect',str(bad)],capture_output=True,text=True)
        self.assertEqual(result.returncode,2);self.assertEqual(json.loads(result.stderr)['status'],'refused')
    def test_no_overwrite(self):
        self.out.mkdir();(self.out/'keep').write_text('important');self.refused_existing()
    def refused_existing(self):
        with self.assertRaisesRegex(r.RescueError,'already exists'):r.repair(self.map,self.out)
        self.assertEqual((self.out/'keep').read_text(),'important')
    def test_ambiguous_uri(self):
        for uri in [' https://example.org','https://bad host/x','https://example.org\\x','mailto:hello@example.org?subject=unencoded space']:
            with self.subTest(uri=uri),self.assertRaises(r.RescueError):r.uri_ok(TextStringObject(uri))
    def test_canonical_preserves_primitive_types(self):
        reader=PdfReader(self.d/'magazine-export.pdf')
        self.assertNotEqual(r.canonical(NameObject('/X'),reader),r.canonical(TextStringObject('/X'),reader))
        self.assertNotEqual(r.canonical(NumberObject(2**53),reader),r.canonical(NumberObject(2**53+1),reader))
    def test_canonical_work_bound(self):
        node=ArrayObject([NumberObject(1)]);writer=PdfWriter()
        for _ in range(20):ref=writer._add_object(node);node=ArrayObject([ref,ref])
        with self.assertRaisesRegex(r.RescueError,'work exceeds'):r.canonical(node,writer)
    def test_standalone_copied_skill(self):
        standalone=self.d/'copied-skill';shutil.copytree(ROOT/'skills/placed-link-rescue',standalone)
        result=subprocess.run([sys.executable,str(standalone/'scripts/placed_link_rescue.py'),'repair','--map',str(self.map),'--output-dir',str(self.out)],cwd=self.tmp.name,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['added'],3)

if __name__=='__main__':unittest.main()
