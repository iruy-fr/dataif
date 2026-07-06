#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import https from "node:https";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const packageRoot = path.resolve(__dirname, "..");
const embeddedTemplateRoot = path.join(packageRoot, "templates", "dataif");
const defaultInstallDir = path.join(os.homedir(), ".dataif", "current");

const requiredProjectFiles = [
  "infra/docker-compose.yml",
  "scripts/deploy.sh",
  "scripts/configure-env.sh"
];

const installEntries = [
  "docs",
  "infra",
  "pipelines",
  "scripts",
  "services",
  "sql",
  "README.md"
];

const ignoredNames = new Set([
  ".env",
  ".git",
  ".pytest_cache",
  "__pycache__",
  "node_modules",
  "dist",
  "build",
  ".DS_Store"
]);

main().catch((error) => {
  fail(error.message || String(error));
});

async function main() {
  validateNodeRuntime();

  const args = process.argv.slice(2);
  const command = args[0];

  if (!command || command === "-h" || command === "--help") {
    printMainHelp();
    return;
  }

  const commandArgs = args.slice(1);
  switch (command) {
    case "install":
      await installCommand(commandArgs);
      break;
    case "deploy":
      await deployCommand(commandArgs);
      break;
    case "status":
      statusCommand(commandArgs);
      break;
    case "doctor":
      await doctorCommand(commandArgs);
      break;
    default:
      fail(`Comando desconhecido: ${command}\n\nExecute: dataif --help`);
  }
}

function printMainHelp() {
  console.log(`DataIF CLI

Uso:
  dataif install [--dir <path>] [--source <path>] [--force]
  dataif deploy [--mode stg|prod] [--llm] [--build-local] [--dir <path>] [--yes] [--reset-volumes]
  dataif status [--dir <path>]
  dataif doctor [--dir <path>]

Comandos:
  install  Prepara uma instalacao local da stack DataIF.
  deploy   Configura credenciais/portas e sobe a stack com Docker Compose.
  status   Mostra containers e URLs da instalacao.
  doctor   Valida Docker, Compose, endpoints e servicos de bootstrap.

Padrao:
  Diretorio de instalacao: ${defaultInstallDir}

Exemplos:
  dataif install
  dataif deploy --mode prod
  dataif deploy --mode stg --llm
`);
}

function printInstallHelp() {
  console.log(`Uso: dataif install [--dir <path>] [--source <path>] [--force]

Opcoes:
  --dir <path>     Pasta de destino. Padrao: ${defaultInstallDir}
  --source <path>  Projeto DataIF local para copiar. Padrao: repo atual ou template npm.
  --force          Sobrescreve arquivos existentes no destino.
`);
}

function printDeployHelp() {
  console.log(`Uso: dataif deploy [--mode stg|prod] [--llm] [--build-local] [--dir <path>] [--yes] [--reset-volumes]

Opcoes:
  --mode <mode>    stg ou prod. Se omitido, a CLI pergunta.
  --llm            Inclui profile llm/Ollama.
  --build-local    Usa build local e volumes de desenvolvimento.
  --dir <path>     Pasta da instalacao. Padrao: ${defaultInstallDir}
  --yes            Nao pergunta confirmacao antes de subir containers.
  --force-env      Recria infra/.env a partir do template do modo.
  --reset-volumes  Executa docker compose down -v antes de subir a stack.

Variaveis:
  DATAIF_DEPLOY_CONFIG_ONLY=true  Configura e valida sem subir containers.
`);
}

function printStatusHelp() {
  console.log(`Uso: dataif status [--dir <path>]

Opcoes:
  --dir <path>  Pasta da instalacao. Padrao: ${defaultInstallDir}
`);
}

function printDoctorHelp() {
  console.log(`Uso: dataif doctor [--dir <path>]

Opcoes:
  --dir <path>  Pasta da instalacao. Padrao: ${defaultInstallDir}
`);
}

