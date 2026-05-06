CREATE TABLE IF NOT EXISTS config.app_settings (
  setting_key TEXT PRIMARY KEY,
  setting_value JSONB NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raw.pnp_connections (
  connection_key TEXT PRIMARY KEY,
  connection_name TEXT NOT NULL,
  page_url TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION raw.touch_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_pnp_connections_updated_at ON raw.pnp_connections;
CREATE TRIGGER trg_pnp_connections_updated_at
BEFORE UPDATE ON raw.pnp_connections
FOR EACH ROW
EXECUTE FUNCTION raw.touch_updated_at();

CREATE INDEX IF NOT EXISTS idx_raw_pnp_connections_active
  ON raw.pnp_connections (is_active, updated_at DESC);

CREATE TABLE IF NOT EXISTS raw.pnp_instances (
  pipeline_id UUID NOT NULL DEFAULT gen_random_uuid(),
  instance_key TEXT PRIMARY KEY,
  instance_name TEXT NOT NULL,
  connection_key TEXT,
  connection_name TEXT,
  page_url TEXT NOT NULL,
  schedule TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  legacy_mode TEXT,
  legacy_endpoint_id BIGINT,
  legacy_endpoint_key TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'uq_raw_pnp_instances_pipeline_id'
      AND conrelid = 'raw.pnp_instances'::regclass
  ) THEN
    ALTER TABLE raw.pnp_instances
      ADD CONSTRAINT uq_raw_pnp_instances_pipeline_id UNIQUE (pipeline_id);
  END IF;
END $$;

DROP TRIGGER IF EXISTS trg_pnp_instances_updated_at ON raw.pnp_instances;
CREATE TRIGGER trg_pnp_instances_updated_at
BEFORE UPDATE ON raw.pnp_instances
FOR EACH ROW
EXECUTE FUNCTION raw.touch_updated_at();

CREATE INDEX IF NOT EXISTS idx_raw_pnp_instances_active
  ON raw.pnp_instances (is_active, updated_at DESC);

CREATE TABLE IF NOT EXISTS raw.pnp_instance_selection (
  selection_id BIGSERIAL PRIMARY KEY,
  pipeline_id UUID,
  instance_key TEXT NOT NULL REFERENCES raw.pnp_instances(instance_key) ON DELETE CASCADE,
  ano_base TEXT NOT NULL,
  tipo_microdados TEXT NOT NULL,
  configured_microdados_url TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  selection_rank INTEGER,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_raw_pnp_instance_selection UNIQUE (instance_key, ano_base, tipo_microdados)
);

DROP TRIGGER IF EXISTS trg_pnp_instance_selection_updated_at ON raw.pnp_instance_selection;
CREATE TRIGGER trg_pnp_instance_selection_updated_at
BEFORE UPDATE ON raw.pnp_instance_selection
FOR EACH ROW
EXECUTE FUNCTION raw.touch_updated_at();

CREATE INDEX IF NOT EXISTS idx_raw_pnp_instance_selection_instance
  ON raw.pnp_instance_selection (instance_key, is_active, ano_base, tipo_microdados);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_instance_selection_pipeline
  ON raw.pnp_instance_selection (pipeline_id, is_active, ano_base, tipo_microdados);

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
  pipeline_id UUID,
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

CREATE INDEX IF NOT EXISTS idx_raw_pnp_pipeline_endpoints_pipeline
  ON raw.pnp_pipeline_endpoints (pipeline_id, is_active, endpoint_key);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_pipeline_endpoints_connection
  ON raw.pnp_pipeline_endpoints (connection_key, is_active, instance_key);

CREATE TABLE IF NOT EXISTS raw.pnp_runs (
  run_id TEXT PRIMARY KEY,
  instance_key TEXT,
  airflow_dag_id TEXT,
  airflow_dag_run_id TEXT,
  logical_date TIMESTAMPTZ,
  trigger_mode TEXT,
  requested_by TEXT,
  status TEXT NOT NULL,
  legacy_status TEXT,
  catalog_entry_count INTEGER NOT NULL DEFAULT 0,
  selected_download_count INTEGER NOT NULL DEFAULT 0,
  downloaded_file_count INTEGER NOT NULL DEFAULT 0,
  raw_record_count BIGINT NOT NULL DEFAULT 0,
  error_message TEXT,
  run_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_pnp_runs_airflow
  ON raw.pnp_runs (airflow_dag_id, airflow_dag_run_id)
  WHERE airflow_dag_id IS NOT NULL AND airflow_dag_run_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_raw_pnp_runs_instance_started
  ON raw.pnp_runs (instance_key, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_runs_status
  ON raw.pnp_runs (status, started_at DESC);

CREATE TABLE IF NOT EXISTS raw.pnp_run_steps (
  step_id BIGSERIAL PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES raw.pnp_runs(run_id) ON DELETE CASCADE,
  instance_key TEXT,
  airflow_task_id TEXT NOT NULL,
  map_index INTEGER,
  map_index_key INTEGER GENERATED ALWAYS AS (COALESCE(map_index, -1)) STORED,
  status TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  records_affected BIGINT,
  error_message TEXT,
  details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT uq_raw_pnp_run_steps_task_map UNIQUE (run_id, airflow_task_id, map_index_key)
);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_run_steps_run
  ON raw.pnp_run_steps (run_id, started_at DESC);

CREATE TABLE IF NOT EXISTS raw.pnp_run_packages (
  package_id BIGSERIAL PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES raw.pnp_runs(run_id) ON DELETE CASCADE,
  instance_key TEXT,
  airflow_dag_id TEXT,
  airflow_dag_run_id TEXT,
  airflow_task_id TEXT NOT NULL,
  package_type TEXT NOT NULL,
  package_name TEXT NOT NULL,
  package_status TEXT NOT NULL,
  records_affected BIGINT,
  payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_run_packages_run
  ON raw.pnp_run_packages (run_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_run_packages_task
  ON raw.pnp_run_packages (airflow_task_id, created_at DESC);

CREATE TABLE IF NOT EXISTS raw.pnp_catalog_entries (
  catalog_entry_id BIGSERIAL PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES raw.pnp_runs(run_id) ON DELETE CASCADE,
  instance_key TEXT,
  ano_base TEXT NOT NULL,
  tipo_microdados TEXT NOT NULL,
  microdados_url TEXT NOT NULL,
  resource_key TEXT,
  visual_id TEXT,
  api_base_url TEXT,
  catalog_hash TEXT,
  is_selected BOOLEAN NOT NULL DEFAULT FALSE,
  captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_raw_pnp_catalog_entries UNIQUE (run_id, ano_base, tipo_microdados, microdados_url)
);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_catalog_entries_run
  ON raw.pnp_catalog_entries (run_id, is_selected, ano_base, tipo_microdados);

CREATE TABLE IF NOT EXISTS raw.pnp_run_selection (
  run_selection_id BIGSERIAL PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES raw.pnp_runs(run_id) ON DELETE CASCADE,
  instance_key TEXT,
  ano_base TEXT NOT NULL,
  tipo_microdados TEXT NOT NULL,
  microdados_url TEXT NOT NULL,
  selection_source TEXT,
  selection_rank INTEGER,
  details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  selected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_raw_pnp_run_selection UNIQUE (run_id, ano_base, tipo_microdados, microdados_url)
);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_run_selection_run
  ON raw.pnp_run_selection (run_id, ano_base, tipo_microdados);

CREATE TABLE IF NOT EXISTS raw.pnp_downloads (
  download_id BIGSERIAL PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES raw.pnp_runs(run_id) ON DELETE CASCADE,
  instance_key TEXT,
  run_selection_id BIGINT REFERENCES raw.pnp_run_selection(run_selection_id) ON DELETE SET NULL,
  legacy_asset_id BIGINT,
  ano_base TEXT NOT NULL,
  tipo_microdados TEXT NOT NULL,
  microdados_url TEXT NOT NULL,
  source_file_name TEXT,
  source_file_sha256 TEXT,
  content_type TEXT,
  size_bytes BIGINT,
  row_count_raw BIGINT,
  status TEXT NOT NULL DEFAULT 'pending',
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  error_message TEXT,
  details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT uq_raw_pnp_downloads UNIQUE (run_id, microdados_url)
);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_downloads_run
  ON raw.pnp_downloads (run_id, status, ano_base, tipo_microdados);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_downloads_sha
  ON raw.pnp_downloads (source_file_sha256);

CREATE TABLE IF NOT EXISTS raw.pnp_download_columns (
  download_column_id BIGSERIAL PRIMARY KEY,
  download_id BIGINT NOT NULL REFERENCES raw.pnp_downloads(download_id) ON DELETE CASCADE,
  column_position INTEGER NOT NULL,
  column_name TEXT NOT NULL,
  normalized_column_name TEXT NOT NULL,
  captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_raw_pnp_download_columns_position UNIQUE (download_id, column_position)
);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_download_columns_download
  ON raw.pnp_download_columns (download_id, column_position);

CREATE TABLE IF NOT EXISTS raw.pnp_ingestion_quarantine (
  quarantine_id BIGSERIAL PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES raw.pnp_runs(run_id) ON DELETE CASCADE,
  instance_key TEXT,
  download_id BIGINT REFERENCES raw.pnp_downloads(download_id) ON DELETE SET NULL,
  source_row_number INTEGER,
  error_type TEXT NOT NULL,
  error_message TEXT NOT NULL,
  raw_line_text TEXT,
  details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_ingestion_quarantine_run
  ON raw.pnp_ingestion_quarantine (run_id, download_id, source_row_number);

CREATE TABLE IF NOT EXISTS raw.pnp_matriculas_src (
  raw_record_id BIGSERIAL PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES raw.pnp_runs(run_id) ON DELETE CASCADE,
  instance_key TEXT,
  download_id BIGINT REFERENCES raw.pnp_downloads(download_id) ON DELETE SET NULL,
  record_hash TEXT NOT NULL,
  source_record_id TEXT,
  source_row_number INTEGER,
  source_file_name TEXT,
  source_file_sha256 TEXT,
  source_url TEXT NOT NULL,
  ano_base TEXT,
  tipo_microdados TEXT NOT NULL,
  ano TEXT,
  carga_horaria TEXT,
  carga_horaria_minima TEXT,
  categoria_da_situacao TEXT,
  co_inst TEXT,
  cod_unidade TEXT,
  cor_raca TEXT,
  codigo_da_matricula TEXT,
  codigo_da_unidade_de_ensino_sistec TEXT,
  codigo_do_ciclo_matricula TEXT,
  codigo_do_municipio_com_dv TEXT,
  data_de_fim_previsto_do_ciclo TEXT,
  data_de_inicio_do_ciclo TEXT,
  data_de_ocorrencia_da_matricula TEXT,
  eixo_tecnologico TEXT,
  faixa_etaria TEXT,
  fator_esforco_curso TEXT,
  fonte_de_financiamento TEXT,
  forma_de_ingresso TEXT,
  habilitacao TEXT,
  idade TEXT,
  instituicao TEXT,
  matricula_atendida TEXT,
  modalidade_de_ensino TEXT,
  municipio TEXT,
  mes_de_ocorrencia_da_situacao TEXT,
  nome_de_curso TEXT,
  regiao TEXT,
  renda_familiar TEXT,
  sexo TEXT,
  situacao_de_matricula TEXT,
  subeixo_tecnologico TEXT,
  tipo_de_curso TEXT,
  tipo_de_oferta TEXT,
  total_de_inscritos TEXT,
  turno TEXT,
  uf TEXT,
  unidade_de_ensino TEXT,
  vagas_extraordinarias_ac TEXT,
  vagas_extraordinarias_l1 TEXT,
  vagas_extraordinarias_l10 TEXT,
  vagas_extraordinarias_l13 TEXT,
  vagas_extraordinarias_l14 TEXT,
  vagas_extraordinarias_l2 TEXT,
  vagas_extraordinarias_l5 TEXT,
  vagas_extraordinarias_l6 TEXT,
  vagas_extraordinarias_l9 TEXT,
  vagas_extraordinarias_lb_ppi TEXT,
  vagas_extraordinarias_lb_q TEXT,
  vagas_extraordinarias_lb_pcd TEXT,
  vagas_extraordinarias_lb_ep TEXT,
  vagas_extraordinarias_li_ppi TEXT,
  vagas_extraordinarias_li_q TEXT,
  vagas_extraordinarias_li_pcd TEXT,
  vagas_extraordinarias_li_ep TEXT,
  vagas_ofertadas TEXT,
  vagas_regulares_ac TEXT,
  vagas_regulares_l1 TEXT,
  vagas_regulares_l10 TEXT,
  vagas_regulares_l13 TEXT,
  vagas_regulares_l14 TEXT,
  vagas_regulares_l2 TEXT,
  vagas_regulares_l5 TEXT,
  vagas_regulares_l6 TEXT,
  vagas_regulares_l9 TEXT,
  vagas_regulares_lb_ppi TEXT,
  vagas_regulares_lb_q TEXT,
  vagas_regulares_lb_pcd TEXT,
  vagas_regulares_lb_ep TEXT,
  vagas_regulares_li_ppi TEXT,
  vagas_regulares_li_q TEXT,
  vagas_regulares_li_pcd TEXT,
  vagas_regulares_li_ep TEXT,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_raw_pnp_matriculas_src_run_download_row UNIQUE (run_id, download_id, source_row_number)
);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_matriculas_src_run
  ON raw.pnp_matriculas_src (run_id, download_id);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_matriculas_src_hash
  ON raw.pnp_matriculas_src (record_hash);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_matriculas_src_instance_hash
  ON raw.pnp_matriculas_src (instance_key, record_hash);

CREATE TABLE IF NOT EXISTS raw.pnp_eficiencia_academica_src (
  raw_record_id BIGSERIAL PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES raw.pnp_runs(run_id) ON DELETE CASCADE,
  instance_key TEXT,
  download_id BIGINT REFERENCES raw.pnp_downloads(download_id) ON DELETE SET NULL,
  record_hash TEXT NOT NULL,
  source_record_id TEXT,
  source_row_number INTEGER,
  source_file_name TEXT,
  source_file_sha256 TEXT,
  source_url TEXT NOT NULL,
  ano_base TEXT,
  tipo_microdados TEXT NOT NULL,
  ano TEXT,
  carga_horaria TEXT,
  carga_horaria_minima TEXT,
  categoria_da_situacao TEXT,
  co_inst TEXT,
  cod_unidade TEXT,
  cor_raca TEXT,
  codigo_da_matricula TEXT,
  codigo_da_unidade_de_ensino_sistec TEXT,
  codigo_do_ciclo_matricula TEXT,
  codigo_do_municipio_com_dv TEXT,
  data_de_fim_previsto_do_ciclo TEXT,
  data_de_inicio_do_ciclo TEXT,
  data_de_ocorrencia_da_matricula TEXT,
  eixo_tecnologico TEXT,
  faixa_etaria TEXT,
  fator_esforco_curso TEXT,
  fonte_de_financiamento TEXT,
  forma_de_ingresso TEXT,
  habilitacao TEXT,
  idade TEXT,
  instituicao TEXT,
  matricula_atendida TEXT,
  modalidade_de_ensino TEXT,
  municipio TEXT,
  mes_de_ocorrencia_da_situacao TEXT,
  nome_de_curso TEXT,
  regiao TEXT,
  renda_familiar TEXT,
  sexo TEXT,
  situacao_de_matricula TEXT,
  subeixo_tecnologico TEXT,
  tipo_de_curso TEXT,
  tipo_de_oferta TEXT,
  total_de_inscritos TEXT,
  turno TEXT,
  uf TEXT,
  unidade_de_ensino TEXT,
  vagas_extraordinarias_ac TEXT,
  vagas_extraordinarias_l1 TEXT,
  vagas_extraordinarias_l10 TEXT,
  vagas_extraordinarias_l13 TEXT,
  vagas_extraordinarias_l14 TEXT,
  vagas_extraordinarias_l2 TEXT,
  vagas_extraordinarias_l5 TEXT,
  vagas_extraordinarias_l6 TEXT,
  vagas_extraordinarias_l9 TEXT,
  vagas_extraordinarias_lb_ppi TEXT,
  vagas_extraordinarias_lb_q TEXT,
  vagas_extraordinarias_lb_pcd TEXT,
  vagas_extraordinarias_lb_ep TEXT,
  vagas_extraordinarias_li_ppi TEXT,
  vagas_extraordinarias_li_q TEXT,
  vagas_extraordinarias_li_pcd TEXT,
  vagas_extraordinarias_li_ep TEXT,
  vagas_ofertadas TEXT,
  vagas_regulares_ac TEXT,
  vagas_regulares_l1 TEXT,
  vagas_regulares_l10 TEXT,
  vagas_regulares_l13 TEXT,
  vagas_regulares_l14 TEXT,
  vagas_regulares_l2 TEXT,
  vagas_regulares_l5 TEXT,
  vagas_regulares_l6 TEXT,
  vagas_regulares_l9 TEXT,
  vagas_regulares_lb_ppi TEXT,
  vagas_regulares_lb_q TEXT,
  vagas_regulares_lb_pcd TEXT,
  vagas_regulares_lb_ep TEXT,
  vagas_regulares_li_ppi TEXT,
  vagas_regulares_li_q TEXT,
  vagas_regulares_li_pcd TEXT,
  vagas_regulares_li_ep TEXT,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_raw_pnp_eficiencia_src_run_download_row UNIQUE (run_id, download_id, source_row_number)
);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_eficiencia_src_run
  ON raw.pnp_eficiencia_academica_src (run_id, download_id);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_eficiencia_src_hash
  ON raw.pnp_eficiencia_academica_src (record_hash);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_eficiencia_src_instance_hash
  ON raw.pnp_eficiencia_academica_src (instance_key, record_hash);

CREATE TABLE IF NOT EXISTS raw.pnp_financeiro_src (
  raw_record_id BIGSERIAL PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES raw.pnp_runs(run_id) ON DELETE CASCADE,
  instance_key TEXT,
  download_id BIGINT REFERENCES raw.pnp_downloads(download_id) ON DELETE SET NULL,
  record_hash TEXT NOT NULL,
  source_record_id TEXT,
  source_row_number INTEGER,
  source_file_name TEXT,
  source_file_sha256 TEXT,
  source_url TEXT NOT NULL,
  ano_base TEXT,
  tipo_microdados TEXT NOT NULL,
  uo TEXT,
  nome_uo TEXT,
  cod_acao TEXT,
  nome_acao TEXT,
  grupo_despesa TEXT,
  liquidacoes_totais TEXT,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_raw_pnp_financeiro_src_run_download_row UNIQUE (run_id, download_id, source_row_number)
);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_financeiro_src_run
  ON raw.pnp_financeiro_src (run_id, download_id);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_financeiro_src_hash
  ON raw.pnp_financeiro_src (record_hash);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_financeiro_src_instance_hash
  ON raw.pnp_financeiro_src (instance_key, record_hash);

CREATE TABLE IF NOT EXISTS raw.pnp_servidores_src (
  raw_record_id BIGSERIAL PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES raw.pnp_runs(run_id) ON DELETE CASCADE,
  instance_key TEXT,
  download_id BIGINT REFERENCES raw.pnp_downloads(download_id) ON DELETE SET NULL,
  record_hash TEXT NOT NULL,
  source_record_id TEXT,
  source_row_number INTEGER,
  source_file_name TEXT,
  source_file_sha256 TEXT,
  source_url TEXT NOT NULL,
  ano_base TEXT,
  tipo_microdados TEXT NOT NULL,
  classe TEXT,
  cod_unidade TEXT,
  codigo_da_unidade_de_ensino_sistec TEXT,
  codigo_municipio_com_dv TEXT,
  instituicao TEXT,
  jornada_de_trabalho TEXT,
  matricula TEXT,
  municipio TEXT,
  regiao TEXT,
  rsc TEXT,
  titulacao TEXT,
  unidade_de_lotacao TEXT,
  vinculo_carreira TEXT,
  vinculo_contrato TEXT,
  vinculo_professor TEXT,
  numero_de_registros TEXT,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_raw_pnp_servidores_src_run_download_row UNIQUE (run_id, download_id, source_row_number)
);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_servidores_src_run
  ON raw.pnp_servidores_src (run_id, download_id);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_servidores_src_hash
  ON raw.pnp_servidores_src (record_hash);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_servidores_src_instance_hash
  ON raw.pnp_servidores_src (instance_key, record_hash);

CREATE TABLE IF NOT EXISTS staging.pnp_ingestion_runs (
  run_id TEXT PRIMARY KEY REFERENCES raw.pnp_runs(run_id) ON DELETE CASCADE,
  instance_key TEXT,
  status TEXT NOT NULL,
  selected_download_count INTEGER NOT NULL DEFAULT 0,
  downloaded_file_count INTEGER NOT NULL DEFAULT 0,
  raw_record_count BIGINT NOT NULL DEFAULT 0,
  deduplicated_record_count BIGINT NOT NULL DEFAULT 0,
  quality_status TEXT,
  quality_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS staging.pnp_matriculas (
  raw_record_id BIGINT PRIMARY KEY REFERENCES raw.pnp_matriculas_src(raw_record_id) ON DELETE CASCADE,
  run_id TEXT NOT NULL,
  instance_key TEXT,
  ano INTEGER,
  instituicao TEXT,
  regiao TEXT,
  uf TEXT,
  municipio TEXT,
  sexo TEXT,
  cor_raca TEXT,
  renda_familiar TEXT,
  faixa_etaria TEXT,
  situacao_matricula TEXT,
  modalidade_ensino TEXT,
  tipo_curso TEXT,
  tipo_oferta TEXT,
  turno TEXT,
  eixo_tecnologico TEXT,
  subeixo_tecnologico TEXT,
  nome_curso TEXT,
  total_inscritos NUMERIC,
  vagas_ofertadas NUMERIC,
  processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_staging_pnp_matriculas_ano_inst
  ON staging.pnp_matriculas (ano, instituicao, uf, municipio);

CREATE TABLE IF NOT EXISTS staging.pnp_eficiencia_academica (
  raw_record_id BIGINT PRIMARY KEY REFERENCES raw.pnp_eficiencia_academica_src(raw_record_id) ON DELETE CASCADE,
  run_id TEXT NOT NULL,
  instance_key TEXT,
  ano INTEGER,
  instituicao TEXT,
  regiao TEXT,
  uf TEXT,
  municipio TEXT,
  sexo TEXT,
  cor_raca TEXT,
  renda_familiar TEXT,
  faixa_etaria TEXT,
  categoria_situacao TEXT,
  situacao_matricula TEXT,
  matricula_atendida TEXT,
  processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_staging_pnp_eficiencia_ano_inst
  ON staging.pnp_eficiencia_academica (ano, instituicao, uf, municipio);

CREATE TABLE IF NOT EXISTS staging.pnp_servidores (
  raw_record_id BIGINT PRIMARY KEY REFERENCES raw.pnp_servidores_src(raw_record_id) ON DELETE CASCADE,
  run_id TEXT NOT NULL,
  instance_key TEXT,
  ano INTEGER,
  instituicao TEXT,
  regiao TEXT,
  uf TEXT,
  municipio TEXT,
  classe TEXT,
  jornada_trabalho TEXT,
  titulacao TEXT,
  rsc TEXT,
  vinculo_carreira TEXT,
  vinculo_contrato TEXT,
  vinculo_professor TEXT,
  numero_registros NUMERIC,
  processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_staging_pnp_servidores_ano_inst
  ON staging.pnp_servidores (ano, instituicao, regiao);

CREATE TABLE IF NOT EXISTS staging.pnp_financeiro (
  raw_record_id BIGINT PRIMARY KEY REFERENCES raw.pnp_financeiro_src(raw_record_id) ON DELETE CASCADE,
  run_id TEXT NOT NULL,
  instance_key TEXT,
  ano INTEGER,
  nome_uo TEXT,
  uo TEXT,
  cod_acao TEXT,
  nome_acao TEXT,
  grupo_despesa TEXT,
  liquidacoes_totais NUMERIC,
  processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_staging_pnp_financeiro_ano_uo
  ON staging.pnp_financeiro (ano, nome_uo, cod_acao, grupo_despesa);
