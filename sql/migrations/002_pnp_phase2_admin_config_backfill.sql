WITH explicit_connections AS (
  SELECT DISTINCT ON (connection_key)
    COALESCE(NULLIF(request_params->>'connection_key', ''), REPLACE(endpoint_key, '__connection', '')) AS connection_key,
    COALESCE(
      NULLIF(request_params->>'connection_name', ''),
      NULLIF(description, ''),
      COALESCE(NULLIF(request_params->>'connection_key', ''), REPLACE(endpoint_key, '__connection', ''))
    ) AS connection_name,
    COALESCE(NULLIF(page_url, ''), NULLIF(api_endpoint_url, ''), NULLIF(csv_url, '')) AS page_url,
    is_active,
    jsonb_build_object(
      'legacy_source', 'config.connector_endpoints',
      'legacy_endpoint_key', endpoint_key,
      'legacy_description', description,
      'legacy_request_params', request_params
    ) AS metadata,
    created_at,
    updated_at,
    CASE
      WHEN COALESCE(request_params->>'deleted', 'false') = 'true'
        THEN COALESCE(NULLIF(request_params->>'deleted_at', '')::timestamptz, updated_at)
      ELSE NULL
    END AS deleted_at
  FROM config.connector_endpoints
  WHERE connector_id = 'nilo_pecanha'
    AND request_params->>'mode' = 'powerbi_microdados'
    AND COALESCE(request_params->>'entity_type', 'pipeline') = 'connection'
    AND COALESCE(NULLIF(request_params->>'connection_key', ''), REPLACE(endpoint_key, '__connection', '')) IS NOT NULL
  ORDER BY connection_key, updated_at DESC, id DESC
)
INSERT INTO raw.pnp_connections (
  connection_key,
  connection_name,
  page_url,
  is_active,
  metadata,
  created_at,
  updated_at,
  deleted_at
)
SELECT
  connection_key,
  connection_name,
  page_url,
  is_active,
  metadata,
  created_at,
  updated_at,
  deleted_at
FROM explicit_connections
WHERE connection_key IS NOT NULL
  AND connection_name IS NOT NULL
  AND page_url IS NOT NULL
ON CONFLICT (connection_key) DO UPDATE
SET
  connection_name = EXCLUDED.connection_name,
  page_url = EXCLUDED.page_url,
  is_active = EXCLUDED.is_active,
  metadata = EXCLUDED.metadata,
  updated_at = EXCLUDED.updated_at,
  deleted_at = EXCLUDED.deleted_at;

WITH instances_needing_connection AS (
  SELECT DISTINCT
    page_url
  FROM raw.pnp_instances
  WHERE page_url IS NOT NULL
    AND (
      COALESCE(connection_key, '') = ''
      OR NOT EXISTS (
        SELECT 1
        FROM raw.pnp_connections c
        WHERE c.connection_key = raw.pnp_instances.connection_key
      )
    )
),
fallback_connections AS (
  SELECT
    CASE
      WHEN ROW_NUMBER() OVER (ORDER BY page_url) = 1 THEN 'pnp_conn_principal'
      ELSE format('pnp_conn_principal_%s', lpad(ROW_NUMBER() OVER (ORDER BY page_url)::text, 2, '0'))
    END AS connection_key,
    CASE
      WHEN ROW_NUMBER() OVER (ORDER BY page_url) = 1 THEN 'PNP Principal'
      ELSE format('PNP Principal %s', ROW_NUMBER() OVER (ORDER BY page_url))
    END AS connection_name,
    page_url
  FROM instances_needing_connection
)
INSERT INTO raw.pnp_connections (
  connection_key,
  connection_name,
  page_url,
  is_active,
  metadata
)
SELECT
  connection_key,
  connection_name,
  page_url,
  TRUE,
  jsonb_build_object(
    'backfill_source', 'raw.pnp_instances.page_url',
    'synthetic', TRUE
  )
FROM fallback_connections
ON CONFLICT (connection_key) DO UPDATE
SET
  connection_name = EXCLUDED.connection_name,
  page_url = EXCLUDED.page_url,
  metadata = raw.pnp_connections.metadata || EXCLUDED.metadata;

WITH resolved_connections AS (
  SELECT
    i.instance_key,
    COALESCE(i.connection_key, fallback.connection_key) AS connection_key,
    COALESCE(NULLIF(i.connection_name, ''), explicit.connection_name, fallback.connection_name) AS connection_name
  FROM raw.pnp_instances i
  LEFT JOIN raw.pnp_connections explicit
    ON explicit.connection_key = i.connection_key
  LEFT JOIN raw.pnp_connections fallback
    ON fallback.page_url = i.page_url
   AND COALESCE(i.connection_key, '') = ''
)
UPDATE raw.pnp_instances i
SET
  connection_key = resolved.connection_key,
  connection_name = resolved.connection_name,
  updated_at = NOW()
FROM resolved_connections resolved
WHERE i.instance_key = resolved.instance_key
  AND resolved.connection_key IS NOT NULL
  AND (
    COALESCE(i.connection_key, '') <> resolved.connection_key
    OR COALESCE(i.connection_name, '') <> COALESCE(resolved.connection_name, '')
  );

WITH connection_status AS (
  SELECT
    c.connection_key,
    BOOL_OR(i.deleted_at IS NULL AND i.is_active = TRUE) AS has_active_instances,
    MAX(i.deleted_at) AS latest_instance_deleted_at
  FROM raw.pnp_connections c
  LEFT JOIN raw.pnp_instances i
    ON i.connection_key = c.connection_key
  GROUP BY c.connection_key
)
UPDATE raw.pnp_connections c
SET
  is_active = COALESCE(status.has_active_instances, c.is_active),
  deleted_at = CASE
    WHEN COALESCE(status.has_active_instances, FALSE) THEN NULL
    ELSE COALESCE(c.deleted_at, status.latest_instance_deleted_at)
  END,
  updated_at = NOW()
FROM connection_status status
WHERE c.connection_key = status.connection_key;

WITH instance_connection AS (
  SELECT
    instance_key,
    connection_key,
    connection_name
  FROM raw.pnp_instances
  WHERE connection_key IS NOT NULL
)
UPDATE config.connector_endpoints e
SET
  request_params = jsonb_set(
    jsonb_set(COALESCE(e.request_params, '{}'::jsonb), '{connection_key}', to_jsonb(ic.connection_key), TRUE),
    '{connection_name}',
    to_jsonb(ic.connection_name),
    TRUE
  ),
  updated_at = NOW()
FROM instance_connection ic
WHERE e.connector_id = 'nilo_pecanha'
  AND e.request_params->>'mode' = 'powerbi_microdados'
  AND COALESCE(e.request_params->>'entity_type', 'pipeline') <> 'connection'
  AND COALESCE(NULLIF(e.request_params->>'instance_key', ''), NULLIF(e.request_params->>'pipeline_key', '')) = ic.instance_key
  AND (
    COALESCE(e.request_params->>'connection_key', '') <> ic.connection_key
    OR COALESCE(e.request_params->>'connection_name', '') <> ic.connection_name
  );
