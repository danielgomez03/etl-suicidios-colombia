-- Control de acceso para la base gold en PostgreSQL (retroalimentacion Avance 1: privacidad).
-- Ejecutar como administrador DESPUES de correr python main.py con DATABASE_URL de PostgreSQL:
--   psql -U postgres -d suicidios -f sql/roles_postgres.sql
--
-- Niveles de acceso:
--   rol_tablero  -> solo datos agregados (tasas, conteos con supresion < 5, KPIs y tablas maestras).
--                   Es el que usa Power BI / el tablero publico.
--   rol_analista -> ademas puede leer el detalle por caso (gold_suicidios), ya minimizado.
--                   Solo para el equipo de analisis.
-- Las contrasenas se definen aqui como ejemplo: cambiarlas antes de usar.

DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rol_tablero') THEN
    CREATE ROLE rol_tablero LOGIN PASSWORD 'cambiar_tablero';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rol_analista') THEN
    CREATE ROLE rol_analista LOGIN PASSWORD 'cambiar_analista';
  END IF;
END $$;

-- Nadie lee por defecto
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO rol_tablero, rol_analista;

-- Agregados: tablero y analistas
GRANT SELECT ON gold_agregado_tablero, gold_tasa_mortalidad, gold_kpi_calidad,
                dim_departamento, dim_municipio, dim_grupo_edad
      TO rol_tablero, rol_analista;

-- Detalle por caso: solo analistas
GRANT SELECT ON gold_suicidios TO rol_analista;
REVOKE ALL ON gold_suicidios FROM rol_tablero;
