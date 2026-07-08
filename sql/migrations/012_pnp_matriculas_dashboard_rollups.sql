DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_matriculas_rollup_status;
DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_matriculas_rollup_course;
DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_matriculas_rollup_profile;

CREATE MATERIALIZED VIEW IF NOT EXISTS curated.mv_pnp_matriculas_rollup_org AS
SELECT ano, instituicao, regiao, uf, municipio, SUM(matriculas) AS matriculas, SUM(inscritos) AS inscritos, SUM(vagas_ofertadas) AS vagas_ofertadas
FROM curated.mv_pnp_dashboard_matriculas
GROUP BY ano, instituicao, regiao, uf, municipio;

CREATE MATERIALIZED VIEW IF NOT EXISTS curated.mv_pnp_matriculas_rollup_sexo AS
SELECT ano, instituicao, regiao, uf, municipio, sexo, SUM(matriculas) AS matriculas
FROM curated.mv_pnp_dashboard_matriculas
GROUP BY ano, instituicao, regiao, uf, municipio, sexo;

CREATE MATERIALIZED VIEW IF NOT EXISTS curated.mv_pnp_matriculas_rollup_cor_raca AS
SELECT ano, instituicao, regiao, uf, municipio, cor_raca, SUM(matriculas) AS matriculas
FROM curated.mv_pnp_dashboard_matriculas
GROUP BY ano, instituicao, regiao, uf, municipio, cor_raca;

CREATE MATERIALIZED VIEW IF NOT EXISTS curated.mv_pnp_matriculas_rollup_faixa_etaria AS
SELECT ano, instituicao, regiao, uf, municipio, faixa_etaria, SUM(matriculas) AS matriculas
FROM curated.mv_pnp_dashboard_matriculas
GROUP BY ano, instituicao, regiao, uf, municipio, faixa_etaria;

CREATE MATERIALIZED VIEW IF NOT EXISTS curated.mv_pnp_matriculas_rollup_renda AS
SELECT ano, instituicao, regiao, uf, municipio, renda_familiar, SUM(matriculas) AS matriculas
FROM curated.mv_pnp_dashboard_matriculas
GROUP BY ano, instituicao, regiao, uf, municipio, renda_familiar;

CREATE MATERIALIZED VIEW IF NOT EXISTS curated.mv_pnp_matriculas_rollup_tipo_curso AS
SELECT ano, instituicao, regiao, uf, municipio, tipo_curso, SUM(matriculas) AS matriculas
FROM curated.mv_pnp_dashboard_matriculas
GROUP BY ano, instituicao, regiao, uf, municipio, tipo_curso;

CREATE MATERIALIZED VIEW IF NOT EXISTS curated.mv_pnp_matriculas_rollup_modalidade AS
SELECT ano, instituicao, regiao, uf, municipio, modalidade_ensino, SUM(matriculas) AS matriculas
FROM curated.mv_pnp_dashboard_matriculas
GROUP BY ano, instituicao, regiao, uf, municipio, modalidade_ensino;

CREATE MATERIALIZED VIEW IF NOT EXISTS curated.mv_pnp_matriculas_rollup_turno AS
SELECT ano, instituicao, regiao, uf, municipio, turno, SUM(matriculas) AS matriculas
FROM curated.mv_pnp_dashboard_matriculas
GROUP BY ano, instituicao, regiao, uf, municipio, turno;

CREATE MATERIALIZED VIEW IF NOT EXISTS curated.mv_pnp_matriculas_rollup_curso AS
SELECT ano, instituicao, regiao, uf, municipio, nome_curso, tipo_curso, modalidade_ensino, tipo_oferta, turno, SUM(matriculas) AS matriculas, SUM(inscritos) AS inscritos, SUM(vagas_ofertadas) AS vagas_ofertadas
FROM curated.mv_pnp_dashboard_matriculas
GROUP BY ano, instituicao, regiao, uf, municipio, nome_curso, tipo_curso, modalidade_ensino, tipo_oferta, turno;

CREATE MATERIALIZED VIEW IF NOT EXISTS curated.mv_pnp_matriculas_rollup_situacao AS
SELECT ano, instituicao, regiao, uf, municipio, situacao_matricula, SUM(matriculas) AS matriculas
FROM curated.mv_pnp_dashboard_matriculas
GROUP BY ano, instituicao, regiao, uf, municipio, situacao_matricula;

