import time

from src.utils import load_config, project_path, get_logger
from src.extract import extract_data as ext
from src.transform import clean_data as cln
from src.transform import gold_data as gld
from src.load import load_data as ld

logger = get_logger("main")


def run_pipeline():
    inicio = time.perf_counter()
    config = load_config()
    logger.info(f"===== INICIO {config['project']['name']} v{config['project']['version']} =====")
    silver_dir = project_path(config["paths"]["silver_dir"])
    gold_dir = project_path(config["paths"]["gold_dir"])

    try:
        # 1. EXTRACT (bronze)
        t = time.perf_counter()
        crudos = {nombre: ext.extract_source(f) for nombre, f in config["sources"].items()}
        logger.info(f"Extract: {time.perf_counter() - t:.2f} s")

        # 2. TRANSFORM (silver)
        t = time.perf_counter()
        limpios = {}
        for nombre, df in crudos.items():
            limpios[nombre] = cln.limpiar_fuente(nombre, df, config)
            ld.save_csv(limpios[nombre], silver_dir / f"{nombre}_clean.csv")
        logger.info(f"Silver: {time.perf_counter() - t:.2f} s")

        # 3. TRANSFORM (gold)
        t = time.perf_counter()
        integ = config.get("integration", {})
        a_integrar = {n: limpios[n] for n in integ.get("sources", list(limpios))}
        gold = gld.integrar_fuentes(a_integrar, integ.get("on"), integ.get("how", "left"))
        gold = gld.agregar_metricas(gold)
        ld.save_csv(gold, gold_dir / "gold.csv")
        logger.info(f"Gold: {time.perf_counter() - t:.2f} s")

        # 4. LOAD
        t = time.perf_counter()
        ld.load_to_database(gold, config["database"]["gold_table"])
        logger.info(f"Load: {time.perf_counter() - t:.2f} s")
    except Exception:
        logger.exception("El ETL fallo")
        raise

    logger.info(f"===== ETL TERMINADO en {time.perf_counter() - inicio:.2f} s =====")


if __name__ == "__main__":
    run_pipeline()
