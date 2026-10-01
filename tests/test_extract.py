import pandas as pd

from src.extract import extract_data as ext


class _RespFalsa:
    def __init__(self, datos):
        self._datos = datos

    def raise_for_status(self):
        pass

    def json(self):
        return self._datos


def test_api_socrata_pagina_por_lotes(monkeypatch):
    """Descarga por lotes hasta que la API devuelve una lista vacia, sin red real."""
    filas = [{"id": str(i), "sexo_de_la_victima": "Hombre"} for i in range(5)]
    offsets = []

    def get_falso(url, headers, params, timeout):
        offsets.append(params["$offset"])
        ini = params["$offset"]
        return _RespFalsa(filas[ini:ini + params["$limit"]])

    monkeypatch.setattr(ext.requests, "get", get_falso)
    df = ext.extract_api_socrata("https://ejemplo/resource/x.json", batch_size=2)

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5 and df["id"].is_unique
    assert offsets == [0, 2, 4, 5]
