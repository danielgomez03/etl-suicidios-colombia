import pandas as pd

from src.utils import get_logger

logger = get_logger(__name__)


def integrar_fuentes(dfs: dict, on: str | None, how: str = "left") -> pd.DataFrame:
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
    """Nuevas columnas / KPIs de negocio. Ejemplo: gold['total'] = gold['precio'] * gold['cantidad']."""
    return gold
