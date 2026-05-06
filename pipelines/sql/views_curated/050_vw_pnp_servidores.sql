CREATE OR REPLACE VIEW curated.vw_pnp_servidores_quadro AS
SELECT
    run_id,
    instance_key,
    ano,
    instituicao,
    regiao,
    classe,
    jornada_trabalho,
    titulacao,
    rsc,
    vinculo_carreira,
    vinculo_contrato,
    vinculo_professor,
    COUNT(*) AS servidores,
    SUM(numero_registros) AS total_registros
FROM staging.pnp_servidores
GROUP BY
    run_id,
    instance_key,
    ano,
    instituicao,
    regiao,
    classe,
    jornada_trabalho,
    titulacao,
    rsc,
    vinculo_carreira,
    vinculo_contrato,
    vinculo_professor;
