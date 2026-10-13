"""
Funciones para guardar archivos CSV y cargar las tablas Gold en la base de datos.

El destino lo define DATABASE_URL (variable de entorno o archivo .env, que NO se sube al
repositorio). El grupo usa PostgreSQL en Neon; sin DATABASE_URL se usa SQLite local.

En PostgreSQL, cada carga:
  1. borra las tablas anteriores (con sus llaves) y carga las nuevas;
  2. crea las llaves primarias y foraneas (integridad referencial);
  3. aplica los roles de acceso de sql/roles_postgres.sql;
  4. VERIFICA que llaves y permisos quedaron aplicados. Si algo falta, la carga falla.
"""

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from src.utils import BASE_DIR, get_logger

logger = get_logger(__name__)

# Cargar variables de entorno del .env del proyecto (si existe)
load_dotenv(BASE_DIR / ".env")

URL_POR_DEFECTO = "sqlite:///data/gold/suicidios.db"
SIN_INFO = "Sin informacion"


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
    """Conexion de destino a partir de DATABASE_URL. Sin ella, SQLite local."""
    url = os.getenv("DATABASE_URL")
    if not url:
        logger.warning(f"No hay DATABASE_URL (ver .env.example): se usa {URL_POR_DEFECTO}")
        url = URL_POR_DEFECTO

    # Indicar explicitamente que SQLAlchemy utilice psycopg2
    url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

    # SQLite con ruta relativa: se toma desde la raiz del proyecto
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        url = f"sqlite:///{BASE_DIR / url.removeprefix('sqlite:///')}"
    return create_engine(url)


def es_postgres() -> bool:
    engine = get_engine()
    try:
        return engine.dialect.name == "postgresql"
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Modelo relacional de la base (solo PostgreSQL)
# ---------------------------------------------------------------------------

# Llave primaria de cada tabla: identifica cada fila sin repetidos
LLAVES_PRIMARIAS = {
    "gold_suicidios": ["id"],
    "gold_tasa_mortalidad": ["nivel", "codigo", "periodo", "sexo", "grupo_edad"],
    "gold_agregado_tablero": ["nivel", "codigo", "periodo", "variable", "categoria"],
    "gold_kpi_calidad": ["indicador", "dimension"],
    "dim_departamento": ["codigo_dane"],
    "dim_municipio": ["codigo_municipio"],
    "dim_grupo_edad": ["grupo_edad"],
}

# Llaves foraneas (integridad referencial): (tabla, columna) -> (tabla maestra, columna)
# La tasa y el agregado del tablero no llevan llave foranea al territorio porque su columna
# "codigo" depende del nivel (nacional, departamento o municipio); su consistencia se
# comprueba en las pruebas automaticas (tests/test_base_datos.py).
LLAVES_FORANEAS = [
    ("dim_municipio", "codigo_dane", "dim_departamento", "codigo_dane"),
    ("gold_suicidios", "codigo_dane_departamento", "dim_departamento", "codigo_dane"),
    ("gold_suicidios", "codigo_dane_municipio", "dim_municipio", "codigo_municipio"),
    ("gold_suicidios", "grupo_de_edad_quinquenal", "dim_grupo_edad", "grupo_edad"),
    ("gold_tasa_mortalidad", "grupo_edad", "dim_grupo_edad", "grupo_edad"),
]

# Permisos esperados despues de aplicar sql/roles_postgres.sql
TABLAS_TABLERO = ["gold_agregado_tablero", "gold_tasa_mortalidad", "gold_kpi_calidad",
                  "dim_departamento", "dim_municipio", "dim_grupo_edad"]
TABLAS_SOLO_ANALISTA = ["gold_suicidios"]

ROLES_SQL = BASE_DIR / "sql" / "roles_postgres.sql"


def completar_dimensiones(tablas: dict) -> dict:
    """Miembro "Sin informacion" en las tablas maestras (practica estandar de bodegas de datos).

    Los 4 casos sin departamento ni municipio (codigo 999 de Medicina Legal) y la fila "Total"
    de las tasas necesitan un registro al que apuntar para que las llaves foraneas se cumplan.
    Solo se agrega a la copia que va a la base; los calculos y los CSV de gold no cambian."""
    t = dict(tablas)
    if "dim_departamento" in t:
        d = t["dim_departamento"]
        if SIN_INFO not in set(d["codigo_dane"]):
            fila = {"codigo_dane": SIN_INFO, "departamento": "Sin información", "region": "Sin información"}
            t["dim_departamento"] = pd.concat([d, pd.DataFrame([fila])], ignore_index=True)
    if "dim_municipio" in t and "gold_suicidios" in t:
        m = t["dim_municipio"]
        conocidos = set(m["codigo_municipio"])
        casos = t["gold_suicidios"]
        faltantes = sorted(set(casos["codigo_dane_municipio"].dropna()) - conocidos)
        if faltantes:
            filas = pd.DataFrame({"codigo_municipio": faltantes, "municipio": "Sin información",
                                  "codigo_dane": SIN_INFO, "municipio_foco": False})
            t["dim_municipio"] = pd.concat([m, filas], ignore_index=True)
    if "dim_grupo_edad" in t and "Total" not in set(t["dim_grupo_edad"]["grupo_edad"]):
        e = t["dim_grupo_edad"]
        fila = {"grupo_edad": "Total", "edad_min": 0, "edad_max": 100, "menor_de_edad": None, "orden": 0}
        fila = {k: v for k, v in fila.items() if k in e.columns}
        t["dim_grupo_edad"] = pd.concat([e, pd.DataFrame([fila])], ignore_index=True)
    return t


