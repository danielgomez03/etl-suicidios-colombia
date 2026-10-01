import logging
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parents[1]


def load_config() -> dict:
    """Lee config/config.yaml como diccionario."""
    with open(BASE_DIR / "config" / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def project_path(relativa: str) -> Path:
    """Convierte una ruta relativa del YAML en absoluta dentro del proyecto."""
    return BASE_DIR / relativa


def get_logger(name: str) -> logging.Logger:
    """Logger con fecha y hora, en consola y en logs/etl_log.txt."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        (BASE_DIR / "logs").mkdir(exist_ok=True)
        for h in (logging.FileHandler(BASE_DIR / "logs" / "etl_log.txt", encoding="utf-8"),
                  logging.StreamHandler()):
            h.setFormatter(fmt)
            logger.addHandler(h)
    return logger
