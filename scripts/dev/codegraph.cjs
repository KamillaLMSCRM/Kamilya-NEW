#!/usr/bin/env node
'use strict';

// Repository-local navigation, not runtime, security or release evidence.
const fs = require('node:fs');
const path = require('node:path');
const VERSION = '1.6.1';
const ROOT = path.resolve(__dirname, '../..');
const TOOL_ROOT = path.join(ROOT, '.release-evidence', 'codegraph-pilot');
const LIMIT = 12;
const MAX_OUTPUT = 6000;
const COMMANDS = new Set(['index', 'sync', 'status', 'search', 'callers', 'callees']);
const REQUIRED_EXCLUDES = ['**/.env*', '**/*.pem', '**/*.key', '**/*.crt',
  '.release-evidence/**', 'graphify-out/**', 'outputs/**', 'docs/**',
  '**/node_modules/**', '**/.venv/**', '**/.next/**', 'apps/api/storage/**', 'storage/**'];

function validateConfig(config) {
  if (!config || Object.keys(config).some(key => !['exclude', 'deprioritize'].includes(key))
      || !Array.isArray(config.exclude) || config.exclude.some(pattern => typeof pattern !== 'string' || !pattern || pattern.startsWith('!'))
      || REQUIRED_EXCLUDES.some(pattern => !config.exclude.includes(pattern))) {
    throw new Error('Unsafe/missing CodeGraph exclusions; indexing refused before source scanning.');
  }
  return config;
}

function parseArgs(args) {
  const [command, symbol, file] = args;
  if (!COMMANDS.has(command) || args.length > 3) throw new Error(
    'Usage: node --liftoff-only scripts/dev/codegraph.cjs index|sync|status|search|callers|callees [symbol] [file]');
  const query = ['search', 'callers', 'callees'].includes(command);
  if (query && (!symbol || symbol.length > 256)) throw new Error('A bounded symbol/query is required.');
  if (!query && (symbol || file)) throw new Error('This command takes no extra arguments.');
  if (file && (path.isAbsolute(file) || file.split(/[\\/]/).includes('..'))) {
    throw new Error('File must be project-relative, without traversal.');
  }
  return { command, symbol, file: file?.replaceAll('\\', '/') };
}

function configureEnvironment() {
  // Set before loading the SDK; never alter the global user config or Git hooks.
  Object.assign(process.env, {
    CODEGRAPH_TELEMETRY: '0', DO_NOT_TRACK: '1', CODEGRAPH_NO_UPDATE_CHECK: '1',
    CODEGRAPH_NO_WATCH: '1', CODEGRAPH_NO_DAEMON: '1', CODEGRAPH_DIR: '.codegraph',
    CODEGRAPH_INSTALL_DIR: path.join(TOOL_ROOT, 'cache'),
    NODE_COMPILE_CACHE: path.join(TOOL_ROOT, 'node-cache'),
  });
}

function forbiddenPath(file) {
  file = file.replaceAll('\\', '/');
  return /(^|\/)\.env[^/]*($|\/)|(^|\/)(\.venv|node_modules|\.next|\.release-evidence|graphify-out|outputs|docs)(\/|$)|\.(pem|key|crt)$/i.test(file);
}

function nodeSummary(node) {
  return { id: node.id, name: node.name, kind: node.kind, file: node.filePath, line: node.startLine };
}

function boundedJson(payload) {
  let output = JSON.stringify(payload);
  // Keep valid JSON and mark omissions rather than truncating arbitrary bytes.
  while (output.length > MAX_OUTPUT && payload.items?.length) {
    payload.items.pop();
    payload.truncated = true;
    output = JSON.stringify(payload);
  }
  if (output.length > MAX_OUTPUT) throw new Error('Summary exceeds output budget. Narrow the query.');
  return output;
}

