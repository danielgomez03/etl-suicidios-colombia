"""Validacion de la capa silver (KPI 1 - Tasa de consistencia y KR1).

Dos tipos de regla, siguiendo la retroalimentacion del Avance 1 (no "forzar" el 100 %):

- obligatoria: si falla, el registro se RECHAZA (no pasa a gold) y queda documentado
  en data/silver/rechazados_suicidios.csv con la regla y el valor que fallo.
- calidad: si falla, el registro SE CONSERVA y queda marcado como alerta. Son
  inconsistencias que no impiden usar el registro (por ejemplo, un municipio que no
  cruza con el DANE no impide contarlo a nivel departamental).

"Sin informacion" NO es un error: es una categoria valida (dato no reportado).
"""
import pandas as pd

from src.utils import get_logger

logger = get_logger(__name__)

SIN_INFO = "Sin informacion"
SEXOS_VALIDOS = {"Hombre", "Mujer"}

# Rango de edad de cada ciclo vital, para verificar coherencia con el grupo quinquenal
RANGO_CICLO = {
    "(06 a 11) Infancia": (6, 11),
    "(12 a 17) Adolescencia": (12, 17),
    "(18 a 28) Juventud": (18, 28),
    "(29 a 59) Adultez": (29, 59),
    "(Más de 60) Adulto Mayor": (60, 120),
}


def _regla(nombre, tipo, descripcion, falla: pd.Series, valores: pd.Series, ids: pd.Series):
    """Devuelve (resumen de la regla, detalle de los registros que fallan)."""
    resumen = {"regla": nombre, "tipo": tipo, "descripcion": descripcion,
               "registros_evaluados": len(falla), "registros_fallan": int(falla.sum())}
    detalle = pd.DataFrame({"id": ids[falla], "regla": nombre, "tipo": tipo,
                            "valor": valores[falla].astype(str)})
    return resumen, detalle


