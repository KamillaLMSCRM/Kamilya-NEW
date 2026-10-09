#!/usr/bin/env node
'use strict';

// Explicit, checkout-local AST preparation. Default mode is read-only.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const { validateConfig, forbiddenPath } = require('./codegraph.cjs');
const ROOT = path.resolve(__dirname, '../..');
const VERSION = '1.6.1';
const DEFAULT_PYTHON = 'C:/Users/user/AppData/Local/pipx/pipx/venvs/graphifyy/Scripts/python.exe';
const RECEIPT = '.release-evidence/navigation/receipt.json';
const SDK = '.release-evidence/codegraph-pilot/runtime/node_modules/@colbymchenry/codegraph/package.json';
const INDEXES = ['.codegraph/codegraph.db', 'graphify-out/graph.json'];
// Conservative union of local extractor languages; hashes are not graph input.
const EXTENSIONS = new Set(('py ts tsx mts cts js jsx mjs cjs ejs ets go rs java groovy gradle cpp cc cxx c h hpp cu cuh metal rb rake swift kt kts cs scala php lua luau toc zig ps1 psm1 psd1 ex exs m mm jl vue svelte astro dart v sv svh sql r f f90 f95 f03 f08 pas pp dpr dpk lpr inc dfm lfm lpk sh bash json tf tfvars hcl dm dme dmi dmm dmf sln slnx csproj fsproj vbproj xaml razor cshtml cls trigger yaml yml').split(' '));

EXTENSIONS.add('toml'); // Graphify also emits package nodes from pyproject.toml.

function childEnvironment() {
  const env = {};
  for (const key of ['PATH', 'Path', 'PATHEXT', 'SystemRoot', 'WINDIR', 'ComSpec', 'TEMP', 'TMP', 'USERPROFILE', 'HOME']) {
    if (process.env[key] !== undefined) env[key] = process.env[key];
  }
  return { ...env, GRAPHIFY_MAX_WORKERS: '2', GRAPHIFY_FORCE: '0', PYTHONUTF8: '1',
    CODEGRAPH_TELEMETRY: '0', CODEGRAPH_NO_UPDATE_CHECK: '1', DO_NOT_TRACK: '1' };
}

function parseArgs(args) {
  let prepare = false, python = DEFAULT_PYTHON;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--prepare' && !prepare) prepare = true;
    else if (args[i] === '--graphify-python' && args[i + 1] && path.isAbsolute(args[i + 1])) python = args[++i];
    else throw new Error('Usage: node scripts/dev/prepare_navigation.cjs [--prepare] [--graphify-python ABSOLUTE_PATH]');
  }
  return { prepare, python: path.resolve(python) };
}

function safeFile(root, relative) {
  const absolute = path.resolve(root, relative);
  const rel = path.relative(root, absolute);
  if (!rel || rel.startsWith('..') || path.isAbsolute(rel)) throw new Error('Path escaped checkout.');
  let current = root;
  for (const part of rel.split(path.sep)) {
    current = path.join(current, part);
    if (fs.existsSync(current) && fs.lstatSync(current).isSymbolicLink()) throw new Error('Symlink/junction refused.');
  }
  return absolute;
}

const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const fileHash = (root, relative) => hash(fs.readFileSync(safeFile(root, relative)));
function includedSource(relative) {
  const normalized = relative.replaceAll('\\', '/');
  return !forbiddenPath(normalized)
    && !/(^|\/)(\.git|\.codegraph|\.worktrees)(\/|$)|^(apps\/api\/storage|storage)\//i.test(normalized)
    && (EXTENSIONS.has(path.extname(normalized).slice(1).toLowerCase())
      || /^infra\/(deploy|systemd)\/kamilya-[^/.]+$/.test(normalized)
      || ['.graphifyignore', 'scripts/dev/codegraph.public.npmrc', 'scripts/dev/codegraph.global.npmrc'].includes(normalized));
}

function fingerprint(root, files) {
  const selected = [...new Set(files.filter(includedSource))].sort();
  // A tracked deletion is a meaningful input, not a silently skipped file.
  const entries = selected.map(file => [file, fs.existsSync(safeFile(root, file)) ? fileHash(root, file) : 'DELETED']);
  return { sha256: hash(JSON.stringify(entries)), fileCount: selected.length };
}

