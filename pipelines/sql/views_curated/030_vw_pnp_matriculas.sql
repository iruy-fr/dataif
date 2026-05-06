CREATE OR REPLACE VIEW curated.vw_pnp_matriculas_perfil AS
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
    situacao_matricula;

CREATE OR REPLACE VIEW curated.vw_pnp_matriculas_oferta AS
SELECT
    run_id,
    instance_key,
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
FROM staging.pnp_matriculas
GROUP BY
    run_id,
    instance_key,
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
