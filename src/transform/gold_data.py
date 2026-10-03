"""Capa gold: tablas listas para el analisis, el tablero y R.

Tablas que produce (ver main.py):
- dim_departamento, dim_municipio, dim_grupo_edad: tablas maestras y llave de cruce con el DANE
- gold_suicidios: detalle por caso, minimizado (sin variables sensibles que no se usan). Acceso restringido.
- gold_tasa_mortalidad: tasa de mortalidad por presunto suicidio por 100.000 hab.
  (nacional, departamental y municipios foco; por anio, quinquenio y decenio; por sexo y grupo de edad)
- gold_agregado_tablero: conteos agregados con supresion de celdas pequenas (privacidad)
- gold_kpi_calidad: KR y KPI medidos en cada ejecucion
"""
from itertools import product
from typing import Optional

import pandas as pd

from src.transform.clean_data import clave_categoria, es_sin_info
from src.utils import get_logger, project_path

logger = get_logger(__name__)

SIN_INFO = "Sin informacion"

# ---------- Clasificacion de mecanismo (anexo del documento) ----------
VIOLENTO = {
    "generadoresdeasfixia", "proyectildearmadefuego", "contundente",
    "cortopunzante", "cortante", "cortocontundente", "punzante",
    "termico", "electrico", "agenteomecanismoexplosivo",
    "agentesymecanismoexplosivo", "mecanismooagenteexplosivo",
}
NO_VIOLENTO = {"toxico", "caustico"}

# ---------- Agrupacion de razones: 9 categorias principales del EDA ----------
# Las llaves son la forma normalizada (clave_categoria) de como vienen escritas en la base.
RAZONES_PRINCIPALES = {
    "conflictoconparejaoexpareja": "Conflicto de pareja o expareja",
    "enfermedadfisicaomental": "Enfermedad fisica o mental",
    "enfermedadmental": "Enfermedad mental",
    "desamor": "Desamor",
    "economicas": "Economicas",
    "enfermedadfisica": "Enfermedad fisica",
    "abusodesustanciasyalcohol": "Abuso de sustancias y alcohol",
    "abusodesustanciayalcohol": "Abuso de sustancias y alcohol",
    "muertedeunfamiliaroamigo": "Muerte de un familiar o amigo",
    "juridicas": "Juridicas",
}

# ---------- Escolaridad: la base mezcla dos clasificaciones segun el anio ----------
ESCOLARIDAD = {
    "sinescolaridad": "Sin escolaridad", "ninguna": "Sin escolaridad",
    "educacioninicialyeducacionpreescolar": "Preescolar", "preescolar": "Preescolar",
    "educacionbasicaprimaria": "Basica primaria", "basicaprimaria": "Basica primaria",
    "educacionbasicasecundariaosecundariabaja": "Basica secundaria", "basicasecundaria": "Basica secundaria",
    "educacionmediaosecundariaalta": "Media",
    "educaciontecnicaprofesionalytecnologica": "Tecnica o tecnologica", "tecnologica": "Tecnica o tecnologica",
    "universitario": "Universitaria", "profesional": "Universitaria",
    "especializacionmaestriaoequivalente": "Posgrado", "maestria": "Posgrado", "doctoradooequivalente": "Posgrado",
}

# Variables sensibles que no se usan en el analisis: se excluyen de gold (minimizacion)
COLUMNAS_EXCLUIDAS = [
    "orientacion_sexual", "identidad_de_genero", "transgenero", "pueblo_indigena", "ancestro_racial",
    "pertenencia_grupal", "pais_de_nacimiento", "localidad_del_hecho",
    "diagnostico_topografico_de_la_lesion_fatal", "rango_de_hora_del_hecho_x_3_horas",
]

# Variables que se publican agregadas en el tablero
VARIABLES_TABLERO = ["sexo_de_la_victima", "ciclo_vital", "grupo_de_edad_quinquenal", "tipo_mecanismo",
                     "razon_agrupada", "escolaridad_agrupada", "pertenencia_etnica", "estado_civil",
                     "zona_del_hecho"]


# ======================================================================
# Tablas maestras (llave de cruce con el DANE)
# ======================================================================

