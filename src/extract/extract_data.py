import os
from pathlib import Path

import pandas as pd
import requests
import yaml
from dotenv import load_dotenv

# Raíz del proyecto
BASE_DIR = Path(__file__).resolve().parents[2]

load_dotenv(BASE_DIR / ".env")

with open(BASE_DIR / "config" / "config.yaml", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)
print(list(cfg.keys()))
(BASE_DIR / cfg["paths"]["bronze_dir"]).mkdir(parents=True, exist_ok=True)


def extract_api(fuente):
    """Descarga completa de la API Socrata"""
    token = os.getenv(fuente["token_env"])
    headers = {"X-App-Token": token} if token else {}
    if not token:
        print(f"Aviso: no se encontró {fuente['token_env']} en .env")

    todos, offset = [], 0
    while True:
        params = {
            "$limit": fuente["batch_size"],
            "$offset": offset,
            "$order": fuente["order"],
        }
        resp = requests.get(fuente["url"], headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        lote = resp.json()
        if not lote:
            break
        todos.extend(lote)
        offset += len(lote)
        print(f"Descargadas {len(todos)} filas...")
    return pd.DataFrame(todos).astype("string")


def extract_excel(fuente):
    ruta = BASE_DIR / fuente["path"]
    if not ruta.exists():
        disponibles = [p.name for p in ruta.parent.glob("*")]
        raise FileNotFoundError(
            f"No existe {ruta.name} en {ruta.parent}. Archivos encontrados: {disponibles}")

    crudo = pd.read_excel(ruta, sheet_name=fuente["sheet"], header=None, dtype=str)

    # encabezado
    marca = fuente["header_starts"]
    filas = crudo.index[crudo.iloc[:, 0].str.strip().eq(marca)]
    if filas.empty:
        raise ValueError(f"No se encontró la fila de encabezado '{marca}' en {ruta.name}")
    inicio = filas[0]

    df.columns = crudo.loc[inicio].str.strip()
    df = df.dropna(how="all").dropna(axis=1, how="all")
    es_dato = df.iloc[:, 0].str.strip().str.fullmatch(r"\d{1,2}", na=False)
    print(f"Filas descartadas (notas/pies): {(~es_dato).sum()}")
    df = df[es_dato]

    return df.reset_index(drop=True)


if __name__ == "__main__":
    for nombre, fuente in cfg["sources"].items():
        salida = BASE_DIR / fuente["output"]
        salida.parent.mkdir(parents=True, exist_ok=True)

        if fuente["type"] == "api":
            df = extract_api(fuente)
        elif fuente["type"] == "excel":
            df = extract_excel(fuente)
        else:
            raise ValueError(f"Tipo de fuente no soportado: {fuente['type']}")

        df.to_csv(salida, index=False, encoding="utf-8")
        print(f"{nombre}: {df.shape} -> {salida.relative_to(BASE_DIR)}")
