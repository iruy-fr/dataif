CREATE OR REPLACE VIEW curated.vw_pnp_admin_matriculas_perfil AS
SELECT
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
  COUNT(*) AS matriculas,
  SUM(vagas_ofertadas) AS vagas_ofertadas,
  SUM(total_inscritos) AS inscritos
FROM staging.stg_pnp_matriculas
GROUP BY ano, instituicao, regiao, uf, municipio, sexo, cor_raca, renda_familiar, faixa_etaria, situacao_matricula;


CREATE OR REPLACE VIEW curated.vw_pnp_admin_matriculas_oferta AS
SELECT
  ano,
  instituicao,
  regiao,
  uf,
  municipio,
  modalidade_ensino,
  tipo_curso,
  tipo_oferta,
  turno,
  eixo_tecnologico,
  subeixo_tecnologico,
  nome_curso,
  COUNT(*) AS matriculas,
  SUM(vagas_ofertadas) AS vagas_ofertadas,
  SUM(total_inscritos) AS inscritos
FROM staging.stg_pnp_matriculas
GROUP BY
  ano,
  instituicao,
  regiao,
  uf,
  municipio,
  modalidade_ensino,
  tipo_curso,
  tipo_oferta,
  turno,
  eixo_tecnologico,
  subeixo_tecnologico,
  nome_curso;


CREATE OR REPLACE VIEW curated.vw_pnp_admin_eficiencia_situacao AS
SELECT
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
FROM staging.stg_pnp_eficiencia_academica
GROUP BY
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


CREATE OR REPLACE VIEW curated.vw_pnp_admin_servidores_quadro AS
SELECT
  ano,
  instituicao,
  regiao,
  classe,
  jornada_trabalho,
  titulacao,
  vinculo_carreira,
  vinculo_contrato,
  vinculo_professor,
  COUNT(*) AS servidores,
  SUM(numero_registros) AS total_registros
FROM staging.stg_pnp_servidores
GROUP BY
  ano,
  instituicao,
  regiao,
  classe,
  jornada_trabalho,
  titulacao,
  vinculo_carreira,
  vinculo_contrato,
  vinculo_professor;


CREATE OR REPLACE VIEW curated.vw_pnp_admin_financeiro_execucao AS
SELECT
  ano,
  nome_uo,
  uo,
  cod_acao,
  nome_acao,
  grupo_despesa,
  COUNT(*) AS registros,
  SUM(liquidacoes_totais) AS liquidacoes_totais
FROM staging.stg_pnp_financeiro
GROUP BY ano, nome_uo, uo, cod_acao, nome_acao, grupo_despesa;


CREATE OR REPLACE VIEW curated.vw_pnp_admin_qualidade_dados AS
SELECT
  tipo_microdados,
  COUNT(*) AS registros,
  COUNT(*) FILTER (WHERE instituicao IS NULL) AS registros_sem_instituicao,
  COUNT(*) FILTER (WHERE uf IS NULL) AS registros_sem_uf,
  COUNT(*) FILTER (WHERE sexo IS NULL) AS registros_sem_sexo,
  COUNT(*) FILTER (WHERE cor_raca IS NULL) AS registros_sem_cor_raca,
  COUNT(*) FILTER (WHERE renda_familiar IS NULL) AS registros_sem_renda_familiar,
  COUNT(*) FILTER (WHERE faixa_etaria IS NULL) AS registros_sem_faixa_etaria,
  COUNT(*) FILTER (WHERE tipo_microdados = 'Financeiro' AND liquidacoes_totais IS NULL) AS registros_financeiros_sem_valor,
  COUNT(*) FILTER (WHERE tipo_microdados = 'Servidores' AND numero_registros IS NULL) AS registros_servidores_sem_quantidade,
  ROUND(100.0 * COUNT(*) FILTER (WHERE instituicao IS NULL) / NULLIF(COUNT(*), 0), 2) AS pct_sem_instituicao,
  ROUND(100.0 * COUNT(*) FILTER (WHERE uf IS NULL) / NULLIF(COUNT(*), 0), 2) AS pct_sem_uf
FROM staging.stg_pnp_microdados_base
GROUP BY tipo_microdados;


CREATE OR REPLACE VIEW curated.vw_pnp_admin_ingestao_raw AS
SELECT
  run_id,
  connector_id,
  status,
  endpoint_key,
  extracted_count,
  loaded_count,
  registros_raw,
  payloads_distintos,
  assets_total,
  manifests_total,
  downloads_total,
  started_at,
  finished_at,
  primeira_ingestao_em,
  ultima_ingestao_em,
  details
FROM staging.stg_pnp_ingestao_execucoes;
