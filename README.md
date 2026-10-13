# Presuntos Suicidios en Colombia 2015–2024 — ETL

[![Pipeline ETL y pruebas](https://github.com/danielgomez03/etl-suicidios-colombia/actions/workflows/pipeline.yml/badge.svg)](https://github.com/danielgomez03/etl-suicidios-colombia/actions/workflows/pipeline.yml)

Pipeline ETL en Python con **arquitectura medallón** (bronze → silver → gold) sobre los registros de presuntos suicidios de Medicina Legal y las proyecciones de población del DANE. Produce la **tasa de mortalidad por presunto suicidio** a nivel nacional, departamental (con foco en el Valle del Cauca) y municipal, junto con indicadores de calidad del dato.

**Autores:** Ana María Toro · Ana Sofía Perhueza · Daniel Gómez Sermeño · Daniel Steven Colmenares

## Fuentes de datos

| Fuente (`config.yaml`) | Descripción | Cómo se obtiene |
| --- | --- | --- |
| `suicidios` | *Presuntos Suicidios. Colombia, 2015 a 2024. Cifras definitivas* (INMLCF), 26.558 registros | API de Datos Abiertos [`f75u-mirk`](https://www.datos.gov.co/resource/f75u-mirk.json). Se descarga sola al correr `main.py` y queda en `data/bronze/suicidios_raw.csv` |
| `poblacion_2005_2050` | Población departamental por área, 2005-2050 (DANE) | `data/bronze/DCD-area-proypoblacion-dep-2005-2050_VP.xlsx` |
| `poblacion_sexo_edad_2005_2017` / `_2018_2050` | Población departamental por área, **sexo y edad simple** (DANE) | [DCD-area-sexo-edad-proypoblacion-dep-2005-2017_VP.xlsx](https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Departamental/DCD-area-sexo-edad-proypoblacion-dep-2005-2017_VP.xlsx) y [PPED-AreaSexoEdadDep-2018-2050_VP.xlsx](https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Departamental/PPED-AreaSexoEdadDep-2018-2050_VP.xlsx) |
| `poblacion_municipal_2005_2017` / `_2018_2042` | Población **municipal** por área (DANE) | [DCD-area-proypoblacion-Mun-2005-2017_VP.xlsx](https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Municipal/DCD-area-proypoblacion-Mun-2005-2017_VP.xlsx) y [PPED-AreaMun-2018-2042_VP.xlsx](https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Municipal/PPED-AreaMun-2018-2042_VP.xlsx) |
| `poblacion_municipal_sexo_edad_2005_2017` / `_2018_2042` | Población **municipal por sexo y edad simple** (DANE); se usan los municipios del Valle | [DCD-area-sexo-edad-proypoblacion-Mun-2005-2017_VP.xlsx](https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Municipal/DCD-area-sexo-edad-proypoblacion-Mun-2005-2017_VP.xlsx) (56 MB) y [PPED-AreaSexoEdadMun-2018-2042_VP.xlsx](https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Municipal/PPED-AreaSexoEdadMun-2018-2042_VP.xlsx) (132 MB) |

Los Excel del DANE están en `data/bronze/` dentro del repositorio porque no se pueden descargar automáticamente. El municipal por sexo y edad 2018-2042 pesa 132 MB y GitHub no acepta archivos de más de 100 MB, así que está dividido en dos partes (`.part0` y `.part1`). El pipeline las une en memoria y verifica con su huella SHA-256 que el resultado es idéntico al archivo publicado por el DANE; no hay que hacer nada al clonar. Si se descarga el archivo completo en `data/bronze/`, se usa ese. Página oficial: [DANE — Proyecciones de población](https://www.dane.gov.co/index.php/estadisticas-por-tema/demografia-y-poblacion/proyecciones-de-poblacion).

## Arquitectura

| Capa | Carpeta | Qué contiene |
| --- | --- | --- |
| Bronze | `data/bronze/` | Datos crudos tal como llegan. **Nunca se modifican.** |
| Silver | `data/silver/` | Una tabla limpia por fuente, más `rechazados_suicidios.csv` (registros que fallan una regla obligatoria, con su motivo) y `validaciones_suicidios.csv` (todas las fallas y alertas). |
| Gold | `data/gold/` + base de datos (Neon) | Tablas para el análisis y el tablero (abajo). |

`main.py` es el orquestador: **extract → silver (limpieza + validación) → gold → load**.

### Tablas gold

| Tabla | Contenido | Acceso |
| --- | --- | --- |
| `gold_tasa_mortalidad` | Casos, población y tasa por 100.000 hab.: nacional, departamental y los 6 municipios foco del Valle (Cali, Palmira, Buenaventura, Jamundí, Tuluá, Buga), por sexo y grupo de edad; por año, quinquenio y decenio. Marca las tasas inestables (< 20 casos) | Tablero |
| `gold_agregado_tablero` | Conteos por territorio, periodo y variable. Las celdas con menos de 5 casos se suprimen | Tablero |
| `gold_kpi_calidad` | KR1, KR2, KPI 1 (consistencia), KPI 2 (tasa) y KPI 3 (completitud), medidos en cada ejecución | Tablero |
| `dim_departamento`, `dim_municipio`, `dim_grupo_edad` | Tablas maestras: llave de cruce con el DANE y región natural de cada departamento (`config/regiones.csv`) | Tablero |
| `gold_suicidios` | Un registro por caso, con variables derivadas (`tipo_mecanismo`, `razon_agrupada`, `escolaridad_agrupada`, `region`) y **sin** las variables sensibles que no se usan | Solo analistas |

## Calidad y privacidad

- **Validación:** las reglas **obligatorias** (año en el periodo, sexo, grupo de edad y departamento válidos, etc.) rechazan el registro y documentan el motivo. Las reglas de **calidad** (municipio que cruza con el DANE, coherencia entre grupos de edad) solo marcan una alerta. "Sin información" es una categoría válida, no un error.
- **Umbrales** (`config.yaml`, sección `thresholds`): ≥ 99,5 % de registros válidos, ≥ 99 % de códigos que cruzan con el DANE, consistencia ≥ 99 % y semáforo de completitud (95 % / 80 %).
- **Privacidad:** minimización (10 variables sensibles fuera de gold), supresión de celdas con menos de 5 casos en el tablero y roles de acceso en PostgreSQL (`sql/roles_postgres.sql`, aplicados automáticamente en cada carga).
- **Limitaciones de los datos:** la razón del suicidio solo está registrada en el 47 % de los casos y la pertenencia étnica no se registró antes de 2018. El informe (sección 9) cuantifica estas limitaciones y explica qué conclusiones no se pueden sostener.

## Base de datos: integridad y control de acceso

En PostgreSQL (Neon o local), cada carga reemplaza las tablas y luego:

1. Crea la **llave primaria** de cada tabla y las **llaves foráneas** (integridad referencial): cada caso apunta a un departamento, un municipio y un grupo de edad que existen en las tablas maestras; los municipios apuntan a su departamento y las tasas, a su grupo de edad. Las tablas maestras de la base incluyen un miembro "Sin información" para los 4 casos sin departamento ni municipio registrados.
2. Aplica los **roles de acceso** de `sql/roles_postgres.sql`: `rol_tablero` solo lee los agregados y `rol_analista` además lee el detalle por caso (`gold_suicidios`).
3. **Verifica en la base** que todas las llaves y permisos quedaron aplicados (26 comprobaciones). Si alguna falla, el ETL se detiene con error. El resultado queda en `data/gold/verificacion_base.csv`.

La tasa y el agregado del tablero no llevan llave foránea al territorio porque su columna `codigo` depende del nivel (nacional, departamento o municipio); su consistencia la comprueban las pruebas.

## Seguridad de las credenciales

- Las credenciales (contraseña de la base y token de la API) van **solo** en el archivo `.env` de cada persona. Ese archivo está en `.gitignore` y **no se sube** al repositorio; en el repositorio solo está `.env.example`, sin valores reales.
- En GitHub Actions el token se guarda como **secreto del repositorio** (`SOCRATA_APP_TOKEN`), nunca en el código.
- La prueba `tests/test_seguridad.py` falla si alguien vuelve a subir el `.env` o un archivo con una contraseña o un token.
- Si una credencial llega a publicarse, borrarla del repositorio no basta (queda en el historial de git): hay que **cambiarla** en el servicio (Neon, datos.gov.co).

## Pruebas automáticas

En cada cambio, [GitHub Actions](https://github.com/danielgomez03/etl-suicidios-colombia/actions/workflows/pipeline.yml) levanta un PostgreSQL limpio, ejecuta el ETL completo (desde la API hasta la base), corre **todas las pruebas** y ejecuta el informe. El resumen de cada ejecución muestra los KPI, la verificación de la base y el resultado de las pruebas; los reportes quedan como archivos descargables.

| Archivo | Qué comprueba |
|---|---|
| `tests/test_extract.py`, `test_quality.py`, `test_transform.py` | Lectura de las fuentes, llaves únicas y reglas de limpieza |
| `tests/test_gold.py` | Reglas de negocio y cifras de control (tasas nacionales, Tabla 4, supresión, minimización) |
| `tests/test_base_datos.py` | Llaves primarias y foráneas, que la base rechace códigos inexistentes e id repetidos, permisos por rol y que `rol_tablero` no pueda leer el detalle |
| `tests/test_seguridad.py` | Que no haya credenciales en el repositorio |

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
├── .github/workflows/pipeline.yml # ejecucion completa y pruebas en cada cambio
├── src/
│   ├── utils.py                  # config, rutas relativas y logger
│   ├── extract/extract_data.py   # API Socrata, Excel del DANE y CSV
│   ├── transform/clean_data.py   # limpieza por fuente (silver)
│   ├── transform/validate.py     # reglas de validacion y rechazados (KPI 1)
│   ├── transform/gold_data.py    # tablas maestras, tasas, tablero y KPIs (gold)
│   └── load/load_data.py         # CSV, carga, llaves, roles y verificacion de la base
├── tests/
├── main.py                       # orquestador (el unico que ejecuta)
└── .env.example                  # plantilla de variables de entorno (sin credenciales)
```

## Instalación (Windows / PowerShell)

```powershell
py -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env      # y luego poner los valores reales en .env
```

En `.env` van el token de datos.gov.co (`SOCRATA_APP_TOKEN`) y la dirección de la base (`DATABASE_URL`). Sin token la API también funciona, pero es más lenta. **Nunca subas el `.env` al repositorio.**

### Base de datos

La base de destino se define con `DATABASE_URL` en el `.env`. Si no está definida, se usa SQLite (`data/gold/suicidios.db`).

- **Neon** (la que usa el grupo): PostgreSQL gratuito en la nube. La dirección de conexión (`postgresql://usuario:<contraseña>@...neon.tech/suicidios_colombia?sslmode=require`) se pide al equipo y se pone en el `.env` local. Las tablas gold se reemplazan en cada ejecución.
- **SQLite** (sin instalar nada, para pruebas locales): `DATABASE_URL=sqlite:///data/gold/suicidios.db`.
- **PostgreSQL local** (permite control de acceso): `DATABASE_URL=postgresql+psycopg2://usuario:contrasena@localhost:5432/suicidios`.

Con PostgreSQL se aplican y verifican las llaves y los roles (ver *Base de datos: integridad y control de acceso*). Los roles no tienen contraseña; para dar acceso se crea un usuario y se le asigna el rol (ejemplo en el script). En SQLite este paso se omite.

## Ejecución

Desde la raíz del proyecto y con el `venv` activo:

```powershell
python main.py            # corre el ETL completo (~80 s; la mayor parte es leer los Excel municipales)
python -m pytest -v       # pruebas (las de llaves y roles corren si DATABASE_URL es PostgreSQL)
```

Después se puede abrir `notebooks/informe.ipynb`.

Con `use_cache: true` (en `config.yaml`) la API solo se consulta la primera vez; después se usa `data/bronze/suicidios_raw.csv`. Para volver a descargar, pon `use_cache: false` o borra ese archivo.

## Licencia

Código bajo licencia MIT. Los datos pertenecen al INMLCF y al DANE (Datos Abiertos de Colombia).
