CREATE OR REPLACE VIEW curated.vw_pnp_eficiencia_situacao AS
SELECT
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
    COUNT(*) AS registros
FROM staging.pnp_eficiencia_academica
GROUP BY
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
    matricula_atendida;
