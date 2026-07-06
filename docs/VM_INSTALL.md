# Instalacao em VM Linux, Oracle Cloud e VirtualBox NAT

Este guia complementa o `README.md` para uma VM Linux limpa, como Oracle Linux em Oracle Cloud ou VirtualBox NAT.

## SSH

Se o cliente SSH tiver muitas chaves carregadas, use a chave correta de forma explícita:

```bash
ssh -o IdentitiesOnly=yes -i ssh-key-2026-07-05.key opc@<ip>
```

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

## Node.js

Use Node.js 20 para executar `@dataif/cli`. Node.js 16 falha antes do deploy porque nao possui APIs usadas pelo CLI.

```bash
node --version
```

Se a versao for menor que 18, instale Node.js 20 antes de rodar `npx`.

## Disco

Reserve pelo menos 30 GB livres para imagens e volumes Docker. Em VM Oracle Cloud com disco raiz pequeno, anexe um block volume, formate em XFS, monte em `/dataif` e aponte o Docker para `/dataif/docker` via `/etc/docker/daemon.json`:

```json
{
  "data-root": "/dataif/docker"
}
```

Depois reinicie o Docker:

```bash
sudo systemctl restart docker
docker info --format '{{.DockerRootDir}}'
```

## Deploy

```bash
npx @dataif/cli install
npx @dataif/cli deploy --mode prod --dir ~/.dataif/current
npx @dataif/cli doctor
```

Se estiver usando uma pasta especifica:

```bash
npx @dataif/cli install --dir ./dataif-local
npx @dataif/cli deploy --dir ./dataif-local --mode prod
npx @dataif/cli doctor --dir ./dataif-local
```

No prompt `URL publica da aplicacao`, informe a URL que o navegador vai usar, por exemplo `http://<ip>:5173`. Essa URL alimenta Airflow, Metabase, CORS e os links exibidos pelo CLI.

## Firewall e OCI

Libere as portas no `firewalld` da VM e também na Security List/NSG da OCI:

```bash
sudo firewall-cmd --permanent --add-port=5173/tcp
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --permanent --add-port=3000/tcp
sudo firewall-cmd --permanent --add-port=8088/tcp
sudo firewall-cmd --permanent --add-port=8081/tcp
sudo firewall-cmd --permanent --add-port=9000/tcp
sudo firewall-cmd --reload
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

Se alterar `infra/.env`, recrie os containers afetados. Exemplo para a API:

```bash
docker compose --env-file infra/.env -f infra/docker-compose.yml up -d --force-recreate api
```
