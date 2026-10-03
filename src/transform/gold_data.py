import pandas as pd
from typing import Optional

from src.utils import get_logger, load_config, project_path
from src.transform.clean_data import clave_categoria

logger = get_logger(__name__)


# ---------- Clasificación de mecanismo (del anexo del documento) ----------
VIOLENTO = {
    "generadoresdeasfixia", "proyectildearmadefuego", "contundente",
    "cortopunzante", "cortante", "cortocontundente", "punzante",
    "termico", "electrico", "agenteomecanismoexplosivo",
    "agentesymecanismoexplosivo", "mecanismooagenteexplosivo"
}
NO_VIOLENTO = {"toxico", "caustico"}


# ---------- Agrupación de razones (9 categorías principales del EDA) ----------
RAZONES_PRINCIPALES = {
    "conflictodeparejaexpareja": "Conflicto de pareja",
    "enfermedadfisicaymental": "Enfermedad fisica o mental",
    "enfermedadmental": "Enfermedad mental",
    "desamor": "Desamor",
    "economicas": "Economicas",
    "enfermedadfisica": "Enfermedad fisica",
    "abusodesustancias": "Abuso de sustancias",
    "muertefamiliaramigo": "Muerte familiar o amigo",
    "juridicas": "Juridicas",
}


def _clasificar_mecanismo(serie: pd.Series) -> pd.Series:
    """Clasifica mecanismo_causal en Violento / No violento / Por determinar."""
    clave = serie.map(clave_categoria)
    tipo = pd.Series("Por determinar", index=serie.index, dtype="string")
    tipo[clave.isin(VIOLENTO)] = "Violento"
    tipo[clave.isin(NO_VIOLENTO)] = "No violento"
    return tipo


def _agrupar_razon(serie: pd.Series) -> pd.Series:
    """Agrupa razon_del_suicidio en 9 categorías + Otras + Sin información."""
    from src.transform.clean_data import es_sin_info, clave_categoria as _clave

    clave = serie.map(_clave)
    resultado = pd.Series("Otras", index=serie.index, dtype="string")
    # Sin información se conserva
    resultado[es_sin_info(serie)] = "Sin informacion"
    # Mapear las 9 principales
    for k, v in RAZONES_PRINCIPALES.items():
        resultado[clave == k] = v
    return resultado


def _cargar_poblacion_silver() -> pd.DataFrame:
    """Carga y apila las dos tablas silver de población, agrega por depto/año."""
    config = load_config()
    silver_dir = project_path(config["paths"]["silver_dir"])

    # Cargar ambos archivos de población (si existen)
    poblacion_dfs = []
    for nombre in ["poblacion_2005_2050"]:
        ruta = silver_dir / f"{nombre}_clean.csv"
        if ruta.exists():
            df = pd.read_csv(ruta, dtype=str)
            poblacion_dfs.append(df)
        else:
            logger.warning(f"Archivo de población no encontrado: {ruta}")

    if not poblacion_dfs:
        logger.warning("No se encontraron archivos de población en silver")
        return pd.DataFrame(columns=["codigo_dane", "ano", "poblacion"])

    pop = pd.concat(poblacion_dfs, ignore_index=True)

    # Asegurar tipos
    pop["poblacion"] = pd.to_numeric(pop["poblacion"], errors="coerce").astype("Int64")
    pop["ano"] = pd.to_numeric(pop["ano"], errors="coerce").astype("Int64")
    pop["codigo_dane"] = pop["codigo_dane"].astype("string").str.zfill(2)

    # Agregar por departamento y año (suma de áreas = total departamental)
    pop_agg = pop.groupby(["codigo_dane", "ano"], as_index=False)["poblacion"].sum()
    logger.info(f"Población agregada: {len(pop_agg)} combinaciones depto-año")
    return pop_agg


def integrar_fuentes(dfs: dict, on: Optional[str], how: str = "left") -> pd.DataFrame:
    """Une las tablas silver en orden. Con una sola fuente la devuelve tal cual."""
    nombres = list(dfs)
    gold = dfs[nombres[0]]
    for nombre in nombres[1:]:
        antes = len(gold)
        gold = gold.merge(dfs[nombre], on=on, how=how, suffixes=("", f"_{nombre}"))
        if how == "left" and len(gold) > antes:
            logger.warning(f"El merge con {nombre} multiplico filas: {antes} -> {len(gold)}. "
                           f"Revisa duplicados en la llave '{on}'.")
    logger.info(f"integrar_fuentes: {len(gold)} filas, {gold.shape[1]} columnas")
    return gold


def agregar_metricas(gold: pd.DataFrame) -> pd.DataFrame:
    """Añade columnas derivadas / KPIs de negocio a la capa gold."""
    g = gold.copy()

    # 1. Tipo de mecanismo (Violento / No violento / Por determinar)
    if "mecanismo_causal_de_la_lesion_fatal" in g.columns:
        g["tipo_mecanismo"] = _clasificar_mecanismo(g["mecanismo_causal_de_la_lesion_fatal"])
        g["es_violento"] = g["tipo_mecanismo"].eq("Violento")
        logger.info(f"tipo_mecanismo: {g['tipo_mecanismo'].value_counts().to_dict()}")

    # 2. Razón agrupada (9 principales + Otras + Sin información)
    if "razon_del_suicidio" in g.columns:
        g["razon_agrupada"] = _agrupar_razon(g["razon_del_suicidio"])
        logger.info(f"razon_agrupada: {g['razon_agrupada'].value_counts().to_dict()}")

    # 3. Flag mayor de edad
    if "grupo_mayor_menor_de_edad" in g.columns:
        g["es_mayor_edad"] = g["grupo_mayor_menor_de_edad"].eq("Mayor de edad")

    # 4. Tasa por 100.000 habitantes (requiere población agregada por depto/año)
    if "codigo_dane_departamento" in g.columns and "ano_del_hecho" in g.columns:
        pop_agg = _cargar_poblacion_silver()
        if not pop_agg.empty:
            # Preparar llaves de merge
            g["codigo_dane_departamento"] = g["codigo_dane_departamento"].astype("string").str.zfill(2)
            g["ano_del_hecho"] = pd.to_numeric(g["ano_del_hecho"], errors="coerce").astype("Int64")

            # Contar casos por depto/año
            casos = g.groupby(["codigo_dane_departamento", "ano_del_hecho"]).size().reset_index(name="n_casos")

            # Merge con población
            casos = casos.merge(pop_agg, left_on=["codigo_dane_departamento", "ano_del_hecho"],
                                right_on=["codigo_dane", "ano"], how="left")

            # Calcular tasa
            casos["tasa_100k"] = (casos["n_casos"] / casos["poblacion"] * 100000).round(2)

            # Volver a mergear la tasa al gold original
            g = g.merge(
                casos[["codigo_dane_departamento", "ano_del_hecho", "tasa_100k"]],
                on=["codigo_dane_departamento", "ano_del_hecho"],
                how="left"
            )
            logger.info(f"Tasa 100k calculada: {casos['tasa_100k'].notna().sum()} de {len(casos)} combinaciones con población")

    logger.info(f"agregar_metricas: {len(g)} filas, {g.shape[1]} columnas")
    return g