async function installCommand(args) {
  const options = parseOptions(args);
  if (options.help) {
    printInstallHelp();
    return;
  }

  const targetDir = expandHome(options.dir || defaultInstallDir);
  const sourceDir = resolveInstallSource(options.source);

  ensureProjectRoot(sourceDir, "origem");
  await prepareInstallDir(sourceDir, targetDir, Boolean(options.force));

  console.log("\nInstalacao DataIF pronta.");
  console.log(`Pasta: ${targetDir}`);
  console.log(`Proximo passo: dataif deploy --dir ${quotePath(targetDir)}`);
}

async function deployCommand(args) {
  const options = parseOptions(args, { booleans: ["llm", "build-local", "yes", "force-env", "reset-volumes"] });
  if (options.help) {
    printDeployHelp();
    return;
  }

  let mode = options.mode;
  if (!mode) {
    mode = await chooseMode();
  }
  if (!["stg", "prod"].includes(mode)) {
    fail(`Modo invalido: ${mode}. Use stg ou prod.`);
  }

  const configOnly = process.env.DATAIF_DEPLOY_CONFIG_ONLY === "true";
  const projectDir = await resolveProjectDir(options.dir);
  await validateDocker({ requireDaemon: !configOnly });
  if (!configOnly) {
    validateHostCapacity(projectDir);
  }
  const envPath = path.join(projectDir, "infra", ".env");
  if ((options["force-env"] || options["reset-volumes"]) && fs.existsSync(envPath)) {
    snapshotEnvFile(envPath);
  }

  const env = {
    ...process.env,
    DATAIF_DEPLOY_CONFIG_ONLY: "true"
  };
  if (options["force-env"]) {
    env.DATAIF_FORCE_ENV = "true";
  }

  console.log(`\nConfigurando DataIF (${mode}) em ${projectDir}`);
  run(path.join(projectDir, "scripts", "deploy.sh"), buildDeployArgs(mode, options.llm, options["build-local"]), {
    cwd: projectDir,
    env,
    stdio: "inherit"
  });

  const envValues = readEnvFile(envPath);
  if (!configOnly) {
    await validatePorts(envValues, Boolean(options.yes));
  }

  const composeArgs = buildComposeArgs(projectDir, envPath, Boolean(options.llm), Boolean(options["build-local"]));

  printDeploySummary(projectDir, mode, Boolean(options.llm), Boolean(options["build-local"]), envValues);
  if (options["reset-volumes"] && !options.yes) {
    const resetConfirmed = await confirm("Remover containers e volumes antes de subir? Isso apaga dados locais da stack", false);
    if (!resetConfirmed) {
      console.log("Deploy cancelado antes do reset de volumes.");
      return;
    }
  }

  if (!options.yes) {
    const confirmed = await confirm("Subir containers agora?", true);
    if (!confirmed) {
      console.log("Deploy cancelado antes de subir containers.");
      console.log(`Configuracao mantida em: ${envPath}`);
      return;
    }
  }

  console.log("\nValidando Docker Compose...");
  run("docker", [...composeArgs, "config"], { cwd: path.join(projectDir, "infra") });

  if (configOnly) {
    console.log(`Configuracao validada: ${envPath}`);
    return;
  }

  if (options["reset-volumes"]) {
    console.log("\nRemovendo containers e volumes da stack DataIF...");
    run("docker", [...composeArgs, "down", "-v"], {
      cwd: path.join(projectDir, "infra"),
      stdio: "inherit"
    });
  }

  if (options["build-local"]) {
    console.log("\nSubindo stack DataIF com build local...");
    run("docker", [...composeArgs, "up", "-d", "--build"], {
      cwd: path.join(projectDir, "infra"),
      stdio: "inherit"
    });
  } else {
    console.log("\nBaixando imagens DataIF...");
    run("docker", [...composeArgs, "pull"], {
      cwd: path.join(projectDir, "infra"),
      stdio: "inherit"
    });

    console.log("\nSubindo stack DataIF...");
    run("docker", [...composeArgs, "up", "-d"], {
      cwd: path.join(projectDir, "infra"),
      stdio: "inherit"
    });
  }

  console.log("\nDataIF ativo.");
  console.log(`Web: ${publicBaseUrl(envValues)}`);
  console.log(`Status: dataif status --dir ${quotePath(projectDir)}`);
}

