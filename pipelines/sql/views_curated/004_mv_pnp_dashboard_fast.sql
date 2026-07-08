-- curated.mv_pnp_dashboard_matriculas eh uma TABLE particionada por RANGE (ano), nao uma
-- MATERIALIZED VIEW: o Postgres nao suporta particionamento nativo em MVs, e o volume desta
-- fonte (~4,6M linhas) exige poda de particao para agregacoes ficarem rapidas (ver
-- docs/plans/context-codex.md para o historico do problema de performance).
-- Manutencao: ao iniciar a ingestao de um novo ano_base (ex.: 2026), adicionar a particao
-- dedicada correspondente ANTES da proxima execucao da pipeline; ate la, o ano cai na
-- particao DEFAULT (funciona, mas sem poda de particao).
-- DROP condicional ao tipo de objeto existente: instalacoes que ainda tem a versao antiga em
-- MATERIALIZED VIEW precisam de DROP MATERIALIZED VIEW; apos a primeira execucao, o objeto ja
-- e uma TABLE particionada e as proximas rodadas usam DROP TABLE. Idempotente para os dois casos.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'curated' AND c.relname = 'mv_pnp_dashboard_matriculas' AND c.relkind = 'm'
  ) THEN
    EXECUTE 'DROP MATERIALIZED VIEW curated.mv_pnp_dashboard_matriculas CASCADE';
  ELSIF EXISTS (
    SELECT 1 FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'curated' AND c.relname = 'mv_pnp_dashboard_matriculas' AND c.relkind IN ('r', 'p')
  ) THEN
    EXECUTE 'DROP TABLE curated.mv_pnp_dashboard_matriculas CASCADE';
  END IF;
END $$;

CREATE TABLE curated.mv_pnp_dashboard_matriculas (
  run_id             TEXT,
  instance_key       TEXT,
  ano                INTEGER,
  instituicao        TEXT,
  regiao             TEXT,
  uf                 TEXT,
  municipio          TEXT,
  sexo               TEXT,
  cor_raca           TEXT,
  renda_familiar     TEXT,
  faixa_etaria       TEXT,
  situacao_matricula TEXT,
  modalidade_ensino  TEXT,
  tipo_curso         TEXT,
  tipo_oferta        TEXT,
  turno              TEXT,
  nome_curso         TEXT,
  matriculas         BIGINT,
  vagas_ofertadas    NUMERIC,
  inscritos          NUMERIC
) PARTITION BY RANGE (ano);

CREATE TABLE curated.mv_pnp_dashboard_matriculas_y2017 PARTITION OF curated.mv_pnp_dashboard_matriculas FOR VALUES FROM (2017) TO (2018);
CREATE TABLE curated.mv_pnp_dashboard_matriculas_y2018 PARTITION OF curated.mv_pnp_dashboard_matriculas FOR VALUES FROM (2018) TO (2019);
CREATE TABLE curated.mv_pnp_dashboard_matriculas_y2019 PARTITION OF curated.mv_pnp_dashboard_matriculas FOR VALUES FROM (2019) TO (2020);
CREATE TABLE curated.mv_pnp_dashboard_matriculas_y2020 PARTITION OF curated.mv_pnp_dashboard_matriculas FOR VALUES FROM (2020) TO (2021);
CREATE TABLE curated.mv_pnp_dashboard_matriculas_y2021 PARTITION OF curated.mv_pnp_dashboard_matriculas FOR VALUES FROM (2021) TO (2022);
CREATE TABLE curated.mv_pnp_dashboard_matriculas_y2022 PARTITION OF curated.mv_pnp_dashboard_matriculas FOR VALUES FROM (2022) TO (2023);
CREATE TABLE curated.mv_pnp_dashboard_matriculas_y2023 PARTITION OF curated.mv_pnp_dashboard_matriculas FOR VALUES FROM (2023) TO (2024);
CREATE TABLE curated.mv_pnp_dashboard_matriculas_y2024 PARTITION OF curated.mv_pnp_dashboard_matriculas FOR VALUES FROM (2024) TO (2025);
CREATE TABLE curated.mv_pnp_dashboard_matriculas_y2025 PARTITION OF curated.mv_pnp_dashboard_matriculas FOR VALUES FROM (2025) TO (2026);
-- Particao DEFAULT: cobre ano NULL (staging.pnp_matriculas.ano eh nullable) e qualquer ano
-- fora do intervalo 2017-2025 ainda sem particao dedicada.
CREATE TABLE curated.mv_pnp_dashboard_matriculas_default PARTITION OF curated.mv_pnp_dashboard_matriculas DEFAULT;

