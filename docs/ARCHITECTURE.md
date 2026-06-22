# Arquitetura dataif

## Objetivo
Integrar fontes governamentais de forma plugavel, persistir os dados em PostgreSQL e expor analise operacional no Metabase e consultas guiadas via Vanna.

## Frontends
- `services/web`
  - navegacao em `Inicio`, `Pipelines`, `Conexoes`, `Dashboards` e `SQL`
  - login admin via Keycloak
  - criacao e observacao das instancias do conector PNP
  - embed do Metabase e consultas seguras no Vanna

## Camadas de dados
- `raw`: manifestos e linhas parseadas carregadas pelo Airflow
- `staging`: tratamento manual inicial via SGBD
- `curated`: publicacao manual para BI e Vanna

## Fluxo atual da PNP
1. O admin cria uma instancia PNP na tela de conexoes.
2. A API resolve o catalogo publico do relatorio Power BI.
3. O recorte de anos e tipos vira uma configuração persistida em `config.connector_endpoints`.
4. O Airflow executa a validação das fontes ou a ingestão completa.
5. O conector baixa os microdados publicos, registra manifestos em `raw.nilo_pecanha_assets` e carrega os registros em `raw.nilo_pecanha_records`.
6. O tratamento posterior dos dados ocorre manualmente no banco, promovendo de `raw` para `staging` e depois para `curated`.

## Seguranca
- `etl_user`: escrita nas camadas operacionais
- `metabase_user`: leitura em `curated`
- `vanna_user`: leitura em `curated`
- embeds do Metabase sao assinados no backend
- Vanna continua restrito ao schema `curated` e executa SQL somente depois do `SQLGuard`
- operacoes administrativas exigem sessão OIDC valida

## Vanna AI
- O frontend envia perguntas pela tela `Inicio` para `/api/vanna/ask`.
- A API faz proxy para o servico interno `vanna`; o browser nao acessa o container diretamente.
- O servico gera SQL com Vanna + provedor configurado (`ollama` ou `maritaca`), treina somente com metadados das relacoes acessiveis em `curated` e executa a consulta com `vanna_user`.
- O contrato detalhado esta em `docs/VANNA_CURATED_ONLY.md`.

## Decisao estrutural
O caminho legado de browser assistido foi removido. A operacao oficial da PNP agora depende apenas do catalogo publico de microdados via Power BI, com o Airflow limitado a extracao e validação em `raw`.
