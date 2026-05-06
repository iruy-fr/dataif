CREATE TABLE IF NOT EXISTS raw.pnp_endpoint_tables (
  endpoint_key TEXT PRIMARY KEY,
  endpoint_name TEXT NOT NULL,
  tipo_microdados TEXT NOT NULL UNIQUE,
  raw_table_schema TEXT NOT NULL DEFAULT 'raw',
  raw_table_name TEXT NOT NULL,
  staging_table_schema TEXT NOT NULL DEFAULT 'staging',
  staging_table_name TEXT,
  curated_relation_schema TEXT NOT NULL DEFAULT 'curated',
  curated_relation_name TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_raw_pnp_endpoint_tables_raw_table UNIQUE (raw_table_schema, raw_table_name)
);

DROP TRIGGER IF EXISTS trg_pnp_endpoint_tables_updated_at ON raw.pnp_endpoint_tables;
CREATE TRIGGER trg_pnp_endpoint_tables_updated_at
BEFORE UPDATE ON raw.pnp_endpoint_tables
FOR EACH ROW
EXECUTE FUNCTION raw.touch_updated_at();

CREATE INDEX IF NOT EXISTS idx_raw_pnp_endpoint_tables_active
  ON raw.pnp_endpoint_tables (is_active, endpoint_name);

CREATE TABLE IF NOT EXISTS raw.pnp_pipeline_endpoints (
  pipeline_endpoint_id BIGSERIAL PRIMARY KEY,
  instance_key TEXT NOT NULL REFERENCES raw.pnp_instances(instance_key) ON DELETE CASCADE,
  connection_key TEXT,
  endpoint_key TEXT NOT NULL REFERENCES raw.pnp_endpoint_tables(endpoint_key),
  selection_source TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_raw_pnp_pipeline_endpoints UNIQUE (instance_key, endpoint_key)
);

DROP TRIGGER IF EXISTS trg_pnp_pipeline_endpoints_updated_at ON raw.pnp_pipeline_endpoints;
CREATE TRIGGER trg_pnp_pipeline_endpoints_updated_at
BEFORE UPDATE ON raw.pnp_pipeline_endpoints
FOR EACH ROW
EXECUTE FUNCTION raw.touch_updated_at();

CREATE INDEX IF NOT EXISTS idx_raw_pnp_pipeline_endpoints_instance
  ON raw.pnp_pipeline_endpoints (instance_key, is_active, endpoint_key);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_pipeline_endpoints_connection
  ON raw.pnp_pipeline_endpoints (connection_key, is_active, instance_key);

INSERT INTO raw.pnp_endpoint_tables (
  endpoint_key,
  endpoint_name,
  tipo_microdados,
  raw_table_schema,
  raw_table_name,
  staging_table_schema,
  staging_table_name,
  curated_relation_schema,
  curated_relation_name,
  metadata
)
VALUES
  (
    'matriculas',
    'Matrículas',
    'Matrículas',
    'raw',
    'pnp_matriculas_src',
    'staging',
    'pnp_matriculas',
    'curated',
    NULL,
    jsonb_build_object('domain_key', 'matriculas')
  ),
  (
    'eficiencia_academica',
    'Eficiência Acadêmica',
    'Eficiência Acadêmica',
    'raw',
    'pnp_eficiencia_academica_src',
    'staging',
    'pnp_eficiencia_academica',
    'curated',
    NULL,
    jsonb_build_object('domain_key', 'eficiencia_academica')
  ),
  (
    'servidores',
    'Servidores',
    'Servidores',
    'raw',
    'pnp_servidores_src',
    'staging',
    'pnp_servidores',
    'curated',
    NULL,
    jsonb_build_object('domain_key', 'servidores')
  ),
  (
    'financeiro',
    'Financeiro',
    'Financeiro',
    'raw',
    'pnp_financeiro_src',
    'staging',
    'pnp_financeiro',
    'curated',
    NULL,
    jsonb_build_object('domain_key', 'financeiro')
  )
ON CONFLICT (endpoint_key) DO UPDATE
SET
  endpoint_name = EXCLUDED.endpoint_name,
  tipo_microdados = EXCLUDED.tipo_microdados,
  raw_table_schema = EXCLUDED.raw_table_schema,
  raw_table_name = EXCLUDED.raw_table_name,
  staging_table_schema = EXCLUDED.staging_table_schema,
  staging_table_name = EXCLUDED.staging_table_name,
  curated_relation_schema = EXCLUDED.curated_relation_schema,
  curated_relation_name = EXCLUDED.curated_relation_name,
  is_active = TRUE,
  metadata = EXCLUDED.metadata,
  updated_at = NOW();

INSERT INTO raw.pnp_pipeline_endpoints (
  instance_key,
  connection_key,
  endpoint_key,
  selection_source,
  is_active,
  metadata
)
SELECT
  i.instance_key,
  i.connection_key,
  et.endpoint_key,
  'phase7a_backfill',
  COALESCE(i.is_active, TRUE) AND BOOL_OR(COALESCE(s.is_active, TRUE)),
  jsonb_build_object(
    'tipo_microdados', s.tipo_microdados,
    'raw_table', format('%s.%s', et.raw_table_schema, et.raw_table_name),
    'staging_table', CASE
      WHEN et.staging_table_name IS NULL THEN NULL
      ELSE format('%s.%s', et.staging_table_schema, et.staging_table_name)
    END
  )
FROM raw.pnp_instances i
JOIN raw.pnp_instance_selection s
  ON s.instance_key = i.instance_key
JOIN raw.pnp_endpoint_tables et
  ON et.tipo_microdados = s.tipo_microdados
GROUP BY
  i.instance_key,
  i.connection_key,
  et.endpoint_key,
  s.tipo_microdados,
  et.raw_table_schema,
  et.raw_table_name,
  et.staging_table_schema,
  et.staging_table_name
ON CONFLICT (instance_key, endpoint_key) DO UPDATE
SET
  connection_key = EXCLUDED.connection_key,
  selection_source = EXCLUDED.selection_source,
  is_active = EXCLUDED.is_active,
  metadata = EXCLUDED.metadata,
  updated_at = NOW();