CREATE MATERIALIZED VIEW IF NOT EXISTS curated.mv_pnp_matriculas_rollup_situacao_tipo AS
SELECT ano, instituicao, regiao, uf, municipio, tipo_curso, modalidade_ensino, situacao_matricula, SUM(matriculas) AS matriculas
FROM curated.mv_pnp_dashboard_matriculas
GROUP BY ano, instituicao, regiao, uf, municipio, tipo_curso, modalidade_ensino, situacao_matricula;

CREATE INDEX IF NOT EXISTS idx_mv_pnp_matriculas_rollup_org_filters ON curated.mv_pnp_matriculas_rollup_org (ano, regiao, uf, municipio, instituicao);
CREATE INDEX IF NOT EXISTS idx_mv_pnp_matriculas_rollup_sexo_filters ON curated.mv_pnp_matriculas_rollup_sexo (ano, regiao, uf, municipio, instituicao, sexo);
CREATE INDEX IF NOT EXISTS idx_mv_pnp_matriculas_rollup_cor_raca_filters ON curated.mv_pnp_matriculas_rollup_cor_raca (ano, regiao, uf, municipio, instituicao, cor_raca);
CREATE INDEX IF NOT EXISTS idx_mv_pnp_matriculas_rollup_faixa_etaria_filters ON curated.mv_pnp_matriculas_rollup_faixa_etaria (ano, regiao, uf, municipio, instituicao, faixa_etaria);
CREATE INDEX IF NOT EXISTS idx_mv_pnp_matriculas_rollup_renda_filters ON curated.mv_pnp_matriculas_rollup_renda (ano, regiao, uf, municipio, instituicao, renda_familiar);
CREATE INDEX IF NOT EXISTS idx_mv_pnp_matriculas_rollup_tipo_curso_filters ON curated.mv_pnp_matriculas_rollup_tipo_curso (ano, regiao, uf, municipio, instituicao, tipo_curso);
CREATE INDEX IF NOT EXISTS idx_mv_pnp_matriculas_rollup_modalidade_filters ON curated.mv_pnp_matriculas_rollup_modalidade (ano, regiao, uf, municipio, instituicao, modalidade_ensino);
CREATE INDEX IF NOT EXISTS idx_mv_pnp_matriculas_rollup_turno_filters ON curated.mv_pnp_matriculas_rollup_turno (ano, regiao, uf, municipio, instituicao, turno);
CREATE INDEX IF NOT EXISTS idx_mv_pnp_matriculas_rollup_curso_filters ON curated.mv_pnp_matriculas_rollup_curso (ano, regiao, uf, municipio, instituicao, modalidade_ensino, tipo_curso, tipo_oferta, turno, nome_curso);
CREATE INDEX IF NOT EXISTS idx_mv_pnp_matriculas_rollup_situacao_filters ON curated.mv_pnp_matriculas_rollup_situacao (ano, regiao, uf, municipio, instituicao, situacao_matricula);
CREATE INDEX IF NOT EXISTS idx_mv_pnp_matriculas_rollup_situacao_tipo_filters ON curated.mv_pnp_matriculas_rollup_situacao_tipo (ano, regiao, uf, municipio, instituicao, tipo_curso, modalidade_ensino, situacao_matricula);

ANALYZE curated.mv_pnp_matriculas_rollup_org;
ANALYZE curated.mv_pnp_matriculas_rollup_sexo;
ANALYZE curated.mv_pnp_matriculas_rollup_cor_raca;
ANALYZE curated.mv_pnp_matriculas_rollup_faixa_etaria;
ANALYZE curated.mv_pnp_matriculas_rollup_renda;
ANALYZE curated.mv_pnp_matriculas_rollup_tipo_curso;
ANALYZE curated.mv_pnp_matriculas_rollup_modalidade;
ANALYZE curated.mv_pnp_matriculas_rollup_turno;
ANALYZE curated.mv_pnp_matriculas_rollup_curso;
ANALYZE curated.mv_pnp_matriculas_rollup_situacao;
ANALYZE curated.mv_pnp_matriculas_rollup_situacao_tipo;

GRANT SELECT ON ALL TABLES IN SCHEMA curated TO metabase_user, vanna_user;