def construir_dim_grupo_edad(grupos: pd.Series) -> pd.DataFrame:
    """Grupo quinquenal de Medicina Legal -> rango de edades simples del DANE.
    '(15 a 17)' -> 15..17 ; '(80 y más)' -> 80..100 (el DANE agrupa '100 y más')."""
    etiquetas = sorted(set(grupos.dropna()))
    filas = []
    for g in etiquetas:
        nums = [int(x) for x in pd.Series([g]).str.findall(r"\d+").iloc[0]]
        edad_min = nums[0]
        edad_max = nums[1] if len(nums) > 1 else 100
        filas.append({"grupo_edad": g, "edad_min": edad_min, "edad_max": edad_max,
                      "menor_de_edad": edad_max < 18})
    dim = pd.DataFrame(filas).sort_values("edad_min").reset_index(drop=True)
    dim["orden"] = range(1, len(dim) + 1)
    return dim


def construir_dim_departamento(pob_dep: pd.DataFrame, ruta_regiones: str) -> pd.DataFrame:
    """Codigo DANE de departamento, nombre oficial (DANE) y region natural."""
    dim = pob_dep[["codigo_dane", "departamento"]].drop_duplicates("codigo_dane")
    regiones = pd.read_csv(project_path(ruta_regiones), dtype=str)
    dim = dim.merge(regiones, on="codigo_dane", how="left")
    if dim["region"].isna().any():
        logger.warning(f"Departamentos sin region: {dim.loc[dim['region'].isna(), 'departamento'].tolist()}")
    return dim.sort_values("codigo_dane").reset_index(drop=True)


