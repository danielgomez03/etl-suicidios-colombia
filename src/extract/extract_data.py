"""Extraccion (bronze): API Socrata de datos.gov.co, Excel del DANE y CSV.

Este modulo solo define funciones: no lee el config ni escribe archivos al importarse.
El orquestador (main.py) decide que fuentes extraer y en que orden.
"""
import os
from typing import Optional

import pandas as pd
import requests
from dotenv import load_dotenv

from src.utils import BASE_DIR, get_logger

logger = get_logger(__name__)


def extract_csv(ruta) -> pd.DataFrame:
    """Lee un CSV como texto (bronze no se toca)."""
    df = pd.read_csv(BASE_DIR / ruta, dtype=str, encoding="utf-8")
    logger.info(f"Extraido {ruta}: {df.shape[0]} filas, {df.shape[1]} columnas")
    return df


def extract_api(fuente: dict) -> pd.DataFrame:
    """API Socrata por lotes ($limit/$offset). Guarda el crudo en bronze (raw_path) y,
    con use_cache, reutiliza esa copia en vez de volver a descargar."""
    raw_path = fuente.get("raw_path") or fuente.get("output")
    if raw_path and fuente.get("use_cache", False) and (BASE_DIR / raw_path).exists():
        logger.info(f"Usando copia local de bronze: {raw_path}")
        return extract_csv(raw_path)

    load_dotenv(BASE_DIR / ".env")
    token_env = fuente.get("token_env") or ""
    token = os.getenv(token_env) if token_env else None
    if token_env and not token:
        logger.warning(f"No se encontro {token_env} en .env: se descarga sin token (mas lento)")
    headers = {"X-App-Token": token} if token else {}

    todos, offset = [], 0
    while True:
        params = {"$limit": fuente.get("batch_size", 50000), "$offset": offset,
                  "$order": fuente.get("order", ":id")}
        resp = requests.get(fuente["url"], headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        lote = resp.json()
        if not lote:
            break
        todos.extend(lote)
        offset += len(lote)
        logger.info(f"API: {len(todos)} filas descargadas...")

    df = pd.DataFrame(todos).astype("string")
    logger.info(f"Extraido API: {df.shape[0]} filas, {df.shape[1]} columnas")
    if raw_path:
        (BASE_DIR / raw_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(BASE_DIR / raw_path, index=False, encoding="utf-8")
        logger.info(f"Crudo guardado en bronze: {raw_path}")
    return df


def extract_api_socrata(url: str, batch_size: int = 50000, token: Optional[str] = None) -> pd.DataFrame:
    """Atajo para descargar una API Socrata por URL directa (lo usan las pruebas)."""
    if token:
        os.environ["SOCRATA_APP_TOKEN"] = token
    fuente = {"url": url, "batch_size": batch_size, "order": ":id", "use_cache": False,
              "token_env": "SOCRATA_APP_TOKEN" if token else None}
    return extract_api(fuente)


def extract_excel(fuente: dict) -> pd.DataFrame:
    """Lee una hoja de Excel del DANE como texto.

    - header_starts: texto de la primera celda del encabezado ('DP'); se ignoran los titulos de arriba.
    - header_rows: 2 cuando el encabezado ocupa dos filas (archivos por sexo y edad 2018-2050:
      la segunda fila trae 'Hombres 0 años', 'Hombres 1 año', ...).
    - Se descartan las filas vacias y las notas al pie (filas cuyo codigo DP no es numerico).
    """
    ruta = BASE_DIR / fuente["path"]
    if not ruta.exists():
        disponibles = sorted(p.name for p in ruta.parent.glob("*") if p.is_file())
        raise FileNotFoundError(f"No existe {ruta.name} en {ruta.parent}. Archivos: {disponibles}")

    crudo = pd.read_excel(ruta, sheet_name=fuente.get("sheet", 0), header=None, dtype=str)

    marca = fuente.get("header_starts", "DP")
    filas = crudo.index[crudo.iloc[:, 0].str.strip().eq(marca)]
    if filas.empty:
        raise ValueError(f"No se encontro la fila de encabezado '{marca}' en {ruta.name}")
    inicio = filas[0]

    encabezado = crudo.loc[inicio].copy()
    n_filas_encabezado = fuente.get("header_rows", 1)
    if n_filas_encabezado == 2:
        segunda = crudo.loc[inicio + 1]
        encabezado = segunda.where(segunda.notna(), encabezado)

    df = crudo.loc[inicio + n_filas_encabezado:].copy()
    df.columns = encabezado.astype(str).str.strip()
    df = df.dropna(how="all").dropna(axis=1, how="all")

    es_dato = df.iloc[:, 0].str.strip().str.fullmatch(r"\d{1,2}", na=False)
    if (~es_dato).sum():
        logger.info(f"{ruta.name}: {(~es_dato).sum()} filas de notas al pie descartadas")
    df = df[es_dato].reset_index(drop=True)
    logger.info(f"Extraido {ruta.name}: {df.shape[0]} filas, {df.shape[1]} columnas")
    return df


def extract_source(fuente: dict) -> pd.DataFrame:
    """Elige el extractor segun el campo 'type' de la fuente en config.yaml."""
    tipo = fuente["type"]
    if tipo == "csv":
        return extract_csv(fuente["path"])
    if tipo == "excel":
        return extract_excel(fuente)
    if tipo == "api":
        return extract_api(fuente)
    raise ValueError(f"Tipo de fuente no soportado: {tipo}")


if __name__ == "__main__":
    # Extraccion sola, sin transformar: python -m src.extract.extract_data
    from src.utils import load_config

    for nombre, fuente in load_config()["sources"].items():
        df = extract_source(fuente)
        logger.info(f"{nombre}: {df.shape}")
