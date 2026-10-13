"""Pruebas de la base de datos: integridad referencial, restricciones y permisos.

Las pruebas contra la base solo corren cuando DATABASE_URL apunta a PostgreSQL (Neon, local
o el servicio de GitHub Actions) y ya se ejecuto `python main.py`; con SQLite se saltan.
"""
import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from src.load import load_data as ld
from src.utils import load_config, project_path

CONFIG = load_config()
GOLD = project_path(CONFIG["paths"]["gold_dir"])


# ---------- Sin base de datos ----------

def test_dimensiones_completas_para_las_llaves_foraneas():
    """Cada codigo usado en los casos existe en su tabla maestra (con el miembro 'Sin informacion')."""
    dim_dep = pd.DataFrame({"codigo_dane": ["76"], "departamento": ["Valle"], "region": ["Pacifica"]})
    dim_mun = pd.DataFrame({"codigo_municipio": ["76001"], "municipio": ["Cali"], "codigo_dane": ["76"],
                            "municipio_foco": [True]})
    dim_edad = pd.DataFrame({"grupo_edad": ["(20 a 24)"], "edad_min": [20], "edad_max": [24],
                             "menor_de_edad": [False], "orden": [1]})
    casos = pd.DataFrame({"id": [1, 2], "codigo_dane_departamento": ["76", ld.SIN_INFO],
                          "codigo_dane_municipio": ["76001", "00999"], "grupo_de_edad_quinquenal": ["(20 a 24)"] * 2})
    t = ld.completar_dimensiones({"dim_departamento": dim_dep, "dim_municipio": dim_mun,
                                  "dim_grupo_edad": dim_edad, "gold_suicidios": casos})
    assert set(casos["codigo_dane_departamento"]) <= set(t["dim_departamento"]["codigo_dane"])
    assert set(casos["codigo_dane_municipio"]) <= set(t["dim_municipio"]["codigo_municipio"])
    assert set(t["dim_municipio"]["codigo_dane"]) <= set(t["dim_departamento"]["codigo_dane"])
    assert "Total" in set(t["dim_grupo_edad"]["grupo_edad"])
    assert len(dim_dep) == 1  # la tabla original no se modifica


def test_codigos_de_gold_cruzan_con_las_maestras():
    """Integridad referencial sobre los CSV de gold (vale tambien para SQLite)."""
    archivos = {n: GOLD / f"{n}.csv" for n in ["gold_suicidios", "gold_tasa_mortalidad",
                                                 "dim_departamento", "dim_municipio", "dim_grupo_edad"]}
    if not all(r.exists() for r in archivos.values()):
        pytest.skip("Faltan tablas gold: corre python main.py")
    t = {n: pd.read_csv(r, dtype=str) for n, r in archivos.items()}
    t = ld.completar_dimensiones(t)
    for tabla, col, ref, ref_col in ld.LLAVES_FORANEAS:
        huerfanos = set(t[tabla][col].dropna()) - set(t[ref][ref_col])
        assert not huerfanos, f"{tabla}.{col} tiene codigos sin {ref}: {sorted(huerfanos)[:5]}"
    tasas = t["gold_tasa_mortalidad"]
    for nivel, ref, ref_col in [("Departamento", "dim_departamento", "codigo_dane"),
                                ("Municipio", "dim_municipio", "codigo_municipio")]:
        assert set(tasas.loc[tasas["nivel"] == nivel, "codigo"]) <= set(t[ref][ref_col])


# ---------- Contra PostgreSQL ----------

@pytest.fixture(scope="module")
def engine():
    if not ld.es_postgres():
        pytest.skip("DATABASE_URL no es PostgreSQL: las restricciones y roles solo aplican alli")
    eng = ld.get_engine()
    with eng.connect() as con:
        existe = con.execute(text("SELECT to_regclass('public.gold_suicidios')")).scalar()
    if existe is None:
        pytest.skip("La base no tiene tablas gold: corre python main.py")
    yield eng
    eng.dispose()


def _restricciones(engine, tipo):
    with engine.connect() as con:
        return {r[0] for r in con.execute(text(
            "SELECT conname FROM pg_constraint WHERE connamespace = 'public'::regnamespace AND contype = :t"),
            {"t": tipo})}


def test_llaves_primarias_en_la_base(engine):
    assert {f"pk_{t}" for t in ld.LLAVES_PRIMARIAS} <= _restricciones(engine, "p")


def test_llaves_foraneas_en_la_base(engine):
    esperadas = {f"fk_{t}_{c}" for t, c, _, _ in ld.LLAVES_FORANEAS}
    assert esperadas <= _restricciones(engine, "f")


def test_la_base_rechaza_un_codigo_que_no_existe(engine):
    """La llave foranea impide guardar un caso con un departamento que no esta en la tabla maestra."""
    with engine.connect() as con:
        tx = con.begin()
        try:
            with pytest.raises(IntegrityError):
                con.execute(text("INSERT INTO gold_suicidios (id, codigo_dane_departamento) VALUES (-1, 'ZZ')"))
        finally:
            tx.rollback()


def test_la_base_rechaza_un_id_repetido(engine):
    with engine.connect() as con:
        id_existente = con.execute(text("SELECT id FROM gold_suicidios LIMIT 1")).scalar()
        con.rollback()
        tx = con.begin()
        try:
            with pytest.raises(IntegrityError):
                con.execute(text("INSERT INTO gold_suicidios (id) VALUES (:i)"), {"i": id_existente})
        finally:
            tx.rollback()


def test_permisos_por_rol(engine):
    def puede(con, rol, tabla):
        return con.execute(text("SELECT has_table_privilege(:r, :t, 'SELECT')"),
                           {"r": rol, "t": f"public.{tabla}"}).scalar()
    with engine.connect() as con:
        for tabla in ld.TABLAS_TABLERO:
            assert puede(con, "rol_tablero", tabla) and puede(con, "rol_analista", tabla)
        assert puede(con, "rol_analista", "gold_suicidios")
        assert not puede(con, "rol_tablero", "gold_suicidios")


def test_rol_tablero_no_puede_leer_el_detalle(engine):
    """Prueba real: con el rol del tablero, la base niega la lectura de los casos."""
    with engine.connect() as con:
        if not con.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")).scalar():
            pytest.skip("Hace falta un usuario administrador para cambiar de rol")
        con.rollback()
        tx = con.begin()
        try:
            con.execute(text("SET LOCAL ROLE rol_tablero"))
            assert con.execute(text("SELECT count(*) FROM gold_tasa_mortalidad")).scalar() > 0
            with pytest.raises(ProgrammingError, match="permission denied"):
                con.execute(text("SELECT count(*) FROM gold_suicidios"))
        finally:
            tx.rollback()


def test_la_base_tiene_lo_mismo_que_gold(engine):
    with engine.connect() as con:
        for tabla in ["gold_suicidios", "gold_tasa_mortalidad", "gold_agregado_tablero", "gold_kpi_calidad"]:
            n_base = con.execute(text(f'SELECT count(*) FROM "{tabla}"')).scalar()
            assert n_base == len(pd.read_csv(GOLD / f"{tabla}.csv")), tabla


def test_verificacion_de_la_ultima_carga():
    ruta = GOLD / "verificacion_base.csv"
    if not ruta.exists() or not ld.es_postgres():
        pytest.skip("La verificacion solo se genera al cargar en PostgreSQL")
    v = pd.read_csv(ruta)
    assert len(v) > 0 and v["cumple"].all()
