
import os
from pathlib import Path
from typing import Optional

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


def extract_csv(ruta) -> pd.DataFrame:
    df = pd.read_csv(BASE_DIR / ruta, dtype=str, encoding="utf-8")
    return df



def extract_api(fuente):
    raw_path = fuente.get("raw_path") or fuente.get("output")
    if raw_path and fuente.get("use_cache", False) and (BASE_DIR / raw_path).exists():
        print(f"Usando copia local de bronze: {raw_path}")
        return extract_csv(raw_path)
    token_env = fuente.get("token_env") or ""
    token = os.getenv(token_env)
    headers = {"X-App-Token": token} if token else {}
    todos, offset = [], 0
    while True:
        params = {"$limit": fuente.get("batch_size", 50000), "$offset": offset, "$order": fuente.get("order", ":id")}
        resp = requests.get(fuente["url"], headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        lote = resp.json()
        if not lote: break
        todos.extend(lote)
        offset += len(lote)
    df = pd.DataFrame(todos).astype("string")
    if raw_path:
        (BASE_DIR / raw_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(BASE_DIR / raw_path, index=False, encoding="utf-8")
    return df


def extract_api_socrata(url: str, batch_size: int = 50000, token: Optional[str] = None) -> pd.DataFrame:
    """Wrapper para compatibilidad con tests: extrae de API Socrata por URL directa."""
    fuente = {
        "url": url,
        "batch_size": batch_size,
        "token_env": "SOCRATA_APP_TOKEN" if token else None,
        "order": ":id",
        "use_cache": False,
    }
    if token:
        os.environ["SOCRATA_APP_TOKEN"] = token
    return extract_api(fuente)



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

    df = crudo.loc[inicio + 1:].copy()
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


def extract_source(fuente: dict) -> pd.DataFrame:
    tipo = fuente["type"]
    if tipo == "csv":
        return extract_csv(fuente["path"])
    if tipo == "excel":
        return extract_excel(fuente)
    if tipo == "api":
        return extract_api(fuente)
    raise ValueError(f"Tipo de fuente no soportado: {tipo}")