function exec(executable, args, root, options = {}) {
  const started = Date.now();
  const child = spawnSync(executable, args, { cwd: root, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024,
    timeout: 10 * 60 * 1000, windowsHide: true, env: childEnvironment(), ...options });
  if (child.error || child.status !== 0) throw new Error(`Command failed: ${path.basename(executable)} ${args[0] || ''}; ${child.error?.code || `exit ${child.status}`}. No further preparation performed.`);
  return { stdout: child.stdout, stderr: child.stderr, elapsedMs: Date.now() - started };
}

function inputs(root) {
  return fingerprint(root, exec('git', ['ls-files', '--cached', '--others', '--exclude-standard', '-z'], root).stdout.split('\0').filter(Boolean));
}

function artifactHashes(root) {
  const artifacts = [...INDEXES, 'graphify-out/.graphify_root', 'graphify-out/.graphify_python'];
  // SQLite readers can create empty WAL/SHM files without changing the index.
  // Nonempty WAL contains snapshot data; never ignore those bytes.
  const wal = safeFile(root, '.codegraph/codegraph.db-wal');
  if (fs.existsSync(wal) && fs.statSync(wal).size > 0) artifacts.push('.codegraph/codegraph.db-wal');
  return Object.fromEntries(artifacts.map(file => [file, fileHash(root, file)]));
}

function validateReceipt(receipt, actual) {
  if (receipt?.schema !== 1 || receipt.root !== actual.root) throw new Error('Missing receipt or different checkout root.');
  if (receipt.codegraphVersion !== VERSION || receipt.graphifyVersion !== actual.graphifyVersion
      || receipt.graphifyPython !== actual.graphifyPython) throw new Error('Tool identity changed.');
  if (receipt.sources?.sha256 !== actual.sources.sha256) throw new Error('Source snapshot changed; prepare the indexes once before graph-dependent review.');
  if (JSON.stringify(receipt.artifacts) !== JSON.stringify(actual.artifacts)) throw new Error('Index snapshot changed; verify/rebuild before accepting a new receipt.');
}

function auditGraph(root, graph) {
  if (!Array.isArray(graph.nodes) || !graph.nodes.length || !Array.isArray(graph.links || graph.edges)) throw new Error('Graphify graph is empty or unreadable.');
  const sources = new Set(graph.nodes.map(node => node.source_file).filter(Boolean));
  if (!sources.size) throw new Error('Graphify source metadata missing.');
  for (const file of sources) {
    const relative = path.relative(root, path.resolve(root, file)).replaceAll('\\', '/');
    if (!includedSource(relative) || !fs.existsSync(safeFile(root, relative))) throw new Error('Graphify source audit failed; graph not accepted.');
  }
  return { nodes: graph.nodes.length, edges: (graph.links || graph.edges).length, sourceFiles: sources.size, excludedPathAudit: 'PASS' };
}