INSERT INTO curated.mv_pnp_dashboard_matriculas (
  run_id, instance_key, ano, instituicao, regiao, uf, municipio,
  sexo, cor_raca, renda_familiar, faixa_etaria, situacao_matricula,
  modalidade_ensino, tipo_curso, tipo_oferta, turno, nome_curso,
  matriculas, vagas_ofertadas, inscritos
)
SELECT
  run_id, instance_key, ano, instituicao, regiao, uf, municipio,
  sexo, cor_raca, renda_familiar, faixa_etaria, situacao_matricula,
  modalidade_ensino, tipo_curso, tipo_oferta, turno, nome_curso,
  COUNT(*) AS matriculas,
  SUM(vagas_ofertadas) AS vagas_ofertadas,
  SUM(total_inscritos) AS inscritos
FROM staging.pnp_matriculas
GROUP BY
  run_id, instance_key, ano, instituicao, regiao, uf, municipio,
  sexo, cor_raca, renda_familiar, faixa_etaria, situacao_matricula,
  modalidade_ensino, tipo_curso, tipo_oferta, turno, nome_curso;

-- Indices criados sobre a tabela particionada (sem ONLY) se propagam automaticamente para
-- cada particao existente e para qualquer particao criada depois.
--
-- Estrategia (revisada apos observar timeout real em producao): indices estreitos por
-- combinacao de colunas nao generalizam -- perguntas em linguagem natural podem filtrar
-- QUALQUER combinacao de dimensoes (ex.: ano + instituicao + sexo), e essa tabela tem ~13
-- colunas de dimensao, entao o numero de combinacoes possiveis de filtro e proibitivo de
-- cobrir uma a uma. Quando o filtro usado nao bate exatamente com a chave de um indice
-- estreito, o planner cai em Bitmap Heap Scan e precisa visitar o heap linha a linha -- em
-- ~68 mil linhas isso já levou mais de 6 minutos em producao (I/O aleatorio), mesmo com
-- indices "proximos" disponiveis.
--
-- Correcao: os dois filtros mais usados em qualquer pergunta sobre esses dados sao "ano" e,
-- em seguida, "instituicao" (praticamente toda pergunta de matriculas menciona um ano; a
-- maioria tambem menciona uma instituicao). Em vez de um indice estreito por combinacao,
-- os dois indices abaixo cobrem TODAS as demais colunas em INCLUDE -- ficam mais largos em
-- disco, mas qualquer filtro/agrupamento adicional (sexo, cor_raca, curso, etc.) e resolvido
-- via Index Only Scan sem tocar o heap, independente de qual dimensao extra a pergunta usar.
CREATE INDEX idx_mv_pnp_dashboard_matriculas_ano_wide
  ON curated.mv_pnp_dashboard_matriculas (ano)
  INCLUDE (
    instituicao, regiao, uf, municipio, sexo, cor_raca, renda_familiar, faixa_etaria,
    situacao_matricula, modalidade_ensino, tipo_curso, tipo_oferta, turno, nome_curso,
    matriculas, vagas_ofertadas, inscritos
  );
