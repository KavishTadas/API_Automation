"""Open the exported .xlsx / .docx the way Excel and Word would.

test-export.js proves the bytes are a well-formed ZIP; this proves the parts
inside are the ones OOXML requires and that the XML parses. Run it after
test-export.js, which writes the files.
"""
import sys, zipfile, pathlib
from xml.etree import ElementTree as ET

OUT = pathlib.Path(__file__).resolve().parents[2] / '.export-test'
bad = 0

def ok(name, cond, detail=''):
    global bad
    print(('  PASS  ' if cond else '  FAIL  ') + name + ('' if cond else '\n          -> ' + str(detail)))
    if not cond:
        bad += 1

def only(ext):
    hits = sorted(OUT.glob('*.' + ext))
    return hits[0] if hits else None

print('xlsx:')
p = only('xlsx')
ok('an xlsx was written', p is not None, OUT)
if p:
    z = zipfile.ZipFile(p)
    ok('zip integrity (CRCs match)', z.testzip() is None, z.testzip())
    names = set(z.namelist())
    for req in ['[Content_Types].xml', '_rels/.rels', 'xl/workbook.xml',
                'xl/_rels/workbook.xml.rels', 'xl/styles.xml']:
        ok('has ' + req, req in names)
    sheets = sorted(n for n in names if n.startswith('xl/worksheets/'))
    ok('carries six worksheets', len(sheets) == 6, len(sheets))
    for n in names:
        try:
            ET.fromstring(z.read(n))
        except Exception as e:
            ok('parses ' + n, False, e)
    wb = z.read('xl/workbook.xml').decode('utf8')
    tabs = [t.split('"')[0] for t in wb.split('<sheet name="')[1:]]
    ok('tabs match the template convention',
       tabs == ['Run_Summary', 'API_Overview', 'Test_Results', 'Defects',
                'Assertion_Gaps', 'Contract_Rules'], tabs)
    s1 = z.read('xl/worksheets/sheet1.xml').decode('utf8')
    ok('header row is styled', 's="2"' in s1)
    ok('panes are frozen', 'state="frozen"' in s1)
    ok('an autofilter is set', '<autoFilter' in s1)
    ok('columns are sized', '<col min="1"' in s1)
    ok('cells use inline strings like the reference template', 't="inlineStr"' in s1)
    st = z.read('xl/styles.xml').decode('utf8')
    ok('state fills defined', all(c in st for c in ['FFDCFCE7', 'FFFEE2E2', 'FFFEF3C7', 'FFF3E8FF']))
    ok('brand header fill defined', 'FF1F5F5B' in st)

print('\ndocx:')
p = only('docx')
ok('a docx was written', p is not None, OUT)
if p:
    z = zipfile.ZipFile(p)
    ok('zip integrity (CRCs match)', z.testzip() is None, z.testzip())
    names = set(z.namelist())
    for req in ['[Content_Types].xml', '_rels/.rels', 'word/document.xml', 'word/styles.xml']:
        ok('has ' + req, req in names)
    for n in names:
        try:
            ET.fromstring(z.read(n))
        except Exception as e:
            ok('parses ' + n, False, e)
    d = z.read('word/document.xml').decode('utf8')
    ok('document has a body', '<w:body>' in d)
    ok('tables are present', d.count('<w:tbl>') >= 4, d.count('<w:tbl>'))
    ok('table headers repeat across pages', '<w:tblHeader/>' in d)
    ok('state cells are shaded', 'w:fill="FEE2E2"' in d or 'w:fill="DCFCE7"' in d)
    ok('page size and margins set', '<w:pgSz' in d and '<w:pgMar' in d)
    s = z.read('word/styles.xml').decode('utf8')
    ok('heading styles defined', 'Heading1' in s and 'Title' in s)

print('\n%s' % ('OOXML OK' if bad == 0 else '%d ISSUE(S)' % bad))
sys.exit(0 if bad == 0 else 1)
