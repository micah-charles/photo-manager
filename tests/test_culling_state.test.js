const test = require('node:test');
const assert = require('node:assert/strict');
const state = require('../src/photovault/web/static/culling-state.js');

test('navigation clamps at the page edges', () => {
  assert.equal(state.nextIndex(0, -1, 8), 0);
  assert.equal(state.nextIndex(7, 1, 8), 7);
  assert.equal(state.nextIndex(3, -1, 8), 2);
});

test('pick and reject are explicit toggles, never view actions', () => {
  assert.equal(state.decisionFor(undefined, 'pick'), 'pick');
  assert.equal(state.decisionFor('pick', 'pick'), 'clear');
  assert.equal(state.decisionFor('reject', 'pick'), 'pick');
  assert.equal(state.decisionFor(undefined, 'reject'), 'reject');
});

test('nearby same-source captures form an honest comparison group', () => {
  const photos = Array.from({length: 8}, (_, index) => ({
    source_id: 'pixel-a',
    captured: `2026-08-23T15:45:${String(index * 2).padStart(2, '0')}`,
  }));
  const groups = state.groups(photos);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].length, 8);
  assert.equal(state.groups([
    {source_id: 'pixel-a', captured: '2026-08-23T15:45:00'},
    {source_id: 'pixel-b', captured: '2026-08-23T15:45:02'},
  ]).length, 0);
});
