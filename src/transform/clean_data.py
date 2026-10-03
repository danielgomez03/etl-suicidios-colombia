import re
import unicodedata

import pandas as pd

from src.utils import get_logger

logger = get_logger(__name__)


# ---------- herramientas reutilizables ----------

def quitar_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def clave_categoria(texto) -> str:
    """Forma normalizada de un texto: sin tildes, minusculas y sin espacios ni signos.
    Es la misma 'clave' que usa el EDA para detectar variantes de una categoria."""
    return "".join(c for c in quitar_tildes(str(texto)).lower() if c.isalnum())


def es_sin_info(serie: pd.Series) -> pd.Series:
    """Detecta valores 'Sin información' (cualquier variante de escritura)."""
    return serie.map(clave_categoria).eq("sininformacion")


def normalizar_texto(serie: pd.Series) -> pd.Series:
    """Quita espacios sobrantes y pone Formato Titulo."""
    return serie.str.strip().str.replace(r"\s+", " ", regex=True).str.title()


def unificar_categorias(serie: pd.Series) -> pd.Series:
    """Agrupa variantes (mayusculas, tildes, espacios, signos) y usa la escritura mas comun."""
    s = serie.str.strip()
    clave = s.dropna().map(clave_categoria)
    oficial = s.dropna().groupby(clave).agg(lambda v: v.value_counts().index[0])
    return s.map(lambda x: oficial[clave_categoria(x)] if isinstance(x, str) else x)


def unificar_por_codigo(nombres: pd.Series, codigos: pd.Series) -> pd.Series:
    """Un solo nombre por codigo (el mas frecuente). Mas fiable que comparar texto:
    'Itagui' e 'Itagüí' comparten el codigo 05360. Sin codigo, se deja el nombre tal cual."""
    validos = pd.DataFrame({"n": nombres, "c": codigos}).dropna()
    oficial = validos.groupby("c")["n"].agg(lambda v: v.value_counts().index[0])
    return codigos.map(oficial).fillna(nombres)


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


SIN_INFO = "Sin informacion"
COLUMNAS_CONSTANTES = ["circunstancia_del_hecho_detallada", "manera_de_muerte"]
EXPLOSIVO = {"agenteomecanismoexplosivo", "agentesymecanismoexplosivo", "mecanismooagenteexplosivo"}
GRUPOS_MENORES = ("(05 ", "(10 ", "(15 ")   # quinquenales que corresponden a menores de edad


def _mecanismo(x):
    if isinstance(x, str) and clave_categoria(x) in EXPLOSIVO:
        return "Agente o mecanismo explosivo"
    return x


def _edad_mayor_menor(x):
    if isinstance(x, str):
        if "mayor" in x.lower():
            return "Mayor de edad"
        if "menor" in x.lower():
            return "Menor de edad"
    return x


