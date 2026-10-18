from dataclasses import dataclass
from pathlib import Path
import copy
import xml.etree.ElementTree as ET


XLIFF_NS = "urn:oasis:names:tc:xliff:document:1.2"
NS = {"x": XLIFF_NS}


def _tag(name: str) -> str:
    return f"{{{XLIFF_NS}}}{name}"


def _inner_xml(element: ET.Element) -> str:
    chunks = [element.text or ""]
    chunks.extend(ET.tostring(child, encoding="unicode") for child in element)
    return "".join(chunks)


def _plain_text(element: ET.Element) -> str:
    return "".join(element.itertext()).strip()


def _inline_signature(element: ET.Element) -> list[tuple[str, str | None]]:
    """Inline code order must remain intact after model translation."""
    return [
        (node.tag.rsplit("}", 1)[-1], node.get("id"))
        for node in element.iter()
        if node is not element
    ]


def _set_inner_xml(element: ET.Element, value: str, source: ET.Element) -> None:
    try:
        wrapper = ET.fromstring(f'<wrapper xmlns="{XLIFF_NS}">{value}</wrapper>')
    except ET.ParseError as error:
        raise ValueError(f"Модель вернула некорректные inline-теги: {error}") from error
    if _inline_signature(wrapper) != _inline_signature(source):
        raise ValueError("Модель изменила inline-теги XLIFF")
    element.clear()
    element.text = wrapper.text
    for child in wrapper:
        element.append(copy.deepcopy(child))


@dataclass
class XliffSegment:
    id: str
    source_xml: str
    source_text: str
    source_element: ET.Element
    target_element: ET.Element


class XliffDocument:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.tree = ET.parse(path)
        self.root = self.tree.getroot()

    def segments(self) -> list[XliffSegment]:
        segments: list[XliffSegment] = []
        for unit in self.root.findall(".//x:trans-unit", NS):
            source = unit.find("x:source", NS)
            if source is None:
                continue
            target = unit.find("x:target", NS)
            if target is None:
                target = ET.SubElement(unit, _tag("target"))
            marked_sources = source.findall(".//x:mrk[@mtype='seg']", NS)
            if marked_sources:
                target_by_mid = {item.get("mid"): item for item in target.findall(".//x:mrk[@mtype='seg']", NS)}
                for index, source_mrk in enumerate(marked_sources, start=1):
                    if not _plain_text(source_mrk):
                        continue
                    mid = source_mrk.get("mid") or str(index)
                    target_mrk = target_by_mid.get(mid)
                    if target_mrk is None:
                        target_mrk = ET.SubElement(target, _tag("mrk"), {"mtype": "seg", "mid": mid})
                    segments.append(XliffSegment(
                        id=f"{unit.get('id', 'unit')}.{mid}",
                        source_xml=_inner_xml(source_mrk),
                        source_text=_plain_text(source_mrk),
                        source_element=source_mrk,
                        target_element=target_mrk,
                    ))
            elif _plain_text(source):
                segments.append(XliffSegment(
                    id=unit.get("id", f"unit-{len(segments) + 1}"),
                    source_xml=_inner_xml(source),
                    source_text=_plain_text(source),
                    source_element=source,
                    target_element=target,
                ))
        return segments

    def apply(self, segment: XliffSegment, translation: str) -> None:
        _set_inner_xml(segment.target_element, translation, segment.source_element)

    def save(self) -> None:
        ET.register_namespace("", XLIFF_NS)
        self.tree.write(self.path, encoding="utf-8", xml_declaration=True)
