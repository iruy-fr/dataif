WITH selected_rows AS (
    SELECT
        src.*,
        ROW_NUMBER() OVER (
            PARTITION BY src.instance_key, src.record_hash
            ORDER BY src.raw_record_id DESC
        ) AS dedup_rank
    FROM raw.pnp_financeiro_src src
    LEFT JOIN raw.pnp_downloads downloads ON downloads.download_id = src.download_id
    JOIN raw.pnp_instance_selection selection
      ON selection.instance_key = src.instance_key
     AND selection.is_active = TRUE
     AND selection.ano_base = src.ano_base
     AND selection.tipo_microdados = src.tipo_microdados
     AND (
        selection.configured_microdados_url IS NULL
        OR selection.configured_microdados_url = downloads.microdados_url
     )
    WHERE src.run_id = %(run_id)s
      AND src.instance_key IS NOT DISTINCT FROM %(instance_key)s
      AND src.download_id = %(download_id)s
),
deduplicated_rows AS (
    SELECT *
    FROM selected_rows
    WHERE dedup_rank = 1
)
INSERT INTO staging.pnp_financeiro (
    raw_record_id,
    run_id,
    instance_key,
    ano,
    nome_uo,
    uo,
    cod_acao,
    nome_acao,
    grupo_despesa,
    liquidacoes_totais,
    processed_at
)
SELECT
    deduplicated_rows.raw_record_id,
    deduplicated_rows.run_id,
    deduplicated_rows.instance_key,
    CASE
        WHEN NULLIF(deduplicated_rows.ano_base, '') ~ '^[0-9]{1,4}$' THEN deduplicated_rows.ano_base::INTEGER
        ELSE NULL
    END AS ano,
    NULLIF(deduplicated_rows.nome_uo, '') AS nome_uo,
    NULLIF(deduplicated_rows.uo, '') AS uo,
    NULLIF(deduplicated_rows.cod_acao, '') AS cod_acao,
    NULLIF(deduplicated_rows.nome_acao, '') AS nome_acao,
    NULLIF(deduplicated_rows.grupo_despesa, '') AS grupo_despesa,
    CASE
        WHEN REPLACE(REPLACE(NULLIF(BTRIM(deduplicated_rows.liquidacoes_totais), ''), '.', ''), ',', '.') ~ '^-?[0-9]+(\.[0-9]+)?$'
            THEN REPLACE(REPLACE(NULLIF(BTRIM(deduplicated_rows.liquidacoes_totais), ''), '.', ''), ',', '.')::NUMERIC
        ELSE NULL
    END AS liquidacoes_totais,
    NOW()
FROM deduplicated_rows
ON CONFLICT (raw_record_id) DO UPDATE
SET
    run_id = EXCLUDED.run_id,
    instance_key = EXCLUDED.instance_key,
    ano = EXCLUDED.ano,
    nome_uo = EXCLUDED.nome_uo,
    uo = EXCLUDED.uo,
    cod_acao = EXCLUDED.cod_acao,
    nome_acao = EXCLUDED.nome_acao,
    grupo_despesa = EXCLUDED.grupo_despesa,
    liquidacoes_totais = EXCLUDED.liquidacoes_totais,
    processed_at = NOW();
