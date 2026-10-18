"""Read and update the user-owned Okapi OpenXML filter configuration."""

from pathlib import Path
from threading import RLock
import re
from shutil import copyfile
from zipfile import ZipFile
from xml.etree import ElementTree as ET


CONFIGURATION_ID = "okf_openxml@copy-of-default"
# Tikal is started in its own installation directory.  Passing this absolute
# path keeps project-owned presets independent from that installation.
CONFIGURATION_PATH = Path(__file__).resolve().parent.parent / "config" / "okapi" / f"{CONFIGURATION_ID}.fprm"


def word_templates() -> list[dict[str, str | bool]]:
    """Return the built-in preset followed by project-owned OpenXML presets."""
    templates: list[dict[str, str | bool]] = [{
        "id": "",
        "label": "Встроенный шаблон OpenXML по умолчанию",
        "custom": False,
    }]
    if CONFIGURATION_PATH.parent.is_dir():
        for path in sorted(CONFIGURATION_PATH.parent.glob("okf_openxml@*.fprm"), key=lambda item: item.stat().st_mtime, reverse=True):
            templates.append({
                "id": path.name,
                "label": path.stem.removeprefix("okf_openxml@"),
                "custom": True,
            })
    return templates


def resolve_word_template(template_id: str) -> Path | None:
    """Resolve only a listed project template; never accept a client file path."""
    if not template_id:
        return None
    allowed = {str(item["id"]) for item in word_templates() if item["custom"]}
    if template_id not in allowed:
        raise ValueError("Выбранный шаблон MS Word больше недоступен.")
    return CONFIGURATION_PATH.parent / template_id


def word_template_options(template_id: str = "") -> dict:
    """Read a project template selected by its safe, listed identifier."""
    return OpenXmlOptions(resolve_word_template(template_id) or CONFIGURATION_PATH).public()


def create_word_template(template_name: str, base_template_id: str = "") -> dict:
    """Create a named project template from the selected existing template."""
    target = template_path(template_name)
    source = resolve_word_template(base_template_id) or CONFIGURATION_PATH
    if target.exists():
        raise ValueError("Шаблон с таким именем уже существует.")
    if not source.is_file():
        raise ValueError("Не найдена основа для нового шаблона.")
    target.parent.mkdir(parents=True, exist_ok=True)
    copyfile(source, target)
    return OpenXmlOptions(target).public()


def delete_word_template(template_id: str) -> None:
    """Delete only a user-created template; retain the project fallback preset."""
    target = resolve_word_template(template_id)
    if target is None:
        raise ValueError("Встроенный шаблон удалить нельзя.")
    if target == CONFIGURATION_PATH:
        raise ValueError("Нельзя удалить базовый шаблон проекта.")
    target.unlink(missing_ok=False)


def template_path(template_name: str) -> Path:
    clean = template_name.strip()
    if not clean or any(char in clean for char in '<>:"/\\|?*') or len(clean) > 120:
        raise ValueError("Укажите имя шаблона без символов < > : \" / \\ | ? *.")
    return CONFIGURATION_PATH.parent / f"okf_openxml@{clean.removesuffix('.fprm')}.fprm"


def analyse_word_document(path: Path) -> dict[str, list[str]]:
    """Collect OpenXML option candidates without changing the uploaded document."""
    word = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    ns = {"w": word}
    attr = f"{{{word}}}val"
    fields: set[str] = set()
    styles: set[str] = set()
    highlights: set[str] = set()
    with ZipFile(path) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
        for node in document.findall(".//w:fldSimple", ns):
            instruction = node.get(f"{{{word}}}instr", "")
            match = re.search(r"[A-Za-z]+", instruction)
            if match:
                fields.add(match.group(0).upper())
        for node in document.findall(".//w:instrText", ns):
            match = re.search(r"[A-Za-z]+", node.text or "")
            if match:
                fields.add(match.group(0).upper())
        for node in document.findall(".//w:highlight", ns):
            value = node.get(attr, "")
            if value and value != "none":
                highlights.add(value)
        styles_xml = ET.fromstring(archive.read("word/styles.xml"))
        for node in styles_xml.findall(".//w:style", ns):
            if node.get(f"{{{word}}}type") not in {"paragraph", "character"}:
                continue
            name = node.find("w:name", ns)
            if name is not None and name.get(attr):
                styles.add(name.get(attr))
    return {"fields": sorted(fields), "styles": sorted(styles, key=str.casefold), "highlights": sorted(highlights, key=str.casefold)}

# The names are the exact ParametersString keys used by Okapi OpenXML 1.47.
BOOLEAN_DEFAULTS = {
    "bPreferenceTranslateDocProperties": True,
    "bPreferenceTranslateComments": True,
    "bPreferenceAggressiveCleanup": False,
    "bPreferenceAddTabAsCharacter": False,
    "bPreferenceAddLineSeparatorAsCharacter": False,
    "bExtractExternalHyperlinks": False,
    "bPreferenceTranslateWordHeadersFooters": True,
    "translateWordNumberingLevelText": False,
    "bPreferenceTranslateWordHidden": False,
    "bPreferenceTranslateWordExcludeGraphicMetaData": False,
    "bPreferenceAutomaticallyAcceptRevisions": True,
    "bPreferenceIgnoreSoftHyphenTag": False,
    "bPreferenceReplaceNoBreakHyphenTag": False,
    "allowWordStyleOptimisation": True,
    "bInExcludeMode": True,
    # With an empty colour list, Include mode excludes every unhighlighted run.
    # Exclude is the safe OpenXML default: an empty list excludes nothing.
    "bInExcludeHighlightMode": True,
    "ignoreWordFontColors": False,
    "bPreferenceTranslateExcelHidden": False,
    "bPreferenceTranslateExcelSheetNames": False,
    "translateExcelCellsCopied": True,
    "bPreferenceTranslateExcelDiagramData": False,
    "bPreferenceTranslateExcelDrawings": False,
    "preserveExcelStylesInTargetColumns": False,
    "translatePowerpointDocProperties": True,
    "reorderPowerpointDocProperties": False,
    "translatePowerpointDiagramData": True,
    "reorderPowerpointDiagramData": False,
    "translatePowerpointCharts": True,
    "reorderPowerpointCharts": False,
    "bPreferenceTranslatePowerpointNotes": True,
    "bPreferenceReorderPowerpointNotes": False,
    "translatePowerpointComments": True,
    "reorderPowerpointComments": False,
    "bPreferenceTranslatePowerpointMasters": True,
    "bPreferenceIgnorePlaceholdersInPowerpointMasters": False,
    "bPreferencePowerpointIncludedSlideNumbersOnly": False,
    "bReorderPowerpointNotesAndComments": False,
}

