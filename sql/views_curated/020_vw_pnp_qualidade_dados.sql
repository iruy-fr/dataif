CREATE OR REPLACE VIEW curated.vw_pnp_qualidade_dados AS
WITH quality_rows AS (
    SELECT
        run_id,
        instance_key,
        'Matrículas'::TEXT AS tipo_microdados,
        instituicao,
        uf,
        sexo,
        cor_raca,
        renda_familiar,
        faixa_etaria,
        NULL::NUMERIC AS liquidacoes_totais,
        NULL::NUMERIC AS numero_registros
    FROM staging.pnp_matriculas
    UNION ALL
    SELECT
        run_id,
        instance_key,
        'Eficiência Acadêmica'::TEXT AS tipo_microdados,
        instituicao,
        uf,
        sexo,
        cor_raca,
        renda_familiar,
        faixa_etaria,
        NULL::NUMERIC AS liquidacoes_totais,
        NULL::NUMERIC AS numero_registros
    FROM staging.pnp_eficiencia_academica
    UNION ALL
    SELECT
        run_id,
        instance_key,
        'Servidores'::TEXT AS tipo_microdados,
        instituicao,
        NULL::TEXT AS uf,
        NULL::TEXT AS sexo,
        NULL::TEXT AS cor_raca,
        NULL::TEXT AS renda_familiar,
        NULL::TEXT AS faixa_etaria,
        NULL::NUMERIC AS liquidacoes_totais,
        numero_registros
    FROM staging.pnp_servidores
    UNION ALL
    SELECT
        run_id,
        instance_key,
        'Financeiro'::TEXT AS tipo_microdados,
        NULL::TEXT AS instituicao,
        NULL::TEXT AS uf,
        NULL::TEXT AS sexo,
        NULL::TEXT AS cor_raca,
        NULL::TEXT AS renda_familiar,
        NULL::TEXT AS faixa_etaria,
        liquidacoes_totais,
        NULL::NUMERIC AS numero_registros
    FROM staging.pnp_financeiro
)
SELECT
    quality_rows.run_id,
    quality_rows.instance_key,
    quality_rows.tipo_microdados,
    COUNT(*) AS registros,
    COUNT(*) FILTER (
        WHERE quality_rows.tipo_microdados <> 'Financeiro'
          AND quality_rows.instituicao IS NULL
    ) AS registros_sem_instituicao,
    COUNT(*) FILTER (
        WHERE quality_rows.tipo_microdados IN ('Matrículas', 'Eficiência Acadêmica')
          AND quality_rows.uf IS NULL
    ) AS registros_sem_uf,
    COUNT(*) FILTER (
        WHERE quality_rows.tipo_microdados IN ('Matrículas', 'Eficiência Acadêmica')
          AND quality_rows.sexo IS NULL
    ) AS registros_sem_sexo,
    COUNT(*) FILTER (
        WHERE quality_rows.tipo_microdados IN ('Matrículas', 'Eficiência Acadêmica')
          AND quality_rows.cor_raca IS NULL
    ) AS registros_sem_cor_raca,
    COUNT(*) FILTER (
        WHERE quality_rows.tipo_microdados IN ('Matrículas', 'Eficiência Acadêmica')
          AND quality_rows.renda_familiar IS NULL
    ) AS registros_sem_renda_familiar,
    COUNT(*) FILTER (
        WHERE quality_rows.tipo_microdados IN ('Matrículas', 'Eficiência Acadêmica')
          AND quality_rows.faixa_etaria IS NULL
    ) AS registros_sem_faixa_etaria,
    COUNT(*) FILTER (
        WHERE quality_rows.tipo_microdados = 'Financeiro'
          AND quality_rows.liquidacoes_totais IS NULL
    ) AS registros_financeiros_sem_valor,
    COUNT(*) FILTER (
        WHERE quality_rows.tipo_microdados = 'Servidores'
          AND quality_rows.numero_registros IS NULL
    ) AS registros_servidores_sem_quantidade,
    ROUND(
        100.0 * COUNT(*) FILTER (
            WHERE quality_rows.tipo_microdados <> 'Financeiro'
              AND quality_rows.instituicao IS NULL
        ) / NULLIF(COUNT(*), 0),
        2
    ) AS pct_sem_instituicao,
    ROUND(
        100.0 * COUNT(*) FILTER (
            WHERE quality_rows.tipo_microdados IN ('Matrículas', 'Eficiência Acadêmica')
              AND quality_rows.uf IS NULL
        ) / NULLIF(COUNT(*), 0),
        2
    ) AS pct_sem_uf
FROM quality_rows
GROUP BY
    quality_rows.run_id,
    quality_rows.instance_key,
    quality_rows.tipo_microdados;
