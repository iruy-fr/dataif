DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_dashboard_matriculas CASCADE;
CREATE MATERIALIZED VIEW curated.mv_pnp_dashboard_matriculas AS
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
  situacao_matricula,
  modalidade_ensino,
  tipo_curso,
  tipo_oferta,
  turno,
  nome_curso,
  COUNT(*) AS matriculas,
  SUM(vagas_ofertadas) AS vagas_ofertadas,
  SUM(total_inscritos) AS inscritos
FROM staging.pnp_matriculas
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
  situacao_matricula,
  modalidade_ensino,
  tipo_curso,
  tipo_oferta,
  turno,
  nome_curso;

CREATE INDEX idx_mv_pnp_dashboard_matriculas_geo
  ON curated.mv_pnp_dashboard_matriculas (run_id, ano, instituicao, regiao, uf, municipio);
CREATE INDEX idx_mv_pnp_dashboard_matriculas_perfil
  ON curated.mv_pnp_dashboard_matriculas (sexo, cor_raca, renda_familiar, faixa_etaria, situacao_matricula);
CREATE INDEX idx_mv_pnp_dashboard_matriculas_oferta
  ON curated.mv_pnp_dashboard_matriculas (modalidade_ensino, tipo_curso, tipo_oferta, turno);
CREATE INDEX idx_mv_pnp_dashboard_matriculas_curso
  ON curated.mv_pnp_dashboard_matriculas (nome_curso);


DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_dashboard_eficiencia CASCADE;
CREATE MATERIALIZED VIEW curated.mv_pnp_dashboard_eficiencia AS
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
  SUM(registros) AS registros
FROM curated.vw_pnp_eficiencia_situacao
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

CREATE INDEX idx_mv_pnp_dashboard_eficiencia_geo
  ON curated.mv_pnp_dashboard_eficiencia (run_id, ano, instituicao, regiao, uf, municipio);
CREATE INDEX idx_mv_pnp_dashboard_eficiencia_perfil
  ON curated.mv_pnp_dashboard_eficiencia (sexo, cor_raca, renda_familiar, faixa_etaria);
CREATE INDEX idx_mv_pnp_dashboard_eficiencia_situacao
  ON curated.mv_pnp_dashboard_eficiencia (categoria_situacao, situacao_matricula, matricula_atendida);


DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_dashboard_servidores CASCADE;
CREATE MATERIALIZED VIEW curated.mv_pnp_dashboard_servidores AS
SELECT
  run_id,
  instance_key,
  ano,
  instituicao,
  regiao,
  classe,
  jornada_trabalho,
  titulacao,
  vinculo_carreira,
  vinculo_contrato,
  vinculo_professor,
  SUM(servidores) AS servidores,
  SUM(total_registros) AS total_registros
FROM curated.vw_pnp_servidores_quadro
GROUP BY
  run_id,
  instance_key,
  ano,
  instituicao,
  regiao,
  classe,
  jornada_trabalho,
  titulacao,
  vinculo_carreira,
  vinculo_contrato,
  vinculo_professor;

CREATE INDEX idx_mv_pnp_dashboard_servidores_geo
  ON curated.mv_pnp_dashboard_servidores (run_id, ano, instituicao, regiao);
CREATE INDEX idx_mv_pnp_dashboard_servidores_dim
  ON curated.mv_pnp_dashboard_servidores (classe, jornada_trabalho, titulacao, vinculo_carreira, vinculo_contrato, vinculo_professor);


DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_dashboard_financeiro CASCADE;
CREATE MATERIALIZED VIEW curated.mv_pnp_dashboard_financeiro AS
SELECT
  run_id,
  instance_key,
  ano,
  nome_uo,
  uo,
  cod_acao,
  nome_acao,
  grupo_despesa,
  SUM(registros) AS registros,
  SUM(liquidacoes_totais) AS liquidacoes_totais
FROM curated.vw_pnp_financeiro_execucao
GROUP BY run_id, instance_key, ano, nome_uo, uo, cod_acao, nome_acao, grupo_despesa;

CREATE INDEX idx_mv_pnp_dashboard_financeiro_dim
  ON curated.mv_pnp_dashboard_financeiro (run_id, ano, nome_uo, grupo_despesa, cod_acao, nome_acao);


DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_dashboard_qualidade CASCADE;
CREATE MATERIALIZED VIEW curated.mv_pnp_dashboard_qualidade AS
SELECT
  run_id,
  instance_key,
  tipo_microdados,
  registros,
  registros_sem_instituicao,
  registros_sem_uf,
  registros_sem_sexo,
  registros_sem_cor_raca,
  registros_sem_renda_familiar,
  registros_sem_faixa_etaria,
  registros_financeiros_sem_valor,
  registros_servidores_sem_quantidade,
  pct_sem_instituicao,
  pct_sem_uf
FROM curated.vw_pnp_qualidade_dados;


DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_dashboard_ingestao CASCADE;
CREATE MATERIALIZED VIEW curated.mv_pnp_dashboard_ingestao AS
SELECT
  run_id,
  instance_key,
  connection_key,
  connection_name,
  airflow_dag_id,
  airflow_dag_run_id,
  trigger_mode,
  requested_by,
  logical_date,
  status,
  catalog_entry_count,
  selected_download_count,
  downloaded_file_count,
  raw_record_count,
  staging_record_count,
  package_count,
  quarantine_count,
  quality_status,
  started_at,
  finished_at,
  duration_seconds,
  error_message
FROM curated.vw_pnp_admin_ingestao;

CREATE INDEX idx_mv_pnp_dashboard_ingestao_run
  ON curated.mv_pnp_dashboard_ingestao (run_id, status);


GRANT SELECT ON ALL TABLES IN SCHEMA curated TO metabase_user, vanna_user;
