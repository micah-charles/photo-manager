import assert from 'node:assert/strict';

import { createCommandRegistry } from '../src/photovault/web/static/voice/command_registry.js';
import { matchVoiceCommand } from '../src/photovault/web/static/voice/command_matcher.js';
import { createCullingVoiceAdapter } from '../src/photovault/web/static/voice/culling_adapter.js';
import { normalizeTranscript } from '../src/photovault/web/static/voice/transcript_normalizer.js';
import { SpeechRecognitionAdapter } from '../src/photovault/web/static/voice/speech_recognition.js';
import { VoiceController, VOICE_STATES } from '../src/photovault/web/static/voice/voice_controller.js';

assert.equal(normalizeTranscript('  Next,   PHOTO!  '), 'next photo');
assert.equal(normalizeTranscript('“Keep—best”'), 'keep best');
assert.equal(normalizeTranscript('選擇照片'), '選擇照片');

const registry = createCommandRegistry();
let executed = 0;
registry.register({
  id: 'next',
  context: 'culling.viewer',
  phrases: ['next', 'next photo'],
  description: 'next photo',
  execute: () => { executed += 1; },
});
registry.register({
  id: 'unavailable',
  context: 'culling.viewer',
  phrases: ['blocked'],
  description: 'blocked action',
  when: () => false,
  execute: () => { executed += 100; },
});
registry.register({
  id: 'ambiguous-a',
  context: 'culling.compare',
  phrases: ['choose'],
  execute: () => {},
});
registry.register({
  id: 'ambiguous-b',
  context: 'culling.compare',
  phrases: ['choose'],
  execute: () => {},
});

assert.equal(matchVoiceCommand(registry, 'NEXT PHOTO', { context: 'culling.viewer', confidence: 0.9 }).status, 'matched');
assert.equal(matchVoiceCommand(registry, 'next', { context: 'culling.grid', confidence: 0.9 }).status, 'unknown');
assert.equal(matchVoiceCommand(registry, 'blocked', { context: 'culling.viewer', confidence: 0.9 }).status, 'unavailable');
assert.equal(matchVoiceCommand(registry, 'choose', { context: 'culling.compare', confidence: 0.9 }).status, 'ambiguous');
assert.equal(matchVoiceCommand(registry, 'next', { context: 'culling.viewer', confidence: 0.4 }).status, 'low-confidence');
assert.equal(matchVoiceCommand(registry, 'next', { context: 'culling.viewer', confidence: null }).status, 'matched');

const winnerCalls = [];
const cullingAdapter = createCullingVoiceAdapter({
  getContext: () => 'culling.compare',
  getState: () => ({ hasActivePhoto: true, compare: true }),
  getActivePhoto: () => ({ asset_id: 'photo-1' }),
  isAvailable: () => true,
  decide: (photo, action) => `decide:${photo.asset_id}:${action}`,
  navigate: (delta) => `navigate:${delta}`,
  winner: (side) => { winnerCalls.push(side); return `winner:${side}`; },
  zoom: (delta) => `zoom:${delta}`,
  fit: () => 'fit',
  original: () => 'original',
  close: () => 'close',
});
assert.equal(cullingAdapter.actions.preferLeft(), 'winner:0');
assert.equal(cullingAdapter.actions.preferRight(), 'winner:1');
assert.deepEqual(winnerCalls, [0, 1], 'compare voice actions must select the semantic winner side');
assert.equal(cullingAdapter.actions.pick(), 'decide:photo-1:pick');
assert.equal(cullingAdapter.actions.navigate(1), 'navigate:1');

const recognitionInstances = [];
class MockSpeechRecognition {
  constructor() {
    this.lang = '';
    this.continuous = true;
    this.interimResults = false;
    this.maxAlternatives = 1;
    this.onresult = null;
    this.onerror = null;
    this.onend = null;
    this.started = 0;
    this.stopped = 0;
    this.aborted = 0;
    recognitionInstances.push(this);
  }

  start() { this.started += 1; }
  stop() { this.stopped += 1; }
  abort() { this.aborted += 1; }
}

function resultEvent(transcript, confidence = 0.9, isFinal = true) {
  const result = [{ transcript, confidence }];
  result.isFinal = isFinal;
  return { resultIndex: 0, results: [result] };
}

