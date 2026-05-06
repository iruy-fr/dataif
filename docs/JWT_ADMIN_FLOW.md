# JWT Admin Flow

## Estado atual

O fluxo administrativo oficial da `dataif` usa login OIDC no Keycloak.

O frontend administrativo disponível no projeto é:

- `http://localhost:5173`

O uso manual de `Bearer token` continua apenas como fallback técnico para teste direto da API.

## Credenciais locais padrão

- realm: `dataif`
- usuário admin: `dataif-admin`
- senha: `admin`
- role: `admin`
- client público: `dataif-web`

Arquivo de referência:

- [realm-dataif.json](/home/iruy-fr/PycharmProjects/dataif/infra/keycloak/realm-dataif.json)

## Subida da stack

```bash
cd /home/iruy-fr/PycharmProjects/dataif
cp infra/.env.example infra/.env
cd infra
docker compose up -d --build
```

Serviços principais:

- Web: `http://localhost:5173`
- API: `http://localhost:8000/docs`
- Keycloak: `http://localhost:8081`
- Airflow via web: `http://localhost:5173/airflow/`
- Metabase via web: `http://localhost:5173/metabase/`

## Fluxo principal pela UI

1. Abrir `http://localhost:5173`
2. Clicar no ícone de admin
3. Autenticar com `dataif-admin` / `admin`
4. Operar as páginas `Conexões`, `Pipelines`, `Dashboards`, `SQL` e `Configuracoes Admin`

## Fluxo administrativo atual da PNP

1. Entrar no admin via Keycloak
2. Abrir `Conexões`
3. Criar uma instância PNP selecionando anos, tipos de microdados e cron
4. Abrir `Pipelines`
5. Selecionar a instância criada
6. Executar `Validar fontes`
7. Executar `Executar ingestão`
8. Acompanhar DAG runs, manifestos e status de ingestão `raw` pela própria interface
9. Ajustar provider/modelo do Vanna e criar/remover admins em `Configuracoes Admin`, quando necessário

## Provisionamento de admins

Ao criar um admin pela interface:

- o usuario e criado no Keycloak com role `admin`
- o mesmo email e provisionado como admin no Metabase vinculado ao projeto

Na primeira instalacao, o Metabase recebe automaticamente um admin tecnico inicial a partir de:

- `METABASE_ADMIN_EMAIL`
- `METABASE_ADMIN_PASSWORD`

Esse admin tecnico e usado pela API do DataIF para sincronizar os demais admins do produto no Metabase.

## Fallback manual via JWT

Se for necessário testar a API sem a UI:

```bash
curl -X POST 'http://localhost:8081/realms/dataif/protocol/openid-connect/token' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'grant_type=password' \
  -d 'client_id=dataif-web' \
  -d 'username=dataif-admin' \
  -d 'password=admin'
```

Com `jq`:

```bash
export ADMIN_JWT="$(
  curl -s -X POST 'http://localhost:8081/realms/dataif/protocol/openid-connect/token' \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    -d 'grant_type=password' \
    -d 'client_id=dataif-web' \
    -d 'username=dataif-admin' \
    -d 'password=admin' | jq -r .access_token
)"
```

Validação direta na API:

```bash
curl http://localhost:8000/api/admin/whoami \
  -H "Authorization: Bearer $ADMIN_JWT"
```

## Observação

O produto não depende mais de fluxo paralelo para autenticação assistida da PNP. A trilha principal agora é:

- login institucional no Keycloak
- seleção do catálogo público da PNP via Power BI
- disparo de pipelines pelo Airflow
- persistência em `raw`
- acompanhamento operacional pela própria UI
