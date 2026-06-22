# Análise da RAW da PNP e Proposta de STAGING/CURATED

## Escopo analisado

A análise foi feita sobre o estado atual do repositório, do contrato de dados implementado no pipeline da PNP e da base PostgreSQL local ativa em `localhost:5433`.

Os artefatos usados como fonte foram:

- `raw.nilo_pecanha_records`, que guarda cada linha parseada dos microdados em `payload JSONB`;
- `raw.nilo_pecanha_assets`, que guarda manifesto e metadados de download;
- `audit.etl_run_log`, que guarda rastreabilidade das execuções.

## O que existe hoje na RAW

### 1. Dados analíticos

Os registros da PNP entram em `raw.nilo_pecanha_records` com:

- identificação operacional: `run_id`, `endpoint_id`, `endpoint_key`, `source_kind`, `source_url`, `source_record_id`, `payload_hash`, `ingested_at`;
- dados semiestruturados em `payload JSONB`;
- metadados adicionados pelo conector: `dataset`, `ano`, `tipo_microdados`, `source_file_name`, `source_file_sha256`, `microdados_url`, `source_method`.

Na base real, o recorte relevante para a modelagem atual é:

- `pnp_pnp_full_pbi__powerbi_microdados`, com `3.036.958` registros em `1` execução, todos de `2024`.

Distribuição do endpoint atual `pnp_pnp_full_pbi__powerbi_microdados`:

- `Matrículas`: `1.982.778` registros;
- `Eficiência Acadêmica`: `968.568` registros;
- `Servidores`: `84.397` registros;
- `Financeiro`: `1.215` registros.

Já o endpoint atual `pnp_pnp_full_pbi__powerbi_microdados` traz microdados detalhados por domínio. Exemplos de colunas observadas:

- `Matrículas`: `Instituição`, `UF`, `Município`, `Sexo`, `Cor / Raça`, `Renda Familiar`, `Faixa Etária`, `Situação de Matrícula`, `Tipo de Curso`, `Tipo de Oferta`, `Nome de Curso`, `Total de Inscritos`, `Vagas Ofertadas`;
- `Eficiência Acadêmica`: mesmas dimensões demográficas de `Matrículas`, além de `Categoria da Situação`, `Situação de Matrícula` e `Matrícula Atendida`;
- `Servidores`: `Institui��o`, `Jornada_de_Trabalho`, `Titula��o`, `Classe`, `RSC`, `Vinculo_Carreira`, `Vinculo_Contrato`, `Vinculo_Professor`, `N�mero_de_registros`;
- `Financeiro`: `nomeUO`, `UO`, `codAcao`, `nomeAcao`, `GrupoDespesa`, `liquidacoesTotais`.

### 2. Dados operacionais

Os assets em `raw.nilo_pecanha_assets` registram:

- manifesto da seleção (`powerbi_microdados_manifest`);
- metadados por download (`powerbi_microdados_download`).

Isso permite responder perguntas operacionais como:

- quantos arquivos foram baixados por execução;
- quantos registros foram persistidos por `run_id`;
- quais recortes de ano e tipo de microdado foram usados;
- quando houve execução com manifesto, mas sem carga útil em `raw`.

## Métricas que podem apoiar equipes administrativas

### 1. Métricas de matrículas

- matrículas por instituição, UF, município e curso;
- matrículas por sexo, cor/raça, renda e faixa etária;
- matrículas por situação;
- inscritos e vagas ofertadas por curso, turno, modalidade e tipo de oferta;
- relação `inscritos / vagas ofertadas`.

### 2. Métricas de eficiência acadêmica

- distribuição por `Categoria da Situação`;
- distribuição por `Situação de Matrícula`;
- recorte por sexo, cor/raça, renda e faixa etária;
- comparação entre instituições e UFs;
- participação de matrículas atendidas ou não.

### 3. Métricas de servidores

