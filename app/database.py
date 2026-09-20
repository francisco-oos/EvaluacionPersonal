from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from .config import (
    AREAS,
    DEFAULT_ADMIN_USERNAME,
    INITIAL_ADMIN_PASSWORD,
    INITIAL_ADMIN_PASSWORD_FILE,
    DEFAULT_DEPARTMENT_CODE,
    DEFAULT_DEPARTMENT_NAME,
    LEGACY_CATEGORIES,
    PASSWORD_ITERATIONS,
    SCORE_FIELDS,
    SESSION_HOURS,
)


class ValidationError(ValueError):
    pass


class ConflictError(RuntimeError):
    """Evita sobrescrituras, duplicados o cambios administrativos incompatibles."""


class AuthenticationError(RuntimeError):
    pass


class PermissionDenied(RuntimeError):
    pass


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initial_admin_password: str | None = None
        self.initialize()

    @contextmanager
    def connect(self):
        # Una conexión por solicitud; WAL y busy_timeout permiten varios teléfonos.
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA busy_timeout = 30000")
        try:
            yield con
        finally:
            con.close()

    @staticmethod
    def _column_names(con: sqlite3.Connection, table: str) -> set[str]:
        return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    def initialize(self) -> None:
        with self.connect() as con:
            con.execute("PRAGMA journal_mode = WAL")
            con.execute("PRAGMA synchronous = NORMAL")
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS departments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    department_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(department_id, normalized_name),
                    FOREIGN KEY (department_id) REFERENCES departments(id)
                );

                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'capturist')),
                    department_id INTEGER,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
                    must_change_password INTEGER NOT NULL DEFAULT 1 CHECK(must_change_password IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (department_id) REFERENCES departments(id)
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS employees (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    normalized_name TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    last_category TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS employee_department_positions (
                    employee_id INTEGER NOT NULL,
                    department_id INTEGER NOT NULL,
                    last_position TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(employee_id, department_id),
                    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE,
                    FOREIGN KEY (department_id) REFERENCES departments(id)
                );

                CREATE TABLE IF NOT EXISTS evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    evaluation_date TEXT NOT NULL,
                    employee_name TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'final')),
                    operator_code TEXT NOT NULL DEFAULT 'PC',
                    client_record_id TEXT NOT NULL DEFAULT '',
                    normalized_employee_name TEXT NOT NULL DEFAULT '',
                    revision INTEGER NOT NULL DEFAULT 1,
                    department_id INTEGER,
                    captured_by_user_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (department_id) REFERENCES departments(id),
                    FOREIGN KEY (captured_by_user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS area_results (
                    evaluation_id INTEGER NOT NULL,
                    area_code TEXT NOT NULL,
                    attitude INTEGER CHECK(attitude BETWEEN 1 AND 3 OR attitude IS NULL),
                    performance INTEGER CHECK(performance BETWEEN 1 AND 3 OR performance IS NULL),
                    technical INTEGER CHECK(technical BETWEEN 1 AND 3 OR technical IS NULL),
                    has_comment INTEGER NOT NULL DEFAULT 0 CHECK(has_comment IN (0, 1)),
                    comment TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (evaluation_id, area_code),
                    FOREIGN KEY (evaluation_id) REFERENCES evaluations(id) ON DELETE CASCADE
                );
                """
            )

            now = self._now()
            con.execute(
                """INSERT INTO departments(code, name, active, created_at, updated_at)
                   VALUES (?, ?, 1, ?, ?)
                   ON CONFLICT(code) DO UPDATE SET updated_at=excluded.updated_at""",
                (DEFAULT_DEPARTMENT_CODE, DEFAULT_DEPARTMENT_NAME, now, now),
            )
            default_department_id = int(
                con.execute("SELECT id FROM departments WHERE code=?", (DEFAULT_DEPARTMENT_CODE,)).fetchone()[0]
            )

            # Migración automática desde las versiones 1.0/1.1.
            columns = self._column_names(con, "evaluations")
            migrations = {
                "operator_code": "ALTER TABLE evaluations ADD COLUMN operator_code TEXT NOT NULL DEFAULT 'PC'",
                "client_record_id": "ALTER TABLE evaluations ADD COLUMN client_record_id TEXT NOT NULL DEFAULT ''",
                "normalized_employee_name": "ALTER TABLE evaluations ADD COLUMN normalized_employee_name TEXT NOT NULL DEFAULT ''",
                "revision": "ALTER TABLE evaluations ADD COLUMN revision INTEGER NOT NULL DEFAULT 1",
                "department_id": "ALTER TABLE evaluations ADD COLUMN department_id INTEGER REFERENCES departments(id)",
                "captured_by_user_id": "ALTER TABLE evaluations ADD COLUMN captured_by_user_id INTEGER REFERENCES users(id)",
            }
            for name, sql in migrations.items():
                if name not in columns:
                    con.execute(sql)

            con.execute(
                "UPDATE evaluations SET department_id=? WHERE department_id IS NULL",
                (default_department_id,),
            )
            rows = con.execute(
                "SELECT id, employee_name FROM evaluations WHERE normalized_employee_name = '' AND employee_name <> ''"
            ).fetchall()
            for row in rows:
                con.execute(
                    "UPDATE evaluations SET normalized_employee_name=? WHERE id=?",
                    (self._normalize_name(row["employee_name"]), row["id"]),
                )

            for category in LEGACY_CATEGORIES:
                con.execute(
                    """INSERT INTO positions(department_id, name, normalized_name, active, created_at, updated_at)
                       VALUES (?, ?, ?, 1, ?, ?)
                       ON CONFLICT(department_id, normalized_name) DO NOTHING""",
                    (default_department_id, category, self._normalize_name(category), now, now),
                )

            # Conserva el autocompletado histórico dentro del departamento original.
            employee_rows = con.execute("SELECT id, last_category FROM employees").fetchall()
            for employee in employee_rows:
                con.execute(
                    """INSERT INTO employee_department_positions(employee_id, department_id, last_position, updated_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(employee_id, department_id) DO NOTHING""",
                    (employee["id"], default_department_id, employee["last_category"] or "", now),
                )

            if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
                initial_password = INITIAL_ADMIN_PASSWORD or secrets.token_urlsafe(24)
                self.initial_admin_password = initial_password
                salt, password_hash = self._hash_password(initial_password)
                con.execute(
                    """INSERT INTO users
                       (username, display_name, role, department_id, password_salt, password_hash,
                        active, must_change_password, created_at, updated_at)
                       VALUES (?, 'Administrador', 'admin', NULL, ?, ?, 1, 1, ?, ?)""",
                    (DEFAULT_ADMIN_USERNAME, salt, password_hash, now, now),
                )
                if not INITIAL_ADMIN_PASSWORD:
                    INITIAL_ADMIN_PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True)
                    INITIAL_ADMIN_PASSWORD_FILE.write_text(initial_password + "\n", encoding="utf-8")
                    try:
                        INITIAL_ADMIN_PASSWORD_FILE.chmod(0o600)
                    except OSError:
                        pass
            else:
                pending_admin = con.execute(
                    """SELECT id, password_salt, password_hash, must_change_password
                       FROM users WHERE username=? AND active=1""",
                    (DEFAULT_ADMIN_USERNAME,),
                ).fetchone()
                if pending_admin and bool(pending_admin["must_change_password"]):
                    if INITIAL_ADMIN_PASSWORD:
                        # Recovery path for a pending bootstrap account: an explicitly
                        # configured password may safely rotate an unknown legacy bootstrap.
                        if not self._verify_password(
                            INITIAL_ADMIN_PASSWORD,
                            pending_admin["password_salt"],
                            pending_admin["password_hash"],
                        ):
                            salt, password_hash = self._hash_password(INITIAL_ADMIN_PASSWORD)
                            con.execute(
                                "UPDATE users SET password_salt=?, password_hash=?, updated_at=? WHERE id=?",
                                (salt, password_hash, now, int(pending_admin["id"])),
                            )
                        self.initial_admin_password = INITIAL_ADMIN_PASSWORD
                    elif INITIAL_ADMIN_PASSWORD_FILE.is_file():
                        try:
                            candidate = INITIAL_ADMIN_PASSWORD_FILE.read_text(encoding="utf-8").strip()
                        except OSError:
                            candidate = ""
                        if candidate and self._verify_password(
                            candidate,
                            pending_admin["password_salt"],
                            pending_admin["password_hash"],
                        ):
                            self.initial_admin_password = candidate

            con.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_positions_department ON positions(department_id, active, name);
                CREATE INDEX IF NOT EXISTS idx_users_department ON users(department_id, active);
                CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
                CREATE INDEX IF NOT EXISTS idx_evaluations_date ON evaluations(evaluation_date);
                CREATE INDEX IF NOT EXISTS idx_evaluations_name ON evaluations(employee_name COLLATE NOCASE);
                CREATE INDEX IF NOT EXISTS idx_evaluations_status ON evaluations(status);
                CREATE INDEX IF NOT EXISTS idx_evaluations_operator ON evaluations(operator_code);
                CREATE INDEX IF NOT EXISTS idx_evaluations_department ON evaluations(department_id, evaluation_date);
                CREATE INDEX IF NOT EXISTS idx_evaluations_user ON evaluations(captured_by_user_id);
                CREATE INDEX IF NOT EXISTS idx_evaluations_normalized_name ON evaluations(normalized_employee_name);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_evaluations_client_record
                  ON evaluations(client_record_id) WHERE client_record_id <> '';
                """
            )
            con.commit()

    # ---------- Utilidades y autenticación ----------

    @staticmethod
    def _normalize_name(value: str) -> str:
        return " ".join(value.strip().split()).casefold()

    @staticmethod
    def _clean_text(value: Any) -> str:
        return " ".join(str(value or "").strip().split())

    @staticmethod
    def _clean_comment(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _clean_username(value: Any) -> str:
        username = str(value or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9._-]{3,40}", username):
            raise ValidationError("El usuario debe tener de 3 a 40 caracteres: letras, números, punto, guion o guion bajo.")
        return username

    @staticmethod
    def _validate_password(value: Any) -> str:
        password = str(value or "")
        if len(password) < 8:
            raise ValidationError("La contraseña debe tener al menos 8 caracteres.")
        if len(password) > 200:
            raise ValidationError("La contraseña es demasiado larga.")
        return password

    @staticmethod
    def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
        salt = salt or secrets.token_bytes(18)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
        return base64.b64encode(salt).decode("ascii"), base64.b64encode(digest).decode("ascii")

    @staticmethod
    def _verify_password(password: str, salt_b64: str, expected_b64: str) -> bool:
        try:
            salt = base64.b64decode(salt_b64.encode("ascii"))
            expected = base64.b64decode(expected_b64.encode("ascii"))
        except (ValueError, TypeError):
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
        return hmac.compare_digest(actual, expected)

    @staticmethod
    def _public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        return {
            "id": int(data["id"]),
            "username": data["username"],
            "display_name": data["display_name"],
            "role": data["role"],
            "department_id": data.get("department_id"),
            "department_code": data.get("department_code"),
            "department_name": data.get("department_name"),
            "active": bool(data.get("active", 1)),
            "must_change_password": bool(data.get("must_change_password", 0)),
        }

    def _user_query(self) -> str:
        return """SELECT u.*, d.code AS department_code, d.name AS department_name,
                         d.active AS department_active
                  FROM users u LEFT JOIN departments d ON d.id=u.department_id"""

    def get_user(self, user_id: int) -> dict[str, Any]:
        with self.connect() as con:
            row = con.execute(f"{self._user_query()} WHERE u.id=?", (int(user_id),)).fetchone()
        if not row:
            raise KeyError("Usuario no encontrado.")
        return self._public_user(row)

    def login(self, username: str, password: str) -> tuple[str, dict[str, Any]]:
        clean_username = self._clean_username(username)
        with self.connect() as con:
            row = con.execute(f"{self._user_query()} WHERE u.username=?", (clean_username,)).fetchone()
            if not row or not bool(row["active"]):
                raise AuthenticationError("Usuario o contraseña incorrectos.")
            if not self._verify_password(str(password or ""), row["password_salt"], row["password_hash"]):
                raise AuthenticationError("Usuario o contraseña incorrectos.")
            if row["role"] == "capturist" and (
                row["department_id"] is None or row["department_name"] is None or not bool(row["department_active"])
            ):
                raise AuthenticationError("La cuenta no tiene un departamento activo. Consulte al administrador.")
            con.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
            token = secrets.token_urlsafe(48)
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            expires_at = int(time.time()) + SESSION_HOURS * 3600
            con.execute(
                "INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (token_hash, row["id"], expires_at, self._now()),
            )
            con.commit()
        return token, self._public_user(row)

    def authenticate_session(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now_epoch = int(time.time())
        with self.connect() as con:
            row = con.execute(
                f"""{self._user_query()}
                    JOIN sessions s ON s.user_id=u.id
                    WHERE s.token_hash=? AND s.expires_at>? AND u.active=1""",
                (token_hash, now_epoch),
            ).fetchone()
            if not row:
                con.execute("DELETE FROM sessions WHERE token_hash=? OR expires_at<=?", (token_hash, now_epoch))
                con.commit()
                return None
        return self._public_user(row)

    def logout(self, token: str | None) -> None:
        if not token:
            return
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self.connect() as con:
            con.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
            con.commit()

    def change_password(self, user_id: int, current_password: str, new_password: str) -> dict[str, Any]:
        new_password = self._validate_password(new_password)
        with self.connect() as con:
            row = con.execute("SELECT * FROM users WHERE id=?", (int(user_id),)).fetchone()
            if not row or not bool(row["active"]):
                raise KeyError("Usuario no encontrado.")
            if not self._verify_password(str(current_password or ""), row["password_salt"], row["password_hash"]):
                raise AuthenticationError("La contraseña actual no es correcta.")
            salt, password_hash = self._hash_password(new_password)
            con.execute(
                """UPDATE users SET password_salt=?, password_hash=?, must_change_password=0, updated_at=?
                   WHERE id=?""",
                (salt, password_hash, self._now(), int(user_id)),
            )
            con.execute("DELETE FROM sessions WHERE user_id=?", (int(user_id),))
            con.commit()
        if row["username"] == DEFAULT_ADMIN_USERNAME:
            self.initial_admin_password = None
            try:
                INITIAL_ADMIN_PASSWORD_FILE.unlink(missing_ok=True)
            except OSError:
                pass
        return self.get_user(user_id)

    def initial_admin_pending(self) -> bool:
        with self.connect() as con:
            row = con.execute(
                "SELECT must_change_password FROM users WHERE username=? AND active=1",
                (DEFAULT_ADMIN_USERNAME,),
            ).fetchone()
        return bool(row and row[0])

    # ---------- Catálogos administrativos ----------

    @staticmethod
    def _department_code(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        code = re.sub(r"[^A-Z0-9]+", "-", normalized.upper()).strip("-")[:24]
        return code or "DEPTO"

    def list_departments(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        where = "" if include_inactive else "WHERE active=1"
        with self.connect() as con:
            rows = con.execute(
                f"""SELECT d.*,
                       (SELECT COUNT(*) FROM users u WHERE u.department_id=d.id AND u.active=1) AS active_users,
                       (SELECT COUNT(*) FROM positions p WHERE p.department_id=d.id AND p.active=1) AS active_positions,
                       (SELECT COUNT(*) FROM evaluations e WHERE e.department_id=d.id) AS evaluations
                    FROM departments d {where}
                    ORDER BY active DESC, name COLLATE NOCASE"""
            ).fetchall()
        return [
            {
                **dict(row),
                "id": int(row["id"]),
                "active": bool(row["active"]),
            }
            for row in rows
        ]

    def create_department(self, name: str, code: str = "") -> dict[str, Any]:
        name = self._clean_text(name)
        if len(name) < 3:
            raise ValidationError("Escriba un nombre de departamento de al menos 3 caracteres.")
        base_code = self._department_code(code or name)
        now = self._now()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            if con.execute("SELECT 1 FROM departments WHERE name=? COLLATE NOCASE", (name,)).fetchone():
                raise ConflictError("Ya existe un departamento con ese nombre.")
            final_code = base_code
            suffix = 2
            while con.execute("SELECT 1 FROM departments WHERE code=? COLLATE NOCASE", (final_code,)).fetchone():
                final_code = f"{base_code[:20]}-{suffix}"
                suffix += 1
            cursor = con.execute(
                "INSERT INTO departments(code, name, active, created_at, updated_at) VALUES (?, ?, 1, ?, ?)",
                (final_code, name, now, now),
            )
            department_id = int(cursor.lastrowid)
            con.commit()
        return next(item for item in self.list_departments(True) if item["id"] == department_id)

    def set_department_active(self, department_id: int, active: bool) -> dict[str, Any]:
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM departments WHERE id=?", (int(department_id),)).fetchone()
            if not row:
                raise KeyError("Departamento no encontrado.")
            if not active:
                active_users = con.execute(
                    "SELECT COUNT(*) FROM users WHERE department_id=? AND active=1", (int(department_id),)
                ).fetchone()[0]
                if active_users:
                    raise ConflictError("No puede desactivar el departamento mientras tenga capturistas activos.")
            con.execute(
                "UPDATE departments SET active=?, updated_at=? WHERE id=?",
                (1 if active else 0, self._now(), int(department_id)),
            )
            con.commit()
        return next(item for item in self.list_departments(True) if item["id"] == int(department_id))

    def list_positions(self, department_id: int | None = None, include_inactive: bool = False) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if department_id is not None:
            clauses.append("p.department_id=?")
            params.append(int(department_id))
        if not include_inactive:
            clauses.append("p.active=1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as con:
            rows = con.execute(
                f"""SELECT p.*, d.code AS department_code, d.name AS department_name
                    FROM positions p JOIN departments d ON d.id=p.department_id
                    {where} ORDER BY d.name COLLATE NOCASE, p.active DESC, p.name COLLATE NOCASE""",
                params,
            ).fetchall()
        return [{**dict(row), "id": int(row["id"]), "active": bool(row["active"])} for row in rows]

    def create_position(self, department_id: int, name: str) -> dict[str, Any]:
        name = self._clean_text(name).upper()
        if len(name) < 2:
            raise ValidationError("Escriba el nombre del puesto.")
        now = self._now()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            department = con.execute("SELECT active FROM departments WHERE id=?", (int(department_id),)).fetchone()
            if not department or not bool(department["active"]):
                raise ValidationError("Seleccione un departamento activo.")
            try:
                cursor = con.execute(
                    """INSERT INTO positions(department_id, name, normalized_name, active, created_at, updated_at)
                       VALUES (?, ?, ?, 1, ?, ?)""",
                    (int(department_id), name, self._normalize_name(name), now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError("Ese puesto ya existe en el departamento.") from exc
            position_id = int(cursor.lastrowid)
            con.commit()
        return next(item for item in self.list_positions(None, True) if item["id"] == position_id)

    def set_position_active(self, position_id: int, active: bool) -> dict[str, Any]:
        with self.connect() as con:
            cursor = con.execute(
                "UPDATE positions SET active=?, updated_at=? WHERE id=?",
                (1 if active else 0, self._now(), int(position_id)),
            )
            if cursor.rowcount == 0:
                raise KeyError("Puesto no encontrado.")
            con.commit()
        return next(item for item in self.list_positions(None, True) if item["id"] == int(position_id))

    def list_users(self) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(f"{self._user_query()} ORDER BY u.active DESC, u.display_name COLLATE NOCASE").fetchall()
        return [self._public_user(row) for row in rows]

    def create_user(
        self,
        username: str,
        display_name: str,
        password: str,
        department_id: int | None,
        role: str = "capturist",
    ) -> dict[str, Any]:
        username = self._clean_username(username)
        display_name = self._clean_text(display_name)
        password = self._validate_password(password)
        role = str(role or "capturist").strip().lower()
        if role not in {"admin", "capturist"}:
            raise ValidationError("El rol no es válido.")
        if len(display_name) < 2:
            raise ValidationError("Escriba el nombre del capturista.")
        if role == "capturist":
            if department_id is None:
                raise ValidationError("Seleccione el departamento del capturista.")
            with self.connect() as con:
                department = con.execute("SELECT active FROM departments WHERE id=?", (int(department_id),)).fetchone()
            if not department or not bool(department["active"]):
                raise ValidationError("Seleccione un departamento activo.")
        else:
            department_id = None
        salt, password_hash = self._hash_password(password)
        now = self._now()
        with self.connect() as con:
            try:
                cursor = con.execute(
                    """INSERT INTO users
                       (username, display_name, role, department_id, password_salt, password_hash,
                        active, must_change_password, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, ?)""",
                    (username, display_name, role, department_id, salt, password_hash, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError("Ese nombre de usuario ya está registrado.") from exc
            user_id = int(cursor.lastrowid)
            con.commit()
        return self.get_user(user_id)

    def set_user_active(self, actor_id: int, user_id: int, active: bool) -> dict[str, Any]:
        if int(actor_id) == int(user_id) and not active:
            raise ConflictError("No puede desactivar su propia cuenta mientras está utilizándola.")
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT role FROM users WHERE id=?", (int(user_id),)).fetchone()
            if not row:
                raise KeyError("Usuario no encontrado.")
            if row["role"] == "admin" and not active:
                admins = con.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
                if admins <= 1:
                    raise ConflictError("Debe quedar por lo menos una cuenta administradora activa.")
            if row["role"] == "capturist" and active:
                department = con.execute(
                    "SELECT d.active FROM users u JOIN departments d ON d.id=u.department_id WHERE u.id=?",
                    (int(user_id),),
                ).fetchone()
                if not department or not bool(department["active"]):
                    raise ConflictError("Active primero el departamento asignado a esta cuenta.")
            con.execute(
                "UPDATE users SET active=?, updated_at=? WHERE id=?",
                (1 if active else 0, self._now(), int(user_id)),
            )
            if not active:
                con.execute("DELETE FROM sessions WHERE user_id=?", (int(user_id),))
            con.commit()
        return self.get_user(user_id)

    def reset_user_password(self, user_id: int, new_password: str) -> dict[str, Any]:
        new_password = self._validate_password(new_password)
        salt, password_hash = self._hash_password(new_password)
        with self.connect() as con:
            cursor = con.execute(
                """UPDATE users SET password_salt=?, password_hash=?, must_change_password=1, updated_at=?
                   WHERE id=?""",
                (salt, password_hash, self._now(), int(user_id)),
            )
            if cursor.rowcount == 0:
                raise KeyError("Usuario no encontrado.")
            con.execute("DELETE FROM sessions WHERE user_id=?", (int(user_id),))
            con.commit()
        return self.get_user(user_id)

    # ---------- Evaluaciones ----------

    @staticmethod
    def _clean_score(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Las calificaciones deben ser 1, 2, 3 o quedar en blanco.") from exc
        if number not in (1, 2, 3):
            raise ValidationError("Las calificaciones deben ser 1, 2, 3 o quedar en blanco.")
        return number

    @staticmethod
    def _clean_date(value: Any) -> str:
        text = str(value or "").strip()
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError as exc:
            raise ValidationError("La fecha es obligatoria y debe ser válida.") from exc

    @staticmethod
    def _clean_client_record_id(value: Any) -> str:
        text = str(value or "").strip()
        if len(text) > 100:
            raise ValidationError("El identificador local de la captura no es válido.")
        return text

    @staticmethod
    def _clean_revision(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            revision = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("La versión del registro no es válida.") from exc
        if revision < 1:
            raise ValidationError("La versión del registro no es válida.")
        return revision

    def _validate_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        status = str(payload.get("status") or "draft").strip().lower()
        if status not in {"draft", "final"}:
            raise ValidationError("El estatus debe ser borrador o final.")
        employee_name = self._clean_text(payload.get("employee_name"))
        cleaned = {
            "evaluation_date": self._clean_date(payload.get("evaluation_date")),
            "employee_name": employee_name,
            "normalized_employee_name": self._normalize_name(employee_name) if employee_name else "",
            "category": self._clean_text(payload.get("category")).upper(),
            "status": status,
            "department_id": int(payload["department_id"]) if payload.get("department_id") not in (None, "") else None,
            "client_record_id": self._clean_client_record_id(payload.get("client_record_id")),
            "expected_revision": self._clean_revision(payload.get("revision")),
            "areas": {},
        }
        if status == "final":
            if not cleaned["employee_name"]:
                raise ValidationError("Escriba el nombre del empleado antes de finalizar.")
            if not cleaned["category"]:
                raise ValidationError("Seleccione la categoría o puesto antes de finalizar.")
        supplied_areas = payload.get("areas") or {}
        for area in AREAS:
            raw = supplied_areas.get(area["code"]) or {}
            cleaned["areas"][area["code"]] = {
                "attitude": self._clean_score(raw.get("attitude")),
                "performance": self._clean_score(raw.get("performance")),
                "technical": self._clean_score(raw.get("technical")),
                "has_comment": bool(raw.get("has_comment")),
                "comment": self._clean_comment(raw.get("comment")),
            }
            if not cleaned["areas"][area["code"]]["has_comment"]:
                cleaned["areas"][area["code"]]["comment"] = ""
        return cleaned

    @staticmethod
    def _can_access_department(user: dict[str, Any], department_id: int) -> bool:
        return user["role"] == "admin" or int(user.get("department_id") or 0) == int(department_id)

    def _resolve_department(
        self,
        con: sqlite3.Connection,
        user: dict[str, Any],
        requested_department_id: int | None,
        existing_department_id: int | None = None,
    ) -> int:
        if user["role"] == "capturist":
            department_id = int(user.get("department_id") or 0)
            if not department_id:
                raise PermissionDenied("Su cuenta no tiene un departamento asignado.")
        else:
            department_id = int(requested_department_id or existing_department_id or 0)
            if not department_id:
                row = con.execute("SELECT id FROM departments WHERE active=1 ORDER BY id LIMIT 1").fetchone()
                if not row:
                    raise ValidationError("Primero cree un departamento activo.")
                department_id = int(row["id"])
        department = con.execute("SELECT id, active FROM departments WHERE id=?", (department_id,)).fetchone()
        if not department:
            raise ValidationError("El departamento seleccionado no existe.")
        if not bool(department["active"]) and existing_department_id != department_id:
            raise ValidationError("El departamento seleccionado está desactivado.")
        return department_id

    def _validate_position(
        self,
        con: sqlite3.Connection,
        department_id: int,
        category: str,
        *,
        required: bool,
    ) -> None:
        if not category:
            if required:
                raise ValidationError("Seleccione la categoría o puesto antes de finalizar.")
            return
        row = con.execute(
            "SELECT id FROM positions WHERE department_id=? AND normalized_name=?",
            (int(department_id), self._normalize_name(category)),
        ).fetchone()
        if not row:
            raise ValidationError("El puesto seleccionado no pertenece al departamento de captura.")

    def save_evaluation(
        self,
        payload: dict[str, Any],
        user: dict[str, Any],
        evaluation_id: int | None = None,
    ) -> dict[str, Any]:
        data = self._validate_payload(payload)
        now = self._now()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")

            if evaluation_id is None and data["client_record_id"]:
                prior = con.execute(
                    "SELECT id FROM evaluations WHERE client_record_id=?", (data["client_record_id"],)
                ).fetchone()
                if prior:
                    evaluation_id = int(prior["id"])

            current = None
            if evaluation_id is not None:
                current = con.execute(
                    "SELECT * FROM evaluations WHERE id=?", (int(evaluation_id),)
                ).fetchone()
                if not current:
                    raise KeyError("Evaluación no encontrada.")
                if not self._can_access_department(user, int(current["department_id"] or 0)):
                    raise PermissionDenied("No tiene permiso para modificar esa evaluación.")

            department_id = self._resolve_department(
                con,
                user,
                data["department_id"],
                int(current["department_id"]) if current and current["department_id"] else None,
            )
            self._validate_position(con, department_id, data["category"], required=data["status"] == "final")

            if current is None:
                revision = 1
                cursor = con.execute(
                    """INSERT INTO evaluations
                       (evaluation_date, employee_name, normalized_employee_name, category, status,
                        operator_code, client_record_id, revision, department_id, captured_by_user_id,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        data["evaluation_date"], data["employee_name"], data["normalized_employee_name"],
                        data["category"], data["status"], user["display_name"], data["client_record_id"],
                        revision, department_id, user["id"], now, now,
                    ),
                )
                evaluation_id = int(cursor.lastrowid)
            else:
                current_revision = int(current["revision"] or 1)
                expected = data["expected_revision"]
                if expected is not None and expected != current_revision:
                    raise ConflictError(
                        "Esta evaluación fue modificada desde otro teléfono. Abra nuevamente el registro para conservar la versión más reciente."
                    )
                revision = current_revision + 1
                client_record_id = data["client_record_id"] or str(current["client_record_id"] or "")
                con.execute(
                    """UPDATE evaluations SET evaluation_date=?, employee_name=?, normalized_employee_name=?,
                       category=?, status=?, operator_code=?, client_record_id=?, revision=?, department_id=?,
                       captured_by_user_id=?, updated_at=? WHERE id=?""",
                    (
                        data["evaluation_date"], data["employee_name"], data["normalized_employee_name"],
                        data["category"], data["status"], user["display_name"], client_record_id,
                        revision, department_id, user["id"], now, int(evaluation_id),
                    ),
                )
                con.execute("DELETE FROM area_results WHERE evaluation_id=?", (int(evaluation_id),))

            if data["status"] == "final" and data["normalized_employee_name"]:
                duplicate = con.execute(
                    """SELECT id, operator_code FROM evaluations
                       WHERE department_id=? AND evaluation_date=? AND normalized_employee_name=?
                         AND status='final' AND id<>? LIMIT 1""",
                    (department_id, data["evaluation_date"], data["normalized_employee_name"], int(evaluation_id)),
                ).fetchone()
                if duplicate:
                    raise ConflictError(
                        f"Ya existe una evaluación final de ese empleado, en esa fecha y departamento (capturada por {duplicate['operator_code']})."
                    )

            for area_code, result in data["areas"].items():
                con.execute(
                    """INSERT INTO area_results
                       (evaluation_id, area_code, attitude, performance, technical, has_comment, comment)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        int(evaluation_id), area_code, result["attitude"], result["performance"],
                        result["technical"], 1 if result["has_comment"] else 0, result["comment"],
                    ),
                )

            if data["employee_name"]:
                con.execute(
                    """INSERT INTO employees
                       (normalized_name, display_name, last_category, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(normalized_name) DO UPDATE SET
                         display_name=excluded.display_name,
                         last_category=CASE WHEN excluded.last_category<>'' THEN excluded.last_category ELSE employees.last_category END,
                         updated_at=excluded.updated_at""",
                    (data["normalized_employee_name"], data["employee_name"], data["category"], now, now),
                )
                employee_id = int(
                    con.execute("SELECT id FROM employees WHERE normalized_name=?", (data["normalized_employee_name"],)).fetchone()[0]
                )
                con.execute(
                    """INSERT INTO employee_department_positions(employee_id, department_id, last_position, updated_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(employee_id, department_id) DO UPDATE SET
                         last_position=CASE WHEN excluded.last_position<>'' THEN excluded.last_position ELSE employee_department_positions.last_position END,
                         updated_at=excluded.updated_at""",
                    (employee_id, department_id, data["category"], now),
                )
            con.commit()
        return self.get_evaluation(int(evaluation_id), user)

    def get_evaluation(self, evaluation_id: int, user: dict[str, Any] | None = None) -> dict[str, Any]:
        with self.connect() as con:
            row = con.execute(
                """SELECT e.*, d.code AS department_code, d.name AS department_name,
                          COALESCE(u.display_name, e.operator_code) AS captured_by_name,
                          u.username AS captured_by_username
                   FROM evaluations e
                   LEFT JOIN departments d ON d.id=e.department_id
                   LEFT JOIN users u ON u.id=e.captured_by_user_id
                   WHERE e.id=?""",
                (int(evaluation_id),),
            ).fetchone()
            if not row:
                raise KeyError("Evaluación no encontrada.")
            if user and not self._can_access_department(user, int(row["department_id"] or 0)):
                raise PermissionDenied("No tiene permiso para consultar esa evaluación.")
            area_rows = con.execute(
                "SELECT * FROM area_results WHERE evaluation_id=?", (int(evaluation_id),)
            ).fetchall()
        result = dict(row)
        result["areas"] = {
            area["code"]: {
                "attitude": None,
                "performance": None,
                "technical": None,
                "has_comment": False,
                "comment": "",
            }
            for area in AREAS
        }
        for area_row in area_rows:
            result["areas"][area_row["area_code"]] = {
                "attitude": area_row["attitude"],
                "performance": area_row["performance"],
                "technical": area_row["technical"],
                "has_comment": bool(area_row["has_comment"]),
                "comment": area_row["comment"],
            }
        scores = [
            result["areas"][area["code"]][field]
            for area in AREAS
            for field in SCORE_FIELDS
            if result["areas"][area["code"]][field] is not None
        ]
        result["average"] = round(sum(scores) / len(scores), 2) if scores else None
        return result

    def list_evaluations(
        self,
        user: dict[str, Any] | None = None,
        *,
        status: str | None = None,
        start: str | None = None,
        end: str | None = None,
        query: str | None = None,
        department_id: int | None = None,
        captured_by_user_id: int | None = None,
        ids: Iterable[int] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if user and user["role"] == "capturist":
            clauses.append("department_id=?")
            params.append(int(user["department_id"]))
        elif department_id is not None:
            clauses.append("department_id=?")
            params.append(int(department_id))
        if status in {"draft", "final"}:
            clauses.append("status=?")
            params.append(status)
        if start:
            clauses.append("evaluation_date>=?")
            params.append(self._clean_date(start))
        if end:
            clauses.append("evaluation_date<=?")
            params.append(self._clean_date(end))
        if query:
            clauses.append("(employee_name LIKE ? OR category LIKE ? OR operator_code LIKE ?)")
            like = f"%{query.strip()}%"
            params.extend([like, like, like])
        if captured_by_user_id is not None:
            clauses.append("captured_by_user_id=?")
            params.append(int(captured_by_user_id))
        if ids is not None:
            id_list = [int(item) for item in ids]
            if not id_list:
                return []
            clauses.append(f"id IN ({','.join('?' for _ in id_list)})")
            params.extend(id_list)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT id FROM evaluations {where} ORDER BY evaluation_date ASC, employee_name COLLATE NOCASE ASC, id ASC"
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self.connect() as con:
            rows = con.execute(sql, params).fetchall()
        return [self.get_evaluation(int(row["id"]), user) for row in rows]

    def delete_evaluation(self, evaluation_id: int, user: dict[str, Any]) -> None:
        if user["role"] != "admin":
            raise PermissionDenied("Solo el administrador puede eliminar evaluaciones.")
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            cursor = con.execute("DELETE FROM evaluations WHERE id=?", (int(evaluation_id),))
            if cursor.rowcount == 0:
                raise KeyError("Evaluación no encontrada.")
            con.commit()

    def list_employees(self, department_id: int, query: str = "", limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any] = [int(department_id)]
        extra = ""
        if query.strip():
            extra = "AND e.display_name LIKE ?"
            params.append(f"%{query.strip()}%")
        params.append(int(limit))
        with self.connect() as con:
            rows = con.execute(
                f"""SELECT e.display_name, h.last_position AS last_category
                    FROM employees e
                    JOIN employee_department_positions h ON h.employee_id=e.id
                    WHERE h.department_id=? {extra}
                    ORDER BY e.display_name COLLATE NOCASE LIMIT ?""",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def catalog(self, user: dict[str, Any], department_id: int | None = None) -> dict[str, Any]:
        if user["role"] == "capturist":
            department_id = int(user["department_id"])
        elif department_id is None:
            departments = self.list_departments()
            department_id = int(departments[0]["id"]) if departments else None
        if department_id is None:
            return {"department": None, "categories": [], "employees": []}
        if not self._can_access_department(user, int(department_id)):
            raise PermissionDenied("No tiene permiso para consultar ese departamento.")
        departments = self.list_departments(True)
        department = next((item for item in departments if item["id"] == int(department_id)), None)
        if not department:
            raise KeyError("Departamento no encontrado.")
        categories = [item["name"] for item in self.list_positions(int(department_id))]
        return {
            "department": department,
            "categories": categories,
            "employees": self.list_employees(int(department_id), limit=250),
        }

    def stats(self, user: dict[str, Any] | None = None, department_id: int | None = None) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if user and user["role"] == "capturist":
            clauses.append("department_id=?")
            params.append(int(user["department_id"]))
        elif department_id is not None:
            clauses.append("department_id=?")
            params.append(int(department_id))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as con:
            total = con.execute(f"SELECT COUNT(*) FROM evaluations {where}", params).fetchone()[0]
            final_where = f"{where} {'AND' if where else 'WHERE'} status='final'"
            draft_where = f"{where} {'AND' if where else 'WHERE'} status='draft'"
            final = con.execute(f"SELECT COUNT(*) FROM evaluations {final_where}", params).fetchone()[0]
            drafts = con.execute(f"SELECT COUNT(*) FROM evaluations {draft_where}", params).fetchone()[0]
            if clauses:
                employees = con.execute(
                    "SELECT COUNT(DISTINCT normalized_employee_name) FROM evaluations " + where + " AND normalized_employee_name<>''",
                    params,
                ).fetchone()[0]
            else:
                employees = con.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
            operator_rows = con.execute(
                f"SELECT operator_code, COUNT(*) AS total FROM evaluations {where} GROUP BY operator_code ORDER BY operator_code",
                params,
            ).fetchall()
        return {
            "total": int(total),
            "final": int(final),
            "drafts": int(drafts),
            "employees": int(employees),
            "by_operator": {row["operator_code"]: int(row["total"]) for row in operator_rows},
        }

    def backup_to(self, destination: Path) -> None:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=30) as source, sqlite3.connect(destination) as target:
            source.execute("PRAGMA busy_timeout = 30000")
            source.backup(target)
