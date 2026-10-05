"""
Funciones para guardar archivos CSV y cargar las tablas Gold en la base de datos.

El destino lo define DATABASE_URL en el .env: el grupo usa PostgreSQL en Neon
(servicio gratuito en la nube); tambien funciona con SQLite o un PostgreSQL local.
"""

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

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


# Llave primaria de cada tabla gold (solo PostgreSQL). Identifica cada fila sin repetidos;
# no se crean llaves foraneas porque hay casos sin departamento / municipio 999 que no
# existen en las tablas maestras y porque la carga recrea las tablas en cada ejecucion.
LLAVES_PRIMARIAS = {
    "gold_suicidios": ["id"],
    "gold_tasa_mortalidad": ["nivel", "codigo", "periodo", "sexo", "grupo_edad"],
    "gold_agregado_tablero": ["nivel", "codigo", "periodo", "variable", "categoria"],
    "gold_kpi_calidad": ["indicador", "dimension"],
    "dim_departamento": ["codigo_dane"],
    "dim_municipio": ["codigo_municipio"],
    "dim_grupo_edad": ["grupo_edad"],
}

ROLES_SQL = BASE_DIR / "sql" / "roles_postgres.sql"


def aplicar_llaves_y_roles(tablas) -> None:
    """Despues de la carga (solo PostgreSQL, p. ej. Neon): crea las llaves primarias y vuelve
    a aplicar los permisos de sql/roles_postgres.sql, que se pierden porque la carga recrea
    las tablas. En SQLite no hace nada. Si algo falla se avisa en el log sin detener el ETL."""
    engine = get_engine()
    try:
        if engine.dialect.name != "postgresql":
            logger.info("Base SQLite: sin llaves primarias ni roles (solo aplican en PostgreSQL)")
            return
        for tabla in tablas:
            columnas = LLAVES_PRIMARIAS.get(tabla)
            if not columnas:
                continue
            try:
                with engine.begin() as con:
                    lista = ", ".join(f'"{c}"' for c in columnas)
                    con.execute(text(f'ALTER TABLE "{tabla}" DROP CONSTRAINT IF EXISTS "pk_{tabla}"'))
                    con.execute(text(f'ALTER TABLE "{tabla}" ADD CONSTRAINT "pk_{tabla}" PRIMARY KEY ({lista})'))
                logger.info(f"Llave primaria de '{tabla}': {', '.join(columnas)}")
            except Exception as error:
                logger.warning(f"No se pudo crear la llave primaria de '{tabla}': {error}")
        try:
            with engine.begin() as con:
                con.exec_driver_sql(ROLES_SQL.read_text(encoding="utf-8"))
            logger.info("Roles de acceso aplicados (rol_tablero: agregados; rol_analista: + detalle por caso)")
        except Exception as error:
            logger.warning(f"No se pudieron aplicar los roles de {ROLES_SQL.name}: {error}")
    finally:
        engine.dispose()