function statusCommand(args) {
  const options = parseOptions(args);
  if (options.help) {
    printStatusHelp();
    return;
  }

  const projectDir = resolveExistingProjectDir(options.dir);
  const envPath = path.join(projectDir, "infra", ".env");
  const composePath = path.join(projectDir, "infra", "docker-compose.yml");

  if (!fs.existsSync(envPath)) {
    fail(`Nao encontrei ${envPath}.\nExecute: dataif deploy --dir ${quotePath(projectDir)}`);
  }

  const envValues = readEnvFile(envPath);
  const baseUrl = publicBaseUrl(envValues);
  console.log(`DataIF: ${projectDir}`);
  console.log(`Env: ${envPath}`);
  console.log(`Web: ${baseUrl}`);
  console.log(`API: http://localhost:${envValues.API_PORT || "8000"}`);
  console.log(`Airflow: ${baseUrl}/airflow/`);
  console.log(`Metabase: ${baseUrl}/metabase/`);
  console.log("");

  const docker = spawnSync("docker", [
    "compose",
    "--env-file",
    envPath,
    "-f",
    composePath,
    "ps"
  ], {
    cwd: path.join(projectDir, "infra"),
    encoding: "utf8"
  });

  if (docker.error || docker.status !== 0) {
    const detail = docker.stderr || docker.error?.message || "";
    if (detail.includes("permission denied") && detail.includes("docker")) {
      fail([
        "Nao consegui consultar Docker Compose por falta de permissao no Docker.",
        "Abra o Docker Desktop/daemon ou rode com um usuario que tenha acesso ao socket Docker.",
        detail.trim()
      ].join("\n"));
    }
    fail(`Nao consegui consultar Docker Compose.\n${detail}`.trim());
  }
  process.stdout.write(docker.stdout);
}


async function doctorCommand(args) {
  const options = parseOptions(args);
  if (options.help) {
    printDoctorHelp();
    return;
  }

  const projectDir = resolveExistingProjectDir(options.dir);
  const envPath = path.join(projectDir, "infra", ".env");
  if (!fs.existsSync(envPath)) {
    fail(`Nao encontrei ${envPath}.\nExecute: dataif deploy --dir ${quotePath(projectDir)}`);
  }

  const envValues = readEnvFile(envPath);
  const composeArgs = buildComposeArgs(projectDir, envPath, false);
  const baseUrl = publicBaseUrl(envValues);

  console.log(`DataIF doctor: ${projectDir}`);
  printCheck("Docker client", checkCommand("docker", ["--version"]));
  printCheck("Docker Compose v2", checkCommand("docker", ["compose", "version"]));
  printCheck("Docker daemon", checkCommand("docker", ["info"]));
  validateHostCapacity(projectDir);

  console.log("\nContainers");
  const ps = spawnSync("docker", [...composeArgs, "ps"], {
    cwd: path.join(projectDir, "infra"),
    encoding: "utf8"
  });
  if (ps.status === 0) {
    process.stdout.write(ps.stdout || "Nenhum container retornado.\n");
  } else {
    printCheck("docker compose ps", { ok: false, detail: ps.stderr || ps.error?.message || "falha desconhecida" });
  }

  console.log("\nEndpoints");
  const webPort = envValues.WEB_PORT || "5173";
  await printEndpointCheck("API live", `http://localhost:${webPort}/api/health/live`);
  await printEndpointCheck("API ready", `http://localhost:${webPort}/api/health/ready`);
  await printEndpointCheck("Metabase", `http://localhost:${webPort}/metabase/`);
  await printEndpointCheck("Airflow", `http://localhost:${webPort}/airflow/`);
  if (!baseUrl.includes("localhost")) {
    await printEndpointCheck("Public web", baseUrl);
  }

  console.log("\nBootstrap services");
  for (const service of ["airflow-init", "keycloak-bootstrap", "metabase-bootstrap"]) {
    reportBootstrapService(composeArgs, projectDir, service);
  }

  console.log("\nRuntime services");
  for (const service of ["web", "api", "keycloak", "airflow-webserver", "airflow-scheduler"]) {
    reportRunningService(composeArgs, projectDir, service);
  }

  console.log("\nFirewall");
  reportFirewall(envValues);
}

