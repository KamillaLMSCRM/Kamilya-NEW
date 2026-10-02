'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { parseArgs, configureEnvironment, validateConfig, forbiddenPath, boundedJson } = require('./codegraph.cjs');

test('invalid or weakened exclusions fail before source scanning', () => {
  const config = require('../../codegraph.json');
  assert.equal(validateConfig(config), config);
  assert.throws(() => validateConfig({ exclude: [] }));
  assert.throws(() => validateConfig({ ...config, includeIgnored: ['.env*'] }));
  assert.throws(() => validateConfig({ exclude: [...config.exclude, '!docs/private.py'] }));
});

test('commands cannot install hooks, serve, upgrade or accept another project', () => {
  for (const command of ['init', 'install', 'serve', 'watch', 'upgrade', 'uninit']) {
    assert.throws(() => parseArgs([command]));
  }
  assert.throws(() => parseArgs(['status', 'other-project']));
  assert.throws(() => parseArgs(['callers', 'confirm', '../other.py']));
  assert.throws(() => parseArgs(['search']));
  assert.deepEqual(parseArgs(['callers', 'confirm', 'apps/api/router.py']), {
    command: 'callers', symbol: 'confirm', file: 'apps/api/router.py',
  });
});

test('telemetry, update, daemon and watcher disabled before SDK load', () => {
  const keys = ['CODEGRAPH_TELEMETRY', 'DO_NOT_TRACK', 'CODEGRAPH_NO_UPDATE_CHECK', 'CODEGRAPH_NO_WATCH', 'CODEGRAPH_NO_DAEMON', 'CODEGRAPH_DIR', 'CODEGRAPH_INSTALL_DIR', 'NODE_COMPILE_CACHE'];
  const saved = Object.fromEntries(keys.map(key => [key, process.env[key]]));
  try {
    process.env.CODEGRAPH_DIR = '../../outside';
    configureEnvironment();
    assert.equal(process.env.CODEGRAPH_DIR, '.codegraph');
    assert.equal(process.env.CODEGRAPH_TELEMETRY, '0');
    for (const key of keys.slice(1, 5)) assert.equal(process.env[key], '1');
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  }
});

test('exclusion audit matches path segments, not release-evidence skill names', () => {
  for (const file of ['.env', 'apps/api/.env.dev', 'docs/example.py', '.release-evidence/probe.cjs', 'vendor/key.pem', 'vendor/cert.crt', 'apps\\api\\.env.py', 'docs\\private.py', 'apps/web/node_modules/test.js']) assert.equal(forbiddenPath(file), true);
  for (const file of ['apps/api/app/core/storage/local.py', '.codex/skills/kamilya-release-evidence-gate/scripts/evaluate_release_gate.py']) assert.equal(forbiddenPath(file), false);
});

test('bounded JSON remains valid, marks omissions and refuses oversized metadata', () => {
  const payload = { items: Array.from({ length: 12 }, () => ({ text: 'x'.repeat(1000) })) };
  const output = boundedJson(payload);
  assert.ok(output.length <= 6000);
  assert.equal(JSON.parse(output).truncated, true);
  assert.throws(() => boundedJson({ text: 'x'.repeat(6001) }));
});
