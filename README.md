# dataif

Plataforma conteinerizada para ingestao de dados governamentais em PostgreSQL, com operacao administrativa via API e UI, ingestao no Airflow, dashboards no Metabase e consulta assistida via Vanna.

## Estado atual da PNP
- O conector da Plataforma Nilo Pecanha opera somente em `powerbi_microdados`.
- A origem principal e o relatorio publico do Power BI com os links de microdados.
- O fluxo legado com browser assistido foi removido da trilha operacional.
- O Airflow ficou restrito a validar fontes e carregar dados na camada `raw`.
- O tratamento analitico posterior em `staging` e a publicacao em `curated` acontecem manualmente via SGBD, fora do Airflow.

## Stack
- PostgreSQL
- Apache Airflow
- FastAPI
- React + Vite
- Metabase 60
- Vanna
- Keycloak

## Estrutura
- `infra/`: Docker Compose, imagens e bootstrap da stack
- `pipelines/`: DAGs e conectores
- `services/api/`: API administrativa e embeds
- `services/web/`: frontend React
- `services/vanna/`: servico de NL2SQL
- `sql/`: schemas, tabelas e views curadas
- `docs/`: arquitetura e material de apoio

## Subida rapida
1. `cp infra/.env.example infra/.env`
2. `cd infra && docker compose up -d --build`
3. Acessos padrao:
   - Web: `http://localhost:5173`
   - API: `http://localhost:8000/docs`
   - Airflow via web: `http://localhost:5173/airflow/`
   - Metabase via web: `http://localhost:5173/metabase/`
- Keycloak: `http://localhost:8081`
- Vanna: `http://localhost:9000/health`

Versao padrao do Metabase:
- `METABASE_IMAGE_TAG=v0.60.1`

## Deploy remoto
Para distribuicao sem checkout do repositorio, publique as imagens do projeto no registry e use o compose remoto:

1. Publique as imagens customizadas com `./scripts/publish-images.sh`
2. O usuario final pode subir a stack com um comando:
   - `curl -fsSL https://raw.githubusercontent.com/iruy-fr/dataif/main/scripts/deploy-remote.sh | bash`

Esse fluxo baixa `infra/docker-compose.remote.yml`, gera `.dataif-deploy/.env` a partir do template e faz `docker compose pull && docker compose up -d`.

No deploy remoto padrao, o compose sobe a stack inteira incluindo `ollama`, para que o admin possa alternar depois entre Ollama e Maritaca pela tela `Configuracoes Admin` sem depender de instalar novos containers manualmente.
Na primeira instalacao, o bootstrap do Metabase cria automaticamente o admin tecnico configurado em `METABASE_ADMIN_EMAIL` e `METABASE_ADMIN_PASSWORD`. Esse usuario passa a ser a identidade usada pela API do DataIF para provisionar os demais admins no Metabase.

Imagens esperadas no registry:
- `dataif-postgres`
- `dataif-keycloak`
- `dataif-airflow`
- `dataif-api`
- `dataif-web`
- `dataif-vanna`
- `dataif-ollama-bootstrap`

Registry padrao da distribuicao remota:
- `docker.io/dataif`

## Fluxo de dados da PNP
1. O admin acessa a area administrativa via Keycloak.
2. A UI consulta o catalogo publico da PNP no Power BI.
3. O admin cria uma conexao selecionando anos, tipos e cron.
4. O Airflow dispara a validacao ou a ingestao da instancia.
5. O conector baixa os arquivos publicos, grava manifestos em `raw.nilo_pecanha_assets` e linhas parseadas em `raw.nilo_pecanha_records`.
6. O tratamento de `raw` para `staging` e a promocao final para `curated` sao feitos manualmente via SGBD.
7. Metabase e Vanna consomem a camada `curated`.

## Vanna AI local
O Vanna usa apenas relacoes qualificadas no schema `curated` e e chamado pela tela `Inicio`.

Para usar LLM local com Ollama:

```bash
./scripts/use-vanna-ollama.sh
```

O comando define `VANNA_LLM_PROVIDER=ollama`, preserva `VANNA_MARITACA_API_KEY`, sobe o servico Ollama, carrega/importa o modelo configurado e reinicia o Vanna. Use `./scripts/use-vanna-ollama.sh --no-bootstrap` quando o modelo ja existir no Ollama e voce quiser pular apenas o bootstrap.

Mantenha `VANNA_ALLOWED_SCHEMA=curated`; novas tabelas, views e materialized views em `curated` entram no treinamento quando o `vanna_user` tiver `SELECT`.

A configuracao efetiva de provider/modelo tambem pode ser ajustada pela tela `Configuracoes Admin`. Os overrides ficam persistidos em banco e passam a valer sem editar `.env`; o `.env` continua como bootstrap inicial para credenciais, portas e valores default.

Tambem e possivel usar a API da Maritaca com `VANNA_LLM_PROVIDER=maritaca`, `VANNA_MARITACA_API_KEY` e `VANNA_MARITACA_MODEL=sabia-4`. O modelo Sabiá local via Ollama/GGUF continua opcional e nao e redistribuido nas imagens DockerHub do projeto.

## Admins e Metabase
A tela `Configuracoes Admin` cria e remove usuarios administrativos em dois sistemas:

- Keycloak, como identidade de login do produto
- Metabase, como administradores da instancia analitica

O vinculo entre eles usa o email do usuario. Se a criacao no Metabase falhar, a API tenta desfazer a criacao correspondente no Keycloak para evitar estado parcial.

## Observacoes
- O armazenamento operacional continua em `config.connector_endpoints`.
- O frontend ja foi reorganizado em paginas de `Inicio`, `Pipelines`, `Conexoes`, `Dashboards` e `SQL`.
- A documentacao em `docs/` descreve o fluxo oficial atual: `Power BI -> Airflow -> raw`, com `staging` e `curated` fora da orquestracao.
