from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from .config import AREAS, SCORE_FIELDS

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
ET.register_namespace("", NS)
ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
ET.register_namespace("mc", "http://schemas.openxmlformats.org/markup-compatibility/2006")
ET.register_namespace("x14ac", "http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac")
ET.register_namespace("x15", "http://schemas.microsoft.com/office/spreadsheetml/2010/11/main")
ET.register_namespace("x15ac", "http://schemas.microsoft.com/office/spreadsheetml/2010/11/ac")
ET.register_namespace("xr", "http://schemas.microsoft.com/office/spreadsheetml/2014/revision")
ET.register_namespace("xr2", "http://schemas.microsoft.com/office/spreadsheetml/2015/revision2")
ET.register_namespace("xr3", "http://schemas.microsoft.com/office/spreadsheetml/2016/revision3")
ET.register_namespace("xr6", "http://schemas.microsoft.com/office/spreadsheetml/2016/revision6")
ET.register_namespace("xr10", "http://schemas.microsoft.com/office/spreadsheetml/2016/revision10")

COLUMN_ORDER = [
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X"
]
COLUMN_STYLES = {
    "A": "6", "B": "2", "C": "2",
    "D": "3", "E": "3", "F": "3", "G": "3", "H": "3", "I": "3",
    "J": "3", "K": "3", "L": "3", "M": "3", "N": "3", "O": "3",
    "P": "3", "Q": "3", "R": "3", "S": "4",
    "T": "2", "U": "2", "V": "2", "W": "2", "X": "2",
}
AREA_COLUMNS = {
    "material": ("D", "E", "F", "T"),
    "hse": ("G", "H", "I", "U"),
    "inova": ("J", "K", "L", "V"),
    "sercel": ("M", "N", "O", "W"),
    "sismografo": ("P", "Q", "R", "X"),
}


def _cell(row: ET.Element, column: str, row_number: int) -> ET.Element:
    address = f"{column}{row_number}"
    found = row.find(f"{{{NS}}}c[@r='{address}']")
    if found is None:
        found = ET.SubElement(row, f"{{{NS}}}c", {"r": address, "s": COLUMN_STYLES[column]})
    else:
        found.set("s", found.get("s", COLUMN_STYLES[column]))
    for child in list(found):
        found.remove(child)
    found.attrib.pop("t", None)
    return found


def _set_inline_string(cell: ET.Element, value: str) -> None:
    if not value:
        return
    cell.set("t", "inlineStr")
    inline = ET.SubElement(cell, f"{{{NS}}}is")
    text = ET.SubElement(inline, f"{{{NS}}}t")
    if value != value.strip() or "\n" in value:
        text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text.text = value


def _set_number(cell: ET.Element, value: int | float | None) -> None:
    if value is None:
        return
    ET.SubElement(cell, f"{{{NS}}}v").text = str(value)


def _set_formula(cell: ET.Element, formula: str, cached_value: float | None) -> None:
    ET.SubElement(cell, f"{{{NS}}}f").text = formula
    if cached_value is not None:
        ET.SubElement(cell, f"{{{NS}}}v").text = f"{cached_value:.10g}"


def _ensure_row(sheet_data: ET.Element, row_number: int, template_row: ET.Element) -> ET.Element:
    row = sheet_data.find(f"{{{NS}}}row[@r='{row_number}']")
    if row is not None:
        return row
    row = ET.fromstring(ET.tostring(template_row))
    row.set("r", str(row_number))
    row.set("spans", "1:24")
    for cell in row.findall(f"{{{NS}}}c"):
        letters = "".join(ch for ch in cell.get("r", "") if ch.isalpha())
        cell.set("r", f"{letters}{row_number}")
        for child in list(cell):
            cell.remove(child)
    sheet_data.append(row)
    return row


