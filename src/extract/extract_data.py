import os

import pandas as pd
import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from src.utils import BASE_DIR, project_path, get_logger

logger = get_logger(__name__)


def extract_csv(ruta) -> pd.DataFrame:
    """Lee un CSV como texto (bronze no se toca)."""
    df = pd.read_csv(project_path(ruta), dtype=str, encoding="utf-8")
    logger.info(f"Extraido {ruta}: {df.shape[0]} filas, {df.shape[1]} columnas")
    return df


def extract_excel(ruta, sheet=0, header_starts: str | None = None) -> pd.DataFrame:
    """Lee una hoja de Excel como texto. Requiere openpyxl.
    header_starts: texto de la primera celda del encabezado (ej. 'DP' en los archivos del
    DANE). Se busca esa fila y se ignoran los titulos de arriba y las filas vacias."""
    if header_starts is None:
        df = pd.read_excel(project_path(ruta), sheet_name=sheet, dtype=str)
    else:
        crudo = pd.read_excel(project_path(ruta), sheet_name=sheet, header=None, dtype=str)
        fila = crudo.index[crudo.iloc[:, 0].str.strip().eq(header_starts)]
        if fila.empty:
            raise ValueError(f"No se encontro la fila de encabezado '{header_starts}' en {ruta}")
        df = crudo.loc[fila[0] + 1:].copy()
        df.columns = crudo.loc[fila[0]].str.strip()
        df = df.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
    logger.info(f"Extraido {ruta}: {df.shape[0]} filas, {df.shape[1]} columnas")
    return df


def extract_sql(query: str) -> pd.DataFrame:
    """Ejecuta una consulta en la BD de DATABASE_URL_SOURCE (.env) y cierra la conexion."""
    load_dotenv(BASE_DIR / ".env")
    engine = create_engine(os.environ["DATABASE_URL_SOURCE"])
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn)
    finally:
        engine.dispose()
    logger.info(f"Extraido SQL: {df.shape[0]} filas, {df.shape[1]} columnas")
    return df.astype("string")


def extract_api_socrata(url: str, token_env: str | None = None, batch_size: int = 50000,
                        order: str = ":id", timeout: int = 60) -> pd.DataFrame:
    """Descarga completa de una API Socrata (datos.gov.co) por lotes con $limit/$offset.
    El token se lee del .env con el NOMBRE de la variable indicado en token_env."""
    load_dotenv(BASE_DIR / ".env")
    token = os.getenv(token_env) if token_env else None
    headers = {"X-App-Token": token} if token else {}
    if token_env and not token:
        logger.warning(f"No se encontro {token_env} en .env: se descarga sin token (mas lento)")

    todos, offset = [], 0
    while True:
        params = {"$limit": batch_size, "$offset": offset, "$order": order}
        resp = requests.get(url, headers=headers, params=params, timeout=timeout)
        resp.raise_for_status()
        lote = resp.json()
        if not lote:
            break
        todos.extend(lote)
        offset += len(lote)
        logger.info(f"API {url}: {len(todos)} filas descargadas...")

    df = pd.DataFrame(todos).astype("string")
    logger.info(f"Extraido API: {df.shape[0]} filas, {df.shape[1]} columnas")
    return df


def extract_api(fuente: dict) -> pd.DataFrame:
    """Fuente tipo API: guarda el crudo en bronze (raw_path) y, si use_cache es true
    y el archivo ya existe, lo lee de ahi en vez de volver a descargar."""
    raw_path = fuente.get("raw_path")
    if raw_path and fuente.get("use_cache", False) and project_path(raw_path).exists():
        logger.info(f"Usando copia local de bronze: {raw_path}")
        return extract_csv(raw_path)

    df = extract_api_socrata(fuente["url"], fuente.get("token_env"),
                             fuente.get("batch_size", 50000), fuente.get("order", ":id"))
    if raw_path:
        ruta = project_path(raw_path)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(ruta, index=False, encoding="utf-8")
        logger.info(f"Crudo guardado en bronze: {raw_path}")
    return df


def extract_source(fuente: dict) -> pd.DataFrame:
    """Elige el extractor segun el campo 'type' de la fuente en config.yaml."""
    tipo = fuente["type"]
    if tipo == "csv":
        return extract_csv(fuente["path"])
    if tipo == "excel":
        return extract_excel(fuente["path"], fuente.get("sheet", 0), fuente.get("header_starts"))
    if tipo == "sql":
        return extract_sql(fuente["query"])
    if tipo == "api":
        return extract_api(fuente)
    raise ValueError(f"Tipo de fuente no soportado: {tipo}")
