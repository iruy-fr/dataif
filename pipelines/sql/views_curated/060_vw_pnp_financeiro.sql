CREATE OR REPLACE VIEW curated.vw_pnp_financeiro_execucao AS
SELECT
    run_id,
    instance_key,
    ano,
    nome_uo,
    uo,
    cod_acao,
    nome_acao,
    grupo_despesa,
    COUNT(*) AS registros,
    SUM(liquidacoes_totais) AS liquidacoes_totais
FROM staging.pnp_financeiro
GROUP BY
    run_id,
    instance_key,
    ano,
    nome_uo,
    uo,
    cod_acao,
    nome_acao,
    grupo_despesa;