function parseOptions(args, config = {}) {
  const booleans = new Set(["help", "force", ...(config.booleans || [])]);
  const options = {};

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "-h" || arg === "--help") {
      options.help = true;
      continue;
    }
    if (!arg.startsWith("--")) {
      fail(`Argumento inesperado: ${arg}`);
    }

    const key = arg.slice(2);
    if (booleans.has(key)) {
      options[key] = true;
      continue;
    }

    const value = args[index + 1];
    if (!value || value.startsWith("--")) {
      fail(`Opcao ${arg} precisa de valor.`);
    }
    options[key] = value;
    index += 1;
  }

  return options;
}

async function chooseMode() {
  const { createInterface } = await import("node:readline/promises");
  const { stdin: input, stdout: output } = await import("node:process");
  const rl = createInterface({ input, output });
  try {
    while (true) {
      const answer = (await rl.question("Modo de deploy (stg/prod) [prod]: ")).trim() || "prod";
      if (["stg", "prod"].includes(answer)) {
        return answer;
      }
      console.log("Use stg ou prod.");
    }
  } finally {
    rl.close();
  }
}

async function confirm(question, defaultValue) {
  const suffix = defaultValue ? "[S/n]" : "[s/N]";
  const { createInterface } = await import("node:readline/promises");
  const { stdin: input, stdout: output } = await import("node:process");
  const rl = createInterface({ input, output });
  try {
    const answer = (await rl.question(`${question} ${suffix}: `)).trim().toLowerCase();
    if (!answer) {
      return defaultValue;
    }
    return ["s", "sim", "y", "yes"].includes(answer);
  } finally {
    rl.close();
  }
}

async function prepareInstallDir(sourceDir, targetDir, force) {
  if (fs.existsSync(targetDir) && fs.readdirSync(targetDir).length > 0 && !force) {
    const overwrite = await confirm(`A pasta ${targetDir} ja existe. Atualizar arquivos?`, false);
    if (!overwrite) {
      console.log("Instalacao mantida sem alteracoes.");
      return;
    }
  }

  fs.mkdirSync(targetDir, { recursive: true });
  for (const entry of installEntries) {
    const src = path.join(sourceDir, entry);
    if (!fs.existsSync(src)) {
      continue;
    }
    copyRecursive(src, path.join(targetDir, entry));
  }

  for (const script of ["deploy.sh", "configure-env.sh"]) {
    const scriptPath = path.join(targetDir, "scripts", script);
    if (fs.existsSync(scriptPath)) {
      fs.chmodSync(scriptPath, 0o755);
    }
  }
}

async function resolveProjectDir(dirOption) {
  if (dirOption) {
    const dir = expandHome(dirOption);
    if (!isProjectRoot(dir)) {
      const canPrepare = !fs.existsSync(dir) || fs.readdirSync(dir).length === 0;
      if (!canPrepare) {
        fail(`A pasta informada nao parece uma instalacao DataIF: ${dir}`);
      }
      const source = resolveInstallSource();
      console.log(`Instalacao informada nao encontrada. Preparando ${dir}...`);
      await prepareInstallDir(source, dir, false);
      ensureProjectRoot(dir, "instalacao");
    }
    return dir;
  }

  const cwdProject = findProjectRoot(process.cwd());
  if (cwdProject) {
    return cwdProject;
  }

  if (isProjectRoot(defaultInstallDir)) {
    return defaultInstallDir;
  }

  const source = resolveInstallSource();
  console.log(`Instalacao padrao nao encontrada. Preparando ${defaultInstallDir}...`);
  await prepareInstallDir(source, defaultInstallDir, false);
  return defaultInstallDir;
}