def export_to_template(template_path: Path, output_path: Path, evaluations: list[dict[str, Any]]) -> Path:
    template_path = Path(template_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="evaluacion_excel_") as temp_dir:
        temp = Path(temp_dir)
        with ZipFile(template_path) as source:
            source.extractall(temp)

        sheet_path = temp / "xl" / "worksheets" / "sheet1.xml"
        tree = ET.parse(sheet_path)
        root = tree.getroot()
        sheet_data = root.find(f"{{{NS}}}sheetData")
        if sheet_data is None:
            raise RuntimeError("La plantilla no contiene sheetData.")
        template_row = sheet_data.find(f"{{{NS}}}row[@r='3']")
        if template_row is None:
            raise RuntimeError("La plantilla no contiene la fila base 3.")

        max_row = max(3 + len(evaluations) - 1, 3)
        for index, evaluation in enumerate(evaluations, start=3):
            row = _ensure_row(sheet_data, index, template_row)
            row.set("spans", "1:24")
            for column in COLUMN_ORDER:
                _cell(row, column, index)

            try:
                date_text = datetime.strptime(evaluation["evaluation_date"], "%Y-%m-%d").strftime("%d/%m/%Y")
            except (KeyError, ValueError):
                date_text = str(evaluation.get("evaluation_date") or "")
            _set_inline_string(_cell(row, "A", index), date_text)
            _set_inline_string(_cell(row, "B", index), str(evaluation.get("employee_name") or ""))
            _set_inline_string(_cell(row, "C", index), str(evaluation.get("category") or ""))

            score_values: list[int] = []
            for area in AREAS:
                result = (evaluation.get("areas") or {}).get(area["code"]) or {}
                attitude_col, performance_col, technical_col, comment_col = AREA_COLUMNS[area["code"]]
                for field, column in zip(SCORE_FIELDS, (attitude_col, performance_col, technical_col)):
                    value = result.get(field)
                    if value is not None:
                        value = int(value)
                        score_values.append(value)
                    _set_number(_cell(row, column, index), value)
                comment = str(result.get("comment") or "") if result.get("has_comment") else ""
                _set_inline_string(_cell(row, comment_col, index), comment)

            average = sum(score_values) / len(score_values) if score_values else None
            average_cell = _cell(row, "S", index)
            if average is not None:
                _set_formula(average_cell, f'IF(COUNT(D{index}:R{index})=0,"",AVERAGE(D{index}:R{index}))', average)

        # Limpia cualquier dato residual por debajo de la última evaluación, conservando formato.
        for row in sheet_data.findall(f"{{{NS}}}row"):
            row_number = int(row.get("r", "0"))
            if row_number >= 3 and row_number > max_row:
                for column in COLUMN_ORDER:
                    _cell(row, column, row_number)

        dimension = root.find(f"{{{NS}}}dimension")
        final_dimension_row = max(max_row, 123)
        if dimension is not None:
            dimension.set("ref", f"A1:X{final_dimension_row}")
        tree.write(sheet_path, encoding="utf-8", xml_declaration=True)
        # ElementTree elimina declaraciones de prefijos que solo aparecen en mc:Ignorable.
        # Se restauran para que Excel y validadores OOXML no encuentren prefijos sin declarar.
        sheet_xml = sheet_path.read_text(encoding="utf-8")
        if "xmlns:xr2=" not in sheet_xml:
            sheet_xml = sheet_xml.replace(
                "<worksheet ",
                '<worksheet xmlns:xr2="http://schemas.microsoft.com/office/spreadsheetml/2015/revision2" '
                'xmlns:xr3="http://schemas.microsoft.com/office/spreadsheetml/2016/revision3" ',
                1,
            )
        sheet_path.write_text(sheet_xml, encoding="utf-8")

        # Fuerza recálculo limpio al abrir y elimina calcChain obsoleto de la plantilla.
        calc_chain = temp / "xl" / "calcChain.xml"
        if calc_chain.exists():
            calc_chain.unlink()
        rels_path = temp / "xl" / "_rels" / "workbook.xml.rels"
        rels_tree = ET.parse(rels_path)
        rels_root = rels_tree.getroot()
        for rel in list(rels_root):
            if rel.get("Type", "").endswith("/calcChain"):
                rels_root.remove(rel)
        rels_tree.write(rels_path, encoding="utf-8", xml_declaration=True)

        types_path = temp / "[Content_Types].xml"
        types_xml = types_path.read_text(encoding="utf-8")
        types_xml = types_xml.replace(
            '<Override PartName="/xl/calcChain.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.calcChain+xml"/>',
            "",
        )
        types_path.write_text(types_xml, encoding="utf-8")

        workbook_path = temp / "xl" / "workbook.xml"
        workbook_tree = ET.parse(workbook_path)
        workbook_root = workbook_tree.getroot()
        calc_pr = workbook_root.find(f"{{{NS}}}calcPr")
        if calc_pr is None:
            calc_pr = ET.SubElement(workbook_root, f"{{{NS}}}calcPr")
        calc_pr.set("fullCalcOnLoad", "1")
        calc_pr.set("forceFullCalc", "1")
        calc_pr.set("calcMode", "auto")
        workbook_tree.write(workbook_path, encoding="utf-8", xml_declaration=True)
        workbook_xml = workbook_path.read_text(encoding="utf-8")
        if "xmlns:x15=" not in workbook_xml:
            workbook_xml = workbook_xml.replace(
                "<workbook ",
                '<workbook xmlns:x15="http://schemas.microsoft.com/office/spreadsheetml/2010/11/main" ',
                1,
            )
        workbook_path.write_text(workbook_xml, encoding="utf-8")

        with ZipFile(output_path, "w", ZIP_DEFLATED) as target:
            for path in sorted(temp.rglob("*")):
                if path.is_file():
                    target.write(path, path.relative_to(temp).as_posix())
    return output_path



def safe_filename(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", normalized).strip("_")
    return cleaned[:60] or "DEPARTAMENTO"


def create_backup_zip(
    database,
    template_path: Path,
    output_path: Path,
    department_evaluations: dict[str, list[dict[str, Any]]],
) -> Path:
    """Respalda la BD y genera un Excel institucional por departamento."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="evaluacion_backup_") as temp_dir:
        temp = Path(temp_dir)
        db_copy = temp / "evaluaciones_personal.sqlite3"
        excel_dir = temp / "Excel_por_departamento"
        excel_dir.mkdir()
        database.backup_to(db_copy)

        generated_files = [db_copy]
        for department_code, evaluations in department_evaluations.items():
            excel_copy = excel_dir / f"Evaluaciones_{safe_filename(department_code)}.xlsx"
            export_to_template(template_path, excel_copy, evaluations)
            generated_files.append(excel_copy)

        manifest = {
            "tipo": "RESPALDO_EVALUACION_PERSONAL_MULTI_DEPARTAMENTO",
            "creado": datetime.now().isoformat(timespec="seconds"),
            "archivos": {},
        }
        for file in generated_files:
            relative = file.relative_to(temp).as_posix()
            manifest["archivos"][relative] = {
                "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                "bytes": file.stat().st_size,
            }
        manifest_path = temp / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        with ZipFile(output_path, "w", ZIP_DEFLATED) as archive:
            for file in sorted(temp.rglob("*")):
                if file.is_file():
                    archive.write(file, file.relative_to(temp).as_posix())
    return output_path