- quadro de servidores por instituição;
- distribuição por jornada de trabalho;
- distribuição por titulação;
- distribuição por vínculo de carreira, contrato e docência;
- cortes por classe e RSC.

### 4. Métricas financeiras

- liquidações totais por UO;
- liquidações por ação orçamentária;
- liquidações por grupo de despesa;
- concentração de execução financeira por instituição.

### 5. Métricas institucionais transversais

- comparação por instituição entre matrículas, eficiência e quadro de servidores;
- comparação territorial por região e UF;
- leitura temática por campus, município, modalidade e curso.

### 6. Métricas de qualidade do dado

- percentual de registros sem `valor`;
- percentual de registros sem instituição;
- percentual de registros sem UF;
- percentual de registros sem atributos demográficos;
- divergência entre `loaded_count` da auditoria e `registros_raw` efetivamente presentes.

### 7. Métricas operacionais

- quantidade de execuções por status;
- tempo entre `started_at` e `finished_at`;
- quantidade de downloads por execução;
- quantidade de manifests por execução;
- volume de payloads distintos por carga.

Na execução principal validada (`run_id = adcec263-0b11-4b81-b19a-1eebf5bac8d0`), a carga registrou:

- `3.036.958` linhas carregadas;
- `4` downloads;
- `1` manifesto.

## Estratégia de modelagem sugerida

### STAGING

No endpoint atual, a normalização correta não é uma única visão por `indicador` e `valor`. O correto é:

- uma base comum com metadados compartilhados;
- visões por domínio de microdado.

Entidades recomendadas:

- `staging.stg_pnp_ingestão_execucoes`
- `staging.stg_pnp_microdados_base`
- `staging.stg_pnp_matriculas`
- `staging.stg_pnp_eficiencia_academica`
- `staging.stg_pnp_servidores`
- `staging.stg_pnp_financeiro`

### CURATED

A `CURATED` deve publicar visões prontas para consumo administrativo, separando:

- oferta e perfil de matrículas;
- eficiência acadêmica;
- quadro de servidores;
- execução financeira;
- qualidade dos dados;
- visão operacional de ingestão.

## Arquivos SQL propostos

Foram adicionados ao projeto:

- `sql/staging/000_pnp_raw_profiling.sql`
- `sql/staging/002_stg_pnp_microdados_pbi.sql`
- `sql/views_curated/003_vw_pnp_microdados_admin.sql`

Esses scripts criam:

- `staging.stg_pnp_ingestão_execucoes`
- `staging.stg_pnp_microdados_base`
- `staging.stg_pnp_matriculas`
- `staging.stg_pnp_eficiencia_academica`
- `staging.stg_pnp_servidores`
- `staging.stg_pnp_financeiro`
- `curated.vw_pnp_admin_qualidade_dados`
- `curated.vw_pnp_admin_ingestão_raw`
- `curated.vw_pnp_admin_matriculas_perfil`
- `curated.vw_pnp_admin_matriculas_oferta`
- `curated.vw_pnp_admin_eficiencia_situacao`
- `curated.vw_pnp_admin_servidores_quadro`
- `curated.vw_pnp_admin_financeiro_execucao`

## Leitura prática da proposta

- Se a prioridade for gestão de matrículas, começar por `vw_pnp_admin_matriculas_perfil` e `vw_pnp_admin_matriculas_oferta`.
- Se a prioridade for permanência e sucesso, começar por `vw_pnp_admin_eficiencia_situacao`.
- Se a prioridade for gestão de pessoas, começar por `vw_pnp_admin_servidores_quadro`.
- Se a prioridade for orçamento, começar por `vw_pnp_admin_financeiro_execucao`.
- Se a prioridade for governança do pipeline, começar por `vw_pnp_admin_ingestão_raw` e `vw_pnp_admin_qualidade_dados`.

## Próximo passo recomendado

A modelagem final desta proposta fica orientada exclusivamente ao endpoint `pnp_pnp_full_pbi__powerbi_microdados`.
