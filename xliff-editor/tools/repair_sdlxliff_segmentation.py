"""Repair missing target <mrk mtype='seg' mid='…'> markers for Trados.

The script never overwrites its input. For units with several source segments,
the full existing target mixed content is retained in the first marker and the
remaining required markers are empty. This is lossless, but those units may
need linguistic re-segmentation in Trados afterwards.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import re
from xml.etree import ElementTree as ET

XLIFF = "urn:oasis:names:tc:xliff:document:1.2"

def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]

def segment_markers(element: ET.Element) -> list[ET.Element]:
    return [node for node in element if local(node.tag) == "mrk" and node.get("mtype") == "seg"]

def repair(source: Path, destination: Path) -> tuple[int, int]:
    # Preserve namespace prefixes where ElementTree permits it.
    for _, pair in ET.iterparse(source, events=("start-ns",)):
        prefix, uri = pair
        # ElementTree reserves generated prefixes such as ns1/ns2. They remain
        # valid on output under a newly generated prefix.
        if not re.fullmatch(r"ns\d+", prefix or ""):
            ET.register_namespace(prefix or "", uri)
    tree = ET.parse(source)
    repaired = multi_segment = 0
    for unit in (node for node in tree.iter() if local(node.tag) == "trans-unit"):
        seg_source = next((child for child in unit if local(child.tag) == "seg-source"), None)
        target = next((child for child in unit if local(child.tag) == "target"), None)
        if seg_source is None or target is None:
            continue
        expected = segment_markers(seg_source)
        actual = segment_markers(target)
        expected_ids = [node.get("mid") for node in expected]
        if not expected_ids or [node.get("mid") for node in actual] == expected_ids:
            continue
        # Move original mixed content under the first marker. Moving XML nodes,
        # rather than serializing text, retains nested inline codes and tails.
        original_text, original_children = target.text, list(target)
        for child in original_children:
            target.remove(child)
        target.text = None
        for position, mid in enumerate(expected_ids):
            marker = ET.Element(f"{{{XLIFF}}}mrk", {"mtype": "seg", "mid": mid or ""})
            if position == 0:
                marker.text = original_text
                for child in original_children:
                    marker.append(child)
            target.append(marker)
        repaired += 1
        multi_segment += len(expected_ids) > 1
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    return repaired, multi_segment

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    repaired, multi = repair(args.source, args.destination)
    print(f"Repaired {repaired} trans-units ({multi} with multiple segments): {args.destination}")