function resolveExistingProjectDir(dirOption) {
  const explicitDir = dirOption ? expandHome(dirOption) : null;
  const dir = explicitDir || findProjectRoot(process.cwd()) || defaultInstallDir;
  if (!isProjectRoot(dir)) {
    fail(`Nao encontrei uma instalacao DataIF em ${dir}.\nExecute: dataif install --dir ${quotePath(dir)}`);
  }
  return dir;
}

function resolveInstallSource(sourceOption) {
  if (sourceOption) {
    const source = expandHome(sourceOption);
    ensureProjectRoot(source, "origem");
    return source;
  }

  const cwdProject = findProjectRoot(process.cwd());
  if (cwdProject) {
    return cwdProject;
  }

  if (isProjectRoot(embeddedTemplateRoot)) {
    return embeddedTemplateRoot;
  }

  fail([
    "Nao encontrei arquivos do DataIF para instalar.",
    "Execute dentro do repo DataIF ou publique o pacote npm com o template gerado por npm pack."
  ].join("\n"));
}

function findProjectRoot(startDir) {
  let current = path.resolve(startDir);
  while (true) {
    if (isProjectRoot(current)) {
      return current;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      return null;
    }
    current = parent;
  }
}

function isProjectRoot(dir) {
  return requiredProjectFiles.every((file) => fs.existsSync(path.join(dir, file)));
}

function ensureProjectRoot(dir, label) {
  if (!isProjectRoot(dir)) {
    fail(`A ${label} nao contem uma stack DataIF valida: ${dir}`);
  }
}

function copyRecursive(src, dest) {
  if (!shouldCopy(src)) {
    return;
  }

  const stat = fs.statSync(src);
  if (stat.isDirectory()) {
    fs.mkdirSync(dest, { recursive: true });
    for (const entry of fs.readdirSync(src)) {
      copyRecursive(path.join(src, entry), path.join(dest, entry));
    }
    return;
  }

  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(src, dest);
  fs.chmodSync(dest, stat.mode);
}

function shouldCopy(src) {
  const name = path.basename(src);
  if (ignoredNames.has(name)) {
    return false;
  }
  if (name.endsWith(".pyc")) {
    return false;
  }
  return true;
}

function validateNodeRuntime() {
  const [major] = process.versions.node.split(".").map((part) => Number(part));
  if (!Number.isInteger(major) || major < 18) {
    fail([
      `Node.js ${process.versions.node} detectado, mas o DataIF CLI precisa de Node.js >= 18.`,
      "Instale Node.js 20 e execute novamente. Em Oracle Linux, use NodeSource ou outro repositório oficial equivalente."
    ].join("\n"));
  }
}

async function validateDocker({ requireDaemon = true } = {}) {
  const docker = spawnSync("docker", ["--version"], { encoding: "utf8" });
  if (docker.status !== 0) {
    fail("Docker nao encontrado. Instale/inicie Docker Engine antes de rodar o deploy.");
  }

  const compose = spawnSync("docker", ["compose", "version"], { encoding: "utf8" });
  if (compose.status !== 0) {
    fail("Docker Compose v2 nao encontrado. Verifique se `docker compose version` funciona.");
  }

  if (!requireDaemon) {
    return;
  }

  const daemon = spawnSync("docker", ["info"], { encoding: "utf8" });
  if (daemon.status !== 0) {
    fail("Docker esta instalado, mas o daemon nao respondeu. Inicie o Docker e tente novamente.");
  }
}

