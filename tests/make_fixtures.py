"""Original synthetic magazine; no stock imagery, brands or private documents."""
from pathlib import Path
import hashlib, io, json, subprocess, tempfile
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, DictionaryObject, TextStringObject

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import reportlab
FONT_DIR=Path(reportlab.__file__).parent/'fonts'
pdfmetrics.registerFont(TTFont('Demo',str(FONT_DIR/'Vera.ttf')))
pdfmetrics.registerFont(TTFont('DemoBold',str(FONT_DIR/'VeraBd.ttf')))
W,H=432,576

def ads():
    out=io.BytesIO();c=canvas.Canvas(out,pagesize=(W,H),invariant=1)
    c.setTitle('Original advertising artwork | synthetic test only')
    c.setFillColor(HexColor('#112C33'));c.rect(0,0,W,H,fill=1,stroke=0)
    c.setFillColor(HexColor('#5FE1A7'));c.circle(330,315,145,fill=1,stroke=0)
    c.setFillColor(HexColor('#112C33'));c.circle(365,350,115,fill=1,stroke=0)
    c.setFillColor(HexColor('#E8EEE4'));c.setFont('DemoBold',46)
    c.drawString(32,472,'STILL');c.drawString(32,421,'STUDIO')
    c.setFont('Demo',13);c.drawString(34,386,'Objects for a slower morning.')
    c.setFont('DemoBold',14);c.drawString(34,93,'Explore the collection  >')
    c.linkURL('https://example.org/still?edition=fall&ref=print',(30,83,279,113),relative=0,thickness=0)
    c.setFont('Demo',9);c.drawString(34,37,'FICTIONAL AD / ORIGINAL TEST ARTWORK / 01')
    c.showPage()
    c.setFillColor(HexColor('#EEE8D8'));c.rect(0,0,W,H,fill=1,stroke=0)
    c.setStrokeColor(HexColor('#D85237'));c.setLineWidth(14)
    for n in range(7):c.line(25+n*50,175,125+n*50,350)
    c.setFillColor(HexColor('#162737'));c.setFont('DemoBold',40)
    c.drawString(32,471,'NORTH');c.drawString(32,425,'SIGNAL')
    c.setFont('Demo',13);c.drawString(34,389,'A small newsletter. A wider world.')
    c.setFont('DemoBold',13);c.drawString(34,112,'Read the latest issue  >');c.drawString(34,73,'Say hello  >')
    c.linkURL('https://example.org/north/issue-7#field-notes',(30,102,250,132),relative=0,thickness=0)
    c.linkURL('mailto:hello@example.org?subject=Field%20Notes',(30,63,175,93),relative=0,thickness=0)
    c.setFont('Demo',9);c.drawString(34,30,'FICTIONAL AD / ORIGINAL TEST ARTWORK / 02');c.save()
    return out.getvalue()

def editorial():
    out=io.BytesIO();c=canvas.Canvas(out,pagesize=(W,H),invariant=1)
    for index in range(3):
        c.setFillColor(HexColor('#F4F1E9'));c.rect(0,0,W,H,fill=1,stroke=0)
        c.setFillColor(HexColor('#18323A'));c.setFont('DemoBold',34)
        c.drawString(30,505,['FIELDNOTES','Slow is a direction','Endnotes'][index])
        c.setFont('Demo',12)
        lines=[['An imaginary magazine / Issue 07','Contents','02  North Signal','03  Slow is a direction','04  Still Studio'],
               ['Editorial insert','A page between two advertisements.','The recovered links must follow the artwork,','not the original page number.'],
               ['An entirely fictional publication.','All shapes and writing are original.','Visit our example archive  >']][index]
        for n,line in enumerate(lines):c.drawString(32,450-32*n,line)
        c.setFont('Demo',9);c.drawString(32,30,'SYNTHETIC FIXTURE / NOT AN INDESIGN EXPORT')
        c.showPage()
    c.save();return out.getvalue()

def create(directory, raster=False):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    src=directory/'advertisements.pdf';src.write_bytes(ads())
    sources=PdfReader(src);ed=PdfReader(io.BytesIO(editorial()));writer=PdfWriter()
    writer.add_page(ed.pages[0])
    for source_index,insert in [(1,True),(0,False)]:
        if raster:
            with tempfile.TemporaryDirectory() as tmp:
                prefix=Path(tmp)/'art'
                subprocess.run(['pdftoppm','-f',str(source_index+1),'-l',str(source_index+1),'-singlefile','-r','144','-hide-annotations','-png',str(src),str(prefix)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                buf=io.BytesIO();c=canvas.Canvas(buf,pagesize=(W,H),invariant=1)
                c.drawImage(ImageReader(str(prefix.with_suffix('.png'))),0,0,W,H);c.save()
                writer.add_page(PdfReader(buf).pages[0])
        else:
            writer.add_page(sources.pages[source_index]);writer.pages[-1].pop('/Annots',None)
        if insert:writer.add_page(ed.pages[1])
    writer.add_page(ed.pages[2])
    from pypdf.annotations import Link
    writer.add_annotation(0,Link(rect=(28,345,280,367),target_page_index=1))
    writer.add_annotation(4,Link(rect=(28,345,320,367),url='https://example.org/archive'))
    writer.add_outline_item('North Signal',1);writer.add_outline_item('Slow is a direction',2);writer.add_outline_item('Still Studio',3)
    writer.add_named_destination('still-studio',3)
    writer.add_metadata({'/Title':'FIELDNOTES / synthetic exported magazine','/Author':'PlacedLinkRescue fixtures'})
    writer.page_mode='/UseOutlines'
    target=directory/'magazine-export.pdf'
    with target.open('wb') as f:writer.write(f)
    m={'schema':1,'review':{'approved':True,'reviewer':'Automated synthetic-fixture test','note':'TEST-ONLY acknowledgment, not human production review. Known construction: advertisements page 2 is target page 2; page 1 is target page 4. Entire artwork placed 1:1 at zero offset. Original fixture only.','alignment':'reviewed-identity' if raster else 'exact-artwork'},
       'target':{'path':target.name,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()},
       'sources':{'ads':{'path':src.name,'sha256':hashlib.sha256(src.read_bytes()).hexdigest()}},
       'placements':[{'source':'ads','source_page':2,'target_page':2,'transform':[1,0,0,1,0,0]},
                     {'source':'ads','source_page':1,'target_page':4,'transform':[1,0,0,1,0,0]}]}
    (directory/'reviewed-map.json').write_text(json.dumps(m,indent=2)+'\n')
    return directory

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--raster',action='store_true');a=p.parse_args();create(a.directory,a.raster)
