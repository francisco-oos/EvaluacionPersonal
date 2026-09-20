import json
from pathlib import Path
from zipfile import ZipFile
import io

from app.server import Application


def request(app, method, path, payload=None, cookie=None):
    headers = {"Cookie": cookie} if cookie else {}
    status, response_headers, body = app.dispatch(
        method,
        path,
        json.dumps(payload).encode() if payload is not None else b"",
        headers,
    )
    data = None
    if body and response_headers.get("Content-Type", "").startswith("application/json"):
        data = json.loads(body)
    return status, response_headers, data, body


def login(app, username, password):
    status, headers, data, _ = request(app, "POST", "/api/login", {"username": username, "password": password})
    assert status == 200
    return headers["Set-Cookie"].split(";", 1)[0], data["user"]


def test_authenticated_admin_catalog_capture_and_department_exports(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    app = Application(tmp_path / "api.sqlite3", root / "assets" / "ESQUELETO FORMATO.xlsx", tmp_path / "exports")

    bootstrap_password = app.database.initial_admin_password
    assert bootstrap_password
    admin_cookie, admin = login(app, "admin", bootstrap_password)
    status, _, _, _ = request(app, "GET", "/api/admin/users", cookie=admin_cookie)
    assert status == 403
    status, _, data, _ = request(app, "POST", "/api/change-password", {
        "current_password": bootstrap_password, "new_password": "NuevaAdmin12!"
    }, admin_cookie)
    assert status == 200 and data["reauthenticate"] is True
    admin_cookie, admin = login(app, "admin", "NuevaAdmin12!")

    status, _, department, _ = request(app, "POST", "/api/admin/departments", {"name": "HSE CAMPO", "code": "HSE"}, admin_cookie)
    assert status == 201
    did = department["id"]
    assert request(app, "POST", "/api/admin/positions", {"department_id": did, "name": "SUPERVISOR HSE A"}, admin_cookie)[0] == 201
    assert request(app, "POST", "/api/admin/users", {
        "username": "maria", "display_name": "María López", "password": "Temporal12!",
        "department_id": did, "role": "capturist"
    }, admin_cookie)[0] == 201

    maria_cookie, _ = login(app, "maria", "Temporal12!")
    status, _, bootstrap, _ = request(app, "GET", "/api/bootstrap", cookie=maria_cookie)
    assert status == 200 and bootstrap["catalog"]["department"]["id"] == did
    assert request(app, "POST", "/api/change-password", {
        "current_password": "Temporal12!", "new_password": "MariaSegura12!"
    }, maria_cookie)[0] == 200
    maria_cookie, maria = login(app, "maria", "MariaSegura12!")

    evaluation = {
        "evaluation_date": "2026-07-25", "employee_name": "Ana Pérez",
        "category": "SUPERVISOR HSE A", "status": "final", "department_id": 999,
        "client_record_id": "api-1", "areas": {}
    }
    status, _, saved, _ = request(app, "POST", "/api/evaluations", evaluation, maria_cookie)
    assert status == 201
    assert saved["department_id"] == did
    assert saved["captured_by_username"] == "maria"

    status, headers, _, excel = request(app, "GET", f"/export/evaluaciones.xlsx?status=all&department_id={did}", cookie=maria_cookie)
    assert status == 200 and excel.startswith(b"PK")
    with ZipFile(io.BytesIO(excel)) as archive:
        sheet_xml = archive.read("xl/worksheets/sheet1.xml")
    assert b"Ana P" in sheet_xml and b"HSE CAMPO" not in sheet_xml

    status, _, _, department_zip = request(app, "GET", "/export/departamentos.zip", cookie=admin_cookie)
    assert status == 200
    with ZipFile(io.BytesIO(department_zip)) as archive:
        assert any(name.startswith("Evaluaciones_HSE") for name in archive.namelist())
