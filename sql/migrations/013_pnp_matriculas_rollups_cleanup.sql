-- Remove os rollups de emergencia criados fora da pipeline (migration 012), agora substituidos
-- por curated.mv_pnp_dashboard_matriculas particionada por ano + indices INCLUDE (ver
-- pipelines/sql/views_curated/004_mv_pnp_dashboard_fast.sql). Aplicar antes de reconstruir
-- a fonte e antes de republicar o dashboard do Metabase, para o schema sync nao mostrar
-- tabelas fantasmas.
DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_matriculas_rollup_org CASCADE;
DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_matriculas_rollup_sexo CASCADE;
DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_matriculas_rollup_cor_raca CASCADE;
DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_matriculas_rollup_faixa_etaria CASCADE;
DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_matriculas_rollup_renda CASCADE;
DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_matriculas_rollup_tipo_curso CASCADE;
DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_matriculas_rollup_modalidade CASCADE;
DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_matriculas_rollup_turno CASCADE;
DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_matriculas_rollup_curso CASCADE;
DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_matriculas_rollup_situacao CASCADE;
DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_matriculas_rollup_situacao_tipo CASCADE;
-- residuos de nomenclatura de uma tentativa anterior abandonada (ver docs/plans/context-codex.md)
DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_matriculas_rollup_course CASCADE;
DROP MATERIALIZED VIEW IF EXISTS curated.mv_pnp_matriculas_rollup_status CASCADE;