def preparar_base(tablas) -> None:
    """PostgreSQL: borra las tablas anteriores con sus llaves (CASCADE). Sin esto, una tabla
    maestra referenciada por una llave foranea no se puede reemplazar."""
    engine = get_engine()
    try:
        if engine.dialect.name != "postgresql":
            return
        with engine.begin() as con:
            for tabla in tablas:
                con.execute(text(f'DROP TABLE IF EXISTS "{tabla}" CASCADE'))
    finally:
        engine.dispose()


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


def aplicar_llaves_y_roles(tablas) -> None:
    """PostgreSQL: crea llaves primarias y foraneas y aplica los roles de acceso.
    Cualquier error detiene la carga (no se deja una base a medio proteger)."""
    tablas = set(tablas)
    engine = get_engine()
    try:
        if engine.dialect.name != "postgresql":
            logger.info("Base SQLite: sin llaves ni roles (solo aplican en PostgreSQL)")
            return
        with engine.begin() as con:
            for tabla, columnas in LLAVES_PRIMARIAS.items():
                if tabla not in tablas:
                    continue
                lista = ", ".join(f'"{c}"' for c in columnas)
                con.execute(text(f'ALTER TABLE "{tabla}" ADD CONSTRAINT "pk_{tabla}" PRIMARY KEY ({lista})'))
            for tabla, col, ref, ref_col in LLAVES_FORANEAS:
                if tabla in tablas and ref in tablas:
                    con.execute(text(
                        f'ALTER TABLE "{tabla}" ADD CONSTRAINT "fk_{tabla}_{col}" '
                        f'FOREIGN KEY ("{col}") REFERENCES "{ref}" ("{ref_col}")'))
        logger.info(f"Llaves aplicadas: {len(LLAVES_PRIMARIAS)} primarias y {len(LLAVES_FORANEAS)} foraneas")
        with engine.begin() as con:
            con.exec_driver_sql(ROLES_SQL.read_text(encoding="utf-8"))
        logger.info("Roles de acceso aplicados (rol_tablero: agregados; rol_analista: + detalle por caso)")
    finally:
        engine.dispose()


def verificar_base(tablas) -> pd.DataFrame:
    """Comprueba en la base que las llaves y los permisos quedaron aplicados en ESTA carga.
    Devuelve una fila por verificacion y lanza un error si alguna falla."""
    tablas = set(tablas)
    engine = get_engine()
    filas = []
    try:
        if engine.dialect.name != "postgresql":
            return pd.DataFrame(columns=["verificacion", "objeto", "esperado", "obtenido", "cumple"])
        with engine.connect() as con:
            restricciones = {(r.tabla, r.nombre, r.tipo) for r in con.execute(text(
                "SELECT conrelid::regclass::text AS tabla, conname AS nombre, contype AS tipo "
                "FROM pg_constraint WHERE connamespace = 'public'::regnamespace"))}
            restricciones = {(t.strip('"'), n, ty) for t, n, ty in restricciones}

            def permiso(rol, tabla):
                return bool(con.execute(text("SELECT has_table_privilege(:r, :t, 'SELECT')"),
                                        {"r": rol, "t": f'public."{tabla}"'}).scalar())

            for tabla in LLAVES_PRIMARIAS:
                if tabla in tablas:
                    ok = (tabla, f"pk_{tabla}", "p") in restricciones
                    filas.append(("Llave primaria", tabla, "existe", "existe" if ok else "falta", ok))
            for tabla, col, ref, _ in LLAVES_FORANEAS:
                if tabla in tablas and ref in tablas:
                    ok = (tabla, f"fk_{tabla}_{col}", "f") in restricciones
                    filas.append(("Llave foranea", f"{tabla}.{col} -> {ref}", "existe",
                                  "existe" if ok else "falta", ok))
            for tabla in TABLAS_TABLERO:
                if tabla in tablas:
                    for rol in ("rol_tablero", "rol_analista"):
                        ok = permiso(rol, tabla)
                        filas.append(("Permiso de lectura", f"{rol} -> {tabla}", "si", "si" if ok else "no", ok))
            for tabla in TABLAS_SOLO_ANALISTA:
                if tabla in tablas:
                    ok_a = permiso("rol_analista", tabla)
                    filas.append(("Permiso de lectura", f"rol_analista -> {tabla}", "si",
                                  "si" if ok_a else "no", ok_a))
                    ok_t = not permiso("rol_tablero", tabla)
                    filas.append(("Acceso denegado", f"rol_tablero -> {tabla}", "no",
                                  "no" if ok_t else "si", ok_t))
    finally:
        engine.dispose()

    resultado = pd.DataFrame(filas, columns=["verificacion", "objeto", "esperado", "obtenido", "cumple"])
    fallas = resultado[~resultado["cumple"]]
    logger.info(f"Verificacion de la base: {int(resultado['cumple'].sum())}/{len(resultado)} comprobaciones cumplen")
    if not fallas.empty:
        detalle = "; ".join(f"{r.verificacion} {r.objeto}" for r in fallas.itertuples())
        raise RuntimeError(f"La base quedo sin las restricciones o permisos esperados: {detalle}")
    return resultado
