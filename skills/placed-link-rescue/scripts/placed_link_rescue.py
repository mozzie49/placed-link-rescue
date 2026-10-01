#!/usr/bin/env python3
"""PlacedLinkRescue: conservative, local PDF link recovery. MIT License."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

VERSION = "0.1.0"
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_PAGES = 600
MAX_OBJECTS = 100_000
MAX_NODES = 500_000
MAX_LINKS = 20_000
MAX_RENDER_WORK_BYTES = 512 * 1024 * 1024
MAX_EDGE_PT = 2000
DPI = 96
TIMEOUT = 45

class RescueError(Exception):
    pass

def need(condition, message):
    if not condition:
        raise RescueError(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def bounded_read(path, limit=MAX_FILE_BYTES):
    with Path(path).open('rb') as f:
        data = f.read(limit + 1)
    need(len(data) <= limit, 'File exceeds supported byte limit')
    return data

def digest(path):
    return sha(bounded_read(path))

def dump(data):
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

def integer(value, name):
    need(type(value) is int and value > 0, f"{name} must be a positive integer")
    return value

def deps():
    try:
        import pypdf
        from PIL import Image
        from reportlab.pdfgen import canvas
        return pypdf, Image, canvas
    except ImportError as exc:
        raise RescueError("Install the skill's requirements.txt before using this helper") from exc

def deref(obj):
    return obj.get_object() if hasattr(obj, 'get_object') else obj

def geometry(page):
    result = {}
    media = deref(page.get('/MediaBox'))
    crop = deref(page.get('/CropBox', media))
    for name, key, fallback in [('mediabox','/MediaBox',media), ('cropbox','/CropBox',media),
                                ('trimbox','/TrimBox',crop), ('bleedbox','/BleedBox',crop), ('artbox','/ArtBox',crop)]:
        values = deref(page.get(key, fallback))
        need(values is not None and len(values) == 4, 'Malformed page box')
        result[name] = [float(x) for x in values]
    from pypdf.generic import NumberObject
    rotation = deref(page.get('/Rotate', 0))
    need(type(rotation) is int or isinstance(rotation, NumberObject), 'Rotate must be a PDF integer')
    result['rotation'] = int(rotation) % 360
    result['user_unit'] = float(page.get('/UserUnit', 1))
    for value in result.values():
        vals = value if isinstance(value, list) else [value]
        need(all(math.isfinite(x) for x in vals), "Non-finite page geometry")
    mb = result['mediabox']
    need(mb[0:2] == [0, 0] and 0 < mb[2] <= MAX_EDGE_PT and 0 < mb[3] <= MAX_EDGE_PT,
         "Only zero-origin pages up to 2000pt per edge are supported")
    need(result['rotation'] == 0 and result['user_unit'] == 1,
         "Rotated pages and non-default UserUnit are unsupported in v0")
    need(result['cropbox'] == mb, "Cropped pages are unsupported in v0")
    return result

# Scan all reachable dictionaries, including resource objects. Never decode XML/XMP.
# Reject capabilities rather than sanitizing them and claiming preservation.
FORBIDDEN = {'/AcroForm', '/XFA', '/JS', '/JavaScript', '/OpenAction', '/AA', '/OC',
             '/EmbeddedFiles', '/EF', '/AF', '/Collection', '/RichMediaContent',
             '/RichMediaSettings', '/3DD', '/Movie', '/Sound', '/ByteRange', '/Perms',
             '/F', '/FFilter', '/FDecodeParms'}
# /F is commonly an annotation flag, so allow only numeric values there.

def scan(reader, allow_unsupported_uri=True):
    from pypdf.generic import DictionaryObject, ArrayObject, IndirectObject, NumberObject
    seen = set()
    nodes = 0
    def walk(obj, depth=0):
        nonlocal nodes
        nodes += 1
        need(nodes <= MAX_NODES and depth <= 100, "PDF object graph exceeds safety bounds")
        if isinstance(obj, IndirectObject):
            key = (obj.idnum, obj.generation)
            if key in seen:
                return
            seen.add(key)
            need(len(seen) <= MAX_OBJECTS, "Too many PDF objects")
            obj = obj.get_object()
        if isinstance(obj, DictionaryObject):
            def action_check(value):
                action = deref(value)
                need(isinstance(action, DictionaryObject), 'Malformed action dictionary')
                kind = deref(action.get('/S'))
                need(kind in ('/URI', '/GoTo'), f'Unsupported PDF action: {kind}')
                need('/Next' not in action, 'Action chains are unsupported')
                if kind == '/URI':
                    need(set(action).issubset({'/Type','/S','/URI','/IsMap'}), 'Unsupported URI action fields')
                    ok = uri_ok(deref(action.get('/URI')))
                    need(ok or allow_unsupported_uri, 'Unsupported preserved URI action')
                    need(not deref(action.get('/IsMap',False)), 'Server-side image-map actions are unsupported')
                else:
                    need(set(action).issubset({'/Type','/S','/D'}), 'Unsupported GoTo action fields')
                    need('/D' in action, 'GoTo action lacks destination')
            typ = deref(obj.get('/Type'))
            if typ == '/Action':
                action_check(obj)
            for key, value in obj.items():
                if str(key) == '/A':
                    candidate = deref(value)
                    if (deref(obj.get('/Subtype')) == '/Link' or '/Title' in obj
                        or isinstance(candidate, DictionaryObject) and '/S' in candidate):
                        action_check(candidate)
                if str(key) in FORBIDDEN:
                    if str(key) == '/F' and isinstance(deref(value), NumberObject):
                        continue
                    raise RescueError(f"Unsupported PDF feature: {key}")
            if typ == '/Sig' or deref(obj.get('/FT')) == '/Sig':
                raise RescueError("Signed PDFs are unsupported; signatures would be invalidated")
            if typ == '/Filespec':
                raise RescueError("File specifications are unsupported")
            action = deref(obj.get('/S'))
            if action in ('/JavaScript', '/Launch', '/GoToR', '/GoToE', '/SubmitForm',
                          '/ResetForm', '/ImportData', '/Rendition', '/Named', '/SetOCGState',
                          '/Hide', '/Thread', '/Trans', '/Movie', '/Sound', '/GoTo3DView', '/RichMediaExecute'):
                raise RescueError(f'Unsupported PDF action: {action}')
            for value in obj.values():
                walk(value, depth + 1)
        elif isinstance(obj, (ArrayObject, list, tuple)):
            for value in obj:
                walk(value, depth + 1)
    walk(reader.trailer)
    return {'reachable_objects': len(seen), 'visited_nodes': nodes}

def read_pdf(path, role="source", remaining_bytes=MAX_FILE_BYTES):
    pypdf, _, _ = deps()
    path = Path(path).resolve(strict=True)
    need(path.is_file(), f"Not a regular PDF file: {path.name}")
    need(path.stat().st_size <= MAX_FILE_BYTES, f"PDF exceeds {MAX_FILE_BYTES} bytes")
    data = bounded_read(path, min(MAX_FILE_BYTES, remaining_bytes))
    need(data.startswith(b'%PDF-'), f"Missing PDF header: {path.name}")
    try:
        reader = pypdf.PdfReader(io.BytesIO(data), strict=True)
        need(not reader.is_encrypted, "Encrypted PDFs are unsupported, including empty-password files")
        need(0 < len(reader.pages) <= MAX_PAGES, "Page count exceeds supported bounds")
        bounds = scan(reader, allow_unsupported_uri=(role != "target"))
        pages = [geometry(page) for page in reader.pages]
        inventory = [links(page, source=True) for page in reader.pages]
        need(sum(len(x[0]) + len(x[1]) for x in inventory) <= MAX_LINKS, "Too many annotations")
        return {'path': path, 'data': data, 'sha256': sha(data), 'reader': reader,
                'geometry': pages, 'inventory': inventory, 'bounds': bounds}
    except RescueError:
        raise
    except Exception as exc:
        raise RescueError(f"Malformed or unsupported PDF ({path.name}): {type(exc).__name__}: {exc}") from exc

def uri_ok(value):
    from pypdf.generic import TextStringObject
    need(isinstance(value, TextStringObject), "URI must be a decoded PDF text string")
    uri = str(value)
    need(0 < len(uri) <= 4096 and '\\' not in uri and all(ord(c) >= 32 and ord(c) != 127 and not c.isspace() for c in uri),
         "URI is empty, too long, or contains control characters")
    try:
        parsed = urlsplit(uri)
        if parsed.scheme.lower() in ('http', 'https'):
            need(bool(parsed.hostname) and parsed.username is None and parsed.password is None,
                 "HTTP(S) URI must have a host and no embedded credentials")
            _ = parsed.port
            return True
        if parsed.scheme.lower() == 'mailto':
            need(bool(parsed.path), "Empty mailto destination")
            return True
        return False
    except ValueError as exc:
        raise RescueError(f"Invalid URI: {exc}") from exc

def links(page, source=False):
    from pypdf.generic import ArrayObject, DictionaryObject
    supported, skipped = [], []
    annots = deref(page.get('/Annots', []))
    need(isinstance(annots, (ArrayObject, list)) and len(annots) <= MAX_LINKS,
         "Malformed or oversized annotations array")
    for index, ref in enumerate(annots):
        ann = deref(ref)
        need(isinstance(ann, DictionaryObject), "Malformed annotation")
        need(deref(ann.get('/Subtype')) == '/Link', f"Unsupported annotation subtype: {ann.get('/Subtype')}")
        need('/QuadPoints' not in ann, "QuadPoints link geometry is unsupported")
        rect = [float(v) for v in ann.get('/Rect', [])]
        need(len(rect) == 4 and all(math.isfinite(v) for v in rect), "Malformed link rectangle")
        x0, y0, x1, y1 = rect
        mb = geometry(page)['mediabox']
        need(0 <= x0 < x1 <= mb[2] and 0 <= y0 < y1 <= mb[3], "Link rectangle is outside the page or empty")
        action = deref(ann.get('/A', {}))
        need(isinstance(action, (dict, DictionaryObject)), "Malformed link action")
        need(not ('/Dest' in ann and '/A' in ann), "Ambiguous link has both Dest and A")
        if '/Dest' in ann or deref(action.get('/S')) == '/GoTo':
            skipped.append({'annotation': index, 'kind': 'internal-link', 'rect': rect})
            continue
        need(deref(action.get('/S')) == '/URI', f"Unsupported link action: {action.get('/S')}")
        need(set(action).issubset({'/Type', '/S', '/URI', '/IsMap'}), "Unsupported URI action fields")
        need(not deref(action.get('/IsMap', False)), "Server-side image-map links are unsupported")
        uri = deref(action.get('/URI'))
        if not uri_ok(uri):
            need(source, "Target contains an unsupported URI scheme")
            skipped.append({'annotation': index, 'kind': 'unsupported-uri-scheme', 'rect': rect, 'uri': str(uri)})
            continue
        # Hidden, invisible, and no-view source links are not silently made visible/clickable.
        flags = int(deref(ann.get('/F', 0)))
        need(not (flags & (1 | 2 | 32)), "Hidden/invisible/no-view links are unsupported")
        supported.append({'annotation': index, 'rect': rect, 'uri': str(uri)})
    return supported, skipped

def canonical(obj, reader, trail=None, depth=0, budget=None):
    """Semantic comparison independent of object numbering; page refs use page index."""
    from pypdf.generic import (IndirectObject, DictionaryObject, ArrayObject, StreamObject,
                               ByteStringObject, NullObject, BooleanObject, NameObject, TextStringObject, NumberObject, FloatObject)
    budget = [0] if budget is None else budget
    budget[0] += 1
    need(budget[0] <= MAX_NODES, "Canonicalization work exceeds safety bounds")
    need(depth < 120, "Canonicalization exceeds depth limit")
    trail = set() if trail is None else trail
    if isinstance(obj, IndirectObject):
        key = (obj.idnum, obj.generation)
        resolved = obj.get_object()
        if isinstance(resolved, dict) and resolved.get('/Type') == '/Page':
            return {'page': reader.get_page_number(resolved)}
        if key in trail:
            return {'cycle': True}
        return canonical(resolved, reader, trail | {key}, depth + 1, budget)
    if isinstance(obj, StreamObject):
        # Compare stored stream bytes; no XML parsing or decompression needed.
        return {'dict': {str(k): canonical(v, reader, trail, depth + 1, budget)
                         for k,v in sorted(obj.items()) if k != '/Length'},
                'raw_sha256': sha(obj._data)}
    if isinstance(obj, DictionaryObject):
        return {str(k): canonical(v, reader, trail, depth + 1, budget) for k,v in sorted(obj.items())}
    if isinstance(obj, (ArrayObject, list, tuple)):
        return [canonical(v, reader, trail, depth + 1, budget) for v in obj]
    if isinstance(obj, ByteStringObject):
        return {'bytes': bytes(obj).hex()}
    if isinstance(obj, NullObject):
        return None
    if isinstance(obj, BooleanObject):
        return obj.value
    if isinstance(obj, NameObject):
        return {'name':str(obj)}
    if isinstance(obj, TextStringObject):
        return {'text':str(obj)}
    if isinstance(obj, (NumberObject, int)):
        return {'number':str(int(obj))}
    if isinstance(obj, (FloatObject, float)):
        return {'number':str(obj)}
    return {'other':type(obj).__name__,'value':str(obj)}

def snapshot(pdf):
    reader = pdf['reader']
    root = reader.trailer['/Root']
    budget = [0]
    catalog = {str(k): canonical(v, reader, budget=budget) for k,v in root.items() if k != '/Pages'}
    page_data, annotations = [], []
    for p in reader.pages:
        page_data.append({str(k): canonical(v, reader, budget=budget) for k,v in p.items()
                          if k not in ('/Parent', '/Annots')})
        annotations.append([canonical(ref, reader, budget=budget) for ref in p.get('/Annots', [])])
    return {'catalog': catalog, 'pages': page_data, 'annotations': annotations,
            'info': canonical(reader.trailer.get('/Info', {}), reader, budget=budget)}

def render(pdf, page, folder, hide=False, label='page'):
    _, Image, _ = deps()
    executable = shutil.which('pdftoppm')
    need(executable is not None, "Poppler pdftoppm is required; no unchecked repair is produced")
    prefix = Path(folder) / label
    args = [executable, '-f', str(page), '-l', str(page), '-singlefile', '-r', str(DPI), '-png']
    if hide:
        args.append('-hide-annotations')
    args += [str(pdf), str(prefix)]
    try:
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=TIMEOUT, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RescueError(f"Renderer timed out after {TIMEOUT}s for page {page}") from exc
    need(result.returncode == 0, f"Renderer failed for page {page}: {result.stderr[:300].decode(errors='replace')}")
    output = prefix.with_suffix('.png')
    need(output.exists() and output.stat().st_size <= MAX_FILE_BYTES, "Renderer output missing or too large")
    need(sum(p.stat().st_size for p in Path(folder).glob('*.png')) <= MAX_RENDER_WORK_BYTES,
         'Rendered working images exceed 512 MiB')
    with Image.open(output) as image:
        need(image.width * image.height <= 8_000_000, "Rendered page exceeds pixel bounds")
        im = image.convert('RGB')
        fingerprint = {'size': [im.width, im.height], 'sha256': sha(im.tobytes())}
    return output, fingerprint

def load_map(path, require_review=True):
    path = Path(path).resolve(strict=True)
    need(path.is_file(), 'Map must be a regular file')
    need(path.stat().st_size <= 2 * 1024 * 1024, "Map exceeds 2 MiB")
    def unique(pairs):
        d = {}
        for k,v in pairs:
            need(k not in d, f"Duplicate JSON key: {k}")
            d[k] = v
        return d
    map_bytes = bounded_read(path, 2 * 1024 * 1024)
    data = json.loads(map_bytes.decode('utf-8'), object_pairs_hook=unique)
    need(isinstance(data, dict) and set(data) == {'schema', 'review', 'target', 'sources', 'placements'},
         "Map must contain exactly schema, review, target, sources, placements")
    need(data['schema'] == 1 and type(data['schema']) is int, "Unsupported map schema")
    review = data['review']
    need(isinstance(review, dict) and set(review) == {'approved', 'reviewer', 'note', 'alignment'}, "Invalid review record")
    need(review['alignment'] in ('exact-artwork', 'reviewed-identity'), 'Unknown alignment policy')
    if require_review:
        need(review['approved'] is True and all(isinstance(review[k], str) and review[k].strip() for k in ('reviewer','note')),
             'Map has not been reviewed; approve page identity/coordinates before repair')
    need(isinstance(data['sources'], dict) and 0 < len(data['sources']) <= 100, "Map needs 1-100 sources")
    need('target' not in data['sources'], 'Reserved source identifier: target')
    paths = {}
    total_bytes = 0
    for name, item in [('target',data['target'])] + list(data['sources'].items()):
        need(name == 'target' or (isinstance(name, str) and name != 'target' and name.isidentifier()), "Invalid source identifier")
        need(isinstance(item,dict) and set(item) == {'path','sha256'}, "Input record must contain path and sha256")
        need(isinstance(item['path'],str) and isinstance(item['sha256'],str) and len(item['sha256']) == 64,
             "Invalid path or SHA256")
        input_path = path.parent / item['path']
        need(total_bytes + input_path.stat().st_size <= MAX_TOTAL_BYTES, 'Inputs exceed total 256 MiB limit')
        paths[name] = read_pdf(input_path, role='target' if name=='target' else 'source', remaining_bytes=MAX_TOTAL_BYTES-total_bytes)
        total_bytes += len(paths[name]['data'])
        need(paths[name]['sha256'] == item['sha256'], f"Input hash mismatch: {name}; review the new export")
    need(sum(len(p['data']) for p in paths.values()) <= MAX_TOTAL_BYTES, "Inputs exceed total 256 MiB limit")
    placements = data['placements']
    need(isinstance(placements,list) and 0 < len(placements) <= MAX_PAGES, "Map needs 1-600 placements")
    targets = set()
    for item in placements:
        need(isinstance(item,dict) and set(item) == {'source','source_page','target_page','transform'}, "Invalid placement fields")
        need(item['source'] in data['sources'], "Unknown placement source")
        sp = integer(item['source_page'], 'source_page')
        tp = integer(item['target_page'], 'target_page')
        need(isinstance(item['transform'],list) and item['transform'] == [1,0,0,1,0,0]
             and all(type(v) in (int,float) for v in item['transform']),
             "Only identity transforms are supported: no scale, offset, rotation, or skew")
        need(tp not in targets, "Multiple source placements target the same page")
        targets.add(tp)
        source, target = paths[item['source']], paths['target']
        need(sp <= len(source['reader'].pages) and tp <= len(target['reader'].pages), "Placement page is out of range")
        need(source['geometry'][sp-1] == target['geometry'][tp-1], "Mapped pages do not have identical geometry")
    return sha(map_bytes), data, paths

def overlap(a,b):
    return min(a[2],b[2]) > max(a[0],b[0]) and min(a[3],b[3]) > max(a[1],b[1])

def proof_pdf(path, placements, links_to_add, renders, inputs, alignment=None, verified=False):
    _, _, canvas = deps()
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import reportlab
    font = Path(reportlab.__file__).parent / 'fonts' / 'Vera.ttf'
    pdfmetrics.registerFont(TTFont('PLRProof', str(font)))
    c = canvas.Canvas(str(path), pagesize=(960,720), invariant=1, pageCompression=1)
    c.setTitle('PlacedLinkRescue | hotspot proof | NOT THE DELIVERABLE')
    c.setAuthor('PlacedLinkRescue')
    def text(x,y,s,size=10):
        # Built-in fonts: keep non-ASCII destinations lossless in receipt; avoid tofu here.
        s = str(s).encode('ascii', 'backslashreplace').decode('ascii')
        c.setFont('PLRProof',size); c.drawString(x,y,s)
    for i, p in enumerate(placements):
        src = inputs[p['source']]
        w,h = src['geometry'][p['source_page']-1]['mediabox'][2:]
        c.setFillColorRGB(.055,.09,.14); c.rect(0,0,960,720,fill=1,stroke=0)
        c.setFillColorRGB(1,1,1)
        text(30,682,'PLACED / LINK RESCUE',20)
        text(30,657,f"Hotspot proof {i+1} | {p['source']} page {p['source_page']} -> target page {p['target_page']}",12)
        text(30,635,'Synthetic examples are not an InDesign compatibility certification. Boxes are proof overlays only.',9)
        s = min(420/w,455/h)
        for offset, title, file in [(30,'SOURCE',renders[i][0]),(505,'TARGET + RECOVERED HOTSPOTS',renders[i][1])]:
            text(offset,610,title,10)
            c.drawImage(ImageReader(str(file)),offset,140,width=w*s,height=h*s)
            c.setStrokeColorRGB(.02,.8,.64);c.setLineWidth(2)
            for n, link in [(j+1,l) for j,l in enumerate(links_to_add) if l['target_page']==p['target_page'] and l['status']!='source-duplicate']:
                x0,y0,x1,y1=link['rect']; c.rect(offset+x0*s,140+y0*s,(x1-x0)*s,(y1-y0)*s)
                c.setFillColorRGB(.02,.5,.4);c.circle(offset+x0*s,140+y1*s,7,fill=1,stroke=0)
                c.setFillColorRGB(1,1,1);text(offset+x0*s-2,140+y1*s-3,n,8)
        c.setFillColorRGB(1,1,1)
        exact = bool(alignment and alignment[i]['exact_artwork_match'])
        text(30,114,('Artwork: exact 96-dpi match.' if exact else 'Artwork differs: approved review, not automatic proof.' if verified else 'Artwork differs: HUMAN ALIGNMENT REVIEW REQUIRED.') + ' Geometry alone does not prove placement.',10)
        text(30,94,('Target rendering / navigation: verified unchanged.' if verified else 'PREVIEW ONLY. No repair has been performed. Review hotspot position on BOTH pages.'),10)
        text(30,74,'Exact destinations and all rectangles are listed on the following receipt pages.',10)
        c.showPage()
    # Destinations are ordinary non-clickable text. Never turn arbitrary URLs into active proof links.
    c.setFillColorRGB(.055,.09,.14);c.rect(0,0,960,720,fill=1,stroke=0)
    c.setFillColorRGB(1,1,1);text(30,678,'RECOVERED DESTINATIONS',20);y=640
    for n,link in enumerate(links_to_add,1):
        rows=[f"{n}. Target page {link['target_page']} | {link['status']} | rectangle {link['rect']}"]
        url=link['uri'].encode('ascii','backslashreplace').decode('ascii')
        # Wrap the literal string without shortening it.
        while url:
            cut=min(150,len(url))
            while cut>1 and pdfmetrics.stringWidth(url[:cut],'PLRProof',10)>900:cut-=1
            rows.append(url[:cut]);url=url[cut:]
        for row in rows:
            if y<35:
                c.showPage();c.setFillColorRGB(.055,.09,.14);c.rect(0,0,960,720,fill=1,stroke=0);c.setFillColorRGB(1,1,1);y=675
            text(30,y,row,10);y-=15
        y-=12
    c.save()

def repair(map_path, output_dir):
    pypdf, _, _ = deps()
    from pypdf.generic import DictionaryObject, NameObject, ArrayObject, FloatObject, TextStringObject
    map_hash, mapping, inputs = load_map(map_path)
    target = inputs['target']
    # Validate target with stricter URI rules, and snapshot before writer cloning.
    for page in target['reader'].pages:
        links(page, source=False)
    before = snapshot(target)
    output = Path(output_dir).absolute()
    need(not output.exists() and not output.is_symlink(), "Output bundle already exists; choose a NEW directory")
    need(output.parent.is_dir(), "Output parent directory must already exist")
    planned, skipped = [], []
    by_page = {}
    for p in mapping['placements']:
        src = inputs[p['source']]
        external, omitted = src['inventory'][p['source_page']-1]
        skipped += [dict(x,source=p['source'],source_page=p['source_page'],target_page=p['target_page']) for x in omitted]
        target_page = target['reader'].pages[p['target_page']-1]
        ext, internal = links(target_page, source=False)
        existing = ext + internal
        pending = by_page.setdefault(p['target_page'],[])
        unique_source_links = []
        for link in external:
            candidate = dict(link,source=p['source'],source_page=p['source_page'],target_page=p['target_page'],status='added')
            if any(old['rect']==link['rect'] and old['uri']==link['uri'] for old in unique_source_links):
                candidate['status']='source-duplicate';planned.append(candidate);continue
            unique_source_links.append(link)
            for old in existing + pending:
                if old['rect'] == link['rect'] and old.get('uri') == link['uri']:
                    candidate['status']='already-present'
                elif overlap(old['rect'],link['rect']):
                    raise RescueError(f"Conflicting/overlapping hotspot on target page {p['target_page']}")
            planned.append(candidate)
            if candidate['status']=='added':pending.append(candidate)
    need(planned, "No supported external links on mapped source pages")
    with tempfile.TemporaryDirectory(prefix='.placed-link-rescue-',dir=output.parent) as tmp:
        stage=Path(tmp);work=stage/'work';work.mkdir();bundle=stage/'bundle';bundle.mkdir()
        # Render only immutable, hash-checked snapshots, not paths that can change mid-run.
        frozen={}
        for key,pdf in inputs.items():
            frozen[key]=work/f'{key}.pdf';frozen[key].write_bytes(pdf['data'])
        alignment=[];proof_renders=[]
        for i,p in enumerate(mapping['placements']):
            si,sf=render(frozen[p['source']],p['source_page'],work,True,f'source-{i}')
            ti,tf=render(frozen['target'],p['target_page'],work,True,f'target-{i}')
            exact = sf == tf
            need(exact or mapping['review']['alignment'] == 'reviewed-identity',
                 f"Artwork mismatch on target page {p['target_page']}; inspect a preview and explicitly review identity placement. Geometry alone is insufficient")
            alignment.append(dict(p,exact_artwork_match=exact,source_render=sf,target_render=tf,
                                  assurance='render-equal-at-96dpi' if exact else 'human-reviewed-not-automatically-proved'))
            proof_renders.append((si,ti))
        dest=bundle/'digital.pdf'
        additions=[p for p in planned if p['status']=='added']
        if not additions:
            dest.write_bytes(target['data']) # Exact repeat-run idempotence.
        else:
            writer=pypdf.PdfWriter();writer.clone_document_from_reader(target['reader'])
            for item in additions:
                annotation=DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/Link'),
                    NameObject('/Rect'):ArrayObject([FloatObject(v) for v in item['rect']]),
                    NameObject('/Border'):ArrayObject([FloatObject(0),FloatObject(0),FloatObject(0)]),
                    NameObject('/A'):DictionaryObject({NameObject('/S'):NameObject('/URI'),NameObject('/URI'):TextStringObject(item['uri'])})})
                writer.add_annotation(item['target_page']-1,annotation)
            with dest.open('wb') as f:writer.write(f)
        after_pdf=read_pdf(dest,role="target");after=snapshot(after_pdf)
        need(before['catalog']==after['catalog'],"Verification failed: catalog/navigation changed")
        need(before['pages']==after['pages'],"Verification failed: target page content/resources changed")
        need(before['info']==after['info'],"Verification failed: target metadata changed")
        for page_index,original in enumerate(before['annotations']):
            actual=after['annotations'][page_index]
            count=sum(p['target_page']==page_index+1 for p in additions)
            need(actual[:len(original)]==original and len(actual)==len(original)+count,
                 'Verification failed: existing annotations changed or unexpected annotations appeared')
        for page_index,page in enumerate(after_pdf['reader'].pages):
            actual,_=links(page,source=False)
            for expected in [p for p in planned if p['target_page']==page_index+1]:
                need(any(a['rect']==expected['rect'] and a['uri']==expected['uri'] for a in actual),
                     'Verification failed: exact restored destination/rectangle missing')
        rendering=[]
        for i in range(1,len(target['reader'].pages)+1):
            before_image,a=render(frozen['target'],i,work,False,f'before-{i}')
            after_image,b=render(dest,i,work,False,f'after-{i}')
            before_image.unlink();after_image.unlink()
            need(a==b,f'Verification failed: target page {i} rendering changed')
            rendering.append(dict(page=i,**a))
        proof_pdf(bundle/'proof.pdf',mapping['placements'],planned,proof_renders,inputs,alignment,True)
        import PIL, reportlab
        try:
            renderer_version = subprocess.run([shutil.which('pdftoppm'),'-v'],capture_output=True,text=True,timeout=5)
            version_lines = (renderer_version.stderr or renderer_version.stdout).splitlines()
            poppler_version = version_lines[0] if version_lines else 'unavailable'
        except (subprocess.TimeoutExpired, OSError):
            poppler_version = 'unavailable'
        receipt={'schema':1,'tool':'PlacedLinkRescue','version':VERSION,
                 'runtime':{'python':sys.version.split()[0],'pypdf':pypdf.__version__,'Pillow':PIL.__version__,
                            'ReportLab':reportlab.Version,'Poppler':poppler_version},
                 'alignment_policy':mapping['review']['alignment'],
                 'review':mapping['review'],'map_sha256':map_hash,
                 'inputs':{k:{'sha256':p['sha256'],'pages':len(p['reader'].pages)} for k,p in inputs.items()},
                 'output_sha256':digest(dest),'proof_sha256':digest(bundle/'proof.pdf'),
                 'added':len(additions),'already_present':sum(p['status']=='already-present' for p in planned),
                 'source_duplicates':sum(p['status']=='source-duplicate' for p in planned),
                 'links':planned,'skipped_source_annotations':skipped,
                 'verification':{'catalog_navigation_unchanged':True,'page_objects_unchanged':True,
                                  'existing_annotations_unchanged':True,'exact_destinations_verified':True,
                                  'target_rendering_unchanged':True,'renderer':'Poppler pdftoppm','dpi':DPI,
                                  'alignment':alignment,'target_pages':rendering},
                 'limits':['Synthetic-fixture validated; not tested with real InDesign exports.',
                           '96-dpi artwork equality is not a proof at every resolution.',
                           'Added annotations are untagged; no PDF/UA, PDF/A or print compliance claim.',
                           'No link destinations were visited or checked for availability.']}
        (bundle/'receipt.json').write_text(dump(receipt),'utf-8')
        # os.rename on Unix can replace an EMPTY directory: reserve the destination atomically first.
        output.mkdir(exist_ok=False)
        try:
            for name in ('digital.pdf','proof.pdf','receipt.json'):
                os.rename(bundle/name,output/name)
        except BaseException:
            # Never leave a partial bundle labeled as completed.
            for name in ('digital.pdf','proof.pdf','receipt.json'):
                try:(output/name).unlink()
                except FileNotFoundError:pass
            try:output.rmdir()
            except OSError:pass
            raise
    return receipt

def inspect(paths):
    result=[];total=0
    need(len(paths)<=100, 'Inspect accepts at most 100 inputs')
    for path in paths:
        pdf=read_pdf(path,remaining_bytes=MAX_TOTAL_BYTES-total);total+=len(pdf['data'])
        result.append({'path':str(pdf['path']),'sha256':pdf['sha256'],'pages':len(pdf['reader'].pages),
                       'geometry':pdf['geometry'],'bounds':pdf['bounds'],
                       'annotations':[{'page':i+1,'external':pair[0],'skipped':pair[1]} for i,pair in enumerate(pdf['inventory'])]})
    return {'schema':1,'inputs':result}

def draft(args):
    target=read_pdf(args.target,role='target');sources={};total=len(target['data'])
    need(len(args.source)<=100, 'At most 100 sources supported')
    for entry in args.source:
        name,path=entry.split('=',1)
        need(name.isidentifier() and name!='target' and name not in sources,'Invalid or duplicate source ID')
        sources[name]=read_pdf(path,remaining_bytes=MAX_TOTAL_BYTES-total);total+=len(sources[name]['data'])
    out=Path(args.output).absolute();placements=[]
    for value in args.placement:
        name,sp,tp=value.split(':')
        need(name in sources,'Unknown source ID')
        placements.append({'source':name,'source_page':int(sp),'target_page':int(tp),'transform':[1,0,0,1,0,0]})
    data={'schema':1,'review':{'approved':False,'reviewer':'','note':'','alignment':'exact-artwork'},
          'target':{'path':os.path.relpath(target['path'],out.parent),'sha256':target['sha256']},
          'sources':{k:{'path':os.path.relpath(p['path'],out.parent),'sha256':p['sha256']} for k,p in sources.items()},
          'placements':placements}
    with out.open('x',encoding='utf-8') as f:f.write(dump(data))
    return {'draft':str(out),'review_required':True}

def preview(map_path, output_dir):
    _, mapping, inputs = load_map(map_path, require_review=False)
    out = Path(output_dir).absolute()
    need(not out.exists() and not out.is_symlink(), 'Preview directory already exists; choose a new directory')
    need(out.parent.is_dir(), 'Preview parent must exist')
    with tempfile.TemporaryDirectory(prefix='.placed-link-preview-',dir=out.parent) as tmp:
        work=Path(tmp);frozen={};renders=[];alignment=[];proposed=[]
        for key,pdf in inputs.items():
            frozen[key]=work/f'{key}.pdf';frozen[key].write_bytes(pdf['data'])
        for i,p in enumerate(mapping['placements']):
            si,sf=render(frozen[p['source']],p['source_page'],work,True,f'source-{i}')
            ti,tf=render(frozen['target'],p['target_page'],work,True,f'target-{i}')
            renders.append((si,ti));alignment.append(dict(p,exact_artwork_match=sf==tf,source_render=sf,target_render=tf))
            for link in inputs[p['source']]['inventory'][p['source_page']-1][0]:
                proposed.append(dict(link,source=p['source'],source_page=p['source_page'],target_page=p['target_page'],status='proposed'))
        proof_pdf(work/'proof.pdf',mapping['placements'],proposed,renders,inputs,alignment,False)
        report={'status':'preview-only','alignment':alignment,'links':proposed,
                'instruction':'Review every hotspot on source and target. Approve only verified whole-page identity placement. Never approve shifted/scaled/cropped placement.'}
        (work/'preview.json').write_text(dump(report),'utf-8')
        out.mkdir(exist_ok=False)
        try:
            for name in ('proof.pdf','preview.json'):os.rename(work/name,out/name)
        except BaseException:
            for name in ('proof.pdf','preview.json'):
                try:(out/name).unlink()
                except FileNotFoundError:pass
            try:out.rmdir()
            except OSError:pass
            raise
    return report

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',action='version',version=VERSION)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('inspect',help='Inspect local PDF links/geometry without visiting destinations');p.add_argument('pdf',nargs='+')
    p=sub.add_parser('draft-map',help='Hash-bind user-supplied placements; emits an UNAPPROVED map')
    p.add_argument('--source',action='append',required=True,help='ID=path.pdf');p.add_argument('--target',required=True)
    p.add_argument('--placement',action='append',required=True,help='ID:source_page:target_page (1-based)');p.add_argument('--output',required=True)
    p=sub.add_parser('preview',help='Create source/target hotspot proofs before approving a map')
    p.add_argument('--map',required=True);p.add_argument('--output-dir',required=True)
    p=sub.add_parser('repair',help='Create a NEW verified digital/proof/receipt bundle')
    p.add_argument('--map',required=True);p.add_argument('--output-dir',required=True)
    args=parser.parse_args(argv)
    try:
        result=inspect(args.pdf) if args.command=='inspect' else draft(args) if args.command=='draft-map' else preview(args.map,args.output_dir) if args.command=='preview' else repair(args.map,args.output_dir)
        print(dump(result),end='');return 0
    except Exception as exc:
        print(dump({'error':str(exc),'error_type':type(exc).__name__,'status':'refused','tool':'PlacedLinkRescue'}),file=sys.stderr,end='');return 2

if __name__=='__main__':
    raise SystemExit(main())
