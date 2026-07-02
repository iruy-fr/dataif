# Melhorias sugeridas para deploy e instalador

Este documento consolida pontos encontrados durante a instalacao real do DataIF em uma VM Oracle Linux via `@dataif/cli`.

## Contexto observado

- Instalacao alvo: VM Oracle Linux 10.1 em VirtualBox NAT.
- Instalador usado: `npx @dataif/cli@latest install` e `npx @dataif/cli@latest deploy --mode prod`.
- Dependencias ausentes na VM: Docker Engine e Docker Compose plugin.
- Node/npm ja estavam instalados.
- Stack subiu com sucesso apos ajustes no `.env` e no `docker-compose.yml` instalado.

## Melhorias prioritarias

### 1. Nao imprimir segredos no `docker compose config`

O CLI executa `docker compose config` com `stdio: "inherit"` antes do `up`. Na pratica, isso imprime no terminal todas as variaveis resolvidas, incluindo senhas de banco, admin e segredos do Metabase.

Sugestao:

- Manter a validacao com `docker compose config`, mas redirecionar stdout para `ignore` ou capturar internamente.
- Em caso de erro, imprimir apenas stderr ou uma mensagem resumida.
- Se for necessario modo debug, expor uma flag explicita como `--verbose`.

Impacto:

- Reduz risco de vazamento de senha em logs de terminal, screenshots e historico de execucao.
- Mantem a validacao do Compose sem prejudicar seguranca operacional.

### 2. Tratar senhas com caracteres especiais em DSNs

Senhas como `!@#WS2ws` funcionam como senha real do Postgres, mas quebram quando interpoladas diretamente em URLs como:

```text
postgresql://usuario:!@#WS2ws@postgres:5432/banco
```

O caractere `#` passa a ser interpretado como fragmento de URL. O erro observado no Airflow foi:

```text
could not translate host name "#WS2ws@postgres" to address
```

Sugestao:

- Gerar variaveis de senha URL-encoded para DSNs, por exemplo:
  - `AIRFLOW_DB_PASSWORD_URLENC`
  - `DATAIF_ETL_PASSWORD_URLENC`
  - `DATAIF_VANNA_PASSWORD_URLENC`
- Usar a senha bruta apenas em campos que nao sao URL.
- Usar a senha encoded nos campos `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN`, `WAREHOUSE_DSN` e `VANNA_DSN`.
- Alternativamente, montar DSNs em codigo com encoder em vez de interpolacao direta no Compose.

Impacto:

- Permite senhas fortes com `!`, `@`, `#`, `/`, `:` e outros caracteres.
- Evita falhas de bootstrap dificeis de diagnosticar.

### 3. Validar senha do Metabase antes do deploy

Quando a senha foi simplificada para `dataif`, o bootstrap do Metabase falhou com:

```text
metabase_bootstrap_failed={'user': {'password': 'password is too common.'}}
```

Sugestao:

- Validar localmente no configurador se a senha do admin Metabase atende uma politica minima.
- Exibir mensagem antes do `docker compose up`, nao depois de baixar imagens e criar volumes.
- Evitar defaults comuns como `admin`, `dataif`, `password` e equivalentes.

Impacto:

- Evita deploy parcialmente criado por falha tardia no bootstrap.
- Melhora a experiencia do instalador interativo.

### 4. Separar claramente usuario e senha nos prompts

Durante a configuracao manual, ficou facil confundir "usuario" com "senha" porque muitos prompts aparecem em sequencia e alguns defaults usam `admin`.

Sugestao:

- Agrupar prompts por secao:
  - URLs e portas
  - usuarios administrativos
  - senhas
  - LLM
- Pedir explicitamente:
  - `Usuario admin Airflow`
  - `Usuario admin Keycloak`
  - `Email admin Metabase`
  - `Senha dos administradores`
- Oferecer opcao de reutilizar uma senha unica para os componentes, mas deixando claro que isso nao altera usuarios.

Impacto:

- Reduz erro humano no primeiro deploy.
- Facilita instalacao assistida em VM nova.

### 5. Adicionar bootstrap de Docker para Linux compativel

Na VM Oracle Linux 10.1, foi necessario instalar:

```bash
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker dataif
```

Sugestao:

- Documentar esse caminho no README ou em um guia de instalacao em VM.
- Opcionalmente, adicionar `dataif doctor` para detectar:
  - distro
  - Docker ausente
  - Compose ausente
  - usuario fora do grupo `docker`
  - daemon parado
- Evitar que o CLI instale pacotes automaticamente sem confirmacao explicita.

Impacto:

- Reduz tempo de setup em VM limpa.
- Mantem controle de privilegios com o operador.

### 6. Melhorar validacao pos-deploy

O `status` atual mostra containers e URLs, mas nao valida rotas reais da aplicacao.

Sugestao:

- Adicionar checks no `dataif status` ou em `dataif doctor`:
  - `GET /api/health/live`
  - `GET /api/health/ready`
  - `GET /metabase/`
  - `GET /airflow/`
  - estado do `metabase-bootstrap`
  - estado do `airflow-init`
- Quando um init falhar, imprimir automaticamente os ultimos logs do container.

Impacto:

- Diferencia "container existe" de "produto esta utilizavel".
- Acelera diagnostico de falhas de bootstrap.

### 7. Documentar acesso por VM NAT/VirtualBox

Em VirtualBox NAT, o IP interno da VM (`10.0.2.15`) nao e acessivel diretamente pelo host. Foi necessario configurar port forwarding:

```text
localhost:2222  -> VM:22
localhost:15173 -> VM:5173
```

Sugestao:

- Adicionar uma secao de VM/VirtualBox no README ou criar `docs/VM_INSTALL.md`.
- Incluir exemplos para SSH e Web.
- Explicar que `localhost` no `.env` dentro da VM se refere a VM, e o host precisa de NAT port forwarding.

Impacto:

- Evita confusao entre IP interno da VM, host local e portas expostas pelo Compose.

### 8. Tornar o deploy mais resiliente a falhas parciais

Quando `airflow-init` ou `metabase-bootstrap` falham, alguns containers ficam `Created` ou `Up` e volumes ja podem ter sido inicializados com credenciais antigas.

Sugestao:

- Ao detectar falha em servico init, mostrar comando recomendado:

```bash
docker compose --env-file .env -f docker-compose.yml down -v
docker compose --env-file .env -f docker-compose.yml up -d --build
```

- Adicionar flag segura como `dataif deploy --reset-volumes`, com confirmacao explicita.
- Salvar snapshot do `.env` antes de reconfigurar.

Impacto:

- Evita estados intermediarios dificeis de recuperar.
- Deixa claro quando e necessario recriar volumes por troca de credenciais.

## Backlog sugerido

1. Ajustar o CLI para nao imprimir `docker compose config` com segredos.
2. Implementar suporte a senha URL-encoded nos DSNs.
3. Adicionar validacao de senha do Metabase no configurador.
4. Reorganizar prompts de `configure-env.sh` por secao.
5. Adicionar `dataif doctor` com checks de Docker, Compose, portas, memoria e endpoints.
6. Criar guia de instalacao em VM/VirtualBox NAT.
7. Adicionar `--reset-volumes` com confirmacao para recuperacao de deploy quebrado.
