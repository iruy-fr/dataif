# @dataif/cli

CLI para instalar e subir o DataIF localmente com Docker Compose.

```bash
npx @dataif/cli install
npx @dataif/cli deploy
```

Comandos:

- `dataif install`: prepara uma pasta local com os arquivos da stack.
- `dataif deploy`: configura credenciais/portas e sobe a stack.
- `dataif status`: mostra containers e URLs da instalacao.

Por padrao, a instalacao fica em `~/.dataif/current`. Use `--dir <path>` para escolher outro destino.
