"""
Funciones para guardar archivos CSV y cargar tablas Gold en Neon.
"""

import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine


# Cargar variables de entorno
load_dotenv()


# Los códigos DANE se leen como texto para no perder ceros iniciales
CODIGOS = [
    "codigo",
    "codigo_dane",
    "codigo_municipio",
    "codigo_dane_departamento",
    "codigo_dane_municipio"
]


def save_csv(df, ruta):
    """Guarda un DataFrame como CSV."""
    df.to_csv(ruta, index=False, encoding="utf-8-sig")


def load_to_database(df, tabla):
    """Carga un DataFrame como tabla en Neon."""

    url = os.environ["DATABASE_URL"]

    # Indicar explícitamente que SQLAlchemy utilice psycopg2
    url = url.replace(
        "postgresql://",
        "postgresql+psycopg2://",
        1
    )

    engine = create_engine(url)

    df.to_sql(
        tabla,
        engine,
        if_exists="replace",
        index=False,
        chunksize=1000,
        method="multi"
    )

    print(f"{tabla}: {len(df)} filas subidas a Neon")

