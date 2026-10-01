import re
import unicodedata

import pandas as pd

from src.utils import get_logger

logger = get_logger(__name__)


# ---------- herramientas reutilizables ----------

def quitar_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def normalizar_texto(serie: pd.Series) -> pd.Series:
    """Quita espacios sobrantes y pone Formato Titulo."""
    return serie.str.strip().str.replace(r"\s+", " ", regex=True).str.title()


def unificar_categorias(serie: pd.Series) -> pd.Series:
    """Agrupa variantes (mayusculas, tildes, espacios) y usa la escritura mas comun."""
    s = serie.str.strip()
    clave = s.dropna().map(lambda x: quitar_tildes(x).lower())
    oficial = s.dropna().groupby(clave).agg(lambda v: v.value_counts().index[0])
    return s.map(lambda x: oficial[quitar_tildes(x).lower()] if isinstance(x, str) else x)


def parsear_fecha(valor, formatos: list):
    """Prueba cada formato en orden; si ninguno sirve devuelve NaT (no adivina)."""
    if pd.isna(valor):
        return pd.NaT
    for fmt in formatos:
        try:
            return pd.to_datetime(str(valor).strip(), format=fmt)
        except ValueError:
            continue
    return pd.NaT


def a_numero(serie: pd.Series) -> pd.Series:
    """'3,75' -> 3.75 ; '20 creditos' -> 20 ; texto sin numero -> NaN."""
    limpio = serie.astype("string").str.replace(",", ".", regex=False).str.extract(r"(-?\d+\.?\d*)")[0]
    return pd.to_numeric(limpio, errors="coerce")


def solo_digitos(serie: pd.Series) -> pd.Series:
    return serie.astype("string").str.replace(r"\D", "", regex=True)


def fuera_de_rango_a_nulo(serie: pd.Series, minimo, maximo) -> pd.Series:
    """Valores imposibles -> nulo (se imputan despues, con justificacion)."""
    return serie.where(serie.between(minimo, maximo))


# ---------- limpieza por fuente ----------
# Escribe una funcion limpiar_<fuente> por cada fuente, DESPUES del EDA.
# Orden: copia -> texto/categorias -> tipos -> reglas de negocio -> nulos -> duplicados.

def limpiar_generico(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Limpieza base que sirve para cualquier tabla. Amplia segun tu EDA."""
    df_copia = df.copy()
    filas = len(df_copia)

    df_copia.columns = (df_copia.columns.str.strip().str.lower()
                        .map(quitar_tildes).str.replace(r"\W+", "_", regex=True))
    for col in df_copia.select_dtypes(include=["object", "string"]).columns:
        df_copia[col] = df_copia[col].str.strip().replace("", pd.NA)

    df_copia = df_copia.drop_duplicates()

    logger.info(f"limpiar_generico: {filas} -> {len(df_copia)} filas")
    return df_copia.reset_index(drop=True)


LIMPIADORES = {
    # "ventas": limpiar_ventas,
}


def limpiar_fuente(nombre: str, df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Generica -> especifica de la fuente -> un registro por llave (al final,
    cuando las variantes ya estan normalizadas)."""
    df = limpiar_generico(df, config)
    if nombre in LIMPIADORES:
        df = LIMPIADORES[nombre](df, config)
    key = config["sources"][nombre].get("key")
    if key and key in df.columns:
        antes = len(df)
        df = df.drop_duplicates(subset=key, keep="first").reset_index(drop=True)
        if len(df) < antes:
            logger.warning(f"{nombre}: {antes - len(df)} registros repetidos por '{key}' eliminados")
    return df
