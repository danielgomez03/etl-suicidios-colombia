import pytest

from src.extract.extract_data import extract_source
from src.transform.clean_data import limpiar_fuente
from src.utils import load_config, project_path

CONFIG = load_config()


def _ruta_local(fuente: dict):
    """Archivo local de la fuente (path, o raw_path si es API). Si el Excel esta dividido
    en partes y no existe completo, basta con que exista la primera parte."""
    ruta = fuente.get("path") or fuente.get("raw_path")
    if ruta and not project_path(ruta).exists() and fuente.get("parts"):
        return fuente["parts"][0]
    return ruta


@pytest.mark.parametrize("nombre", list(CONFIG["sources"]))
def test_llave_unica(nombre):
    fuente = CONFIG["sources"][nombre]
    ruta = _ruta_local(fuente)
    if ruta and not project_path(ruta).exists():
        pytest.skip(f"{ruta} aun no esta en bronze (corre main.py o descarga el archivo)")
    df = limpiar_fuente(nombre, extract_source(fuente), CONFIG)
    assert len(df) > 0
    if fuente.get("key"):
        assert df[fuente["key"]].is_unique
