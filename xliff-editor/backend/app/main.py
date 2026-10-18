from __future__ import annotations
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response
from datetime import datetime, timezone
import json, uuid
from .db import connection
from .schemas import DocumentOut, DocumentDetail, SegmentOut, SegmentPatch
from . import xliff
from xml.etree import ElementTree as ET

app = FastAPI(title='XLIFF Editor API', version='0.1.0')
def now(): return datetime.now(timezone.utc).isoformat()
def row_segment(r): return SegmentOut(**dict(r))

@app.post('/api/documents', response_model=DocumentOut, status_code=201)
async def upload_document(file: UploadFile = File(...)):
    payload = await file.read()
    try: root, files, units, segments = xliff.parse(payload)
    except ET.ParseError as exc: raise HTTPException(422, f'Invalid XLIFF XML: {exc}')
    if not segments: raise HTTPException(422, 'No XLIFF trans-unit or segment elements found')
    document_id=str(uuid.uuid4()); timestamp=now()
    with connection() as con:
        con.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?)',(document_id,file.filename or 'document.xliff',root.get('srcLang') or root.get('source-language'),root.get('trgLang') or root.get('target-language'),payload,timestamp,timestamp))
        con.executemany('INSERT INTO files VALUES(?,?,?,?,?,?)',[(x.id,document_id,x.xliff_id,x.path,x.position,'{}') for x in files])
        con.executemany('INSERT INTO units VALUES(?,?,?,?,?,?,?)',[(x.id,document_id,x.file_id,x.xliff_id,x.path,x.position,'{}') for x in units])
        con.executemany('INSERT INTO segments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',[(x.id,document_id,x.file_id,x.unit_id,x.xliff_id,x.path,x.index,x.source,x.source_xml,x.target,x.state,'[]','{}') for x in segments])
    return DocumentOut(id=document_id,name=file.filename or 'document.xliff',source_language=root.get('srcLang') or root.get('source-language'),target_language=root.get('trgLang') or root.get('target-language'),segment_count=len(segments))

@app.get('/api/documents/{document_id}', response_model=DocumentDetail)
def document(document_id: str):
    with connection() as con:
        d=con.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone()
        rows=con.execute('SELECT id,xliff_id,file_id,unit_id,segment_index,source_text,source_xml,target_xml,state FROM segments WHERE document_id=? ORDER BY segment_index',(document_id,)).fetchall()
    if not d: raise HTTPException(404,'Document not found')
    return DocumentDetail(id=d['id'],name=d['name'],source_language=d['source_language'],target_language=d['target_language'],segment_count=len(rows),segments=[row_segment(r) for r in rows])

@app.get('/api/documents/{document_id}/segments', response_model=list[SegmentOut])
def segments(document_id: str): return document(document_id).segments

@app.patch('/api/documents/{document_id}/segments/{segment_id}', response_model=SegmentOut)
def patch_segment(document_id: str, segment_id: str, patch: SegmentPatch):
    try: xliff.validate_fragment(patch.target_xml)
    except ET.ParseError as exc: raise HTTPException(422, f'Invalid target XML fragment: {exc}')
    with connection() as con:
        old=con.execute('SELECT * FROM segments WHERE id=? AND document_id=?',(segment_id,document_id)).fetchone()
        if not old: raise HTTPException(404,'Segment not found')
        state=patch.state or ('translated' if patch.target_xml.strip() else 'untranslated')
        con.execute('UPDATE segments SET target_xml=?,state=? WHERE id=?',(patch.target_xml,state,segment_id)); con.execute('UPDATE documents SET updated_at=? WHERE id=?',(now(),document_id))
        updated=con.execute('SELECT id,xliff_id,file_id,unit_id,segment_index,source_text,source_xml,target_xml,state FROM segments WHERE id=?',(segment_id,)).fetchone()
    return row_segment(updated)

@app.post('/api/documents/{document_id}/save')
def save(document_id: str):
    with connection() as con:
        if not con.execute('SELECT 1 FROM documents WHERE id=?',(document_id,)).fetchone(): raise HTTPException(404,'Document not found')
        con.execute('UPDATE documents SET updated_at=? WHERE id=?',(now(),document_id))
    return {'status':'saved'}

@app.get('/api/documents/{document_id}/export')
def export(document_id: str):
    with connection() as con:
        doc=con.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone(); rows=con.execute('SELECT original_path,target_xml,state FROM segments WHERE document_id=? ORDER BY segment_index',(document_id,)).fetchall()
    if not doc: raise HTTPException(404,'Document not found')
    root=ET.fromstring(doc['original_xml'])
    for row in rows:
        xliff.set_target(root,row['original_path'],row['target_xml'] or '',row['state'])
    data=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    return Response(data,media_type='application/xliff+xml',headers={'Content-Disposition':f'attachment; filename="{doc["name"]}"'})
