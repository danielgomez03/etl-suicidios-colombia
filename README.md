# Presuntos Suicidios en Colombia 2015–2024 — ETL

Pipeline ETL en Python con **arquitectura medallón** (bronze → silver → gold) que prepara los datos del trabajo *"Presuntos Suicidios en Colombia de 2015 a 2024"* (Maestría en Inteligencia Artificial y Ciencia de Datos).

**Autores:** Ana María Toro · Ana Sofía Perhueza · Daniel Gómez Sermeño · Daniel Steven Colmenares

## Fuentes de datos

| Fuente (`config.yaml`) | Descripción | Cómo se obtiene |
| --- | --- | --- |
| `suicidios` | *Presuntos Suicidios. Colombia, 2015 a 2024. Cifras definitivas* — INMLCF, 26.558 registros | API de Datos Abiertos: [`f75u-mirk`](https://www.datos.gov.co/resource/f75u-mirk.json). Se descarga sola al correr `main.py` y se guarda en `data/bronze/suicidios_raw.csv` |
| `poblacion_2005_2017` | Retroproyecciones de población departamental por área (DANE, Censo 2018) | Descarga manual: [DCD-area-proypoblacion-dep-2005-2017_VP.xlsx](https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Departamental/DCD-area-proypoblacion-dep-2005-2017_VP.xlsx) → `data/bronze/` |
| `poblacion_2018_2050` | Proyecciones de población departamental por área (DANE, actualización post-COVID) | Descarga manual: [PPED-AreaDep-2018-2050_VP.xlsx](https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Departamental/PPED-AreaDep-2018-2050_VP.xlsx) → `data/bronze/` |

Se usan dos archivos del DANE porque el periodo de estudio (2015–2024) cruza el corte de 2018 entre retroproyecciones y proyecciones. Página oficial: [DANE — Proyecciones de población](https://www.dane.gov.co/index.php/estadisticas-por-tema/demografia-y-poblacion/proyecciones-de-poblacion).

Los datos crudos no se suben al repositorio (`data/bronze/*` está en `.gitignore`): se regeneran con la API y los enlaces de arriba.

## Arquitectura

| Capa | Carpeta | Qué contiene |
| --- | --- | --- |
| Bronze | `data/bronze/` | Datos crudos tal como llegan (API e Excel del DANE). **Nunca se modifican.** |
| Silver | `data/silver/` | Una tabla limpia por fuente (`<fuente>_clean.csv`). |
| Gold | `data/gold/` | Base de casos lista para el análisis (`gold.csv` + tabla `gold_suicidios` en la base de datos). |

Flujo que ejecuta `main.py`: **extract → transform (silver) → gold → load**.

La población no se une registro a registro: se agrega por departamento y año y se usa para calcular tasas por 100.000 habitantes (por eso `integration.sources` solo incluye `suicidios`).

## Estructura

```
├── config/config.yaml            # fuentes, periodo, rutas, reglas
├── data/bronze|silver|gold/
├── logs/                         # logs/etl_log.txt
├── notebooks/EDA.ipynb           # análisis exploratorio (no modifica datos)
├── src/
│   ├── utils.py                  # config, rutas relativas y logger
│   ├── extract/extract_data.py   # API Socrata, Excel, CSV y SQL
│   ├── transform/clean_data.py   # limpieza (silver)
│   ├── transform/gold_data.py    # integración y métricas (gold)
│   └── load/load_data.py         # CSV y carga a base de datos
├── tests/
├── main.py                       # orquestador (el único que ejecuta)
├── programar_etl.py              # ejecución programada
└── .env.example                  # variables de entorno (el .env real no se sube)
```

## Instalación (Windows / PowerShell)

```powershell
py -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

En `.env` pon el token de datos.gov.co en `SOCRATA_APP_TOKEN`. Sin token la API también funciona, pero es más lenta y con límite de peticiones. Descarga los dos Excel del DANE en `data/bronze/`.

## Ejecución

Desde la raíz del proyecto y con el `venv` activo:

```powershell
python main.py            # corre el ETL completo
python -m pytest -v       # pruebas
```

Con `use_cache: true` (en `config.yaml`) la API solo se consulta la primera vez; después se usa `data/bronze/suicidios_raw.csv`. Para volver a descargar, pon `use_cache: false` o borra ese archivo.

## Licencia

Código bajo licencia MIT. Los datos pertenecen al INMLCF y al DANE (Datos Abiertos de Colombia).
