from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.database import ConflictError, Database, PermissionDenied


def make_ready_database(tmp_path: Path):
    db = Database(tmp_path / "db.sqlite3")
    token, admin = db.login("admin", "Admin1234!")
    db.change_password(admin["id"], "Admin1234!", "NuevaAdmin12!")
    token, admin = db.login("admin", "NuevaAdmin12!")
    department = db.create_department("HSE CAMPO", "HSE")
    db.create_position(department["id"], "SUPERVISOR HSE A")
    capturist = db.create_user("maria", "María López", "Temporal12!", department["id"])
    db.change_password(capturist["id"], "Temporal12!", "MariaSegura12!")
    _, capturist = db.login("maria", "MariaSegura12!")
    return db, admin, capturist, department


def payload(index=1, status="final"):
    return {
        "evaluation_date": "2026-07-25",
        "employee_name": f"Empleado {index:03d}",
        "category": "SUPERVISOR HSE A",
        "status": status,
        "department_id": 999,
        "client_record_id": f"token-{index}",
        "revision": None,
        "areas": {
            "material": {"attitude": 3, "performance": 2, "technical": 1, "has_comment": True, "comment": "Buen control."},
        },
    }


def test_users_departments_positions_and_scoped_evaluation(tmp_path: Path):
    db, admin, capturist, department = make_ready_database(tmp_path)
    saved = db.save_evaluation(payload(), capturist)
    assert saved["department_id"] == department["id"]
    assert saved["captured_by_name"] == "María López"
    assert saved["average"] == 2.0
    assert db.catalog(capturist, 999)["department"]["id"] == department["id"]

    other = db.create_department("CONTROL DE MATERIAL", "MAT")
    db.create_position(other["id"], "ALMACENISTA A")
    assert db.list_evaluations(capturist, department_id=other["id"])[0]["id"] == saved["id"]

    with pytest.raises(PermissionDenied):
        db.delete_evaluation(saved["id"], capturist)
    db.delete_evaluation(saved["id"], admin)
    assert db.stats(admin)["total"] == 0


def test_duplicate_is_blocked_inside_department_but_allowed_in_another(tmp_path: Path):
    db, admin, capturist, department = make_ready_database(tmp_path)
    db.save_evaluation(payload(1), capturist)
    duplicate = payload(1)
    duplicate["client_record_id"] = "other-token"
    with pytest.raises(ConflictError):
        db.save_evaluation(duplicate, capturist)

    other = db.create_department("ADQUISICIÓN DOS", "ADQ2")
    db.create_position(other["id"], "SUPERVISOR HSE A")
    other_user = db.create_user("pedro", "Pedro Ruiz", "Temporal34!", other["id"])
    db.change_password(other_user["id"], "Temporal34!", "PedroSeguro34!")
    _, other_user = db.login("pedro", "PedroSeguro34!")
    saved = db.save_evaluation(duplicate, other_user)
    assert saved["department_id"] == other["id"]


def test_concurrent_capturists_keep_integrity(tmp_path: Path):
    db, admin, capturist, department = make_ready_database(tmp_path)
    second = db.create_user("laura", "Laura Díaz", "Temporal56!", department["id"])
    db.change_password(second["id"], "Temporal56!", "LauraSegura56!")
    _, second = db.login("laura", "LauraSegura56!")

    def save(index: int):
        user = capturist if index % 2 == 0 else second
        return db.save_evaluation(payload(index), user)

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(save, range(1, 61)))

    assert len({item["id"] for item in results}) == 60
    stats = db.stats(admin, department["id"])
    assert stats["total"] == 60
    assert stats["by_operator"]["María López"] == 30
    assert stats["by_operator"]["Laura Díaz"] == 30