TEXT_DEFAULTS = {
    "sPreferenceLineSeparatorReplacement": "$0a$",
    "subfilter": "",
    "wordFontColoursMinimumIgnoranceThreshold": "",
    "wordFontColoursMaximumIgnoranceThreshold": "",
}

LISTS = {
    "translate_fields": ("tsComplexFieldDefinitionsToExtract", "cfd"),
    "excel_excluded_colours": ("tsExcelExcludedColors", "ccc"),
    "word_styles": ("tsExcludeWordStyles", "ews"),
    "word_highlight_colours": ("tsWordHighlightColors", "whc"),
    "word_excluded_colours": ("tsWordExcludedColors", "wec"),
    "powerpoint_slide_numbers": ("tsPowerpointIncludedSlideNumbers", "psi"),
}


class OpenXmlOptions:
    def __init__(self, path: Path = CONFIGURATION_PATH) -> None:
        self.path = path
        self.lock = RLock()

    def _read(self) -> tuple[list[str], dict[str, str]]:
        if not self.path.is_file():
            return ["#v1"], {}
        lines = self.path.read_text(encoding="utf-8").splitlines()
        values = {}
        for line in lines:
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key] = value
        return lines, values

    @staticmethod
    def _list(values: dict[str, str], count_key: str, item_prefix: str) -> list[str]:
        count = int(values.get(f"{count_key}.i", "0") or 0)
        return [values.get(f"{item_prefix}{index}", "") for index in range(count) if values.get(f"{item_prefix}{index}", "")]

    def public(self) -> dict:
        with self.lock:
            _, values = self._read()
            result = {key: values.get(f"{key}.b", str(default)).lower() == "true" for key, default in BOOLEAN_DEFAULTS.items()}
            result.update({key: values.get(key, default) for key, default in TEXT_DEFAULTS.items()})
            result.update({name: self._list(values, count, prefix) for name, (count, prefix) in LISTS.items()})
            result["worksheet_configurations"] = self._worksheets(values)
            result["configuration_path"] = str(self.path)
            result["configuration_id"] = CONFIGURATION_ID
            return result

    @staticmethod
    def _worksheets(values: dict[str, str]) -> list[dict[str, str]]:
        count = int(values.get("worksheetConfigurations.number.i", "0") or 0)
        fields = ("namePattern", "sourceColumns", "targetColumns", "targetColumnsMaxCharacters", "excludedRows", "excludedColumns", "metadataRows", "metadataColumns")
        return [{field: values.get(f"worksheetConfigurations.{index}.{field}", "") for field in fields} for index in range(count)]

    def update(self, incoming: dict) -> dict:
        with self.lock:
            lines, values = self._read()
            for key in BOOLEAN_DEFAULTS:
                if key in incoming:
                    values[f"{key}.b"] = "true" if bool(incoming[key]) else "false"
            for key in TEXT_DEFAULTS:
                if key in incoming:
                    values[key] = str(incoming[key]).replace("\r", "").replace("\n", "")
            for name, (count_key, prefix) in LISTS.items():
                if name in incoming:
                    entries = [str(item).strip() for item in incoming[name] if str(item).strip()]
                    values[f"{count_key}.i"] = str(len(entries))
                    for key in list(values):
                        if key.startswith(prefix) and key[len(prefix):].isdigit():
                            del values[key]
                    for index, item in enumerate(entries):
                        values[f"{prefix}{index}"] = item
            if "worksheet_configurations" in incoming:
                fields = ("namePattern", "sourceColumns", "targetColumns", "targetColumnsMaxCharacters", "excludedRows", "excludedColumns", "metadataRows", "metadataColumns")
                rows = incoming["worksheet_configurations"]
                values["worksheetConfigurations.number.i"] = str(len(rows))
                for key in list(values):
                    if key.startswith("worksheetConfigurations.") and key != "worksheetConfigurations.number.i":
                        del values[key]
                for index, row in enumerate(rows):
                    for field in fields:
                        values[f"worksheetConfigurations.{index}.{field}"] = str(row.get(field, "")).replace("\n", "")
            self._write(lines, values)
            return self.public()

    def save_template(self, template_name: str, incoming: dict) -> dict:
        target = template_path(template_name)
        with self.lock:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                copyfile(self.path, target)
        return OpenXmlOptions(target).update(incoming)

    def _write(self, original_lines: list[str], values: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        emitted: set[str] = set()
        output = []
        for line in original_lines:
            if "=" in line and not line.lstrip().startswith("#"):
                key = line.split("=", 1)[0]
                if key in values:
                    output.append(f"{key}={values[key]}")
                    emitted.add(key)
                continue
            output.append(line)
        for key, value in values.items():
            if key not in emitted:
                output.append(f"{key}={value}")
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
        temporary.replace(self.path)


openxml_options = OpenXmlOptions()
