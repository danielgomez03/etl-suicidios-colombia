import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

from src.utils import BASE_DIR, get_logger

logger = get_logger(__name__)


def save_csv(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8")
    logger.info(f"Guardado {ruta.relative_to(BASE_DIR)}: {len(df)} filas")


def get_engine():
    """Conexion de destino desde DATABASE_URL (.env). SQLite relativo al proyecto."""
    load_dotenv(BASE_DIR / ".env")
    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("Falta DATABASE_URL en el archivo .env")
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        url = f"sqlite:///{BASE_DIR / url.removeprefix('sqlite:///')}"
    return create_engine(url)


def load_to_database(df: pd.DataFrame, tabla: str) -> None:
    engine = get_engine()
    try:
        df.to_sql(tabla, engine, if_exists="replace", index=False)
    finally:
        engine.dispose()
    logger.info(f"Cargada tabla '{tabla}': {len(df)} filas")
