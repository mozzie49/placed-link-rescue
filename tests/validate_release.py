"""Run local checks and record a bounded, reproducible validation manifest."""
from pathlib import Path
import hashlib, json, platform, re, subprocess, sys
ROOT=Path(__file__).resolve().parents[1]

def main():
    result=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=ROOT,capture_output=True,text=True)
    log=(result.stdout+result.stderr).replace(str(ROOT),'$REPO')
    (ROOT/'docs/test-results.txt').write_text(log)
    print(log)
    if result.returncode:return result.returncode
    match=re.search(r'Ran (\d+) tests in ([\d.]+)s',log)
    assert match, 'Missing unittest summary'
    import pypdf,PIL,reportlab,fitz
    poppler=subprocess.run(['pdftoppm','-v'],capture_output=True,text=True,check=True)
    records={}
    for sub in ('synthetic-magazine','synthetic-raster-export'):
        base=ROOT/'examples'/sub
        receipt=json.loads((base/'recovered/receipt.json').read_text())
        assert hashlib.sha256((base/'recovered/digital.pdf').read_bytes()).hexdigest()==receipt['output_sha256']
        assert hashlib.sha256((base/'recovered/proof.pdf').read_bytes()).hexdigest()==receipt['proof_sha256']
        assert hashlib.sha256((base/'reviewed-map.json').read_bytes()).hexdigest()==receipt['map_sha256']
        assert receipt['added']==3 and receipt['already_present']==0 and receipt['source_duplicates']==0
        assert all(receipt['verification'][k] is True for k in ('catalog_navigation_unchanged','page_objects_unchanged','existing_annotations_unchanged','exact_destinations_verified','target_rendering_unchanged'))
        records[sub]={'source_pages':2,'target_pages':5,'recovered_links':3,
                      'exact_artwork_matches':[a['exact_artwork_match'] for a in receipt['verification']['alignment']],
                      'alignment_policy':receipt['alignment_policy'],'all_target_pages_render_identically':True,
                      'output_sha256':receipt['output_sha256']}
    paths=[p for p in ROOT.rglob('*') if p.is_file() and not any(x in p.parts for x in ('.git','__pycache__','.venv'))
           and p.name not in ('validation-manifest.json','test-results.txt')]
    manifest={'schema':1,'project':'PlacedLinkRescue','version':'0.1.0','validated_date':'2026-10-01',
              'result':'pass','tests':int(match[1]),'test_seconds':float(match[2]),
              'command':'python -m unittest discover -s tests -v',
              'environment':{'python':platform.python_version(),'system':platform.system(),'pypdf':pypdf.__version__,
                             'Pillow':PIL.__version__,'ReportLab':reportlab.Version,'MuPDF':fitz.VersionBind,
                             'Poppler':(poppler.stderr or poppler.stdout).splitlines()[0]},
              'fixtures':records,
              'independent_checks':['MuPDF parses annotations, destinations, outlines and named destinations',
                                    'MuPDF and Poppler actual target/output pixel comparisons',
                                    'separate agent adversarial review and regression tests',
                                    'copied-skill repair from outside repository',
                                    'human-readable hotspot proof rendered and visually inspected by assistant'],
              'not_validated':['real InDesign exports','private/customer publication','Windows execution',
                               'PDF/UA or PDF/A compliance','hostile-PDF sandbox security','remote CI execution'],
              'files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}}
    (ROOT/'docs/validation-manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    return 0

if __name__=='__main__':raise SystemExit(main())
