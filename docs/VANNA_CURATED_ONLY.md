# Vanna AI curated-only

## Objetivo
O Vanna AI e usado como camada NL2SQL para consultas assistidas sobre dados analiticos ja publicados. Ele nao participa da ingestao, nao transforma dados e nao acessa `raw`, `staging`, `config`, `audit`, `mart` ou `public`.

Fluxo oficial:

1. `services/web` envia a pergunta da tela `Inicio` para `services/api`.
2. `services/api` faz proxy para `services/vanna`.
3. `services/vanna` usa Vanna com o provedor configurado (`ollama` ou `maritaca`) para gerar SQL.
4. `SQLGuard` valida o SQL gerado contra a politica de schema curado.
5. O SQL validado roda no Postgres com `vanna_user`.
6. A resposta volta para o web com pergunta, SQL, linhas e contagem.

## Contrato de dados
O schema permitido e configurado por `VANNA_ALLOWED_SCHEMA`. O default do projeto e:

```env
VANNA_ALLOWED_SCHEMA=curated
```

Com `VANNA_ALLOWED_SCHEMA=curated`, o Vanna enxerga qualquer tabela, view ou materialized view existente em `curated` que o `vanna_user` consiga ler. Novas relacoes publicadas no schema entram no treinamento apos reiniciar o servico ou chamar `/train`, sem alterar `.env`. `ALLOWED_CURATED_VIEWS` ainda e aceito como variavel legada, mas nao e mais o mecanismo principal de escopo.

O bootstrap do Postgres concede ao `vanna_user` apenas:

- `CONNECT` no banco `DATAIF_DB_NAME`;
- `USAGE` no schema `curated`;
- `SELECT` nas tabelas/views do schema `curated`.

Mesmo com grants restritos no banco, o servico tambem valida a consulta antes da execucao:

- aceita somente `SELECT`;
- bloqueia multiplas statements;
- bloqueia DDL e DML;
- bloqueia referencias a schemas operacionais;
- exige que todo `FROM` ou `JOIN` use nome qualificado no schema permitido, por exemplo `curated.nome_relacao`;
- aplica `LIMIT` maximo quando o modelo nao gera um limite.

## Vanna e treinamento
O servico usa Vanna com ChromaDB em volume local. O treinamento automatico e idempotente por processo e usa apenas metadados curados:

- DDL sintetizado a partir de `information_schema.columns` para o schema permitido;
- tipo da relacao quando disponivel em `information_schema.tables` ou no catalogo de materialized views;
- documentacao de negocio em `curated.vw_pnp_vanna_catalogo`, quando essa view existir;
- exemplos SQL aprovados sobre relacoes conhecidas em `curated`.

Variaveis principais:

```env
VANNA_LLM_PROVIDER=ollama
VANNA_OLLAMA_BASE_URL=http://ollama:11434
VANNA_OLLAMA_MODEL=sabia-7b
VANNA_MARITACA_API_URL=https://chat.maritaca.ai/api/chat/completions
VANNA_MARITACA_API_KEY=
VANNA_MARITACA_MODEL=sabia-4
VANNA_MARITACA_TIMEOUT_SECONDS=60
VANNA_VECTORSTORE_PATH=/data/vanna/chroma
VANNA_AUTO_TRAIN=true
VANNA_ALLOWED_SCHEMA=curated
VANNA_MAX_ROWS=200
```

## Provedores LLM
`VANNA_LLM_PROVIDER=ollama` mantem o fluxo local atual. Para rodar com Ollama:

```bash
./scripts/use-vanna-ollama.sh
```

O script atualiza `infra/.env` para usar `VANNA_LLM_PROVIDER=ollama`, garante `VANNA_OLLAMA_BASE_URL=http://ollama:11434`, usa `OLLAMA_MODEL_NAME` como default de `VANNA_OLLAMA_MODEL` quando definido e preserva `VANNA_MARITACA_API_KEY`. Depois ele sobe o Ollama, executa o bootstrap idempotente do modelo, reinicia o Vanna e mostra o `curl` de `/health`. Use `./scripts/use-vanna-ollama.sh --no-bootstrap` quando o modelo ja estiver carregado e voce quiser pular apenas o bootstrap.

`VANNA_LLM_PROVIDER=maritaca` chama a API Chat Completions da Maritaca usando `VANNA_MARITACA_API_KEY` e o modelo configurado em `VANNA_MARITACA_MODEL`, com default `sabia-4`. A chave nunca aparece no `/health`; o endpoint expõe apenas `llm_provider`, `model` e `allowed_schema`.

## Modelo local Sabiá
O projeto suporta uso local via Ollama, mas nao empacota modelo na imagem DockerHub. O motivo e operacional e legal:

- modelos 7B sao grandes e nao devem inflar a imagem do servico;
- o usuario pode trocar `VANNA_OLLAMA_MODEL` sem rebuild;
- o `maritaca-ai/sabia-7b` no Hugging Face e um modelo de texto em portugues, com contexto de 2048 tokens e recomendado para few-shot;
- a model card do Sabiá-7B informa licenca alinhada a LLaMA-1, restrita a pesquisa, entao ele deve ser tratado como opcao configuravel pelo operador, nao como dependencia redistribuida pelo projeto.

O servico `ollama-model-bootstrap` e idempotente. Ele espera o Ollama responder em `/api/tags`, verifica se `OLLAMA_MODEL_NAME` ja existe, baixa `OLLAMA_MODEL_GGUF_URL` para o volume `ollama_models` quando necessario e chama `/api/create` com o `Modelfile` do projeto. O default tecnico usa `sabia-7b.Q4_K_M.gguf`, uma quantizacao intermediaria entre tamanho e qualidade.

Variaveis do bootstrap:

```env
OLLAMA_IMAGE_TAG=latest
OLLAMA_PORT=11434
OLLAMA_MEM_LIMIT=8192m
OLLAMA_MODEL_BOOTSTRAP_ENABLED=true
OLLAMA_MODEL_NAME=sabia-7b
OLLAMA_MODEL_GGUF_URL=https://huggingface.co/QuantFactory/sabia-7b-GGUF/resolve/main/sabia-7b.Q4_K_M.gguf
OLLAMA_MODEL_GGUF_FILE=sabia-7b.Q4_K_M.gguf
HF_TOKEN=
```

`HF_TOKEN` e opcional e deve ser definido apenas no `.env` local quando o ambiente exigir autenticacao para baixar o arquivo. O token nao deve ser versionado.

Requisitos recomendados para Sabiá-7B Q4_K_M:

- 6-10 GB livres em disco para o GGUF e overhead do Ollama;
- 8 GB ou mais de memoria disponivel para o servico Ollama;
- revisao da licenca/model card do Sabiá-7B antes de habilitar o uso, pois a licenca original e restrita a pesquisa.

Se o provedor LLM falhar por rede, licenca, autenticacao, timeout ou falta de memoria, o `services/vanna` continua respondendo com fallback curated-only. O `SQLGuard` permanece obrigatorio e restringe a execucao ao schema `curated`, independentemente do modelo configurado.
