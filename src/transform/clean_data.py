import re
from pathlib import Path

import pandas as pd
import yaml

BASE_DIR = Path(__file__).resolve().parents[2]

with open(BASE_DIR / "config" / "config.yaml", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)



 #  BASE DE POBLACIÓN POR DEPARTAMENTOS
# Un solo nombre oficial por código de departamento
DEPARTAMENTOS = {
    "05": "Antioquia", "08": "Atlántico", "11": "Bogotá, D.C.", "13": "Bolívar",
    "15": "Boyacá", "17": "Caldas", "18": "Caquetá", "19": "Cauca", "20": "Cesar",
    "23": "Córdoba", "25": "Cundinamarca", "27": "Chocó", "41": "Huila",
    "44": "La Guajira", "47": "Magdalena", "50": "Meta", "52": "Nariño",
    "54": "Norte de Santander", "63": "Quindío", "66": "Risaralda",
    "68": "Santander", "70": "Sucre", "73": "Tolima", "76": "Valle del Cauca",
    "81": "Arauca", "85": "Casanare", "86": "Putumayo",
    "88": "Archipiélago de San Andrés, Providencia y Santa Catalina",
    "91": "Amazonas", "94": "Guainía", "95": "Guaviare", "97": "Vaupés",
    "99": "Vichada",}

def normalizar(texto: pd.Series) -> pd.Series:

    return texto.astype("string").str.strip().str.replace(r"\s+", " ", regex=True).str.lower()

def silver_poblacion() -> pd.DataFrame:
    fuente = cfg["sources"]["poblacion_2005_2050"]
    df = pd.read_csv(BASE_DIR / fuente["output"], dtype=str, encoding="utf-8")
    df.columns = df.columns.str.strip()
    print(f"Leído bronze: {df.shape}")

    #nombres columnas
    df = df.rename(columns={"DP": "cod_dpto", "DPNOM": "departamento",
                            "AÑO": "anio", "ÁREA GEOGRÁFICA": "area"})

    # columna de población 
    cols_pob = [c for c in df.columns if c.strip().lower() in ("población", "poblacion", "total")]
    if not cols_pob:
        raise ValueError(f"No encontré la columna de población. Columnas: {df.columns.tolist()}")
    df["poblacion"] = df[cols_pob].bfill(axis=1).iloc[:, 0]
    df = df.drop(columns=cols_pob)

    # Definir tipos de columna
    df["cod_dpto"] = df["cod_dpto"].str.strip().str.zfill(2)
    df["anio"] = pd.to_numeric(df["anio"].str.strip(), errors="coerce").astype("Int64")

    df["poblacion"] = pd.to_numeric(
        df["poblacion"].astype("string").str.replace(r"[^\d]", "", regex=True), errors="coerce").astype("Int64")

    # filtrar por 2015-2024 y total de población
    ini, fin = cfg["period"]["start_year"], cfg["period"]["end_year"]
    df = df[df["anio"].between(ini, fin)]
    df = df[normalizar(df["area"]).eq("total")]
    print(f"Tras filtrar {ini}-{fin} y área Total: {df.shape[0]} filas")

    # Unificar nombres por código
    desconocidos = set(df["cod_dpto"]) - set(DEPARTAMENTOS)
    if desconocidos:
        raise ValueError(f"Códigos de departamento no reconocidos: {sorted(desconocidos)}")
    df["departamento"] = df["cod_dpto"].map(DEPARTAMENTOS)

    # Duplicados
    clave = ["cod_dpto", "anio"]
    dup = df[df.duplicated(clave, keep=False)]
    if not dup.empty:
        conflictos = dup.groupby(clave)["poblacion"].nunique()
        if (conflictos > 1).any():
            print("Aviso: hay duplicados con poblaciones distintas (se conserva el primero):")
            print(conflictos[conflictos > 1])
        df = df.drop_duplicates(clave, keep="first")

    df = df[["cod_dpto", "departamento", "anio", "poblacion"]]
    df = df.sort_values(clave).reset_index(drop=True)

    # Validaciones 
    esperado = len(DEPARTAMENTOS) * (fin - ini + 1)
    print(f"Filas finales: {len(df)} (esperadas: {esperado})")
    if len(df) != esperado:
        faltan = (
            pd.MultiIndex.from_product([DEPARTAMENTOS, range(ini, fin + 1)])
            .difference(pd.MultiIndex.from_frame(df[clave]))
        )
        print("Combinaciones (departamento, año) que faltan:", list(faltan)[:10])
    nulos = df["poblacion"].isna().sum()
    if nulos:
        print(f"Aviso: {nulos} filas con población nula")

    return df


if __name__ == "__main__":
    df = silver_poblacion()
    salida = BASE_DIR / cfg["paths"]["silver_dir"] / "poblacion_silver.csv"
    salida.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(salida, index=False, encoding="utf-8")
    print(f"Guardado: {salida.relative_to(BASE_DIR)}")
    print(df.head())
