# Presuntos Suicidios en Colombia 2015–2024 — ETL

Pipeline ETL en Python con **arquitectura medallón** (bronze → silver → gold) sobre los registros de presuntos suicidios de Medicina Legal y las proyecciones de población del DANE. Produce la **tasa de mortalidad por presunto suicidio** a nivel nacional, departamental (con foco en el Valle del Cauca) y municipal, junto con indicadores de calidad del dato.

**Autores:** Ana María Toro · Ana Sofía Perhueza · Daniel Gómez Sermeño · Daniel Steven Colmenares

## Fuentes de datos

| Fuente (`config.yaml`) | Descripción | Cómo se obtiene |
| --- | --- | --- |
| `suicidios` | *Presuntos Suicidios. Colombia, 2015 a 2024. Cifras definitivas* (INMLCF), 26.558 registros | API de Datos Abiertos [`f75u-mirk`](https://www.datos.gov.co/resource/f75u-mirk.json). Se descarga sola al correr `main.py` y queda en `data/bronze/suicidios_raw.csv` |
| `poblacion_2005_2050` | Población departamental por área, 2005-2050 (DANE) | `data/bronze/DCD-area-proypoblacion-dep-2005-2050_VP.xlsx` |
| `poblacion_sexo_edad_2005_2017` / `_2018_2050` | Población departamental por área, **sexo y edad simple** (DANE) | [DCD-area-sexo-edad-proypoblacion-dep-2005-2017_VP.xlsx](https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Departamental/DCD-area-sexo-edad-proypoblacion-dep-2005-2017_VP.xlsx) y [PPED-AreaSexoEdadDep-2018-2050_VP.xlsx](https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Departamental/PPED-AreaSexoEdadDep-2018-2050_VP.xlsx) |
| `poblacion_municipal_2005_2017` / `_2018_2042` | Población **municipal** por área (DANE) | [DCD-area-proypoblacion-Mun-2005-2017_VP.xlsx](https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Municipal/DCD-area-proypoblacion-Mun-2005-2017_VP.xlsx) y [PPED-AreaMun-2018-2042_VP.xlsx](https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Municipal/PPED-AreaMun-2018-2042_VP.xlsx) |

Los Excel del DANE están en `data/bronze/` dentro del repositorio porque no se pueden descargar automáticamente. Página oficial: [DANE — Proyecciones de población](https://www.dane.gov.co/index.php/estadisticas-por-tema/demografia-y-poblacion/proyecciones-de-poblacion).

## Arquitectura

| Capa | Carpeta | Qué contiene |
| --- | --- | --- |
| Bronze | `data/bronze/` | Datos crudos tal como llegan. **Nunca se modifican.** |
| Silver | `data/silver/` | Una tabla limpia por fuente, más `rechazados_suicidios.csv` (registros que fallan una regla obligatoria, con su motivo) y `validaciones_suicidios.csv` (todas las fallas y alertas). |
| Gold | `data/gold/` + base de datos | Tablas para el análisis y el tablero (abajo). |

`main.py` es el orquestador: **extract → silver (limpieza + validación) → gold → load**.

### Tablas gold

| Tabla | Contenido | Acceso |
| --- | --- | --- |
| `gold_tasa_mortalidad` | Casos, población y tasa por 100.000 hab.: nacional y departamental (por sexo y grupo de edad), y los 6 municipios foco del Valle (Cali, Palmira, Buenaventura, Jamundí, Tuluá, Buga); por año, quinquenio y decenio. Marca las tasas inestables (< 20 casos) | Tablero |
| `gold_agregado_tablero` | Conteos por territorio, periodo y variable. Las celdas con menos de 5 casos se suprimen | Tablero |
| `gold_kpi_calidad` | KR1, KR2, KPI 1 (consistencia), KPI 2 (tasa) y KPI 3 (completitud), medidos en cada ejecución | Tablero |
| `dim_departamento`, `dim_municipio`, `dim_grupo_edad` | Tablas maestras: llave de cruce con el DANE y región natural de cada departamento (`config/regiones.csv`) | Tablero |
| `gold_suicidios` | Un registro por caso, con variables derivadas (`tipo_mecanismo`, `razon_agrupada`, `escolaridad_agrupada`, `region`) y **sin** las variables sensibles que no se usan | Solo analistas |

## Calidad y privacidad

- **Validación:** las reglas **obligatorias** (año en el periodo, sexo, grupo de edad y departamento válidos, etc.) rechazan el registro y documentan el motivo. Las reglas de **calidad** (municipio que cruza con el DANE, coherencia entre grupos de edad) solo marcan una alerta. "Sin información" es una categoría válida, no un error.
- **Umbrales** (`config.yaml`, sección `thresholds`): ≥ 99,5 % de registros válidos, ≥ 99 % de códigos que cruzan con el DANE, consistencia ≥ 99 % y semáforo de completitud (95 % / 80 %).
- **Privacidad:** minimización (10 variables sensibles fuera de gold), supresión de celdas con menos de 5 casos en el tablero y roles de acceso en PostgreSQL (`sql/roles_postgres.sql`).

## Estructura

```
├── config/config.yaml            # fuentes, periodo, alcance (Valle y municipios foco), umbrales
├── config/regiones.csv           # departamento -> region natural
├── data/bronze|silver|gold/
├── logs/                         # logs/etl_log.txt
├── notebooks/
│   ├── EDA.ipynb                 # calidad del dato crudo y analisis exploratorio
│   ├── informe.ipynb             # informe: OKR, KPIs, preguntas de negocio, correcciones
│   └── conclusiones.ipynb
├── sql/roles_postgres.sql        # control de acceso en PostgreSQL
├── src/
│   ├── utils.py                  # config, rutas relativas y logger
│   ├── extract/extract_data.py   # API Socrata, Excel del DANE y CSV
│   ├── transform/clean_data.py   # limpieza por fuente (silver)
│   ├── transform/validate.py     # reglas de validacion y rechazados (KPI 1)
│   ├── transform/gold_data.py    # tablas maestras, tasas, tablero y KPIs (gold)
│   └── load/load_data.py         # CSV y carga a base de datos
├── tests/
├── main.py                       # orquestador (el unico que ejecuta)
└── .env.example                  # variables de entorno
```

## Instalación (Windows / PowerShell)

```powershell
py -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env      # si no existe ya un .env
```

En `.env` va el token de datos.gov.co (`SOCRATA_APP_TOKEN`). Sin token la API también funciona, pero es más lenta.

### Base de datos

- **SQLite** (por defecto): `DATABASE_URL=sqlite:///data/gold/suicidios.db`. No requiere instalar nada.
- **PostgreSQL** (recomendada; permite control de acceso): `DATABASE_URL=postgresql+psycopg2://usuario:contrasena@localhost:5432/suicidios`. Después de correr `main.py`, ejecutar `psql -U postgres -d suicidios -f sql/roles_postgres.sql` para crear los roles `rol_tablero` y `rol_analista`.

## Ejecución

Desde la raíz del proyecto y con el `venv` activo:

```powershell
python main.py            # corre el ETL completo (~35 s)
python -m pytest -v       # pruebas
```

Después se puede abrir `notebooks/informe.ipynb`.

Con `use_cache: true` (en `config.yaml`) la API solo se consulta la primera vez; después se usa `data/bronze/suicidios_raw.csv`. Para volver a descargar, pon `use_cache: false` o borra ese archivo.

## Licencia

Código bajo licencia MIT. Los datos pertenecen al INMLCF y al DANE (Datos Abiertos de Colombia).
