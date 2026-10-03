'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { childEnv, structuralOracle } = require('./tool_efficiency_navigation_benchmark.cjs');

const task = {
  oraclePaths: ['apps/web/src/components/layout/Sidebar.tsx'],
  oracleNeedles: ['getNavigationRoutes'],
};

test('oracle rejects unrelated symbol and path mentions', () => {
  assert.deepEqual(structuralOracle(
    'apps/web/src/components/layout/Other.tsx:10: getNavigationRoutes\napps/web/src/components/layout/Sidebar.tsx:20: unrelated',
    task,
  ), { matched: 0, required: 1 });
});

test('oracle accepts same-line/co-located symbol and path evidence', () => {
  assert.deepEqual(structuralOracle(
    'apps/web/src/components/layout/Sidebar.tsx:20: getNavigationRoutes',
    task,
  ), { matched: 1, required: 1 });
});

test('child environment excludes provider and arbitrary process secrets', () => {
  const keys = ['SUPERADMIN_PASSWORD', 'NEXT_PUBLIC_API_URL', 'API_KEY'];
  const previous = keys.map((key) => process.env[key]);
  try {
    keys.forEach((key) => { process.env[key] = 'synthetic-sentinel'; });
    const env = childEnv();
    assert.equal(env.CODEGRAPH_TELEMETRY, '0');
    assert.equal(env.DO_NOT_TRACK, '1');
    keys.forEach((key) => assert.equal(Object.hasOwn(env, key), false));
  } finally {
    keys.forEach((key, index) => {
      if (previous[index] === undefined) delete process.env[key];
      else process.env[key] = previous[index];
    });
  }
});

test('oracle does not combine unrelated JSON siblings or parent subtrees', () => {
  assert.deepEqual(structuralOracle(JSON.stringify({ items: [
    { name: 'getNavigationRoutes', file: 'apps/web/src/lib/routeRegistry.ts' },
    { name: 'unrelated', file: 'apps/web/src/components/layout/Sidebar.tsx' },
  ] }), task), { matched: 0, required: 1 });
  assert.deepEqual(structuralOracle(JSON.stringify({ items: [
    { name: 'getNavigationRoutes', file: 'apps/web/src/components/layout/Sidebar.tsx' },
  ] }), task), { matched: 1, required: 1 });
});
