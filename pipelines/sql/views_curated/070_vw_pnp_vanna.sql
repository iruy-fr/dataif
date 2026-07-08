CREATE OR REPLACE VIEW curated.vw_pnp_vanna_catalogo AS
SELECT
    'vw_pnp_admin_ingestao' AS relation_name,
    'administrativo' AS relation_group,
    'Resumo operacional das execucoes da pipeline PNP.' AS relation_description
UNION ALL
SELECT
    'vw_pnp_qualidade_dados',
    'administrativo',
    'Indicadores de completude e consistencia por tipo de microdado.'
UNION ALL
SELECT
    'vw_pnp_matriculas_perfil',
    'matriculas',
    'Agregacoes de matriculas por perfil socioeconomico e situacao.'
UNION ALL
SELECT
    'vw_pnp_matriculas_oferta',
    'matriculas',
    'Agregacoes de matriculas por curso, oferta e eixo tecnologico.'
UNION ALL
SELECT
    'vw_pnp_eficiencia_situacao',
    'eficiencia',
    'Agregacoes de eficiencia academica por categoria e situacao.'
UNION ALL
SELECT
    'vw_pnp_servidores_quadro',
    'servidores',
    'Agregacoes do quadro de servidores por carreira e titulacao.'
UNION ALL
SELECT
    'vw_pnp_financeiro_execucao',
    'financeiro',
    'Agregacoes da execucao financeira por ano, UO e grupo de despesa.';

CREATE OR REPLACE VIEW curated.vw_pnp_vanna_resumo AS
SELECT
    run_id,
    instance_key,
    'matriculas' AS dominio,
    'matriculas' AS indicador,
    ano,
    instituicao,
    regiao,
    uf,
    municipio,
    SUM(matriculas)::NUMERIC AS valor
FROM curated.mv_pnp_dashboard_matriculas
GROUP BY
    run_id,
    instance_key,
    ano,
    instituicao,
    regiao,
    uf,
    municipio
UNION ALL
SELECT
    run_id,
    instance_key,
    'eficiencia' AS dominio,
    'registros' AS indicador,
    ano,
    instituicao,
    regiao,
    uf,
    municipio,
    SUM(registros)::NUMERIC AS valor
FROM curated.vw_pnp_eficiencia_situacao
GROUP BY
    run_id,
    instance_key,
    ano,
    instituicao,
    regiao,
    uf,
    municipio
UNION ALL
SELECT
    run_id,
    instance_key,
    'servidores' AS dominio,
    'total_registros' AS indicador,
    ano,
    instituicao,
    regiao,
    NULL::TEXT AS uf,
    NULL::TEXT AS municipio,
    SUM(total_registros)::NUMERIC AS valor
FROM curated.vw_pnp_servidores_quadro
GROUP BY
    run_id,
    instance_key,
    ano,
    instituicao,
    regiao
UNION ALL
SELECT
    run_id,
    instance_key,
    'financeiro' AS dominio,
    'liquidacoes_totais' AS indicador,
    ano,
    nome_uo AS instituicao,
    NULL::TEXT AS regiao,
    NULL::TEXT AS uf,
    NULL::TEXT AS municipio,
    SUM(liquidacoes_totais)::NUMERIC AS valor
FROM curated.vw_pnp_financeiro_execucao
GROUP BY
    run_id,
    instance_key,
    ano,
    nome_uo;