def validar_suicidios(df: pd.DataFrame, config: dict, dim_grupo_edad: pd.DataFrame,
                      codigos_departamento: set, codigos_municipio: set):
    """Aplica las reglas a silver de suicidios.

    Devuelve (validos, rechazados, resumen_reglas, detalle_fallas):
      - validos: registros que pasan las reglas obligatorias, con la columna 'n_alertas_calidad'
      - rechazados: registros que fallan alguna regla obligatoria, con el motivo
      - resumen_reglas: una fila por regla con cuantos registros la cumplen
      - detalle_fallas: una fila por registro y regla que falla (obligatoria o de calidad)
    """
    d = df.copy()
    ids = d["id"].astype("string")
    p = config["period"]
    resultados = []

    # ---------- Reglas obligatorias (rechazo) ----------
    resultados.append(_regla(
        "R1_id_unico", "obligatoria", "id presente y sin repetir",
        d["id"].isna() | d["id"].duplicated(keep=False), d["id"], ids))
    resultados.append(_regla(
        "R2_anio_periodo", "obligatoria", f"anio del hecho entre {p['start_year']} y {p['end_year']}",
        ~pd.to_numeric(d["ano_del_hecho"], errors="coerce").between(p["start_year"], p["end_year"]),
        d["ano_del_hecho"], ids))
    resultados.append(_regla(
        "R3_sexo_valido", "obligatoria", "sexo de la victima es Hombre o Mujer",
        ~d["sexo_de_la_victima"].isin(SEXOS_VALIDOS), d["sexo_de_la_victima"], ids))
    resultados.append(_regla(
        "R4_grupo_edad_catalogo", "obligatoria", "grupo de edad quinquenal existe en la tabla maestra",
        ~d["grupo_de_edad_quinquenal"].isin(dim_grupo_edad["grupo_edad"]), d["grupo_de_edad_quinquenal"], ids))
    depto = d["codigo_dane_departamento"]
    resultados.append(_regla(
        "R5_departamento_valido", "obligatoria",
        "codigo de departamento existe en el DANE (o es 'Sin informacion')",
        ~(depto.isin(codigos_departamento) | depto.eq(SIN_INFO)), depto, ids))
    resultados.append(_regla(
        "R6_mecanismo_presente", "obligatoria", "mecanismo causal registrado (incluye 'Por determinar')",
        d["mecanismo_causal_de_la_lesion_fatal"].isna(), d["mecanismo_causal_de_la_lesion_fatal"], ids))

    # ---------- Reglas de calidad (alerta, el registro se conserva) ----------
    mun = d["codigo_dane_municipio"].astype("string")
    resultados.append(_regla(
        "Q1_municipio_cruza_dane", "calidad", "codigo de municipio existe en las proyecciones municipales DANE",
        ~mun.isin(codigos_municipio), mun, ids))
    resultados.append(_regla(
        "Q2_municipio_en_departamento", "calidad", "los 2 primeros digitos del municipio son su departamento",
        mun.isin(codigos_municipio) & (mun.str[:2] != depto), mun + " / " + depto, ids))

    edades = d[["grupo_de_edad_quinquenal"]].merge(dim_grupo_edad, left_on="grupo_de_edad_quinquenal",
                                                   right_on="grupo_edad", how="left").set_index(d.index)
    menor_por_grupo = edades["edad_max"] < 18
    menor_declarado = d["grupo_mayor_menor_de_edad"].eq("Menor de edad")
    resultados.append(_regla(
        "Q3_coherencia_mayor_menor", "calidad", "grupo quinquenal coherente con mayor/menor de edad",
        edades["edad_max"].notna() & (menor_por_grupo != menor_declarado),
        d["grupo_de_edad_quinquenal"] + " / " + d["grupo_mayor_menor_de_edad"].astype(str), ids))

    ciclo = d["ciclo_vital"].map(RANGO_CICLO)
    ciclo_min = ciclo.map(lambda r: r[0] if isinstance(r, tuple) else None)
    ciclo_max = ciclo.map(lambda r: r[1] if isinstance(r, tuple) else None)
    solapa = (edades["edad_min"] <= ciclo_max) & (edades["edad_max"] >= ciclo_min)
    resultados.append(_regla(
        "Q4_coherencia_ciclo_vital", "calidad", "grupo quinquenal coherente con el ciclo vital",
        ciclo.notna() & edades["edad_max"].notna() & ~solapa,
        d["grupo_de_edad_quinquenal"] + " / " + d["ciclo_vital"].astype(str), ids))

    resumen = pd.DataFrame([r for r, _ in resultados])
    resumen["registros_cumplen"] = resumen["registros_evaluados"] - resumen["registros_fallan"]
    resumen["pct_cumple"] = (resumen["registros_cumplen"] / resumen["registros_evaluados"] * 100).round(3)
    detalle = pd.concat([det for _, det in resultados], ignore_index=True)

    ids_rechazo = set(detalle.loc[detalle["tipo"].eq("obligatoria"), "id"])
    rechazado = ids.isin(ids_rechazo)
    motivos = (detalle[detalle["tipo"].eq("obligatoria")].groupby("id")["regla"]
               .agg(", ".join).rename("motivo_rechazo"))
    rechazados = d[rechazado].copy()
    rechazados["motivo_rechazo"] = ids[rechazado].map(motivos).values

    alertas = detalle[detalle["tipo"].eq("calidad")].groupby("id").size()
    validos = d[~rechazado].copy()
    validos["n_alertas_calidad"] = ids[~rechazado].map(alertas).fillna(0).astype(int).values

    logger.info(f"validacion: {len(d)} leidos -> {len(validos)} validos, {len(rechazados)} rechazados, "
                f"{int((validos['n_alertas_calidad'] > 0).sum())} con alertas de calidad")
    return validos.reset_index(drop=True), rechazados.reset_index(drop=True), resumen, detalle
