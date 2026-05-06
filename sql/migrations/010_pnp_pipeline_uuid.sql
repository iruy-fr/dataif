CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE raw.pnp_instances
  ADD COLUMN IF NOT EXISTS pipeline_id UUID;

ALTER TABLE raw.pnp_instances
  ALTER COLUMN pipeline_id SET DEFAULT gen_random_uuid();

UPDATE raw.pnp_instances
SET pipeline_id = gen_random_uuid()
WHERE pipeline_id IS NULL;

ALTER TABLE raw.pnp_instances
  ALTER COLUMN pipeline_id SET NOT NULL;

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

ALTER TABLE raw.pnp_instance_selection
  ADD COLUMN IF NOT EXISTS pipeline_id UUID;

UPDATE raw.pnp_instance_selection selection
SET pipeline_id = instances.pipeline_id
FROM raw.pnp_instances instances
WHERE instances.instance_key = selection.instance_key
  AND (selection.pipeline_id IS NULL OR selection.pipeline_id <> instances.pipeline_id);

ALTER TABLE raw.pnp_pipeline_endpoints
  ADD COLUMN IF NOT EXISTS pipeline_id UUID;

UPDATE raw.pnp_pipeline_endpoints pipeline_endpoints
SET pipeline_id = instances.pipeline_id
FROM raw.pnp_instances instances
WHERE instances.instance_key = pipeline_endpoints.instance_key
  AND (pipeline_endpoints.pipeline_id IS NULL OR pipeline_endpoints.pipeline_id <> instances.pipeline_id);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_instance_selection_pipeline
  ON raw.pnp_instance_selection (pipeline_id, is_active, ano_base, tipo_microdados);

CREATE INDEX IF NOT EXISTS idx_raw_pnp_pipeline_endpoints_pipeline
  ON raw.pnp_pipeline_endpoints (pipeline_id, is_active, endpoint_key);
