#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const packageRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(packageRoot, "..", "..");
const templateRoot = path.join(packageRoot, "templates", "dataif");

const entries = [
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

fs.rmSync(templateRoot, { recursive: true, force: true });
fs.mkdirSync(templateRoot, { recursive: true });

for (const entry of entries) {
  const src = path.join(repoRoot, entry);
  if (!fs.existsSync(src)) {
    throw new Error(`Arquivo esperado nao encontrado: ${src}`);
  }
  copyRecursive(src, path.join(templateRoot, entry));
}

console.log(`Template DataIF gerado em ${templateRoot}`);