function validateHostCapacity(projectDir = os.homedir()) {
  const totalMemGb = os.totalmem() / 1024 / 1024 / 1024;
  if (totalMemGb < 6) {
    console.warn(`Aviso: memoria total detectada abaixo de 6 GB (${totalMemGb.toFixed(1)} GB).`);
  }

  reportDiskCapacity(projectDir, "instalacao DataIF", 20);
  const dockerRoot = detectDockerRootDir();
  if (dockerRoot) {
    reportDiskCapacity(dockerRoot, "Docker data-root", 30);
  }
}

function reportDiskCapacity(targetPath, label, minimumGb) {
  const existingPath = nearestExistingPath(targetPath);
  const available = spawnSync("df", ["-Pk", existingPath], { encoding: "utf8" });
  if (available.status === 0) {
    const lines = available.stdout.trim().split("\n");
    const columns = lines.at(-1)?.trim().split(/\s+/) || [];
    const availableKb = Number(columns[3] || 0);
    const availableGb = availableKb / 1024 / 1024;
    if (availableGb > 0 && availableGb < minimumGb) {
      console.warn(`Aviso: espaco livre abaixo de ${minimumGb} GB em ${label} (${existingPath}: ${availableGb.toFixed(1)} GB).`);
    }
  }
}

function nearestExistingPath(targetPath) {
  let current = path.resolve(targetPath || os.homedir());
  while (!fs.existsSync(current)) {
    const parent = path.dirname(current);
    if (parent === current) {
      return "/";
    }
    current = parent;
  }
  return current;
}

function detectDockerRootDir() {
  const result = spawnSync("docker", ["info", "--format", "{{.DockerRootDir}}"], { encoding: "utf8" });
  if (result.status !== 0) {
    return "";
  }
  return (result.stdout || "").trim();
}

async function validatePorts(envValues, assumeYes) {
  const ports = [
    ["Web", envValues.WEB_PORT],
    ["API", envValues.API_PORT],
    ["Postgres", envValues.POSTGRES_EXPOSE_PORT],
    ["Metabase", envValues.METABASE_PORT],
    ["Airflow", envValues.AIRFLOW_PORT],
    ["Keycloak", envValues.KEYCLOAK_PORT],
    ["Vanna", envValues.VANNA_PORT]
  ].filter(([, port]) => port);

  const busy = [];
  for (const [label, port] of ports) {
    if (!(await isPortAvailable(Number(port)))) {
      busy.push(`${label}:${port}`);
    }
  }

  if (busy.length === 0) {
    return;
  }

  const message = `Portas em uso: ${busy.join(", ")}`;
  if (assumeYes) {
    fail(`${message}\nPare o processo atual ou altere as portas no deploy prod.`);
  }

  console.warn(`Aviso: ${message}`);
  const proceed = await confirm("Continuar mesmo assim?", false);
  if (!proceed) {
    fail("Deploy interrompido por conflito de portas.");
  }
}

function isPortAvailable(port) {
  return new Promise((resolve) => {
    if (!Number.isInteger(port) || port <= 0) {
      resolve(true);
      return;
    }
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    server.listen(port, "0.0.0.0");
  });
}

function buildDeployArgs(mode, includeLlm, buildLocal) {
  const args = [mode];
  if (includeLlm) {
    args.push("--llm");
  }
  if (buildLocal) {
    args.push("--build-local");
  }
  return args;
}

function buildComposeArgs(projectDir, envPath, includeLlm, buildLocal = false) {
  const args = [
    "compose",
    "--env-file",
    envPath,
    "-f",
    path.join(projectDir, "infra", "docker-compose.yml")
  ];
  if (buildLocal) {
    args.push("-f", path.join(projectDir, "infra", "docker-compose.dev.yml"));
  }
  if (includeLlm) {
    args.push("--profile", "llm");
  }
  return args;
}

