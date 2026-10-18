"""Lossless-enough XLIFF mapping: original XML is retained and only target nodes change."""
from __future__ import annotations
from dataclasses import dataclass
from xml.etree import ElementTree as ET
from html import escape
import uuid

def local(tag: str) -> str: return tag.rsplit('}', 1)[-1]
def path_join(path: tuple[int, ...]) -> str: return '/'.join(map(str, path))
def node_at(root: ET.Element, encoded: str) -> ET.Element:
    node = root
    for index in filter(None, encoded.split('/')): node = list(node)[int(index)]
    return node

def inner_xml(node: ET.Element | None) -> str:
    if node is None: return ''
    result = escape(node.text or '')
    for child in node:
        result += ET.tostring(child, encoding='unicode')
    return result

def plain_text(node: ET.Element | None) -> str:
    return ''.join(node.itertext()) if node is not None else ''

def validate_fragment(value: str) -> None:
    ET.fromstring(f'<wrapper>{value}</wrapper>')

@dataclass
class ParsedSegment:
    id: str; xliff_id: str | None; file_id: str; unit_id: str; path: str; index: int
    source: str; source_xml: str; target: str | None; state: str
@dataclass
class ParsedUnit:
    id: str; file_id: str; xliff_id: str | None; path: str; position: int
@dataclass
class ParsedFile:
    id: str; xliff_id: str | None; path: str; position: int

def parse(payload: bytes):
    root = ET.fromstring(payload)
    files: list[ParsedFile] = []; units: list[ParsedUnit] = []; segments: list[ParsedSegment] = []
    file_nodes = [(n,p) for n,p in walk(root) if local(n.tag) == 'file']
    if not file_nodes: file_nodes = [(root, ())]
    global_index = 0
    for fpos,(fnode,fpath) in enumerate(file_nodes):
        file_id = str(uuid.uuid4()); files.append(ParsedFile(file_id, fnode.get('id'), path_join(fpath), fpos))
        # 1.2 trans-unit and 2.x segment are both logical rows.
        # Keep a path lookup from one traversal. Re-walking from root for every
        # row turns a 20k-segment import into quadratic work.
        file_items = list(walk(fnode, fpath))
        node_by_path = {path_join(p): n for n, p in file_items}
        candidates = [(n,p) for n,p in file_items if local(n.tag) in {'trans-unit','segment'}]
        units_by_path: dict[str, str] = {}
        for upos,(snode,spath) in enumerate(candidates):
            # In 1.2 a trans-unit is the unit; in 2.x its parent <unit> owns segments.
            unit_path = path_join(spath if local(snode.tag) == 'trans-unit' else spath[:-1])
            unit_node = snode if local(snode.tag) == 'trans-unit' else node_by_path[unit_path]
            unit_id = units_by_path.get(unit_path)
            if unit_id is None:
                unit_id = str(uuid.uuid4()); units_by_path[unit_path] = unit_id
                units.append(ParsedUnit(unit_id,file_id,unit_node.get('id'),unit_path,len(units_by_path)-1))
            source = next((x for x in snode if local(x.tag)=='source'), None)
            target = next((x for x in snode if local(x.tag)=='target'), None)
            state = (target.get('state') if target is not None else None) or ('translated' if target is not None and plain_text(target) else 'untranslated')
            segments.append(ParsedSegment(str(uuid.uuid4()), snode.get('id'), file_id, unit_id, path_join(spath), global_index, plain_text(source), inner_xml(source), inner_xml(target) if target is not None else None, state))
            global_index += 1
    return root, files, units, segments

def walk(node: ET.Element, path: tuple[int,...]=()):
    yield node,path
    for i,child in enumerate(node): yield from walk(child,path+(i,))

def set_target(root: ET.Element, segment_path: str, fragment: str, state: str) -> None:
    validate_fragment(fragment)
    segment = node_at(root, segment_path)
    target = next((x for x in segment if local(x.tag)=='target'), None)
    if target is None:
        namespace = segment.tag[:segment.tag.rfind('}')+1] if '}' in segment.tag else ''
        target = ET.Element(namespace + 'target'); segment.append(target)
    wrapper = ET.fromstring(f'<wrapper>{fragment}</wrapper>')
    # Element.clear() would also erase vendor attributes/extensions on target.
    # Replace only mixed content; all existing attributes remain intact.
    for child in list(target): target.remove(child)
    target.text = wrapper.text
    for child in wrapper: target.append(child)
    if state: target.set('state', state)
