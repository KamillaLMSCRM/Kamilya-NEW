#!/usr/bin/env node
'use strict';

// Read-only, database-free matched navigation pilot. Never syncs or builds an index.
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const CHILD_ENV_KEYS = [
  'PATH', 'Path', 'PATHEXT', 'SystemRoot', 'WINDIR', 'ComSpec',
  'TEMP', 'TMP', 'USERPROFILE', 'HOME',
];

function childEnv() {
  const env = {};
  for (const key of CHILD_ENV_KEYS) {
    if (process.env[key] !== undefined) env[key] = process.env[key];
  }
  return {
    ...env,
    CODEGRAPH_TELEMETRY: '0',
    CODEGRAPH_NO_UPDATE_CHECK: '1',
    CODEGRAPH_NO_WATCH: '1',
    CODEGRAPH_NO_DAEMON: '1',
    DO_NOT_TRACK: '1',
  };
}

function executablePath(command) {
  if (command === 'node') return process.execPath;
  const lookup = spawnSync(process.platform === 'win32' ? 'where.exe' : 'which', [command], {
    cwd: root, encoding: 'utf8', windowsHide: true, env: childEnv(),
  });
  return (lookup.stdout || '').split(/\r?\n/).map((line) => line.trim()).find(Boolean) || 'NOT_FOUND';
}

function metadata() {
  const graph = spawnSync('graphify', ['--version'], { cwd: root, encoding: 'utf8', windowsHide: true, env: childEnv() });
  const rg = spawnSync('rg', ['--version'], { cwd: root, encoding: 'utf8', windowsHide: true, env: childEnv() });
  const node = spawnSync(process.execPath, ['--version'], { cwd: root, encoding: 'utf8', windowsHide: true, env: childEnv() });
  return {
    capturedAt: new Date().toISOString(),
    paths: {
      node: process.execPath,
      rg: executablePath('rg'),
      graphify: executablePath('graphify'),
      codegraphWrapper: path.join(root, 'scripts/dev/codegraph.cjs'),
    },
    versions: {
      node: (node.stdout || '').trim(),
      rg: (rg.stdout || '').split(/\r?\n/)[0].trim(),
      graphify: (graph.stdout || '').trim(),
      codegraphWrapper: 'wrapper 1.6.1',
    },
    networkGuard: 'NOT_ENFORCED; no provider/network calls intentionally requested',
  };
}

const tasks = [
  {
    id: 'contextual-help-consumer',
    rg: ['-n', '--with-filename', 'getContextualHelp|ContextualHelpButton', 'apps/web/src/lib/contextualHelp.ts', 'apps/web/src/components/layout/ContextualHelpButton.tsx'],
    codegraph: ['callers', 'getContextualHelp', 'apps/web/src/lib/contextualHelp.ts'],
    graphify: 'getContextualHelp',
    oraclePaths: ['apps/web/src/components/layout/ContextualHelpButton.tsx'], oracleNeedles: ['getContextualHelp'],
  },
  {
    id: 'assignment-preview-consumer',
    rg: ['-n', '--with-filename', 'requestAssignmentPreview|assignment-preview', 'apps/web/src/features/methodologist-workbench/AssignmentWorkbench.tsx', 'apps/web/src/lib/methodologistWorkbench.ts'],
    codegraph: ['callers', 'requestAssignmentPreview', 'apps/web/src/lib/methodologistWorkbench.ts'],
    graphify: 'requestAssignmentPreview',
    oraclePaths: ['apps/web/src/features/methodologist-workbench/AssignmentWorkbench.tsx'], oracleNeedles: ['requestAssignmentPreview'],
  },
  {
    id: 'sidebar-route-registry-consumer',
    rg: ['-n', '--with-filename', 'getNavigationRoutes', 'apps/web/src/components/layout/Sidebar.tsx', 'apps/web/src/lib/routeRegistry.ts'],
    codegraph: ['callers', 'getNavigationRoutes', 'apps/web/src/lib/routeRegistry.ts'],
    graphify: 'getNavigationRoutes',
    oraclePaths: ['apps/web/src/components/layout/Sidebar.tsx'], oracleNeedles: ['getNavigationRoutes'],
  },
  {
    id: 'methodologist-preview-api-entry',
    rg: ['-n', '--with-filename', 'preview_assignment|assignment-preview', 'apps/api/app/modules/methodologist_workbench/assignment_router.py'],
    codegraph: ['search', 'preview_assignment', 'apps/api/app/modules/methodologist_workbench/assignment_router.py'],
    graphify: 'preview_assignment',
    oraclePaths: ['apps/api/app/modules/methodologist_workbench/assignment_router.py'], oracleNeedles: ['preview_assignment'],
  },
];