function snapshotEnvFile(envPath) {
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const snapshotPath = `${envPath}.${timestamp}.bak`;
  fs.copyFileSync(envPath, snapshotPath);
  fs.chmodSync(snapshotPath, 0o600);
  console.log(`Snapshot do .env criado: ${snapshotPath}`);
}

function checkCommand(command, args) {
  const result = spawnSync(command, args, { encoding: "utf8" });
  if (result.status !== 0) {
    return { ok: false, detail: result.stderr || result.error?.message || "falha desconhecida" };
  }
  return { ok: true, detail: (result.stdout || "ok").trim().split("\n")[0] };
}

function printCheck(label, result) {
  const status = result.ok ? "ok" : "falhou";
  const detail = result.detail ? ` - ${result.detail.trim()}` : "";
  console.log(`${label}: ${status}${detail}`);
}

async function printEndpointCheck(label, url) {
  const result = await checkHttp(url);
  printCheck(`${label} ${url}`, result);
}

function checkHttp(url) {
  return new Promise((resolve) => {
    const client = url.startsWith("https:") ? https : http;
    const request = client.get(url, { timeout: 5000 }, (response) => {
      response.resume();
      const ok = response.statusCode >= 200 && response.statusCode < 400;
      resolve({ ok, detail: `HTTP ${response.statusCode}` });
    });
    request.on("timeout", () => {
      request.destroy();
      resolve({ ok: false, detail: "timeout" });
    });
    request.on("error", (error) => resolve({ ok: false, detail: error.message }));
  });
}

function reportBootstrapService(composeArgs, projectDir, service) {
  const ps = spawnSync("docker", [...composeArgs, "ps", "--all", "--format", "json", service], {
    cwd: path.join(projectDir, "infra"),
    encoding: "utf8"
  });
  if (ps.status !== 0) {
    printCheck(service, { ok: false, detail: ps.stderr || ps.error?.message || "falha ao consultar" });
    return;
  }

  const records = ps.stdout.trim().split(/\r?\n/).filter(Boolean).map((line) => {
    try {
      return JSON.parse(line);
    } catch {
      return null;
    }
  }).filter(Boolean);
  const record = records[0];
  if (!record) {
    printCheck(service, { ok: false, detail: "servico nao encontrado" });
    return;
  }

  const state = record.State || record.Status || "desconhecido";
  const exitCode = record.ExitCode;
  const ok = state === "exited" && (exitCode === 0 || exitCode === "0" || exitCode === undefined);
  printCheck(service, { ok, detail: `${state}${exitCode !== undefined ? ` exit=${exitCode}` : ""}` });
  if (!ok) {
    const logs = spawnSync("docker", [...composeArgs, "logs", "--tail", "80", service], {
      cwd: path.join(projectDir, "infra"),
      encoding: "utf8"
    });
    if (logs.stdout || logs.stderr) {
      console.log(`Ultimos logs de ${service}:`);
      process.stdout.write(logs.stdout || logs.stderr);
    }
  }
}

function readEnvFile(envPath) {
  if (!fs.existsSync(envPath)) {
    fail(`Arquivo .env nao encontrado: ${envPath}`);
  }

  const values = {};
  const content = fs.readFileSync(envPath, "utf8");
  for (const line of content.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }
    const index = trimmed.indexOf("=");
    if (index === -1) {
      continue;
    }
    values[trimmed.slice(0, index)] = trimmed.slice(index + 1);
  }
  return values;
}

