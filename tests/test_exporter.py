from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from app.exporter import export_to_template

NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def test_export_preserves_template_and_writes_values(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "out.xlsx"
    evaluations = [{
        "evaluation_date": "2026-07-25",
        "employee_name": "María López",
        "category": "TIRADOR B",
        "status": "final",
        "areas": {
            "material": {"attitude": 3, "performance": 2, "technical": 1, "has_comment": True, "comment": "Observación de prueba"},
            "hse": {"attitude": None, "performance": None, "technical": None, "has_comment": False, "comment": ""},
            "inova": {"attitude": 3, "performance": 3, "technical": 3, "has_comment": False, "comment": ""},
            "sercel": {"attitude": None, "performance": 2, "technical": None, "has_comment": False, "comment": ""},
            "sismografo": {"attitude": None, "performance": None, "technical": None, "has_comment": False, "comment": ""},
        },
    }]
    export_to_template(root / "assets" / "ESQUELETO FORMATO.xlsx", output, evaluations)
    assert output.exists() and output.stat().st_size > 10000
    with ZipFile(output) as archive:
        assert "xl/calcChain.xml" not in archive.namelist()
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    b3 = sheet.find(".//x:c[@r='B3']/x:is/x:t", NS)
    d3 = sheet.find(".//x:c[@r='D3']/x:v", NS)
    s3 = sheet.find(".//x:c[@r='S3']/x:f", NS)
    t3 = sheet.find(".//x:c[@r='T3']/x:is/x:t", NS)
    assert b3 is not None and b3.text == "María López"
    assert d3 is not None and d3.text == "3"
    assert s3 is not None and "AVERAGE(D3:R3)" in s3.text
    assert t3 is not None and t3.text == "Observación de prueba"
