# @dataif/cli

CLI para instalar e subir o DataIF localmente com Docker Compose.

```bash
npx @dataif/cli install
npx @dataif/cli deploy
npx @dataif/cli doctor
```

Requisitos principais:

- Node.js 18 ou superior; recomendado Node.js 20.
- Docker Engine com Docker Compose v2.
- Em VM publica, informe a URL publica real no deploy, por exemplo `http://<ip>:5173`.

Comandos:

- `dataif install`: prepara uma pasta local com os arquivos da stack.
- `dataif deploy`: configura credenciais/portas e sobe a stack.
- `dataif status`: mostra containers e URLs da instalacao.
- `dataif doctor`: valida Docker, Compose, endpoints e logs dos servicos de bootstrap.

Use `dataif deploy --reset-volumes` apenas para recuperar uma instalacao local quebrada, pois ele recria os volumes da stack.

Por padrao, a instalacao fica em `~/.dataif/current`. Use `--dir <path>` para escolher outro destino.

Em Oracle Linux/OCI, veja `docs/VM_INSTALL.md` no pacote instalado para requisitos de disco, portas e firewall.
