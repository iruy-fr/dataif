WITH selected_rows AS (
    SELECT
        src.*,
        ROW_NUMBER() OVER (
            PARTITION BY src.instance_key, src.record_hash
            ORDER BY src.raw_record_id DESC
        ) AS dedup_rank
    FROM raw.pnp_servidores_src src
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
INSERT INTO staging.pnp_servidores (
    raw_record_id,
    run_id,
    instance_key,
    ano,
    instituicao,
    regiao,
    uf,
    municipio,
    classe,
    jornada_trabalho,
    titulacao,
    rsc,
    vinculo_carreira,
    vinculo_contrato,
    vinculo_professor,
    numero_registros,
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
    NULLIF(deduplicated_rows.instituicao, '') AS instituicao,
    NULLIF(deduplicated_rows.regiao, '') AS regiao,
    NULLIF(NULL::TEXT, '') AS uf,
    NULLIF(deduplicated_rows.municipio, '') AS municipio,
    NULLIF(deduplicated_rows.classe, '') AS classe,
    NULLIF(deduplicated_rows.jornada_de_trabalho, '') AS jornada_trabalho,
    NULLIF(deduplicated_rows.titulacao, '') AS titulacao,
    NULLIF(deduplicated_rows.rsc, '') AS rsc,
    NULLIF(deduplicated_rows.vinculo_carreira, '') AS vinculo_carreira,
    NULLIF(deduplicated_rows.vinculo_contrato, '') AS vinculo_contrato,
    NULLIF(deduplicated_rows.vinculo_professor, '') AS vinculo_professor,
    CASE
        WHEN REPLACE(REPLACE(NULLIF(BTRIM(deduplicated_rows.numero_de_registros), ''), '.', ''), ',', '.') ~ '^-?[0-9]+(\.[0-9]+)?$'
            THEN REPLACE(REPLACE(NULLIF(BTRIM(deduplicated_rows.numero_de_registros), ''), '.', ''), ',', '.')::NUMERIC
        ELSE NULL
    END AS numero_registros,
    NOW()
FROM deduplicated_rows
ON CONFLICT (raw_record_id) DO UPDATE
SET
    run_id = EXCLUDED.run_id,
    instance_key = EXCLUDED.instance_key,
    ano = EXCLUDED.ano,
    instituicao = EXCLUDED.instituicao,
    regiao = EXCLUDED.regiao,
    uf = EXCLUDED.uf,
    municipio = EXCLUDED.municipio,
    classe = EXCLUDED.classe,
    jornada_trabalho = EXCLUDED.jornada_trabalho,
    titulacao = EXCLUDED.titulacao,
    rsc = EXCLUDED.rsc,
    vinculo_carreira = EXCLUDED.vinculo_carreira,
    vinculo_contrato = EXCLUDED.vinculo_contrato,
    vinculo_professor = EXCLUDED.vinculo_professor,
    numero_registros = EXCLUDED.numero_registros,
    processed_at = NOW();
