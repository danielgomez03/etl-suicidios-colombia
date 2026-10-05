"""
Orquestador del ETL: es el único archivo que se ejecuta.
Etapas:
  1. EXTRACT   API de Medicina Legal + proyecciones DANE
  2. SILVER             limpieza por fuente + validación
  3. GOLD               tablas maestras, casos, tasas, tablero y KPIs
  4. LOAD               CSV en data/gold + base de datos (Neon, segun DATABASE_URL del .env)
"""

import time
import pandas as pd
from src.extract import extract_data as ext
from src.load import load_data as ld
from src.transform import clean_data as cln
from src.transform import gold_data as gld
from src.transform.validate import validar_suicidios
from src.utils import get_logger, load_config, project_path


logger = get_logger("main")
def _etapa(nombre, inicio):
    logger.info(f"{nombre}: {time.perf_counter() - inicio:.2f} s")


def _apilar(limpios: dict, nombres: list) -> pd.DataFrame:
    """Une las series 2005-2017 y 2018-20xx de una misma población DANE."""
    return pd.concat( [limpios[n] for n in nombres], ignore_index=True)

def _diferencia_max(
    sexo_grupo: pd.DataFrame,
    total: pd.DataFrame,
    llave: str,
    p: dict ) -> float:
    """Calcula la diferencia máxima entre población por sexo/edad y total oficial."""

    total = total[total["ano"].between( p["start_year"], p["end_year"])]

    comp = (sexo_grupo.groupby([llave, "ano"])["poblacion"].sum().rename("sexo_edad")
        .to_frame().join(total.set_index([llave, "ano"])["poblacion"], how="inner"))

    return float(
        ((comp["sexo_edad"] - comp["poblacion"]).abs() / comp["poblacion"]* 100 ).max() )


def run_pipeline():
    inicio = time.perf_counter()
    config = load_config()
    logger.info(
        f"===== INICIO {config['project']['name']} " f"v{config['project']['version']} =====")

    silver_dir = project_path(config["paths"]["silver_dir"])

    gold_dir = project_path(config["paths"]["gold_dir"])

    p = config["period"]
    try:
        # 1. EXTRACT
        t = time.perf_counter()
        crudos = { nombre: ext.extract_source(f) for nombre, f in config["sources"].items()}
        _etapa("Extract", t)

        # 2. SILVER
        t = time.perf_counter()
        limpios = {}
        for nombre, df in crudos.items():
            limpios[nombre] = cln.limpiar_fuente(
                nombre,df,config)
            ld.save_csv(
                limpios[nombre],
                silver_dir / f"{nombre}_clean.csv")

        pob_dep = limpios["poblacion_2005_2050"] # Población departamental
        pob_sexo_edad = _apilar(limpios,
            ["poblacion_sexo_edad_2005_2017","poblacion_sexo_edad_2018_2050"])
        
        pob_mun = _apilar(limpios,["poblacion_municipal_2005_2017","poblacion_municipal_2018_2042"])

        pob_mun_sexo_edad = _apilar(limpios,
            ["poblacion_municipal_sexo_edad_2005_2017","poblacion_municipal_sexo_edad_2018_2042" ] )

        # TABLAS MAESTRAS
        dim_grupo_edad = gld.construir_dim_grupo_edad( limpios["suicidios"]["grupo_de_edad_quinquenal"])

        dim_departamento = gld.construir_dim_departamento( pob_dep,config["paths"]["regiones"])

        dim_municipio = gld.construir_dim_municipio( pob_mun,config)

        # VALIDACIÓN
        silver = limpios["suicidios"]
        validos, rechazados, resumen_reglas, detalle_fallas = (
            validar_suicidios(silver,config,dim_grupo_edad,
                codigos_departamento=set( dim_departamento["codigo_dane"]),
                codigos_municipio=set(dim_municipio["codigo_municipio"]
                )
            )
        )


        ld.save_csv(rechazados,silver_dir / "rechazados_suicidios.csv")

        ld.save_csv(detalle_fallas,silver_dir / "validaciones_suicidios.csv" )
        _etapa("Silver", t)

        # 3. GOLD
        t = time.perf_counter()
        integ = config.get("integration", {})
        fuentes = { "suicidios": validos}

        casos = gld.integrar_fuentes(fuentes, integ.get("on"), integ.get("how", "left"))
        casos = gld.agregar_metricas(casos, dim_departamento )
        # Población por sexo y grupo de edad
        pob_sexo_grupo = gld.poblacion_por_sexo_grupo( pob_sexo_edad, dim_grupo_edad)

        pob_mun_sexo_grupo = gld.poblacion_por_sexo_grupo( pob_mun_sexo_edad,dim_grupo_edad,
            "codigo_municipio")

        # CHEQUEO DE DENOMINADORES
        diferencias = { "departamental": _diferencia_max(pob_sexo_grupo,pob_dep,"codigo_dane", p),"municipal (Valle)": _diferencia_max(
                pob_mun_sexo_grupo,pob_mun,"codigo_municipio",
                p), }

        rango = pob_dep["ano"].between( p["start_year"], p["end_year"])

        # TASAS, TABLERO Y KPIs
        tasas = gld.construir_tasas(
            casos,
            pob_dep[rango],
            pob_sexo_grupo,
            pob_mun,
            pob_mun_sexo_grupo,
            dim_departamento,
            dim_municipio,
            config
        )

        tablero = gld.construir_agregado_tablero(
            casos,
            dim_departamento,
            dim_municipio,
            config
        )

        kpis = gld.construir_kpis(
            len(silver),
            validos,
            rechazados,
            resumen_reglas,
            detalle_fallas,
            silver,
            casos,
            tasas,
            diferencias,
            config
        )

        # TABLAS GOLD
        tablas_gold = { config["database"]["gold_table"]: casos,"gold_tasa_mortalidad": tasas,
            "gold_agregado_tablero": tablero,"gold_kpi_calidad": kpis,"dim_departamento": dim_departamento,
            "dim_municipio": dim_municipio,"dim_grupo_edad": dim_grupo_edad,}
        # Guardar Gold como CSV
        for nombre, df in tablas_gold.items():
            ld.save_csv(df,gold_dir / f"{nombre}.csv")
        _etapa("Gold", t)

        # 4. LOAD → base de datos (Neon)
        t = time.perf_counter()
        logger.info("Iniciando carga de tablas Gold en la base de datos...")
        for nombre, df in tablas_gold.items():
            ld.load_to_database( df,nombre)
        # Llaves primarias y roles de acceso (solo PostgreSQL / Neon)
        ld.aplicar_llaves_y_roles(tablas_gold.keys())
        _etapa("Load", t)


    except Exception:
        logger.exception("El ETL falló")
        raise

    logger.info(
        f"===== ETL TERMINADO en "
        f"{time.perf_counter() - inicio:.2f} s =====")

    return tablas_gold


if __name__ == "__main__":
    run_pipeline()
