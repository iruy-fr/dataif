WITH selected_rows AS (
    SELECT
        src.*,
        ROW_NUMBER() OVER (
            PARTITION BY src.instance_key, src.record_hash
            ORDER BY src.raw_record_id DESC
        ) AS dedup_rank
    FROM raw.pnp_eficiencia_academica_src src
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
INSERT INTO staging.pnp_eficiencia_academica (
    raw_record_id,
    run_id,
    instance_key,
    ano,
    instituicao,
    regiao,
    uf,
    municipio,
    sexo,
    cor_raca,
    renda_familiar,
    faixa_etaria,
    categoria_situacao,
    situacao_matricula,
    matricula_atendida,
    processed_at
)
SELECT
    deduplicated_rows.raw_record_id,
    deduplicated_rows.run_id,
    deduplicated_rows.instance_key,
    CASE
        WHEN NULLIF(deduplicated_rows.ano, '') ~ '^[0-9]{1,4}$' THEN deduplicated_rows.ano::INTEGER
        ELSE NULL
    END AS ano,
    NULLIF(deduplicated_rows.instituicao, '') AS instituicao,
    NULLIF(deduplicated_rows.regiao, '') AS regiao,
    NULLIF(deduplicated_rows.uf, '') AS uf,
    NULLIF(deduplicated_rows.municipio, '') AS municipio,
    NULLIF(deduplicated_rows.sexo, '') AS sexo,
    NULLIF(deduplicated_rows.cor_raca, '') AS cor_raca,
    NULLIF(deduplicated_rows.renda_familiar, '') AS renda_familiar,
    NULLIF(deduplicated_rows.faixa_etaria, '') AS faixa_etaria,
    NULLIF(deduplicated_rows.categoria_da_situacao, '') AS categoria_situacao,
    NULLIF(deduplicated_rows.situacao_de_matricula, '') AS situacao_matricula,
    NULLIF(deduplicated_rows.matricula_atendida, '') AS matricula_atendida,
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
    sexo = EXCLUDED.sexo,
    cor_raca = EXCLUDED.cor_raca,
    renda_familiar = EXCLUDED.renda_familiar,
    faixa_etaria = EXCLUDED.faixa_etaria,
    categoria_situacao = EXCLUDED.categoria_situacao,
    situacao_matricula = EXCLUDED.situacao_matricula,
    matricula_atendida = EXCLUDED.matricula_atendida,
    processed_at = NOW();
