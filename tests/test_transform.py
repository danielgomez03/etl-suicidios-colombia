import pandas as pd

from src.transform.clean_data import parsear_fecha, a_numero, unificar_categorias, quitar_tildes

FORMATOS = ["%Y-%m-%d", "%d/%m/%Y", "%m-%d-%Y", "%d-%b-%Y", "%B %d, %Y"]


def test_parsear_fecha():
    esperado = pd.Timestamp("2001-10-25")
    for texto in ["2001-10-25", "25/10/2001", "10-25-2001", "25-Oct-2001", "October 25, 2001"]:
        assert parsear_fecha(texto, FORMATOS) == esperado
    assert pd.isna(parsear_fecha("31/02/2002", FORMATOS))


def test_a_numero():
    r = a_numero(pd.Series(["3,75", "20 creditos", "abc"]))
    assert r[0] == 3.75 and r[1] == 20 and pd.isna(r[2])


def test_unificar_categorias():
    s = pd.Series(["Psicología", "Psicología", " PSICOLOGIA ", "psicología"])
    assert unificar_categorias(s).nunique() == 1


def test_quitar_tildes():
    assert quitar_tildes("Ingeniería") == "Ingenieria"
