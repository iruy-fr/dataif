# Instalacao em VM Linux e VirtualBox NAT

Este guia complementa o `README.md` para uma VM Linux limpa, como Oracle Linux em VirtualBox NAT.

## Docker em Oracle Linux/RHEL compativel

Instale Docker Engine e o plugin Compose antes de executar o DataIF:

```bash
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

Depois saia e entre novamente na sessao. Valide com:

```bash
docker --version
docker compose version
docker info
```

O CLI do DataIF diagnostica Docker ausente ou daemon parado, mas nao instala pacotes automaticamente.

## Deploy

```bash
npx @dataif/cli install
npx @dataif/cli deploy --mode prod
npx @dataif/cli doctor
```

Se estiver usando uma pasta especifica:

```bash
npx @dataif/cli install --dir ./dataif-local
npx @dataif/cli deploy --dir ./dataif-local --mode prod
npx @dataif/cli doctor --dir ./dataif-local
```

## VirtualBox NAT

Em rede NAT, o IP interno da VM, como `10.0.2.15`, normalmente nao e acessivel diretamente pelo host. Configure port forwarding no VirtualBox. Exemplo:

```text
localhost:2222  -> VM:22
localhost:15173 -> VM:5173
```

Acesso SSH pelo host:

```bash
ssh -p 2222 usuario@localhost
```

Acesso Web pelo host:

```text
http://localhost:15173
```

Dentro da VM, `localhost` no `.env` aponta para a propria VM. O host so acessa a aplicacao pelas portas encaminhadas no VirtualBox.

## Recuperacao de deploy parcial

Se `airflow-init` ou `metabase-bootstrap` falharam depois que volumes foram criados, primeiro rode:

```bash
npx @dataif/cli doctor --dir ./dataif-local
```

Para recriar a stack local do zero:

```bash
npx @dataif/cli deploy --dir ./dataif-local --mode prod --force-env --reset-volumes
```

Esse comando apaga volumes locais da stack. Use apenas quando a instalacao puder ser recriada.
