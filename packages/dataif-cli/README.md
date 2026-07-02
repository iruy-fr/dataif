# @dataif/cli

CLI para instalar e subir o DataIF localmente com Docker Compose.

```bash
npx @dataif/cli install
npx @dataif/cli deploy
npx @dataif/cli doctor
```

Comandos:

- `dataif install`: prepara uma pasta local com os arquivos da stack.
- `dataif deploy`: configura credenciais/portas e sobe a stack.
- `dataif status`: mostra containers e URLs da instalacao.
- `dataif doctor`: valida Docker, Compose, endpoints e logs dos servicos de bootstrap.

Use `dataif deploy --reset-volumes` apenas para recuperar uma instalacao local quebrada, pois ele recria os volumes da stack.

Por padrao, a instalacao fica em `~/.dataif/current`. Use `--dir <path>` para escolher outro destino.
