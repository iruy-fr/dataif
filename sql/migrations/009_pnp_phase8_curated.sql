\ir ../views_curated/010_vw_pnp_admin_ingestao.sql
\ir ../views_curated/020_vw_pnp_qualidade_dados.sql
\ir ../views_curated/030_vw_pnp_matriculas.sql
\ir ../views_curated/040_vw_pnp_eficiencia.sql
\ir ../views_curated/050_vw_pnp_servidores.sql
\ir ../views_curated/060_vw_pnp_financeiro.sql
\ir ../views_curated/070_vw_pnp_vanna.sql
\ir ../views_curated/004_mv_pnp_dashboard_fast.sql

UPDATE raw.pnp_endpoint_tables
SET
  curated_relation_schema = 'curated',
  curated_relation_name = CASE endpoint_key
    WHEN 'matriculas' THEN 'vw_pnp_matriculas_perfil'
    WHEN 'eficiencia_academica' THEN 'vw_pnp_eficiencia_situacao'
    WHEN 'servidores' THEN 'vw_pnp_servidores_quadro'
    WHEN 'financeiro' THEN 'vw_pnp_financeiro_execucao'
    ELSE curated_relation_name
  END,
  metadata = jsonb_set(
    COALESCE(metadata, '{}'::jsonb),
    '{curated_relation}',
    to_jsonb(
      CASE endpoint_key
        WHEN 'matriculas' THEN 'curated.vw_pnp_matriculas_perfil'
        WHEN 'eficiencia_academica' THEN 'curated.vw_pnp_eficiencia_situacao'
        WHEN 'servidores' THEN 'curated.vw_pnp_servidores_quadro'
        WHEN 'financeiro' THEN 'curated.vw_pnp_financeiro_execucao'
        ELSE NULL
      END
    ),
    true
  ),
  updated_at = NOW()
WHERE endpoint_key IN ('matriculas', 'eficiencia_academica', 'servidores', 'financeiro');
