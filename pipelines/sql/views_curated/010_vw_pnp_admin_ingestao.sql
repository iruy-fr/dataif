CREATE OR REPLACE VIEW curated.vw_pnp_admin_ingestao AS
WITH package_counts AS (
    SELECT
        run_id,
        COUNT(*) AS package_count
    FROM raw.pnp_run_packages
    GROUP BY run_id
),
quarantine_counts AS (
    SELECT
        run_id,
        COUNT(*) AS quarantine_count
    FROM raw.pnp_ingestion_quarantine
    GROUP BY run_id
)
SELECT
    runs.run_id,
    runs.instance_key,
    instances.connection_key,
    instances.connection_name,
    runs.airflow_dag_id,
    runs.airflow_dag_run_id,
    runs.trigger_mode,
    runs.requested_by,
    runs.logical_date,
    runs.status,
    runs.catalog_entry_count,
    runs.selected_download_count,
    runs.downloaded_file_count,
    runs.raw_record_count,
    COALESCE(staging.deduplicated_record_count, 0) AS staging_record_count,
    COALESCE(package_counts.package_count, 0) AS package_count,
    COALESCE(quarantine_counts.quarantine_count, 0) AS quarantine_count,
    staging.quality_status,
    runs.started_at,
    runs.finished_at,
    CASE
        WHEN runs.finished_at IS NULL THEN NULL
        ELSE EXTRACT(EPOCH FROM (runs.finished_at - runs.started_at))::BIGINT
    END AS duration_seconds,
    runs.error_message,
    runs.run_summary_json
FROM raw.pnp_runs runs
LEFT JOIN raw.pnp_instances instances
  ON instances.instance_key = runs.instance_key
LEFT JOIN staging.pnp_ingestion_runs staging
  ON staging.run_id = runs.run_id
LEFT JOIN package_counts
  ON package_counts.run_id = runs.run_id
LEFT JOIN quarantine_counts
  ON quarantine_counts.run_id = runs.run_id;