def construir_dim_municipio(pob_mun: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Codigo DANE de municipio, nombre oficial, departamento y si es municipio foco del informe."""
    dim = (pob_mun.sort_values("ano", ascending=False)
           .drop_duplicates("codigo_municipio")[["codigo_municipio", "municipio", "codigo_dane"]])
    foco = config.get("scope", {}).get("municipios_foco", {})
    dim["municipio_foco"] = dim["codigo_municipio"].isin(foco)
    return dim.sort_values("codigo_municipio").reset_index(drop=True)


# ======================================================================
# Columnas derivadas de cada caso
# ======================================================================

def _clasificar_mecanismo(serie: pd.Series) -> pd.Series:
    """Clasifica mecanismo_causal en Violento / No violento / Por determinar."""
    clave = serie.map(clave_categoria)
    tipo = pd.Series("Por determinar", index=serie.index, dtype="string")
    tipo[clave.isin(VIOLENTO)] = "Violento"
    tipo[clave.isin(NO_VIOLENTO)] = "No violento"
    return tipo


def _agrupar_razon(serie: pd.Series) -> pd.Series:
    """Agrupa razon_del_suicidio en 9 categorias + Otras + Sin informacion."""
    clave = serie.map(clave_categoria)
    resultado = pd.Series("Otras", index=serie.index, dtype="string")
    resultado[es_sin_info(serie)] = SIN_INFO
    for k, v in RAZONES_PRINCIPALES.items():
        resultado[clave == k] = v
    return resultado


def _agrupar_escolaridad(serie: pd.Series) -> pd.Series:
    clave = serie.map(clave_categoria)
    resultado = clave.map(ESCOLARIDAD).astype("string")
    resultado[es_sin_info(serie)] = SIN_INFO
    return resultado.fillna("Otra")


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


def agregar_metricas(gold: pd.DataFrame, dim_departamento: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Columnas derivadas por caso y minimizacion de variables sensibles."""
    g = gold.copy()

    g["tipo_mecanismo"] = _clasificar_mecanismo(g["mecanismo_causal_de_la_lesion_fatal"])
    g["es_violento"] = g["tipo_mecanismo"].eq("Violento")
    g["razon_agrupada"] = _agrupar_razon(g["razon_del_suicidio"])
    g["escolaridad_agrupada"] = _agrupar_escolaridad(g["escolaridad"])
    g["es_mayor_edad"] = g["grupo_mayor_menor_de_edad"].eq("Mayor de edad")

    if dim_departamento is not None:
        g = g.merge(dim_departamento[["codigo_dane", "region"]], left_on="codigo_dane_departamento",
                    right_on="codigo_dane", how="left").drop(columns="codigo_dane")
        g["region"] = g["region"].fillna(SIN_INFO)

    excluidas = [c for c in COLUMNAS_EXCLUIDAS if c in g.columns]
    g = g.drop(columns=excluidas)
    logger.info(f"tipo_mecanismo: {g['tipo_mecanismo'].value_counts().to_dict()}")
    logger.info(f"razon_agrupada: {g['razon_agrupada'].value_counts().to_dict()}")
    logger.info(f"agregar_metricas: {len(g)} filas, {g.shape[1]} columnas ({len(excluidas)} sensibles excluidas)")
    return g


# ======================================================================
# Denominadores DANE y tasas de mortalidad por presunto suicidio
# ======================================================================

def _periodos(config: dict) -> list:
    """(etiqueta, tipo, anios): cada anio, dos quinquenios y el decenio completo."""
    ini, fin = config["period"]["start_year"], config["period"]["end_year"]
    anios = list(range(ini, fin + 1))
    periodos = [(str(a), "anual", [a]) for a in anios]
    mitad = ini + (len(anios) // 2)
    periodos.append((f"{ini}-{mitad - 1}", "quinquenio", list(range(ini, mitad))))
    periodos.append((f"{mitad}-{fin}", "quinquenio", list(range(mitad, fin + 1))))
    periodos.append((f"{ini}-{fin}", "decenio", anios))
    return periodos


def _con_totales(df: pd.DataFrame, dims: list, valor: str) -> pd.DataFrame:
    """Suma 'valor' agregando tambien 'Total' en cada combinacion de dims.
    Las filas con dim nula (p. ej. edades 0-4 sin grupo) solo cuentan cuando esa dim es 'Total'."""
    claves = [c for c in df.columns if c not in dims + [valor]]
    partes = []
    for totales in product([False, True], repeat=len(dims)):
        t = df.copy()
        for dim, es_total in zip(dims, totales):
            if es_total:
                t[dim] = "Total"
        partes.append(t.groupby(claves + dims, dropna=True)[valor].sum().reset_index())
    return pd.concat(partes, ignore_index=True)


def poblacion_por_sexo_grupo(pob_sexo_edad: pd.DataFrame, dim_grupo_edad: pd.DataFrame) -> pd.DataFrame:
    """Edades simples -> grupos quinquenales de Medicina Legal (codigo_dane, ano, sexo, grupo_edad)."""
    p = pob_sexo_edad.copy()
    p["grupo_edad"] = None
    for _, g in dim_grupo_edad.iterrows():
        p.loc[p["edad"].between(g["edad_min"], g["edad_max"]), "grupo_edad"] = g["grupo_edad"]
    return p.groupby(["codigo_dane", "ano", "sexo", "grupo_edad"], dropna=False)["poblacion"].sum().reset_index()


def _tasas_por_periodo(casos: pd.DataFrame, pob: pd.DataFrame, llaves: list, config: dict) -> pd.DataFrame:
    """Casos y poblacion por llaves + ano -> tasa por 100.000 hab. por periodo.
    La poblacion manda (merge por la izquierda): las combinaciones sin casos quedan con 0."""
    minimo = config["thresholds"]["tasa_min_casos_estable"]
    salida = []
    for etiqueta, tipo, anios in _periodos(config):
        p = pob[pob["ano"].isin(anios)].groupby(llaves)["poblacion"].sum()
        c = casos[casos["ano"].isin(anios)].groupby(llaves)["casos"].sum()
        t = pd.DataFrame({"poblacion": p}).join(c, how="left").fillna({"casos": 0}).reset_index()
        t["periodo"], t["tipo_periodo"], t["n_anios"] = etiqueta, tipo, len(anios)
        salida.append(t)
    t = pd.concat(salida, ignore_index=True)
    t["casos"] = t["casos"].astype(int)
    t["tasa_100k"] = (t["casos"] / t["poblacion"] * 100_000).round(2)
    t["estable"] = t["casos"] >= minimo
    return t


def construir_tasas(casos: pd.DataFrame, pob_dep: pd.DataFrame, pob_sexo_grupo: pd.DataFrame,
                    pob_mun: pd.DataFrame, dim_departamento: pd.DataFrame, dim_municipio: pd.DataFrame,
                    config: dict) -> pd.DataFrame:
    """gold_tasa_mortalidad en formato largo.

    - Nacional y departamental: por sexo (Total/Hombre/Mujer) y grupo de edad (Total/grupos).
      Denominador: proyecciones por sexo y edad simple; el total (Total/Total) usa la serie
      departamental oficial por area.
    - Municipios foco: solo total (el DANE municipal por sexo y edad no se incluye; con pocos
      casos la tasa por sexo seria inestable).
    """
    c = casos.rename(columns={"ano_del_hecho": "ano", "sexo_de_la_victima": "sexo",
                              "grupo_de_edad_quinquenal": "grupo_edad"})
    c = c.assign(casos=1)

    # --- denominadores con totales ---
    pob_sg = _con_totales(pob_sexo_grupo, ["sexo", "grupo_edad"], "poblacion")
    pob_sg = pob_sg[~((pob_sg["sexo"] == "Total") & (pob_sg["grupo_edad"] == "Total"))]
    pob_tt = pob_dep.assign(sexo="Total", grupo_edad="Total")[["codigo_dane", "ano", "sexo", "grupo_edad", "poblacion"]]
    pob_d = pd.concat([pob_sg, pob_tt], ignore_index=True)

    # --- casos con totales ---
    cas_d = _con_totales(c[["codigo_dane_departamento", "ano", "sexo", "grupo_edad", "casos"]]
                         .rename(columns={"codigo_dane_departamento": "codigo_dane"}),
                         ["sexo", "grupo_edad"], "casos")

    llaves = ["codigo", "sexo", "grupo_edad"]
    tablas = []

    # Nacional: todos los casos validos (incluye los de departamento 'Sin informacion')
    cas_n = cas_d.groupby(["ano", "sexo", "grupo_edad"])["casos"].sum().reset_index().assign(codigo="00")
    pob_n = pob_d.groupby(["ano", "sexo", "grupo_edad"])["poblacion"].sum().reset_index().assign(codigo="00")
    tablas.append(_tasas_por_periodo(cas_n, pob_n, llaves, config)
                  .assign(nivel="Nacional", territorio="Colombia", region="Nacional"))

    # Departamental
    cas_dd = cas_d[cas_d["codigo_dane"].ne(SIN_INFO)].rename(columns={"codigo_dane": "codigo"})
    pob_dd = pob_d.rename(columns={"codigo_dane": "codigo"})
    t = _tasas_por_periodo(cas_dd, pob_dd, llaves, config).assign(nivel="Departamento")
    t = t.merge(dim_departamento.rename(columns={"codigo_dane": "codigo", "departamento": "territorio"}),
                on="codigo", how="left")
    tablas.append(t)

    # Municipios foco
    foco = dim_municipio[dim_municipio["municipio_foco"]]
    cas_m = (c[c["codigo_dane_municipio"].isin(foco["codigo_municipio"])]
             .groupby(["codigo_dane_municipio", "ano"])["casos"].sum().reset_index()
             .rename(columns={"codigo_dane_municipio": "codigo"}).assign(sexo="Total", grupo_edad="Total"))
    pob_m = (pob_mun[pob_mun["codigo_municipio"].isin(foco["codigo_municipio"])]
             .rename(columns={"codigo_municipio": "codigo"}).assign(sexo="Total", grupo_edad="Total"))
    t = _tasas_por_periodo(cas_m, pob_m[["codigo", "ano", "sexo", "grupo_edad", "poblacion"]], llaves, config)
    t = t.assign(nivel="Municipio").merge(
        foco.rename(columns={"codigo_municipio": "codigo", "municipio": "territorio"})[["codigo", "territorio"]],
        on="codigo", how="left")
    t["region"] = dim_departamento.set_index("codigo_dane").loc[config["scope"]["departamento_foco"], "region"]
    tablas.append(t)

    tasas = pd.concat(tablas, ignore_index=True)
    columnas = ["nivel", "codigo", "territorio", "region", "periodo", "tipo_periodo", "n_anios",
                "sexo", "grupo_edad", "casos", "poblacion", "tasa_100k", "estable"]
    tasas = tasas[columnas].sort_values(["nivel", "codigo", "tipo_periodo", "periodo", "sexo", "grupo_edad"])
    logger.info(f"gold_tasa_mortalidad: {len(tasas)} filas "
                f"({tasas.groupby('nivel').size().to_dict()})")
    return tasas.reset_index(drop=True)


# ======================================================================
# Tablero: agregados con supresion de celdas pequenas
# ======================================================================

def construir_agregado_tablero(casos: pd.DataFrame, dim_departamento: pd.DataFrame,
                               dim_municipio: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Conteos por territorio, periodo, variable y categoria. Las celdas con 1 a k-1 casos
    se suprimen (casos = nulo, suprimido = True). Nivel municipal: solo municipios del Valle."""
    k = config["thresholds"]["privacidad_min_casos"]
    foco_dep = config["scope"]["departamento_foco"]
    ini, fin = config["period"]["start_year"], config["period"]["end_year"]

    base = casos.copy()
    base["ano"] = base["ano_del_hecho"].astype(int)
    base["todos"] = "Total"
    niveles = [
        ("Nacional", base.assign(codigo="00", territorio="Colombia")),
        ("Departamento", base[base["codigo_dane_departamento"].ne(SIN_INFO)]
            .assign(codigo=lambda x: x["codigo_dane_departamento"])
            .merge(dim_departamento[["codigo_dane", "departamento"]], left_on="codigo", right_on="codigo_dane")
            .rename(columns={"departamento": "territorio"})),
        ("Municipio", base[base["codigo_dane_municipio"].str[:2].eq(foco_dep)]
            .assign(codigo=lambda x: x["codigo_dane_municipio"])
            .merge(dim_municipio[["codigo_municipio", "municipio"]], left_on="codigo", right_on="codigo_municipio")
            .rename(columns={"municipio": "territorio"})),
    ]

    salida = []
    for nivel, df in niveles:
        for variable in ["todos"] + VARIABLES_TABLERO:
            for periodo, filtro in [(str(a), df["ano"].eq(a)) for a in range(ini, fin + 1)] + \
                                   [(f"{ini}-{fin}", df["ano"].between(ini, fin))]:
                conteo = (df[filtro].groupby(["codigo", "territorio", variable]).size()
                          .rename("casos").reset_index().rename(columns={variable: "categoria"}))
                conteo["nivel"], conteo["periodo"] = nivel, periodo
                conteo["variable"] = "total" if variable == "todos" else variable
                salida.append(conteo)
    t = pd.concat(salida, ignore_index=True)
    t["suprimido"] = t["casos"].lt(k)
    t["casos"] = t["casos"].where(~t["suprimido"]).astype("Int64")
    t = t[["nivel", "codigo", "territorio", "periodo", "variable", "categoria", "casos", "suprimido"]]
    logger.info(f"gold_agregado_tablero: {len(t)} celdas, {int(t['suprimido'].sum())} suprimidas (< {k} casos)")
    return t.reset_index(drop=True)


# ======================================================================
# KR y KPI de calidad
# ======================================================================

def _semaforo(valor: float, verde: float, amarillo: float) -> str:
    return "Verde" if valor >= verde else ("Amarillo" if valor >= amarillo else "Rojo")


def _variantes_residuales(df: pd.DataFrame, columnas: list) -> int:
    """Grupos de valores que son la misma categoria escrita distinto (debe ser 0 en silver)."""
    total = 0
    for col in columnas:
        valores = pd.Series(df[col].dropna().unique())
        total += int((valores.groupby(valores.map(clave_categoria)).size() > 1).sum())
    return total


def construir_kpis(leidos: int, validos: pd.DataFrame, rechazados: pd.DataFrame, resumen_reglas: pd.DataFrame,
                   detalle_fallas: pd.DataFrame, silver: pd.DataFrame, gold: pd.DataFrame,
                   tasas: pd.DataFrame, chequeo_denominador: float, config: dict) -> pd.DataFrame:
    """Una fila por indicador medido en esta ejecucion."""
    u = config["thresholds"]
    filas = []

    def fila(indicador, dimension, valor, unidad, meta, estado, detalle="", **extra):
        filas.append({"indicador": indicador, "dimension": dimension, "valor": valor, "unidad": unidad,
                      "meta": meta, "estado": estado, "detalle": detalle, **extra})

    # ---- KR1: carga y transformacion ----
    n_val, n_rech = len(validos), len(rechazados)
    perdidos = leidos - n_val - n_rech
    fila("KR1", "Integridad: leidos = validos + rechazados", perdidos, "registros sin explicar", "= 0",
         "Cumple" if perdidos == 0 else "No cumple", f"leidos={leidos}, validos={n_val}, rechazados={n_rech}")
    pct_val = round(n_val / leidos * 100, 3)
    fila("KR1", "Registros validos cargados a gold", pct_val, "%", f">= {u['kr1_pct_validos_min']}",
         "Cumple" if pct_val >= u["kr1_pct_validos_min"] else "No cumple")
    documentados = 100.0 if n_rech == 0 else round(rechazados["motivo_rechazo"].notna().mean() * 100, 1)
    fila("KR1", "Rechazados con motivo documentado", documentados, "%", "= 100",
         "Cumple" if documentados == 100 else "No cumple", f"{n_rech} rechazados")

    # ---- KR2: homologacion ----
    categoricas = [c for c in gold.columns if c != "id" and gold[c].nunique() <= 100
                   and (pd.api.types.is_string_dtype(gold[c]) or gold[c].dtype == object)]
    residuales = _variantes_residuales(gold, categoricas)
    fila("KR2", "Variantes de escritura residuales en gold", residuales, "grupos", "= 0",
         "Cumple" if residuales == 0 else "No cumple", f"{len(categoricas)} variables categoricas revisadas")
    cruza_dep = validos["codigo_dane_departamento"].ne(SIN_INFO)
    pct_dep = round(cruza_dep.mean() * 100, 3)
    fila("KR2", "Casos con departamento que cruza con poblacion DANE", pct_dep, "%",
         f">= {u['kr2_pct_codigos_cruzan_min']}", "Cumple" if pct_dep >= u["kr2_pct_codigos_cruzan_min"] else "No cumple",
         f"{int((~cruza_dep).sum())} casos sin departamento informado")
    falla_q1 = detalle_fallas[detalle_fallas["regla"].eq("Q1_municipio_cruza_dane")]["id"]
    pct_mun = round((~validos["id"].astype("string").isin(falla_q1)).mean() * 100, 3)
    fila("KR2", "Casos con municipio que cruza con poblacion DANE", pct_mun, "%",
         f">= {u['kr2_pct_codigos_cruzan_min']}", "Cumple" if pct_mun >= u["kr2_pct_codigos_cruzan_min"] else "No cumple")
    fila("KR2", "Diferencia maxima entre poblacion por sexo/edad y total departamental",
         round(chequeo_denominador, 4), "%", "< 0.1", "Cumple" if chequeo_denominador < 0.1 else "No cumple",
         "consistencia de los dos archivos DANE usados como denominador")

    # ---- KPI 1: consistencia ----
    falla_alguna = detalle_fallas["id"].nunique()
    pct_cons = round((leidos - falla_alguna) / leidos * 100, 3)
    fila("KPI1", "Registros que pasan todas las reglas", pct_cons, "%", f">= {u['kpi1_consistencia_meta']}",
         "Verde" if pct_cons >= u["kpi1_consistencia_meta"] else
         ("Amarillo" if pct_cons >= u["kpi1_consistencia_alerta"] else "Rojo"),
         f"{falla_alguna} registros con al menos una falla")
    for _, r in resumen_reglas.iterrows():
        fila("KPI1", f"{r['regla']} ({r['tipo']})", r["pct_cumple"], "%", "", "", r["descripcion"],
             registros_fallan=r["registros_fallan"])

    # ---- KPI 2: tasa de mortalidad por presunto suicidio (resumen) ----
    dec = tasas[(tasas["tipo_periodo"] == "decenio") & (tasas["sexo"] == "Total") & (tasas["grupo_edad"] == "Total")]
    foco = config["scope"]["departamento_foco"]
    for _, r in dec[dec["nivel"].eq("Nacional") | dec["codigo"].eq(foco) | dec["nivel"].eq("Municipio")].iterrows():
        fila("KPI2", f"Tasa {r['periodo']} - {r['territorio']}", r["tasa_100k"], "por 100.000 hab.", "", "",
             f"{r['casos']} casos; {'estable' if r['estable'] else 'inestable (< 20 casos)'}")

    # ---- KPI 3: completitud de variables criticas ----
    criticas = ["razon_del_suicidio", "escolaridad", "mecanismo_causal_de_la_lesion_fatal", "estado_civil",
                "pertenencia_etnica", "zona_del_hecho", "escenario_del_hecho", "codigo_dane_departamento",
                "codigo_dane_municipio"]
    errores_por_var = {"codigo_dane_municipio": set(falla_q1)}
    for col in criticas:
        s = silver[col]
        n = len(s)
        nulo = s.isna()
        sin_info = es_sin_info(s) | s.map(clave_categoria).eq("pordeterminar")
        error = silver["id"].astype("string").isin(errores_por_var.get(col, set())) & ~nulo & ~sin_info
        completo = round((~nulo & ~sin_info & ~error).mean() * 100, 2)
        fila("KPI3", col, completo, "% informado", f">= {u['kpi3_completitud_verde']} (verde)",
             _semaforo(completo, u["kpi3_completitud_verde"], u["kpi3_completitud_amarillo"]),
             pct_nulo=round(nulo.mean() * 100, 2), pct_sin_info=round(sin_info.mean() * 100, 2),
             pct_error=round(error.mean() * 100, 2))

    kpis = pd.DataFrame(filas)
    logger.info("KPIs: " + "; ".join(f"{r.indicador} {r.dimension[:40]}={r.valor} {r.estado}"
                                     for r in kpis[kpis["indicador"].isin(["KR1", "KR2"])].itertuples()))
    return kpis