const speech = new SpeechRecognitionAdapter({ RecognitionCtor: MockSpeechRecognition, defaultLanguage: 'en-GB' });
let finalPayload = null;
const firstAttempt = speech.start({
  language: 'en-GB',
  interimResults: true,
  onFinal: (payload) => { finalPayload = payload; },
});
const firstRecognizer = recognitionInstances[0];
assert.equal(firstRecognizer.lang, 'en-GB');
assert.equal(firstRecognizer.continuous, false);
assert.equal(firstRecognizer.interimResults, true);
firstRecognizer.onresult(resultEvent('next photo', 0.91));
assert.equal(finalPayload.attemptId, firstAttempt);
assert.equal(finalPayload.finalTranscript, 'next photo');
assert.equal(finalPayload.confidence, 0.91);
firstRecognizer.onend({});
assert.equal(speech.getStatus().running, false);

let staleCalled = false;
const staleHandler = firstRecognizer.onresult;
speech.start({ onFinal: () => { staleCalled = true; } });
staleHandler(resultEvent('late result'));
assert.equal(staleCalled, false);
speech.stop();
assert.equal(recognitionInstances[0].stopped, 1);
speech.abort({ silent: true });
assert.equal(speech.getStatus().running, false);

class FakeAdapter {
  constructor() {
    this.supported = true;
    this.starts = 0;
    this.aborts = 0;
    this.current = null;
  }

  isSupported() { return this.supported; }
  getStatus() { return { supported: this.supported, running: Boolean(this.current) }; }
  start(callbacks) {
    const attemptId = `fake-${++this.starts}`;
    this.current = { attemptId, ...callbacks };
    return attemptId;
  }
  abort() {
    if (this.current) this.aborts += 1;
    this.current = null;
  }
  final(transcript, confidence = 0.9) {
    if (!this.current) return;
    this.current.onFinal({ attemptId: this.current.attemptId, transcript, finalTranscript: transcript, confidence, isFinal: true });
  }
  end(code = null) {
    const current = this.current;
    if (!current) return;
    this.current = null;
    current.onEnd({ attemptId: current.attemptId, code, stopRequested: false });
  }
  error(code) {
    if (this.current) this.current.onError({ attemptId: this.current.attemptId, code });
  }
}

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
const commandRegistry = createCommandRegistry();
let actions = 0;
let actionStarted = null;
let releaseAction;
const actionPromise = new Promise((resolve) => { releaseAction = resolve; });
commandRegistry.register({
  id: 'next',
  context: 'culling.viewer',
  phrases: ['next'],
  description: 'next photo',
  execute: async () => {
    actions += 1;
    actionStarted = true;
    await actionPromise;
  },
});

const fake = new FakeAdapter();
const controller = new VoiceController({
  adapter: fake,
  registry: commandRegistry,
  contextProvider: () => 'culling.viewer',
  restartBaseMs: 1,
  restartMaxMs: 4,
});
assert.equal(controller.enable().state, VOICE_STATES.LISTENING);
assert.equal(fake.starts, 1);

fake.final('next');
fake.final('next');
assert.equal(actions, 1, 'a duplicated final result must execute once');
fake.end();
assert.equal(actionStarted, true);
let restartedWhileSaving = false;
await wait(5);
restartedWhileSaving = fake.starts > 1;
assert.equal(restartedWhileSaving, false, 'recognition must wait for async action completion');
releaseAction();
await wait(5);
assert.equal(fake.starts, 2, 'recognition should restart after the action and natural end');

const staleAttempt = fake.current;
controller.disable();
staleAttempt?.onFinal({ attemptId: staleAttempt.attemptId, transcript: 'next', finalTranscript: 'next', confidence: 0.9, isFinal: true });
await wait(5);
assert.equal(fake.starts, 2, 'Voice Off must prevent restart and stale execution');

controller.enable();
assert.equal(fake.starts, 3);
fake.error('not-allowed');
await wait(5);
assert.equal(controller.state, VOICE_STATES.ERROR);
assert.equal(controller.enabled, false);
assert.equal(fake.starts, 3, 'permission denial must not restart recognition');

const unsupported = new FakeAdapter();
unsupported.supported = false;
const unsupportedController = new VoiceController({
  adapter: unsupported,
  registry: commandRegistry,
  contextProvider: () => 'culling.viewer',
});
assert.equal(unsupportedController.enable().state, VOICE_STATES.UNSUPPORTED);

console.log('Voice core tests passed');
