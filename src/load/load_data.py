"""
Funciones para guardar archivos CSV y cargar las tablas Gold en la base de datos.

El destino lo define DATABASE_URL en el .env: el grupo usa PostgreSQL en Neon
(servicio gratuito en la nube); tambien funciona con SQLite o un PostgreSQL local.
"""

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

from src.utils import BASE_DIR, get_logger

logger = get_logger(__name__)

# Cargar variables de entorno del .env del proyecto
load_dotenv(BASE_DIR / ".env")


def save_csv(df: pd.DataFrame, ruta: Path) -> None:
    """Guarda un DataFrame como CSV (crea la carpeta si no existe)."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8-sig")
    logger.info(f"Guardado {ruta.name}: {len(df)} filas")


def _destino(url: str) -> str:
    """Nombre corto del destino para el log, sin usuario ni contrasena."""
    if url.startswith("sqlite"):
        return "SQLite"
    if "neon.tech" in url:
        return "Neon (PostgreSQL)"
    return "PostgreSQL"


def get_engine():
    """Conexion de destino a partir de DATABASE_URL (.env)."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("Falta DATABASE_URL en el archivo .env (ver .env.example)")

    # Indicar explicitamente que SQLAlchemy utilice psycopg2
    url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

    # SQLite con ruta relativa: se toma desde la raiz del proyecto
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        url = f"sqlite:///{BASE_DIR / url.removeprefix('sqlite:///')}"
    return create_engine(url)


def load_to_database(df: pd.DataFrame, tabla: str) -> None:
    """Carga un DataFrame como tabla en la base de datos (reemplaza la tabla si existe)."""
    engine = get_engine()
    try:
        df.to_sql(
            tabla,
            engine,
            if_exists="replace",
            index=False,
            chunksize=1000,
            method="multi"
        )
    finally:
        engine.dispose()
    logger.info(f"Cargada tabla '{tabla}' en {_destino(str(engine.url))}: {len(df)} filas")