async function run(args) {
  const { command, symbol, file } = parseArgs(args);
  if (!fs.existsSync(path.join(ROOT, 'apps/api/app'))) throw new Error('Not a Kamilya LMS checkout.');
  configureEnvironment();
  const config = validateConfig(JSON.parse(fs.readFileSync(path.join(ROOT, 'codegraph.json'), 'utf8')));
  const sdk = path.join(TOOL_ROOT, 'runtime/node_modules/@colbymchenry/codegraph');
  if (!fs.existsSync(path.join(sdk, 'package.json'))) throw new Error('Pinned local runtime missing; see docs/runbooks/codegraph-local.md.');
  if (JSON.parse(fs.readFileSync(path.join(sdk, 'package.json'), 'utf8')).version !== VERSION) {
    throw new Error('Unexpected CodeGraph version; review before upgrading.');
  }
  const { CodeGraph, getCodeGraphDir } = require(sdk);
  if (path.resolve(getCodeGraphDir(ROOT)) !== path.join(ROOT, '.codegraph')) {
    throw new Error('SDK index directory escaped the fixed checkout.');
  }
  const indexDir = path.join(ROOT, '.codegraph');
  if (fs.existsSync(indexDir) && fs.lstatSync(indexDir).isSymbolicLink()) {
    throw new Error('Index directory must not be a symlink/junction.');
  }
  // The pinned SDK auto-discovers project config; verify its effective view BEFORE indexing.
  const configModule = require.resolve(`@colbymchenry/codegraph-${process.platform}-${process.arch}/lib/dist/project-config.js`, { paths: [sdk] });
  const configApi = require(configModule);
  if (JSON.stringify(configApi.loadExcludePatterns(ROOT)) !== JSON.stringify(config.exclude)
      || configApi.loadIncludeIgnoredPatterns(ROOT).length || configApi.loadIncludePatterns(ROOT).length) {
    throw new Error('SDK exclusion discovery mismatch; indexing refused before source scanning.');
  }
  const initialized = CodeGraph.isInitialized(ROOT);
  if (!initialized && command !== 'index') throw new Error('Index missing. Run index explicitly.');
  const writing = ['index', 'sync'].includes(command);
  const graph = initialized ? await CodeGraph.open(ROOT, { readOnly: !writing }) : await CodeGraph.init(ROOT);
  const started = performance.now();
  try {
    const payload = { version: VERSION, command, evidence: 'STATIC_NAVIGATION_ONLY; EDGES_ARE_CANDIDATES_NOT_RUNTIME_PROOF',
      freshness: 'Manual snapshot: sync after edits; confirm decisive links in source/tests.' };
    if (writing) {
      const result = command === 'index' ? await graph.indexAll() : await graph.sync();
      if (result.success === false || result.errors?.length) throw new Error('Indexing errors; index is not accepted.');
      payload.update = { success: true, filesIndexed: result.filesIndexed, durationMs: result.durationMs };
    }
    const forbidden = graph.getFiles().filter(record => forbiddenPath(record.path));
    if (forbidden.length) throw new Error(`Excluded files found (${forbidden.length}); do not query this index.`);
    if (['index', 'sync', 'status'].includes(command)) {
      payload.stats = graph.getStats();
      payload.excludedPathAudit = 'PASS';
    } else {
      const hits = graph.searchNodes(symbol, { limit: 50, includePatterns: file ? [file] : undefined }).map(hit => hit.node)
        .filter(node => !file || node.filePath.replaceAll('\\', '/') === file);
      if (command === 'search') {
        payload.totalCandidates = hits.length;
        payload.items = hits.slice(0, LIMIT).map(nodeSummary);
        payload.truncated = hits.length > LIMIT;
      } else {
        const definitions = hits.filter(node => node.name === symbol && ['function', 'method', 'component'].includes(node.kind));
        if (definitions.length !== 1) throw new Error(`Expected one definition; found ${definitions.length}. Use search then specify its file.`);
        const focal = definitions[0];
        payload.focal = nodeSummary(focal);
        const edges = (command === 'callers' ? graph.getIncomingEdges(focal.id) : graph.getOutgoingEdges(focal.id))
          .filter(edge => edge.kind === 'calls');
        payload.totalEdges = edges.length;
        const summaries = edges.map(edge => ({
          node: nodeSummary(graph.getNode(command === 'callers' ? edge.source : edge.target)),
          kind: edge.kind, callLine: edge.line, provenance: edge.provenance ?? 'unspecified',
        }));
        // Show product callers before scripts/tests when a capped list is needed.
        const rank = item => /^apps\/(api\/app|web\/src)\//.test(item.node.file) ? 0 : 1;
        summaries.sort((a, b) => rank(a) - rank(b) || a.node.file.localeCompare(b.node.file) || a.callLine - b.callLine);
        payload.items = summaries.slice(0, LIMIT);
        payload.truncated = edges.length > LIMIT;
      }
    }
    payload.elapsedMs = Math.round(performance.now() - started);
    return boundedJson(payload);
  } finally { graph.destroy(); }
}

if (require.main === module) run(process.argv.slice(2)).then(console.log).catch(error => {
  console.error(error.message); process.exitCode = 1;
});
module.exports = { parseArgs, configureEnvironment, validateConfig, forbiddenPath, boundedJson, run };
