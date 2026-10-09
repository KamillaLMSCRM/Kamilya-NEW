'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { childEnvironment, parseArgs, safeFile, includedSource, fingerprint, artifactHashes, validateReceipt, auditGraph } = require('./prepare_navigation.cjs');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'kamilya-navigation-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.writeFileSync(path.join(root, 'source.py'), 'def original(): pass\n');
  return root;
}

test('default is read-only; no hooks, force, arbitrary project or relative interpreter', () => {
  assert.equal(parseArgs([]).prepare, false);
  assert.equal(parseArgs(['--prepare']).prepare, true);
  for (const args of [['--force'], ['--install'], ['--root', '..'], ['--graphify-python', '../python']]) assert.throws(() => parseArgs(args));
});

test('children never inherit provider or arbitrary secrets, forced writes or alternate index roots', () => {
  const keys = ['DEEPSEEK_API_KEY', 'ARBITRARY_PASSWORD', 'GRAPHIFY_FORCE', 'CODEGRAPH_DIR'];
  const previous = keys.map(key => process.env[key]);
  try {
    for (const key of keys) process.env[key] = 'synthetic-sentinel';
    const env = childEnvironment();
    assert.equal(env.GRAPHIFY_FORCE, '0');
    for (const key of ['DEEPSEEK_API_KEY', 'ARBITRARY_PASSWORD', 'CODEGRAPH_DIR']) assert.equal(Object.hasOwn(env, key), false);
  } finally {
    keys.forEach((key, index) => {
      if (previous[index] === undefined) delete process.env[key]; else process.env[key] = previous[index];
    });
  }
});

test('source fingerprint detects content edits, additions and tracked deletions', t => {
  const root = fixture(t);
  const before = fingerprint(root, ['source.py']);
  fs.writeFileSync(path.join(root, 'source.py'), 'def changed(): pass\n');
  assert.notEqual(fingerprint(root, ['source.py']).sha256, before.sha256);
  fs.writeFileSync(path.join(root, 'new.ts'), 'export const addition = 1;');
  assert.notEqual(fingerprint(root, ['source.py', 'new.ts']).sha256, fingerprint(root, ['source.py']).sha256);
  fs.unlinkSync(path.join(root, 'source.py'));
  assert.notEqual(fingerprint(root, ['source.py']).sha256, fingerprint(root, []).sha256);
});

test('private, generated, documents and runtime storage are not source inputs', () => {
  for (const file of ['.env.py', 'docs/private.py', '.release-evidence/probe.cjs', '.codegraph/private.json', 'graphify-out/graph.json', 'node_modules/index.js', 'outputs/example.py', 'storage/raw.json', 'apps/api/storage/raw.json', '.worktrees/other/source.py', 'cert.pem']) assert.equal(includedSource(file), false, file);
  for (const file of ['apps/api/app/core/storage/local.py', 'scripts/dev/prepare_navigation.cjs', 'codegraph.json', '.github/workflows/test.yml', 'apps/api/pyproject.toml', 'infra/deploy/kamilya-release-runner']) assert.equal(includedSource(file), true, file);
});

test('path confinement rejects traversal and artifact-directory junctions', t => {
  const root = fixture(t);
  assert.throws(() => safeFile(root, '../outside.py'));
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), 'kamilya-navigation-outside-'));
  t.after(() => fs.rmSync(outside, { recursive: true, force: true }));
  fs.symlinkSync(outside, path.join(root, 'linked'), process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => safeFile(root, 'linked/index.json'));
});

test('receipt rejects wrong worktree, source/tool drift and changed index', () => {
  const actual = { root: 'checkout', sources: { sha256: 'source' }, graphifyVersion: 'graphify 0.9.23', graphifyPython: 'python', artifacts: { graph: 'hash' } };
  const receipt = { ...actual, schema: 1, codegraphVersion: '1.6.1' };
  assert.doesNotThrow(() => validateReceipt(receipt, actual));
  for (const patch of [{ root: 'other' }, { sources: { sha256: 'changed' } }, { graphifyVersion: 'new' }, { graphifyPython: 'other-python' }, { artifacts: { graph: 'changed' } }]) assert.throws(() => validateReceipt(receipt, { ...actual, ...patch }));
  assert.throws(() => validateReceipt({ ...receipt, codegraphVersion: 'other' }, actual));
  assert.throws(() => validateReceipt(undefined, actual));
});

test('empty reader WAL/SHM cannot invalidate a snapshot, nonempty WAL must invalidate it', t => {
  const root = fixture(t);
  fs.mkdirSync(path.join(root, '.codegraph'));
  fs.mkdirSync(path.join(root, 'graphify-out'));
  for (const file of ['.codegraph/codegraph.db', 'graphify-out/graph.json', 'graphify-out/.graphify_root', 'graphify-out/.graphify_python']) fs.writeFileSync(path.join(root, file), 'fixture');
  const before = artifactHashes(root);
  fs.writeFileSync(path.join(root, '.codegraph/codegraph.db-wal'), '');
  fs.writeFileSync(path.join(root, '.codegraph/codegraph.db-shm'), 'reader bookkeeping');
  assert.deepEqual(artifactHashes(root), before);
  fs.writeFileSync(path.join(root, '.codegraph/codegraph.db-wal'), 'changed snapshot data');
  assert.notDeepEqual(artifactHashes(root), before);
});

test('Graphify accepts existing local source only, not empty/excluded/foreign graphs', t => {
  const root = fixture(t);
  assert.deepEqual(auditGraph(root, { nodes: [{ source_file: 'source.py' }], links: [] }), { nodes: 1, edges: 0, sourceFiles: 1, excludedPathAudit: 'PASS' });
  for (const graph of [{ nodes: [], links: [] }, { nodes: [{}], links: [] }, { nodes: [{ source_file: '../foreign.py' }], links: [] }, { nodes: [{ source_file: 'docs/private.py' }], links: [] }, { nodes: [{ source_file: 'missing.py' }], links: [] }]) assert.throws(() => auditGraph(root, graph));
});
