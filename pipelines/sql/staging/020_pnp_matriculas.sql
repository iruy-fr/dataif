WITH selected_rows AS (
    SELECT
        src.*,
        ROW_NUMBER() OVER (
            PARTITION BY src.instance_key, src.record_hash
            ORDER BY src.raw_record_id DESC
        ) AS dedup_rank
    FROM raw.pnp_matriculas_src src
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
INSERT INTO staging.pnp_matriculas (
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
    situacao_matricula,
    modalidade_ensino,
    tipo_curso,
    tipo_oferta,
    turno,
    eixo_tecnologico,
    subeixo_tecnologico,
    nome_curso,
    total_inscritos,
    vagas_ofertadas,
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
    NULLIF(deduplicated_rows.situacao_de_matricula, '') AS situacao_matricula,
    NULLIF(deduplicated_rows.modalidade_de_ensino, '') AS modalidade_ensino,
    NULLIF(deduplicated_rows.tipo_de_curso, '') AS tipo_curso,
    NULLIF(deduplicated_rows.tipo_de_oferta, '') AS tipo_oferta,
    NULLIF(deduplicated_rows.turno, '') AS turno,
    NULLIF(deduplicated_rows.eixo_tecnologico, '') AS eixo_tecnologico,
    NULLIF(deduplicated_rows.subeixo_tecnologico, '') AS subeixo_tecnologico,
    NULLIF(deduplicated_rows.nome_de_curso, '') AS nome_curso,
    CASE
        WHEN REPLACE(REPLACE(NULLIF(BTRIM(deduplicated_rows.total_de_inscritos), ''), '.', ''), ',', '.') ~ '^-?[0-9]+(\.[0-9]+)?$'
            THEN REPLACE(REPLACE(NULLIF(BTRIM(deduplicated_rows.total_de_inscritos), ''), '.', ''), ',', '.')::NUMERIC
        ELSE NULL
    END AS total_inscritos,
    CASE
        WHEN REPLACE(REPLACE(NULLIF(BTRIM(deduplicated_rows.vagas_ofertadas), ''), '.', ''), ',', '.') ~ '^-?[0-9]+(\.[0-9]+)?$'
            THEN REPLACE(REPLACE(NULLIF(BTRIM(deduplicated_rows.vagas_ofertadas), ''), '.', ''), ',', '.')::NUMERIC
        ELSE NULL
    END AS vagas_ofertadas,
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
    situacao_matricula = EXCLUDED.situacao_matricula,
    modalidade_ensino = EXCLUDED.modalidade_ensino,
    tipo_curso = EXCLUDED.tipo_curso,
    tipo_oferta = EXCLUDED.tipo_oferta,
    turno = EXCLUDED.turno,
    eixo_tecnologico = EXCLUDED.eixo_tecnologico,
    subeixo_tecnologico = EXCLUDED.subeixo_tecnologico,
    nome_curso = EXCLUDED.nome_curso,
    total_inscritos = EXCLUDED.total_inscritos,
    vagas_ofertadas = EXCLUDED.vagas_ofertadas,
    processed_at = NOW();
