from __future__ import annotations

import os
import socket
import threading
import webbrowser

from app import create_server
from app.config import DEFAULT_ADMIN_USERNAME


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def main() -> None:
    host = os.environ.get("EVAL_HOST", "0.0.0.0")
    port = int(os.environ.get("EVAL_PORT", "8765"))
    server = create_server(host, port)
    ip = local_ip()
    desktop_url = f"http://127.0.0.1:{port}"
    network_url = f"http://{ip}:{port}"
    print("=" * 78)
    print(" EVALUACIÓN DE PERSONAL · USUARIOS Y DEPARTAMENTOS")
    print("=" * 78)
    print(f"Administración en esta computadora: {desktop_url}")
    print(f"Host para enviar a los capturistas: {network_url}")
    print("Cada persona entra al mismo host con su usuario y contraseña.")
    if server.application.database.initial_admin_pending():
        print("-" * 78)
        print("PRIMER ACCESO ADMINISTRADOR")
        print(f"Usuario:     {DEFAULT_ADMIN_USERNAME}")
        if server.application.database.initial_admin_password:
            print(f"Contraseña:  {server.application.database.initial_admin_password}")
            print("Es temporal, local y el sistema obligará a cambiarla inmediatamente.")
        else:
            print("No hay una contraseña bootstrap recuperable.")
            print("Defina EVALUACION_ADMIN_PASSWORD y reinicie para rotarla mientras siga pendiente.")
    print("-" * 78)
    print("Permita el uso del micrófono en Chrome y no cierre esta ventana.")
    print("Para cerrar el servidor presione Ctrl+C.")
    print("=" * 78)
    if os.environ.get("EVAL_NO_BROWSER") != "1":
        threading.Timer(1.0, lambda: webbrowser.open(desktop_url)).start()
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print("\nCerrando servidor...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