function run(tool, task) {
  let command;
  let args;
  if (tool === 'rg') {
    command = 'rg'; args = task.rg;
  } else if (tool === 'codegraph') {
    command = process.execPath; args = ['--liftoff-only', 'scripts/dev/codegraph.cjs', ...task.codegraph];
  } else {
    command = 'graphify'; args = ['query', task.graphify, '--budget', '800', '--graph', 'graphify-out/graph.json'];
  }
  const started = process.hrtime.bigint();
  const result = spawnSync(command, args, {
    cwd: root, encoding: 'utf8', windowsHide: true, timeout: 30000,
    env: childEnv(),
  });
  const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6;
  const stdout = result.stdout || '';
  const stderr = result.stderr || '';
  const output = stdout + stderr;
  const oracle = structuralOracle(output, task);
  let parsed = null;
  try { parsed = JSON.parse(stdout); } catch { /* rg/Graphify text */ }
  const truncated = tool === 'codegraph'
    ? parsed?.truncated === true
    : tool === 'graphify'
      ? /TRUNCATED:\s+showing\s+\d+\s+of\s+\d+\s+nodes/i.test(output)
      : false;
  const unavailable = result.error || result.status !== 0;
  let outputItems = (output.match(/^NODE |^[^\r\n]*:\d+:/gm) || []).length;
  if (tool === 'codegraph') {
    try { outputItems = parsed?.items?.length ?? 0; } catch { outputItems = 0; }
  }
  return {
    tool, task: task.id, exitCode: result.status, elapsedMs: Math.round(elapsedMs * 100) / 100,
    outputBytes: Buffer.byteLength(output, 'utf8'),
    outputItems,
    truncated, oracleNeedles: oracle.required, oracleHits: oracle.matched,
    correctness: unavailable ? 'NOT_AVAILABLE' : (oracle.matched === oracle.required ? 'PASS' : 'FAIL_OR_UNCONFIRMED'),
    falseRelations: 'NOT_MEASURED', missingRelations: Math.max(0, oracle.required - oracle.matched),
    sourceReadsAvoided: 'NOT_MEASURED', correctionCycles: 'NOT_APPLICABLE',
    error: result.error ? String(result.error.message) : (result.status === 0 ? null : stderr.trim().slice(0, 240)),
  };
}

function structuralOracle(output, task) {
  const pairs = task.oraclePaths.map((sourcePath, index) => ({
    sourcePath: sourcePath.replace(/\\/g, '/').toLowerCase(),
    needle: task.oracleNeedles[index].toLowerCase(),
  }));
  const lines = output.split(/\r?\n/).map((line) => line.toLowerCase().replace(/\\/g, '/'));
  const objects = [];
  let parsed;
  try { parsed = JSON.parse(output); } catch { parsed = null; }
  const visit = (value) => {
    if (!value || typeof value !== 'object') return;
    if (Array.isArray(value)) { value.forEach(visit); return; }
    // Only scalar fields of one object: a parent containing unrelated nodes
    // must not combine a path in one child with a symbol in another.
    objects.push(Object.values(value).filter((field) => typeof field === 'string')
      .join('\n').toLowerCase().replace(/\\/g, '/'));
    Object.values(value).forEach(visit);
  };
  visit(parsed);
  const matched = pairs.filter(({ sourcePath, needle }) =>
    (!parsed && lines.some((line) => line.includes(sourcePath) && line.includes(needle)))
    || objects.some((object) => object.includes(sourcePath) && object.includes(needle)),
  ).length;
  return { matched, required: pairs.length };
}

function main() {
  if (process.argv[2] === '--metadata') {
    process.stdout.write(JSON.stringify(metadata(), null, 2));
    return;
  }
  const rows = [];
  for (let rep = 1; rep <= 2; rep += 1) {
    const order = rep === 1 ? ['rg', 'codegraph', 'graphify'] : ['graphify', 'codegraph', 'rg'];
    for (const tool of order) for (const task of tasks) rows.push({ rep, ...run(tool, task) });
  }
  const graph = spawnSync('graphify', ['--version'], { cwd: root, encoding: 'utf8', windowsHide: true, env: childEnv() });
  const node = spawnSync(process.execPath, ['--version'], { cwd: root, encoding: 'utf8', windowsHide: true, env: childEnv() });
  const payload = {
    benchmark: 'tool-efficiency-navigation-2026-10-03',
    checkout: root, preparation: 'fixed tasks/oracles; no index/sync/update',
    reps: 2, arms: ['rg', 'codegraph', 'graphify'],
    paths: { node: process.execPath, rg: executablePath('rg'), graphify: executablePath('graphify'), codegraphWrapper: path.join(root, 'scripts/dev/codegraph.cjs') },
    versions: { node: (node.stdout || '').trim(), graphify: (graph.stdout || '').trim(), codegraph: 'wrapper 1.6.1' },
    networkGuard: 'NOT_ENFORCED; no provider/network calls intentionally requested',
    rows,
  };
  const capture = process.argv[2] === '--capture' ? process.argv[3] : null;
  const allowed = path.join(root, '.release-evidence', 'CLIENT-ACCEPTANCE-20261003', 'navigation-benchmark.json');
  if (capture && path.resolve(capture) !== allowed) throw new Error('Capture path is fixed to the approved ignored artifact.');
  if (capture) { fs.mkdirSync(path.dirname(allowed), { recursive: true }); fs.writeFileSync(allowed, JSON.stringify(payload, null, 2)); }
  process.stdout.write(JSON.stringify(payload, null, 2));
}
if (require.main === module) main();

module.exports = { childEnv, structuralOracle, tasks };
