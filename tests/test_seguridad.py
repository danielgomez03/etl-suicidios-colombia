"""Pruebas de seguridad: el repositorio no debe contener credenciales.

Las credenciales (contrasena de la base y token de la API) van solo en el archivo .env de cada
persona, que esta en .gitignore. En el repositorio solo vive .env.example, sin valores reales.
"""
import re
import subprocess

import pytest

from src.utils import BASE_DIR

PATRONES = {
    "contrasena dentro de una URL de base de datos": re.compile(
        r"postgres(?:ql)?(?:\+\w+)?://[^:/\s\"']+:(?!contrasena@|postgres@|<)[^@\s\"']+@"),
    "contrasena de Neon": re.compile(r"npg_[A-Za-z0-9]{8,}"),
    "token de datos.gov.co": re.compile(r"SOCRATA_APP_TOKEN\s*=\s*[\"']?[A-Za-z0-9]{20,}"),
}
EXTENSIONES = {".py", ".yaml", ".yml", ".md", ".txt", ".ipynb", ".sql", ".cfg", ".toml", ".ini", ""}


def _archivos_versionados():
    try:
        salida = subprocess.run(["git", "ls-files"], cwd=BASE_DIR, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("No es un repositorio git (por ejemplo, una copia descargada en .zip)")
    return [BASE_DIR / f for f in salida.stdout.splitlines()]


def test_env_no_esta_en_el_repositorio():
    nombres = {p.name for p in _archivos_versionados()}
    assert ".env" not in nombres, "El archivo .env tiene credenciales y no debe subirse"
    assert ".env.example" in nombres


def test_env_esta_en_gitignore():
    reglas = (BASE_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in [r.strip() for r in reglas]


def test_ningun_archivo_versionado_tiene_credenciales():
    hallazgos = []
    for ruta in _archivos_versionados():
        if ruta.suffix not in EXTENSIONES and ruta.name != ".env.example":
            continue
        if not ruta.is_file():
            continue
        contenido = ruta.read_text(encoding="utf-8", errors="ignore")
        for nombre, patron in PATRONES.items():
            if patron.search(contenido):
                hallazgos.append(f"{ruta.relative_to(BASE_DIR)}: {nombre}")
    assert not hallazgos, "Posibles credenciales en el repositorio: " + "; ".join(hallazgos)
