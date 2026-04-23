#!/usr/bin/env node
/*
 * PFIP script dispatcher.
 *
 * Thin wrapper invoked via `pnpm run <script>` / `npm run <script>`.
 * On Windows it dispatches to the matching PowerShell script (.ps1);
 * on POSIX platforms it dispatches to the bash script (.sh).
 *
 * Usage:
 *   node scripts/run.js <target> [extra args...]
 *
 * The mapping table below is the single source of truth for what every
 * npm/pnpm script in package.json actually does.
 */

'use strict';

const { spawnSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');

const IS_WIN = process.platform === 'win32';
const ROOT = path.resolve(__dirname, '..');
const SCRIPTS = __dirname;
const COMPOSE_FILE = path.join(ROOT, 'infra', 'docker-compose.yml');
const ENV_FILE = path.join(ROOT, '.env');

/**
 * @typedef {{script?: string, docker?: string[], exec?: string[], custom?: () => number}} Target
 */

/** @type {Record<string, Target>} */
const TARGETS = {
  up:               { script: 'up' },
  down:             { script: 'down' },
  stop:             { docker: ['stop'] },
  restart:          { custom: () => run('down') || run('up') },
  ps:               { docker: ['ps'] },
  logs:             { docker: ['logs', '-f', '--tail=200'] },
  'logs-backend':   { docker: ['logs', '-f', '--tail=200', 'backend'] },
  'logs-frontend':  { docker: ['logs', '-f', '--tail=200', 'frontend'] },
  health:           { script: 'health' },
  'shell-backend':  { exec: ['docker', 'exec', '-it', 'pfip-backend', 'bash'] },
  'shell-db':       { exec: ['docker', 'exec', '-it', 'pfip-timescaledb', 'psql', '-U', 'pfip', '-d', 'pfip'] },
  migrate:          { script: 'migrate' },
  'ingest-btc':     { script: 'ingest_btc' },
  'pull-models':    { script: 'pull_models' },
  test:             { custom: () => run('test-backend') || run('test-frontend') },
  'test-backend':   { exec: ['docker', 'exec', '-i', 'pfip-backend', 'pytest', '-q'] },
  'test-frontend':  { exec: ['docker', 'exec', '-i', 'pfip-frontend', 'pnpm', 'test', '--', '--run'] },
  lint:             { custom: () => (
    runCmd(['docker', 'exec', '-i', 'pfip-backend', 'ruff', 'check', '.']) ||
    runCmd(['docker', 'exec', '-i', 'pfip-frontend', 'pnpm', 'exec', 'prettier', '--check', '.'])
  )},
  format:           { custom: () => (
    runCmd(['docker', 'exec', '-i', 'pfip-backend', 'ruff', 'check', '--fix', '.']) ||
    runCmd(['docker', 'exec', '-i', 'pfip-frontend', 'pnpm', 'exec', 'prettier', '--write', '.'])
  )},
  backup:           { script: 'backup' },
  'restore-drill':  { script: 'restore_drill' },
};

function die(msg, code = 1) {
  process.stderr.write(`[run.js] ${msg}\n`);
  process.exit(code);
}

function runCmd(argv, opts = {}) {
  const [cmd, ...args] = argv;
  const res = spawnSync(cmd, args, { stdio: 'inherit', shell: false, ...opts });
  if (res.error) {
    process.stderr.write(`[run.js] failed to spawn: ${res.error.message}\n`);
    return res.status ?? 1;
  }
  return res.status ?? 0;
}

function runScript(base, extra) {
  const ps1 = path.join(SCRIPTS, `${base}.ps1`);
  const sh  = path.join(SCRIPTS, `${base}.sh`);

  if (IS_WIN) {
    if (!fs.existsSync(ps1)) die(`missing script: ${ps1}`);
    return runCmd([
      'powershell.exe',
      '-NoProfile',
      '-ExecutionPolicy', 'Bypass',
      '-File', ps1,
      ...extra,
    ]);
  }
  if (!fs.existsSync(sh)) die(`missing script: ${sh}`);
  return runCmd(['bash', sh, ...extra]);
}

function runDocker(subcmd, extra) {
  return runCmd([
    'docker', 'compose',
    '-f', COMPOSE_FILE,
    '--env-file', ENV_FILE,
    ...subcmd, ...extra,
  ]);
}

function run(target, extra = []) {
  const t = TARGETS[target];
  if (!t) die(`unknown target: ${target}. Known: ${Object.keys(TARGETS).join(', ')}`);

  if (t.custom) return t.custom();
  if (t.script) return runScript(t.script, extra);
  if (t.docker) return runDocker(t.docker, extra);
  if (t.exec)   return runCmd([...t.exec, ...extra]);
  die(`target ${target} has no handler`);
}

function main() {
  const [target, ...extra] = process.argv.slice(2);
  if (!target) die(`usage: node run.js <target>\nKnown: ${Object.keys(TARGETS).join(', ')}`);
  process.exit(run(target, extra));
}

main();
