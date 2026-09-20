from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Evaluación de Personal"
APP_VERSION = "1.2.0"
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
EXPORT_DIR = ROOT_DIR / "exports"
TEMPLATE_PATH = ROOT_DIR / "assets" / "ESQUELETO FORMATO.xlsx"
DATABASE_PATH = DATA_DIR / "evaluaciones_personal.sqlite3"

DEFAULT_DEPARTMENT_CODE = "ADQ-REG"
DEFAULT_DEPARTMENT_NAME = "ADQUISICIÓN (REGISTRO)"
DEFAULT_ADMIN_USERNAME = "admin"
INITIAL_ADMIN_PASSWORD = os.environ.get("EVALUACION_ADMIN_PASSWORD", "").strip()
INITIAL_ADMIN_PASSWORD_FILE = DATA_DIR / ".initial_admin_password"
SESSION_HOURS = 12
PASSWORD_ITERATIONS = 240_000

LEGACY_CATEGORIES = [
    "CABO DE TENDIDO C",
    "CABO DE TENDIDO B",
    "CABO DE TENDIDO A",
    "TIRADOR C",
    "TIRADOR B",
    "TIRADOR A",
    "CHECADOR DE LINEA C",
    "CHECADOR DE LINEA B",
    "CHECADOR DE LINEA A",
]

AREAS = [
    {"code": "material", "title": "1. CONTROL DE MATERIAL", "comment": "Observaciones CONTROL DE MATERIA"},
    {"code": "hse", "title": "2. HSE (SEGURIDAD)", "comment": "Observaciones HSE"},
    {"code": "inova", "title": "3. TX INOVA", "comment": "Observaciones TX INOVA"},
    {"code": "sercel", "title": "4. TX SERCEL", "comment": "Observaciones TX SERCEL"},
    {"code": "sismografo", "title": "5. SISMÓGRAFO", "comment": "Observaciones TX SISMOGRAFO"},
]

SCORE_FIELDS = ("attitude", "performance", "technical")