def limpiar_suicidios(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Silver de presuntos suicidios. No elimina registros: solo estandariza.

    La base no trae fecha exacta (solo anio, mes y dia de la semana) ni edad exacta
    (solo grupos), por eso no aplican parsear_fecha ni la validacion de rango de edad.
    """
    d = df.copy()

    # 1. Esquema estable: la API entrega 'a_o_del_hecho' y el CSV descargado 'ano_del_hecho'
    d = d.rename(columns={"a_o_del_hecho": "ano_del_hecho"})

    # 2. Columnas constantes (no aportan informacion)
    d = d.drop(columns=[c for c in COLUMNAS_CONSTANTES if c in d.columns])

    # 3. Codigos DANE (texto con cero a la izquierda: departamento 2 digitos, municipio 5)
    for col, ancho in [("codigo_dane_departamento", 2), ("codigo_dane_municipio", 5)]:
        if col in d.columns:
            d[col] = solo_digitos(d[col]).str.zfill(ancho).where(d[col].notna())

    # 4. Variantes de escritura en columnas categoricas (no en nombres geograficos)
    geograficas = {"municipio_del_hecho_dane", "departamento_del_hecho_dane"}
    for col in d.columns:
        if col != "id" and col not in geograficas and d[col].dtype != "Int64" and d[col].nunique() <= 100:
            d[col] = unificar_categorias(d[col])

    # 5. Nombres geograficos: un nombre por codigo DANE (arregla Bogota, Quindio, Itagui, etc.)
    d["departamento_del_hecho_dane"] = unificar_por_codigo(
        d["departamento_del_hecho_dane"], d["codigo_dane_departamento"])
    d["municipio_del_hecho_dane"] = unificar_por_codigo(
        d["municipio_del_hecho_dane"], d["codigo_dane_municipio"])

    # 6. Redacciones distintas de una misma categoria
    d["mecanismo_causal_de_la_lesion_fatal"] = d["mecanismo_causal_de_la_lesion_fatal"].map(_mecanismo)
    d["grupo_mayor_menor_de_edad"] = d["grupo_mayor_menor_de_edad"].map(_edad_mayor_menor)

    # 7. Departamento sin dato (codigo 999) -> el codigo queda como 'Sin informacion'
    sin_depto = d["codigo_dane_departamento"].eq("999") | d["departamento_del_hecho_dane"].map(
        lambda x: isinstance(x, str) and clave_categoria(x) == "sininformacion")
    d.loc[sin_depto, "codigo_dane_departamento"] = SIN_INFO

    # 8. Tipos y rango: id y anio enteros; anio fuera del periodo del estudio -> nulo
    p = config["period"]
    d["id"] = pd.to_numeric(d["id"], errors="coerce").astype("Int64")
    anio = pd.to_numeric(d["ano_del_hecho"], errors="coerce")
    fuera = anio.notna() & ~anio.between(p["start_year"], p["end_year"])
    if fuera.any():
        logger.warning(f"suicidios: {fuera.sum()} registros con anio fuera de "
                       f"{p['start_year']}-{p['end_year']} pasan a nulo")
    d["ano_del_hecho"] = fuera_de_rango_a_nulo(anio, p["start_year"], p["end_year"]).astype("Int64")

    # 9. Coherencia entre grupo quinquenal y mayor/menor de edad (solo se avisa, no se corrige)
    menor_por_grupo = d["grupo_de_edad_quinquenal"].fillna("").str.startswith(GRUPOS_MENORES)
    incoherentes = (menor_por_grupo != d["grupo_mayor_menor_de_edad"].eq("Menor de edad")) \
        & d["grupo_de_edad_quinquenal"].notna() & d["grupo_mayor_menor_de_edad"].isin(
            ["Mayor de edad", "Menor de edad"])
    if incoherentes.any():
        logger.warning(f"suicidios: {incoherentes.sum()} registros con grupo quinquenal "
                       f"incoherente con mayor/menor de edad")

    return d


def _limpiar_poblacion(df: pd.DataFrame, col_poblacion: str) -> pd.DataFrame:
    """Silver comun de las proyecciones DANE: una fila por departamento y anio, con
    poblacion total entera. Mismo esquema en ambos archivos para poder apilarlos."""
    d = df.copy()

    # 1. Quitar notas al pie (los codigos de departamento validos son de 2 digitos)
    d = d[d["dp"].str.fullmatch(r"\d{2}", na=False)]

    # 2. Solo el total del departamento (sin cabecera ni resto rural)
    d = d[d["area_geografica"].str.lower().eq("total")]

    # 3. Poblacion como entero (viene como texto con separador de miles)
    d["poblacion"] = pd.to_numeric(d[col_poblacion].str.replace(",", "", regex=False), errors="coerce")
    sin_dato = d["poblacion"].isna()
    if sin_dato.any():
        logger.warning(f"poblacion: {sin_dato.sum()} filas sin poblacion valida eliminadas")
        d = d[~sin_dato]
    d["poblacion"] = d["poblacion"].astype("Int64")

    # 4. Esquema final
    d = d.rename(columns={"dp": "codigo_dane", "dpnom": "departamento", "ano": "ano"})
    d["ano"] = pd.to_numeric(d["ano"], errors="coerce").astype("Int64")
    d["departamento"] = unificar_por_codigo(d["departamento"], d["codigo_dane"])
    d = d[["codigo_dane", "departamento", "ano", "poblacion"]]

    if d.duplicated(["codigo_dane", "ano"]).any():
        logger.warning("poblacion: hay mas de una fila por departamento y anio")
    return d.reset_index(drop=True)


def limpiar_poblacion_2005_2050(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    cols_pob = [c for c in df.columns if "poblacion" in c.lower() or "total" in c.lower()]
    return _limpiar_poblacion(df, cols_pob[0])

PATRON_SEXO_EDAD = r"^(hombres|mujeres)_(\d+)(?:_anos?)?(?:_y_mas)?$"


def limpiar_poblacion_sexo_edad(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Silver de las proyecciones departamentales por sexo y edad simple (DANE).

    Formato largo: una fila por departamento, anio, sexo y edad simple (0 a 100 y mas),
    solo area 'Total'. Sirve de denominador para tasas por sexo y grupo de edad.
    Los dos archivos (2005-2017 y 2018-2050) quedan con el mismo esquema.
    """
    d = df.copy()
    d = d[d["dp"].str.fullmatch(r"\d{2}", na=False) & d["area_geografica"].str.lower().eq("total")]
    largo = _a_formato_largo(d, {"dp": "codigo_dane", "dpnom": "departamento"})
    return _revisar_sexo_edad(largo, ["codigo_dane", "ano", "sexo", "edad"], "departamental")


def _a_formato_largo(d: pd.DataFrame, ids: dict) -> pd.DataFrame:
    """Columnas 'hombres_0', 'mujeres_1_ano', ... -> filas (sexo, edad, poblacion).
    En el archivo municipal 2005-2017 la ultima edad es '85 y mas' (edad 85 = 85 o mas)."""
    columnas = [c for c in d.columns if pd.Series([c]).str.fullmatch(PATRON_SEXO_EDAD).iloc[0]]
    largo = d.melt(id_vars=list(ids) + ["ano"], value_vars=columnas, var_name="columna", value_name="poblacion")
    partes = largo["columna"].str.extract(PATRON_SEXO_EDAD)
    largo["sexo"] = partes[0].map({"hombres": "Hombre", "mujeres": "Mujer"})
    largo["edad"] = pd.to_numeric(partes[1]).astype("Int64")
    largo["poblacion"] = pd.to_numeric(largo["poblacion"].str.replace(",", "", regex=False),
                                       errors="coerce").astype("Int64")
    largo["ano"] = pd.to_numeric(largo["ano"], errors="coerce").astype("Int64")
    largo = largo.rename(columns=ids)
    return largo[list(ids.values()) + ["ano", "sexo", "edad", "poblacion"]]


def _revisar_sexo_edad(largo: pd.DataFrame, llave: list, nivel: str) -> pd.DataFrame:
    if largo["poblacion"].isna().any():
        logger.warning(f"poblacion {nivel} sexo/edad: {largo['poblacion'].isna().sum()} celdas sin valor")
    if largo.duplicated(llave).any():
        logger.warning(f"poblacion {nivel} sexo/edad: filas repetidas por {', '.join(llave)}")
    return largo.reset_index(drop=True)


def limpiar_poblacion_municipal_sexo_edad(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Silver de las proyecciones municipales por sexo y edad simple (DANE), area 'Total'.

    Solo se conservan los municipios del departamento foco (Valle del Cauca): el archivo
    nacional tiene 1.123 municipios x 300 columnas y en formato largo pasaria de 5 millones
    de filas. Para ampliar el alcance basta cambiar scope.departamento_foco en config.yaml.
    """
    foco = config["scope"]["departamento_foco"]
    d = df[df["mpio"].str.fullmatch(r"\d{5}", na=False) & df["area_geografica"].str.lower().eq("total")
           & df["mpio"].str.startswith(foco)].copy()
    largo = _a_formato_largo(d, {"mpio": "codigo_municipio", "dpmp": "municipio"})
    logger.info(f"poblacion municipal sexo/edad: {largo['codigo_municipio'].nunique()} municipios del depto {foco}")
    return _revisar_sexo_edad(largo, ["codigo_municipio", "ano", "sexo", "edad"], "municipal")


def limpiar_poblacion_municipal(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Silver de las proyecciones municipales (DANE): una fila por municipio y anio, area 'Total'.
    El codigo de municipio (5 digitos) esta en la columna MPIO en ambos archivos."""
    d = df.copy()
    d = d[d["mpio"].str.fullmatch(r"\d{5}", na=False) & d["area_geografica"].str.lower().eq("total")]
    col_pob = "poblacion" if "poblacion" in d.columns else "total"
    d["poblacion"] = pd.to_numeric(d[col_pob].str.replace(",", "", regex=False), errors="coerce").astype("Int64")
    d["ano"] = pd.to_numeric(d["ano"], errors="coerce").astype("Int64")
    d = d.rename(columns={"mpio": "codigo_municipio", "dpmp": "municipio", "dp": "codigo_dane"})
    d = d[["codigo_dane", "codigo_municipio", "municipio", "ano", "poblacion"]]
    if d.duplicated(["codigo_municipio", "ano"]).any():
        logger.warning("poblacion municipal: mas de una fila por municipio y anio")
    return d.reset_index(drop=True)


LIMPIADORES = {
    "suicidios": limpiar_suicidios,
    "poblacion_2005_2050": limpiar_poblacion_2005_2050,
    "poblacion_sexo_edad_2005_2017": limpiar_poblacion_sexo_edad,
    "poblacion_sexo_edad_2018_2050": limpiar_poblacion_sexo_edad,
    "poblacion_municipal_2005_2017": limpiar_poblacion_municipal,
    "poblacion_municipal_2018_2042": limpiar_poblacion_municipal,
    "poblacion_municipal_sexo_edad_2005_2017": limpiar_poblacion_municipal_sexo_edad,
    "poblacion_municipal_sexo_edad_2018_2042": limpiar_poblacion_municipal_sexo_edad,
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
