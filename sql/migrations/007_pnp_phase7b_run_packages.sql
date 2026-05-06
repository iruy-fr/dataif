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