CREATE INDEX idx_mv_pnp_dashboard_matriculas_instituicao_wide
  ON curated.mv_pnp_dashboard_matriculas (instituicao)
  INCLUDE (
    ano, regiao, uf, municipio, sexo, cor_raca, renda_familiar, faixa_etaria,
    situacao_matricula, modalidade_ensino, tipo_curso, tipo_oferta, turno, nome_curso,
    matriculas, vagas_ofertadas, inscritos
  );

-- O indice largo acima e quase tao largo quanto a propria linha (17 colunas em INCLUDE), o que
-- e otimo quando o filtro em "ano" e seletivo (poda para 1 particao) mas deixa de compensar
-- quando a consulta usa um intervalo/varios anos (ex.: "de 2020 a 2024") -- af, varias
-- particoes precisam ser lidas quase por inteiro, e o indice largo custa quase o mesmo que Seq
-- Scan. Um indice estreito adicional, so com as 3 metricas, cobre esse caso (intervalo de anos
-- ou serie historica) via Index Only Scan bem mais barato.
CREATE INDEX idx_mv_pnp_dashboard_matriculas_ano_metrics
  ON curated.mv_pnp_dashboard_matriculas (ano) INCLUDE (matriculas, inscritos, vagas_ofertadas);

-- Indices estreitos por dimensao unica: cobrem o caso "agrupar por X, sem filtro nenhum" (nem
-- ano nem instituicao), que os dois indices largos acima nao atendem bem porque nao ha
-- condicao de igualdade em nenhuma das duas chaves para o planner usar.
CREATE INDEX idx_mv_pnp_dashboard_matriculas_sexo_only
  ON curated.mv_pnp_dashboard_matriculas (sexo) INCLUDE (matriculas);
CREATE INDEX idx_mv_pnp_dashboard_matriculas_cor_raca_only
  ON curated.mv_pnp_dashboard_matriculas (cor_raca) INCLUDE (matriculas);
CREATE INDEX idx_mv_pnp_dashboard_matriculas_faixa_etaria_only
  ON curated.mv_pnp_dashboard_matriculas (faixa_etaria) INCLUDE (matriculas);
CREATE INDEX idx_mv_pnp_dashboard_matriculas_renda_only
  ON curated.mv_pnp_dashboard_matriculas (renda_familiar) INCLUDE (matriculas);
CREATE INDEX idx_mv_pnp_dashboard_matriculas_situacao_only
  ON curated.mv_pnp_dashboard_matriculas (situacao_matricula) INCLUDE (matriculas);
CREATE INDEX idx_mv_pnp_dashboard_matriculas_tipo_curso_only
  ON curated.mv_pnp_dashboard_matriculas (tipo_curso) INCLUDE (matriculas);
CREATE INDEX idx_mv_pnp_dashboard_matriculas_modalidade_only
  ON curated.mv_pnp_dashboard_matriculas (modalidade_ensino) INCLUDE (matriculas);
CREATE INDEX idx_mv_pnp_dashboard_matriculas_turno_only
  ON curated.mv_pnp_dashboard_matriculas (turno) INCLUDE (matriculas);
CREATE INDEX idx_mv_pnp_dashboard_matriculas_regiao_only
  ON curated.mv_pnp_dashboard_matriculas (regiao) INCLUDE (matriculas);
CREATE INDEX idx_mv_pnp_dashboard_matriculas_uf_only
  ON curated.mv_pnp_dashboard_matriculas (uf) INCLUDE (matriculas);
-- Indice compacto (sem colunas de texto na chave) para os KPIs globais que so somam
-- matriculas/inscritos/vagas_ofertadas sem nenhum GROUP BY nem filtro -- e o caso mais dificil
-- de acelerar via indice, porque nao ha condicao de igualdade/range para o planner podar nada;
-- o ganho aqui vem so de escanear uma estrutura bem mais estreita que a linha completa.
CREATE INDEX idx_mv_pnp_dashboard_matriculas_metrics_only
  ON curated.mv_pnp_dashboard_matriculas (matriculas) INCLUDE (inscritos, vagas_ofertadas);


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
