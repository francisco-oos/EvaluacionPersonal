from __future__ import annotations

import io
import json
import mimetypes
import re
from datetime import date, datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from zipfile import ZIP_DEFLATED, ZipFile

from .config import (
    APP_NAME,
    APP_VERSION,
    AREAS,
    DATABASE_PATH,
    EXPORT_DIR,
    ROOT_DIR,
    SESSION_HOURS,
    TEMPLATE_PATH,
)
from .database import (
    AuthenticationError,
    ConflictError,
    Database,
    PermissionDenied,
    ValidationError,
)
from .exporter import create_backup_zip, export_to_template, safe_filename

SESSION_COOKIE = "eval_session"


class Application:
    def __init__(
        self,
        database_path: Path = DATABASE_PATH,
        template_path: Path = TEMPLATE_PATH,
        export_dir: Path = EXPORT_DIR,
    ):
        self.database = Database(Path(database_path))
        self.template_path = Path(template_path)
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.templates_dir = ROOT_DIR / "app" / "templates"
        self.static_dir = ROOT_DIR / "app" / "static"

    @staticmethod
    def _json_bytes(payload: Any) -> bytes:
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    @staticmethod
    def _first(query: dict[str, list[str]], key: str, default: str = "") -> str:
        values = query.get(key)
        return values[0] if values else default

    @staticmethod
    def _int_query(query: dict[str, list[str]], key: str) -> int | None:
        value = Application._first(query, key)
        if not value:
            return None
        try:
            return int(value)
        except ValueError as exc:
            raise ValidationError(f"El parámetro {key} no es válido.") from exc

    @staticmethod
    def _cookie_token(headers: dict[str, str] | None) -> str | None:
        cookie_header = (headers or {}).get("Cookie") or (headers or {}).get("cookie") or ""
        if not cookie_header:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except Exception:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def _current_user(self, headers: dict[str, str] | None) -> tuple[dict[str, Any], str]:
        token = self._cookie_token(headers)
        user = self.database.authenticate_session(token)
        if not user:
            raise AuthenticationError("La sesión terminó. Inicie sesión nuevamente.")
        return user, token or ""

    @staticmethod
    def _require_admin(user: dict[str, Any]) -> None:
        if user.get("role") != "admin":
            raise PermissionDenied("Esta acción requiere una cuenta administradora.")

    @staticmethod
    def _session_cookie(token: str) -> str:
        return (
            f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; "
            f"Max-Age={SESSION_HOURS * 3600}"
        )

    @staticmethod
    def _clear_session_cookie() -> str:
        return f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"

    def dispatch(
        self,
        method: str,
        raw_path: str,
        body: bytes = b"",
        request_headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        parsed = urlparse(raw_path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        try:
            # Interfaz pública: todos reciben el mismo host y después inician sesión.
            if method == "GET" and (path == "/" or re.fullmatch(r"/captura/\d+", path)):
                html = (self.templates_dir / "index.html").read_text(encoding="utf-8")
                html = html.replace("{{ app_name }}", APP_NAME).replace("{{ app_version }}", APP_VERSION)
                return 200, {"Content-Type": "text/html; charset=utf-8"}, html.encode("utf-8")

            if method == "GET" and path.startswith("/static/"):
                relative = path.removeprefix("/static/")
                target = (self.static_dir / relative).resolve()
                if self.static_dir.resolve() not in target.parents or not target.is_file():
                    return self._error(404, "Archivo estático no encontrado.")
                content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                return 200, {"Content-Type": content_type}, target.read_bytes()

            if method == "GET" and path == "/health":
                return self._ok({"ok": True, "version": APP_VERSION})

            if method == "POST" and path == "/api/login":
                payload = json.loads(body.decode("utf-8") or "{}")
                token, user = self.database.login(payload.get("username", ""), payload.get("password", ""))
                return 200, {
                    "Content-Type": "application/json; charset=utf-8",
                    "Set-Cookie": self._session_cookie(token),
                }, self._json_bytes({"user": user})

            if method == "GET" and path == "/api/session":
                user, _ = self._current_user(request_headers)
                return self._ok({"user": user})

            if method == "POST" and path == "/api/logout":
                _, token = self._current_user(request_headers)
                self.database.logout(token)
                return 204, {"Set-Cookie": self._clear_session_cookie()}, b""

            user, token = self._current_user(request_headers)

            if method == "POST" and path == "/api/change-password":
                payload = json.loads(body.decode("utf-8") or "{}")
                changed = self.database.change_password(
                    user["id"], payload.get("current_password", ""), payload.get("new_password", "")
                )
                return 200, {
                    "Content-Type": "application/json; charset=utf-8",
                    "Set-Cookie": self._clear_session_cookie(),
                }, self._json_bytes({"user": changed, "reauthenticate": True})

            if user.get("must_change_password") and not (method == "GET" and path == "/api/bootstrap"):
                raise PermissionDenied("Debe cambiar la contraseña temporal antes de continuar.")

            if method == "GET" and path == "/api/bootstrap":
                requested_department = self._int_query(query, "department_id")
                catalog = self.database.catalog(user, requested_department)
                current_department_id = catalog["department"]["id"] if catalog["department"] else None
                return self._ok(
                    {
                        "app_name": APP_NAME,
                        "version": APP_VERSION,
                        "today": date.today().isoformat(),
                        "areas": AREAS,
                        "user": user,
                        "departments": self.database.list_departments(),
                        "catalog": catalog,
                        "stats": self.database.stats(user, current_department_id),
                        "permissions": {
                            "admin": user["role"] == "admin",
                            "delete_evaluations": user["role"] == "admin",
                            "backup": user["role"] == "admin",
                        },
                    }
                )

            if method == "GET" and path == "/api/catalog":
                return self._ok(self.database.catalog(user, self._int_query(query, "department_id")))

            if method == "GET" and path == "/api/employees":
                department_id = self._int_query(query, "department_id")
                catalog = self.database.catalog(user, department_id)
                if not catalog["department"]:
                    return self._ok([])
                return self._ok(
                    self.database.list_employees(
                        int(catalog["department"]["id"]), self._first(query, "q"), limit=100
                    )
                )

            if method == "GET" and path == "/api/evaluations":
                status = self._first(query, "status") or None
                try:
                    limit = min(max(int(self._first(query, "limit", "500")), 1), 2000)
                except ValueError:
                    limit = 500
                department_id = self._int_query(query, "department_id")
                items = self.database.list_evaluations(
                    user,
                    status=status,
                    start=self._first(query, "start") or None,
                    end=self._first(query, "end") or None,
                    query=self._first(query, "q") or None,
                    department_id=department_id,
                    limit=limit,
                )
                return self._ok(
                    {
                        "items": items,
                        "stats": self.database.stats(user, department_id),
                    }
                )

            detail_match = re.fullmatch(r"/api/evaluations/(\d+)", path)
            if detail_match:
                evaluation_id = int(detail_match.group(1))
                if method == "GET":
                    return self._ok(self.database.get_evaluation(evaluation_id, user))
                if method == "PUT":
                    payload = json.loads(body.decode("utf-8") or "{}")
                    return self._ok(self.database.save_evaluation(payload, user, evaluation_id))
                if method == "DELETE":
                    self.database.delete_evaluation(evaluation_id, user)
                    return 204, {}, b""

            if method == "POST" and path == "/api/evaluations":
                payload = json.loads(body.decode("utf-8") or "{}")
                saved = self.database.save_evaluation(payload, user)
                return 201, {"Content-Type": "application/json; charset=utf-8"}, self._json_bytes(saved)

            # Administración de departamentos, puestos y cuentas.
            if path == "/api/admin/departments":
                self._require_admin(user)
                if method == "GET":
                    return self._ok(self.database.list_departments(True))
                if method == "POST":
                    payload = json.loads(body.decode("utf-8") or "{}")
                    return 201, {"Content-Type": "application/json; charset=utf-8"}, self._json_bytes(
                        self.database.create_department(payload.get("name", ""), payload.get("code", ""))
                    )

            department_active = re.fullmatch(r"/api/admin/departments/(\d+)/active", path)
            if department_active and method == "PUT":
                self._require_admin(user)
                payload = json.loads(body.decode("utf-8") or "{}")
                return self._ok(
                    self.database.set_department_active(int(department_active.group(1)), bool(payload.get("active")))
                )

            if path == "/api/admin/positions":
                self._require_admin(user)
                if method == "GET":
                    return self._ok(
                        self.database.list_positions(self._int_query(query, "department_id"), True)
                    )
                if method == "POST":
                    payload = json.loads(body.decode("utf-8") or "{}")
                    created = self.database.create_position(int(payload.get("department_id")), payload.get("name", ""))
                    return 201, {"Content-Type": "application/json; charset=utf-8"}, self._json_bytes(created)

            position_active = re.fullmatch(r"/api/admin/positions/(\d+)/active", path)
            if position_active and method == "PUT":
                self._require_admin(user)
                payload = json.loads(body.decode("utf-8") or "{}")
                return self._ok(
                    self.database.set_position_active(int(position_active.group(1)), bool(payload.get("active")))
                )

            if path == "/api/admin/users":
                self._require_admin(user)
                if method == "GET":
                    return self._ok(self.database.list_users())
                if method == "POST":
                    payload = json.loads(body.decode("utf-8") or "{}")
                    department_id = payload.get("department_id")
                    created = self.database.create_user(
                        payload.get("username", ""),
                        payload.get("display_name", ""),
                        payload.get("password", ""),
                        int(department_id) if department_id not in (None, "") else None,
                        payload.get("role", "capturist"),
                    )
                    return 201, {"Content-Type": "application/json; charset=utf-8"}, self._json_bytes(created)

            user_active = re.fullmatch(r"/api/admin/users/(\d+)/active", path)
            if user_active and method == "PUT":
                self._require_admin(user)
                payload = json.loads(body.decode("utf-8") or "{}")
                return self._ok(
                    self.database.set_user_active(user["id"], int(user_active.group(1)), bool(payload.get("active")))
                )

            user_password = re.fullmatch(r"/api/admin/users/(\d+)/password", path)
            if user_password and method == "PUT":
                self._require_admin(user)
                payload = json.loads(body.decode("utf-8") or "{}")
                return self._ok(
                    self.database.reset_user_password(int(user_password.group(1)), payload.get("password", ""))
                )

            if method == "GET" and path == "/export/evaluaciones.xlsx":
                department_id = self._int_query(query, "department_id")
                catalog = self.database.catalog(user, department_id)
                department = catalog["department"]
                if not department:
                    raise ValidationError("No existe un departamento para exportar.")
                status = self._first(query, "status", "final")
                status = None if status == "all" else status
                evaluations = self.database.list_evaluations(
                    user,
                    status=status,
                    start=self._first(query, "start") or None,
                    end=self._first(query, "end") or None,
                    department_id=int(department["id"]),
                )
                filename = (
                    f"Evaluaciones_{safe_filename(department['code'])}_"
                    f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                )
                output = self.export_dir / filename
                export_to_template(self.template_path, output, evaluations)
                return 200, {
                    "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "Content-Disposition": f'attachment; filename="{filename}"',
                }, output.read_bytes()

            if method == "GET" and path == "/export/departamentos.zip":
                self._require_admin(user)
                filename = f"Evaluaciones_por_Departamento_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
                output = self.export_dir / filename
                with ZipFile(output, "w", ZIP_DEFLATED) as archive:
                    for department in self.database.list_departments(True):
                        evaluations = self.database.list_evaluations(
                            user,
                            status=None,
                            department_id=int(department["id"]),
                        )
                        temp_name = f"Evaluaciones_{safe_filename(department['code'])}.xlsx"
                        temp_path = self.export_dir / f"._{temp_name}"
                        export_to_template(self.template_path, temp_path, evaluations)
                        archive.write(temp_path, temp_name)
                        temp_path.unlink(missing_ok=True)
                return 200, {
                    "Content-Type": "application/zip",
                    "Content-Disposition": f'attachment; filename="{filename}"',
                }, output.read_bytes()

            if method == "GET" and path == "/backup/operativo.zip":
                self._require_admin(user)
                filename = f"Respaldo_Evaluaciones_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
                output = self.export_dir / filename
                department_sets = {
                    department["code"]: self.database.list_evaluations(
                        user, department_id=int(department["id"])
                    )
                    for department in self.database.list_departments(True)
                }
                create_backup_zip(self.database, self.template_path, output, department_sets)
                return 200, {
                    "Content-Type": "application/zip",
                    "Content-Disposition": f'attachment; filename="{filename}"',
                }, output.read_bytes()

            return self._error(404, "Recurso no encontrado.")
        except AuthenticationError as exc:
            return 401, {
                "Content-Type": "application/json; charset=utf-8",
                "Set-Cookie": self._clear_session_cookie(),
            }, self._json_bytes({"error": str(exc)})
        except PermissionDenied as exc:
            return self._error(403, str(exc))
        except ConflictError as exc:
            return self._error(409, str(exc))
        except ValidationError as exc:
            return self._error(400, str(exc))
        except KeyError as exc:
            return self._error(404, str(exc).strip("'"))
        except (json.JSONDecodeError, TypeError, ValueError):
            return self._error(400, "Los datos enviados no son válidos.")
        except Exception as exc:
            print(f"[ERROR] {method} {raw_path}: {exc}")
            return self._error(500, "Ocurrió un error interno. Revise la consola del programa.")

    def _ok(self, payload: Any) -> tuple[int, dict[str, str], bytes]:
        return 200, {"Content-Type": "application/json; charset=utf-8"}, self._json_bytes(payload)

    def _error(self, status: int, message: str) -> tuple[int, dict[str, str], bytes]:
        return status, {"Content-Type": "application/json; charset=utf-8"}, self._json_bytes({"error": message})


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "EvaluacionPersonalVoz/1.2.0"

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 2 * 1024 * 1024:
            self.send_error(413, "Solicitud demasiado grande")
            return
        body = self.rfile.read(length) if length else b""
        status, headers, payload = self.server.application.dispatch(  # type: ignore[attr-defined]
            self.command, self.path, body, dict(self.headers.items())
        )
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        cache_control = "no-store" if self.path.startswith("/api/") or self.path == "/" else "private, max-age=300"
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_DELETE = _handle

    def log_message(self, format: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} - {format % args}")


class EvaluationServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, application: Application):
        super().__init__(server_address, RequestHandler)
        self.application = application


def create_server(
    host: str = "0.0.0.0",
    port: int = 8765,
    *,
    database_path: Path = DATABASE_PATH,
    template_path: Path = TEMPLATE_PATH,
    export_dir: Path = EXPORT_DIR,
) -> EvaluationServer:
    return EvaluationServer((host, port), Application(database_path, template_path, export_dir))
