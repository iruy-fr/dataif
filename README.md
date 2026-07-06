# dataif

Plataforma conteinerizada para ingestão de dados governamentais em PostgreSQL, com operacao administrativa via API e UI, ingestão no Airflow, dashboards no Metabase e consulta assistida via Vanna.

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
1. `./scripts/deploy.sh stg`
2. Para producao local em nova maquina: `./scripts/deploy.sh prod`
3. Acessos padrao:
   - Staging Web: `http://localhost:15173`
   - Producao Web: porta definida no configurador
   - API: `/api` via Web ou porta configurada
   - Airflow via Web: `/airflow/`
   - Metabase via Web: `/metabase/`

Versao padrao do Metabase:
- `METABASE_IMAGE_TAG=v0.60.1`

## Instalador npm

Tambem existe uma CLI npm para preparar uma maquina nova sem exigir que o usuario conheca os scripts internos:

```bash
npx @dataif/cli install
npx @dataif/cli deploy
npx @dataif/cli doctor
```

O instalador cria uma copia local da stack em `~/.dataif/current`, valida Docker/Docker Compose, coleta as credenciais de forma interativa e entao sobe os containers. O comando `doctor` valida Docker, Compose, endpoints da aplicacao e logs dos servicos de bootstrap. Para usar uma pasta especifica:

```bash
npx @dataif/cli install --dir ./dataif-local
npx @dataif/cli deploy --dir ./dataif-local --mode prod
npx @dataif/cli doctor --dir ./dataif-local
```

Para recuperar um deploy local inicializado com credenciais erradas, recrie os volumes explicitamente:

```bash
npx @dataif/cli deploy --dir ./dataif-local --mode prod --force-env --reset-volumes
```

`--reset-volumes` executa `docker compose down -v` e apaga dados locais da stack antes de subir novamente.

Por padrao, `deploy` usa imagens publicadas em `DATAIF_IMAGE_REGISTRY` com a tag fixa `DATAIF_IMAGE_TAG` do pacote. Para desenvolvimento local com rebuild e bind mounts de codigo, use `--build-local`:

```bash
npx @dataif/cli deploy --mode stg --build-local
```

Durante o desenvolvimento do pacote:

```bash
cd packages/dataif-cli
npm run smoke
npm pack --dry-run
```

## Guia de uso local

Pre-requisitos:
- Docker Engine com Docker Compose v2
- Node.js 18+ para usar a CLI npm; recomendado Node.js 20
- 6 GB de RAM livres para stack basica
- 12 GB de RAM livres se usar Ollama local
- 30 GB livres recomendados para imagens e volumes Docker em VM

Em VM Linux limpa, instale Docker manualmente antes do deploy. Em Oracle Linux/RHEL compativel:

```bash
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

Saia e entre novamente na sessao para o grupo `docker` ser aplicado. Para VirtualBox NAT e port forwarding, veja `docs/VM_INSTALL.md`.

Em VM publica, configure `URL publica da aplicacao` como a URL final do navegador, por exemplo `http://<ip>:5173`. Essa URL configura os redirects do Airflow, a URL do Metabase, CORS e os links exibidos pelo CLI.

Subir ambiente de teste/staging:

```bash
./scripts/deploy.sh stg
```

Esse modo usa `infra/.env.stg.example`, cria `infra/.env` com valores presetados e sobe a stack usando imagens publicadas. Use para demonstracoes locais e validacao de instalacao. Para desenvolvimento com build local e volumes de codigo:

```bash
./scripts/deploy.sh stg --build-local
```

Para recriar `infra/.env` de staging:

```bash
DATAIF_FORCE_ENV=true ./scripts/deploy.sh stg
```

Subir producao local em nova maquina:

```bash
./scripts/deploy.sh prod
```

Esse modo usa `infra/.env.example` apenas como template versionado, chama `scripts/configure-env.sh`, gera segredos e grava `infra/.env`. Nao edite `infra/.env.example` para uma instancia real. Configure senhas e `METABASE_EMBED_SECRET` antes do primeiro `up`, pois o Postgres inicializa usuarios somente na criacao do volume.

Validar configuração sem subir:

```bash
cd infra
docker compose --env-file .env config >/dev/null
```

Ativar LLM local com Ollama:

```bash
./scripts/deploy.sh stg --llm
# ou
./scripts/deploy.sh prod --llm
```

Refazer do zero na maquina local:

```bash
cd infra
docker compose --env-file .env down -v
cd ..
./scripts/deploy.sh stg
```

Depois da instalacao, o provider/modelo do Vanna pode ser ajustado pela tela `Configurações Admin`. Sem Ollama ativo e sem chave Maritaca, o servico Vanna permanece disponivel, mas respostas por LLM ficam indisponiveis ate configurar um provider.

## Fluxo de dados da PNP
1. O admin acessa a area administrativa via Keycloak.
2. A UI consulta o catalogo publico da PNP no Power BI.
3. O admin cria uma conexão selecionando anos, tipos e cron.
4. O Airflow dispara a validação ou a ingestão da instancia.
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

A configuração efetiva de provider/modelo tambem pode ser ajustada pela tela `Configurações Admin`. Os overrides ficam persistidos em banco e passam a valer sem editar `.env`; o `.env` continua como bootstrap inicial para credenciais, portas e valores default.

Tambem e possivel usar a API da Maritaca com `VANNA_LLM_PROVIDER=maritaca`, `VANNA_MARITACA_API_KEY` e `VANNA_MARITACA_MODEL=sabia-4`. O modelo Sabiá local via Ollama/GGUF continua opcional e nao e redistribuido nas imagens DockerHub do projeto.

## Admins e Metabase
A tela `Configurações Admin` cria e remove usuarios administrativos em dois sistemas:

- Keycloak, como identidade de login do produto
- Metabase, como administradores da instancia analitica

O vinculo entre eles usa o email do usuario. Se a criacao no Metabase falhar, a API tenta desfazer a criacao correspondente no Keycloak para evitar estado parcial.

## Observacoes
- O armazenamento operacional continua em `config.connector_endpoints`.
- O frontend ja foi reorganizado em paginas de `Inicio`, `Pipelines`, `Conexoes`, `Dashboards` e `SQL`.
- A documentacao em `docs/` descreve o fluxo oficial atual: `Power BI -> Airflow -> raw`, com `staging` e `curated` fora da orquestração.