function run(args) {
  const { prepare, python } = parseArgs(args);
  const root = fs.realpathSync(ROOT);
  if (!fs.existsSync(path.join(root, 'apps/api/app'))) throw new Error('Not a Kamilya LMS checkout.');
  const config = validateConfig(JSON.parse(fs.readFileSync(path.join(root, 'codegraph.json'), 'utf8')));
  for (const file of [...INDEXES, SDK, RECEIPT]) safeFile(root, file);
  if (!fs.existsSync(safeFile(root, SDK))) throw new Error('CodeGraph runtime missing; run pinned install and signature audit in docs/runbooks/codegraph-local.md.');
  if (JSON.parse(fs.readFileSync(safeFile(root, SDK), 'utf8')).version !== VERSION) throw new Error('Unexpected CodeGraph runtime; do not upgrade automatically.');
  if (!fs.existsSync(python)) throw new Error('Graphify interpreter missing; use the documented installed runtime, not a new global install.');
  // Never inherit a forced overwrite or LLM credentials into AST preparation.
  const env = childEnvironment();
  const version = exec(python, ['-m', 'graphify', '--version'], root, { env });
  const graphifyVersion = version.stdout.trim();
  const sources = inputs(root);
  const marker = safeFile(root, 'graphify-out/.graphify_root');
  if (fs.existsSync(marker) && path.resolve(fs.readFileSync(marker, 'utf8').trim()) !== root) throw new Error('Graphify index belongs to another checkout; do not copy/overwrite it.');
  if (!prepare) {
    const receipt = JSON.parse(fs.readFileSync(safeFile(root, RECEIPT), 'utf8'));
    validateReceipt(receipt, { root, sources, graphifyVersion, graphifyPython: python, artifacts: artifactHashes(root) });
    return { result: 'READY', mode: 'READ_ONLY', root, codegraphVersion: VERSION, graphifyVersion, sources,
      evidence: 'STATIC_NAVIGATION_ONLY; validate decisive links in source/tests/runtime.' };
  }
  exec('py', ['-3', 'scripts/dev/check_primary_checkout.py', '--mode', 'write'], root);
  const timings = {};
  const codegraph = exec(process.execPath, ['--liftoff-only', 'scripts/dev/codegraph.cjs', fs.existsSync(safeFile(root, INDEXES[0])) ? 'sync' : 'index'], root);
  timings.codegraphMs = codegraph.elapsedMs;
  const codegraphResult = JSON.parse(codegraph.stdout.trim());
  if (codegraphResult.excludedPathAudit !== 'PASS' || !codegraphResult.stats?.fileCount) throw new Error('CodeGraph acceptance failed.');
  const graphArgs = ['-m', 'graphify', 'extract', '.', '--code-only', '--max-workers', '2'];
  for (const exclusion of config.exclude) graphArgs.push('--exclude', exclusion);
  const graphify = exec(python, graphArgs, root, { env });
  timings.graphifyMs = graphify.elapsedMs;
  if (!fs.existsSync(marker) || path.resolve(fs.readFileSync(marker, 'utf8').trim()) !== root) throw new Error('Graphify root marker missing or incorrect.');
  const graph = JSON.parse(fs.readFileSync(safeFile(root, INDEXES[1]), 'utf8'));
  const graphStats = auditGraph(root, graph);
  const analysis = JSON.parse(fs.readFileSync(safeFile(root, 'graphify-out/.graphify_analysis.json'), 'utf8'));
  if (analysis.tokens?.input !== 0 || analysis.tokens?.output !== 0) throw new Error('Graphify preparation was not zero-token AST-only; no receipt accepted.');
  const after = inputs(root);
  if (after.sha256 !== sources.sha256) throw new Error('Source changed during preparation; no receipt written.');
  fs.writeFileSync(safeFile(root, 'graphify-out/.graphify_python'), python, 'utf8');
  fs.mkdirSync(safeFile(root, '.release-evidence/navigation'), { recursive: true });
  const receipt = { schema: 1, root, preparedAt: new Date().toISOString(),
    revision: exec('git', ['rev-parse', 'HEAD'], root).stdout.trim(),
    codegraphVersion: VERSION, graphifyVersion, graphifyPython: python, sources,
    artifacts: artifactHashes(root), codegraphStats: codegraphResult.stats, graphifyStats: graphStats, timings,
    warning: version.stderr.includes('warning:') ? 'Graphify CLI/skill metadata differ; AST extract capability verified, no global upgrade performed.' : null };
  fs.writeFileSync(safeFile(root, RECEIPT), `${JSON.stringify(receipt, null, 2)}\n`, 'utf8');
  return { result: 'PREPARED', root, receipt: RECEIPT, codegraphFiles: codegraphResult.stats.fileCount,
    graphify: graphStats, timings, warning: receipt.warning };
}

if (require.main === module) {
  try { console.log(JSON.stringify(run(process.argv.slice(2)))); }
  catch (error) { console.error(JSON.stringify({ result: 'NOT_READY', reason: error.code === 'ENOENT' ? 'Required local index/receipt missing; see docs/runbooks/codegraph-local.md.' : error.message })); process.exitCode = 1; }
}
module.exports = { childEnvironment, parseArgs, safeFile, includedSource, fingerprint, artifactHashes, validateReceipt, auditGraph, run };
