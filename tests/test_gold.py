"""Pruebas de la capa gold: reglas de negocio (sin datos) y cifras de control (con datos reales)."""
import pandas as pd
import pytest

from src.transform.gold_data import (_agrupar_razon, _clasificar_mecanismo, _con_totales,
                                     construir_dim_grupo_edad)
from src.utils import load_config, project_path

CONFIG = load_config()
GOLD = project_path(CONFIG["paths"]["gold_dir"])


# ---------- Reglas (no necesitan datos) ----------

def test_razon_agrupada_con_escritura_real():
    """Las 9 categorias principales se reconocen tal como vienen escritas en la base."""
    reales = pd.Series(["Conflicto con pareja o ex-pareja", "Enfermedad física o mental", "Enfermedad mental",
                        "Desamor", "Económicas", "Enfermedad física", "Abuso de sustancias y alcohol",
                        "Abuso de sustancia y alcohol", "Muerte de un familiar o amigo", "Jurídicas"])
    assert not _agrupar_razon(reales).eq("Otras").any()
    assert _agrupar_razon(pd.Series(["Bullying", "Sin información"])).tolist() == ["Otras", "Sin informacion"]


def test_mecanismo_violento_no_violento():
    s = pd.Series(["Generadores de asfixia", "Tóxico", "Caústico", "Corto punzante", "Por determinar"])
    assert _clasificar_mecanismo(s).tolist() == ["Violento", "No violento", "No violento", "Violento",
                                                 "Por determinar"]


def test_dim_grupo_edad_rangos():
    dim = construir_dim_grupo_edad(pd.Series(["(15 a 17)", "(80 y más)", "(05 a 09)"])).set_index("grupo_edad")
    assert (dim.loc["(15 a 17)", "edad_min"], dim.loc["(15 a 17)", "edad_max"]) == (15, 17)
    assert dim.loc["(80 y más)", "edad_max"] == 100
    assert dim.loc["(15 a 17)", "menor_de_edad"] and not dim.loc["(80 y más)", "menor_de_edad"]


def test_totales_incluyen_edades_sin_grupo():
    """Las edades 0-4 (sin grupo) cuentan en el total pero no en ningun grupo."""
    df = pd.DataFrame({"codigo": ["1", "1"], "sexo": ["Hombre", "Hombre"], "grupo_edad": [None, "(05 a 09)"],
                       "poblacion": [10, 5]})
    t = _con_totales(df, ["sexo", "grupo_edad"], "poblacion").set_index(["sexo", "grupo_edad"])["poblacion"]
    assert t[("Hombre", "Total")] == 15 and t[("Hombre", "(05 a 09)")] == 5


# ---------- Cifras de control con datos reales (se saltan si no se ha corrido main.py) ----------

def _leer(nombre):
    ruta = GOLD / f"{nombre}.csv"
    if not ruta.exists():
        pytest.skip(f"{ruta.name} no existe: corre python main.py")
    return pd.read_csv(ruta, dtype={"codigo": str, "codigo_dane_departamento": str})


def test_kr1_integridad_de_la_carga():
    k = _leer("gold_kpi_calidad")
    assert k.loc[k["dimension"].str.startswith("Integridad"), "valor"].iloc[0] == 0


def test_tabla4_paradoja_de_genero():
    g = _leer("gold_suicidios")
    assert len(g) == 26558
    assert g["tipo_mecanismo"].value_counts().to_dict() == {"Violento": 22288, "No violento": 4235,
                                                           "Por determinar": 35}


def test_tasas_nacionales_del_documento():
    t = _leer("gold_tasa_mortalidad")
    n = t[(t["nivel"] == "Nacional") & (t["sexo"] == "Total") & (t["grupo_edad"] == "Total")].set_index("periodo")
    assert n.loc["2015", "tasa_100k"] == pytest.approx(4.47, abs=0.005)
    assert n.loc["2023", "tasa_100k"] == pytest.approx(6.13, abs=0.005)
    assert n.loc["2024", "tasa_100k"] == pytest.approx(5.73, abs=0.005)


def test_suma_por_sexo_igual_al_total():
    t = _leer("gold_tasa_mortalidad")
    n = t[(t["nivel"] == "Nacional") & (t["grupo_edad"] == "Total") & (t["periodo"] == "2015-2024")]
    casos = n.set_index("sexo")["casos"]
    assert casos["Hombre"] + casos["Mujer"] == casos["Total"]


def test_tablero_no_publica_celdas_pequenas():
    t = _leer("gold_agregado_tablero")
    k = CONFIG["thresholds"]["privacidad_min_casos"]
    assert not (t["casos"].dropna() < k).any()
    assert t.loc[t["suprimido"], "casos"].isna().all()


def test_gold_sin_variables_sensibles():
    g = _leer("gold_suicidios")
    assert not {"orientacion_sexual", "identidad_de_genero", "transgenero"} & set(g.columns)
