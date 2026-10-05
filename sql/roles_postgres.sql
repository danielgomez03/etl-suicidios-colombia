-- Control de acceso para la base gold en PostgreSQL (retroalimentacion Avance 1: privacidad).
-- main.py lo ejecuta solo al final de cada carga cuando DATABASE_URL es PostgreSQL (Neon o local),
-- porque la carga recrea las tablas y con eso se pierden los permisos. Se puede correr muchas veces.
-- Tambien se puede correr a mano:  psql "<DATABASE_URL>" -f sql/roles_postgres.sql
--
-- Niveles de acceso:
--   rol_tablero  -> solo datos agregados (tasas, conteos con supresion < 5, KPIs y tablas maestras).
--                   Es el que usa Power BI / el tablero.
--   rol_analista -> ademas puede leer el detalle por caso (gold_suicidios), ya minimizado.
--                   Solo para el equipo de analisis.
--
-- Los roles son de grupo (NOLOGIN): no tienen contrasena y nadie entra directamente con ellos.
-- Para dar acceso a una persona o al tablero se crea su usuario y se le asigna el rol, por ejemplo:
--   CREATE ROLE usuario_powerbi LOGIN PASSWORD '<contrasena segura>';
--   GRANT rol_tablero TO usuario_powerbi;

DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rol_tablero') THEN
    CREATE ROLE rol_tablero NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rol_analista') THEN
    CREATE ROLE rol_analista NOLOGIN;
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