function printDeploySummary(projectDir, mode, includeLlm, buildLocal, envValues) {
  const baseUrl = publicBaseUrl(envValues);
  const registry = envValues.DATAIF_IMAGE_REGISTRY || "docker.io/dataif";
  const tag = envValues.DATAIF_IMAGE_TAG || "0.1.2";
  console.log("\nResumo do deploy");
  console.log(`- Pasta: ${projectDir}`);
  console.log(`- Modo: ${mode}`);
  console.log(`- Projeto Compose: ${envValues.COMPOSE_PROJECT_NAME || "dataif"}`);
  console.log(`- Origem: ${buildLocal ? "build local" : `${registry}/*:${tag}`}`);
  console.log(`- Web: ${baseUrl}`);
  console.log(`- API: http://localhost:${envValues.API_PORT || "8000"}`);
  console.log(`- Metabase: ${baseUrl}/metabase/`);
  console.log(`- Airflow: ${baseUrl}/airflow/`);
  console.log(`- LLM local: ${includeLlm ? "sim" : "nao"}`);
}

function publicBaseUrl(envValues) {
  return (envValues.DATAIF_PUBLIC_BASE_URL || `http://localhost:${envValues.WEB_PORT || "5173"}`).replace(/\/+$/, "");
}

function reportRunningService(composeArgs, projectDir, service) {
  const ps = spawnSync("docker", [...composeArgs, "ps", "--format", "json", service], {
    cwd: path.join(projectDir, "infra"),
    encoding: "utf8"
  });
  if (ps.status !== 0) {
    printCheck(service, { ok: false, detail: ps.stderr || ps.error?.message || "falha ao consultar" });
    return;
  }
  const record = ps.stdout.trim().split(/\r?\n/).filter(Boolean).map((line) => {
    try {
      return JSON.parse(line);
    } catch {
      return null;
    }
  }).filter(Boolean)[0];
  if (!record) {
    printCheck(service, { ok: false, detail: "servico nao encontrado ou parado" });
    return;
  }
  const state = record.State || record.Status || "desconhecido";
  printCheck(service, { ok: state === "running", detail: state });
}

function reportFirewall(envValues) {
  const firewall = spawnSync("firewall-cmd", ["--state"], { encoding: "utf8" });
  if (firewall.error) {
    printCheck("firewalld", { ok: true, detail: "firewall-cmd nao encontrado" });
    return;
  }
  if (firewall.status !== 0) {
    printCheck("firewalld", { ok: true, detail: "inativo" });
    return;
  }
  const ports = [
    envValues.WEB_PORT,
    envValues.API_PORT,
    envValues.METABASE_PORT,
    envValues.AIRFLOW_PORT,
    envValues.KEYCLOAK_PORT,
    envValues.VANNA_PORT
  ].filter(Boolean);
  const open = spawnSync("firewall-cmd", ["--list-ports"], { encoding: "utf8" });
  const openPorts = new Set((open.stdout || "").trim().split(/\s+/).filter(Boolean));
  const missing = ports.filter((port) => !openPorts.has(`${port}/tcp`));
  if (missing.length === 0) {
    printCheck("firewalld portas", { ok: true, detail: "portas DataIF liberadas" });
  } else {
    printCheck("firewalld portas", {
      ok: false,
      detail: `faltando ${missing.map((port) => `${port}/tcp`).join(", ")}`
    });
  }
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: options.stdio || "pipe",
    cwd: options.cwd,
    env: options.env,
    encoding: options.stdio === "inherit" ? undefined : "utf8"
  });

  if (result.error && result.status === null) {
    fail(`Falha ao executar ${command}: ${result.error.message}`);
  }
  if (result.status !== 0) {
    const stderr = result.stderr ? `\n${result.stderr}` : "";
    fail(`Comando falhou (${result.status}): ${command} ${args.join(" ")}${stderr}`);
  }
  return result;
}

function expandHome(value) {
  if (!value) {
    return value;
  }
  if (value === "~") {
    return os.homedir();
  }
  if (value.startsWith("~/")) {
    return path.join(os.homedir(), value.slice(2));
  }
  return path.resolve(value);
}

function quotePath(value) {
  return value.includes(" ") ? `"${value}"` : value;
}

function fail(message) {
  console.error(`Erro: ${message}`);
  process.exit(1);
}
