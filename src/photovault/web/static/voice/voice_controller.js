import { matchVoiceCommand } from './command_matcher.js';
import { SPEECH_ERROR_CODES } from './speech_recognition.js';

export const VOICE_STATES = Object.freeze({
  OFF: 'OFF',
  STARTING: 'STARTING',
  LISTENING: 'LISTENING',
  PROCESSING: 'PROCESSING',
  RESTARTING: 'RESTARTING',
  ERROR: 'ERROR',
  UNSUPPORTED: 'UNSUPPORTED',
});

const FATAL_ERRORS = new Set([
  SPEECH_ERROR_CODES.NOT_ALLOWED,
  SPEECH_ERROR_CODES.AUDIO_CAPTURE,
]);

export class VoiceController {
  constructor({
    adapter,
    registry,
    contextProvider = () => null,
    contextAllowed = (context) => Boolean(context),
    language = 'en-GB',
    minimumConfidence = 0.60,
    restartBaseMs = 150,
    restartMaxMs = 1200,
    duplicateWindowMs = 750,
    now = () => Date.now(),
    setTimer = (callback, delay) => setTimeout(callback, delay),
    clearTimer = (timer) => clearTimeout(timer),
    onChange = () => {},
  } = {}) {
    if (!adapter || !registry) throw new TypeError('VoiceController needs an adapter and registry');
    this.adapter = adapter;
    this.registry = registry;
    this.contextProvider = contextProvider;
    this.contextAllowed = contextAllowed;
    this.language = language;
    this.minimumConfidence = minimumConfidence;
    this.restartBaseMs = restartBaseMs;
    this.restartMaxMs = restartMaxMs;
    this.duplicateWindowMs = duplicateWindowMs;
    this.now = now;
    this.setTimer = setTimer;
    this.clearTimer = clearTimer;
    this.onChange = onChange;
    this.state = VOICE_STATES.OFF;
    this.enabled = false;
    this.context = this.contextProvider();
    this.generation = 0;
    this.activeAttemptId = null;
    this.finalAttempts = new Set();
    this.lastFingerprint = null;
    this.retryCount = 0;
    this.restartTimer = null;
    this.pendingEnd = false;
    this.processing = false;
    this.lastTranscript = '';
    this.interimTranscript = '';
    this.feedback = 'Voice is off.';
    this.lastError = null;
  }

  snapshot() {
    return {
      state: this.state,
      enabled: this.enabled,
      context: this.context,
      attemptId: this.activeAttemptId,
      transcript: this.lastTranscript,
      interimTranscript: this.interimTranscript,
      feedback: this.feedback,
      error: this.lastError,
    };
  }

  emit(patch = {}) {
    Object.assign(this, patch);
    this.onChange(this.snapshot());
  }

  setState(state, feedback = this.feedback, error = this.lastError) {
    this.emit({ state, feedback, lastError: error });
  }

  setContext(context) {
    const nextContext = context ?? this.contextProvider();
    const changed = nextContext !== this.context;
    this.context = nextContext;
    if (!this.enabled) {
      this.emit({ context: nextContext });
      return;
    }
    if (!this.contextAllowed(nextContext)) {
      this.disable('Voice stopped outside a supported viewer context.');
      return;
    }
    if (changed) {
      this.generation += 1;
      this.clearRestartTimer();
      this.adapter.abort({ silent: true });
      this.activeAttemptId = null;
      this.startRecognition(this.generation);
    }
  }

  enable() {
    if (this.enabled) return this.snapshot();
    this.context = this.contextProvider();
    if (!this.contextAllowed(this.context)) {
      this.setState(VOICE_STATES.ERROR, 'Open a photo viewer before enabling Voice Mode.', 'context-unavailable');
      return this.snapshot();
    }
    if (!this.adapter.isSupported()) {
      this.enabled = false;
      this.setState(VOICE_STATES.UNSUPPORTED, 'Voice recognition is not supported by this browser.', 'unsupported');
      return this.snapshot();
    }
    this.enabled = true;
    this.generation += 1;
    this.retryCount = 0;
    this.pendingEnd = false;
    this.processing = false;
    this.finalAttempts.clear();
    this.lastError = null;
    this.setState(VOICE_STATES.STARTING, 'Starting microphone…', null);
    this.startRecognition(this.generation);
    return this.snapshot();
  }

  disable(feedback = 'Voice is off.') {
    this.enabled = false;
    this.generation += 1;
    this.clearRestartTimer();
    this.adapter.abort({ silent: true });
    this.activeAttemptId = null;
    this.pendingEnd = false;
    this.processing = false;
    this.setState(VOICE_STATES.OFF, feedback, null);
    return this.snapshot();
  }

  clearRestartTimer() {
    if (this.restartTimer !== null) this.clearTimer(this.restartTimer);
    this.restartTimer = null;
  }

  startRecognition(generation) {
    if (!this.enabled || generation !== this.generation) return;
    this.context = this.contextProvider() ?? this.context;
    if (!this.contextAllowed(this.context)) {
      this.disable('Voice stopped because the viewer is no longer active.');
      return;
    }
    this.pendingEnd = false;
    this.processing = false;
    this.finalAttempts.clear();
    this.setState(VOICE_STATES.STARTING, 'Listening for a command…', null);
    const attemptId = this.adapter.start({
      language: this.language,
      interimResults: true,
      maxAlternatives: 5,
      onInterim: (payload) => this.handleInterim(generation, payload),
      onFinal: (payload) => this.handleFinal(generation, payload),
      onError: (payload) => this.handleError(generation, payload),
      onEnd: (payload) => this.handleEnd(generation, payload),
    });
    if (generation !== this.generation || !this.enabled) return;
    if (!attemptId) {
      this.enabled = false;
      const unsupported = !this.adapter.isSupported();
      this.setState(unsupported ? VOICE_STATES.UNSUPPORTED : VOICE_STATES.ERROR, unsupported ? 'Voice recognition is not supported by this browser.' : 'Could not start voice recognition.', unsupported ? 'unsupported' : 'start-failed');
      return;
    }
    this.activeAttemptId = attemptId;
    this.setState(VOICE_STATES.LISTENING, 'Listening…', null);
  }

  handleInterim(generation, payload) {
    if (!this.enabled || generation !== this.generation || payload.attemptId !== this.activeAttemptId) return;
    this.emit({ interimTranscript: payload.interimTranscript || payload.transcript });
  }

  async handleFinal(generation, payload) {
    if (!this.enabled || generation !== this.generation || payload.attemptId !== this.activeAttemptId) return;
    if (this.finalAttempts.has(payload.attemptId)) return;
    this.finalAttempts.add(payload.attemptId);
    this.processing = true;
    this.lastTranscript = payload.finalTranscript || payload.transcript;
    this.interimTranscript = '';
    this.setState(VOICE_STATES.PROCESSING, 'Processing command…', null);

    const context = this.contextProvider() ?? this.context;
    this.context = context;
    const match = matchVoiceCommand(this.registry, this.lastTranscript, {
      context,
      confidence: payload.confidence,
      minimumConfidence: this.minimumConfidence,
    });
    if (match.status !== 'matched') {
      this.finishProcessing(generation, `Not executed: ${match.reason}.`, null);
      return;
    }

    const fingerprint = `${context}\u0000${match.commandId}\u0000${match.normalized}`;
    const currentTime = this.now();
    if (this.lastFingerprint && this.lastFingerprint.value === fingerprint && currentTime - this.lastFingerprint.time < this.duplicateWindowMs) {
      this.finishProcessing(generation, `Ignored duplicate: “${this.lastTranscript}”.`, null);
      return;
    }
    this.lastFingerprint = { value: fingerprint, time: currentTime };
    try {
      await match.command.execute({ command: match.command, context, payload, transcript: this.lastTranscript });
      if (generation === this.generation && this.enabled) this.retryCount = 0;
      this.finishProcessing(generation, `Executed: ${match.command.description}.`, null);
    } catch (error) {
      this.finishProcessing(generation, `Command failed: ${error?.message || 'unknown error'}.`, 'command-failed');
    }
  }

  finishProcessing(generation, feedback, error) {
    if (generation !== this.generation || !this.enabled) return;
    this.processing = false;
    this.setState(VOICE_STATES.PROCESSING, feedback, error);
    if (this.pendingEnd || !this.adapter.getStatus?.().running) this.scheduleRestart(generation);
  }

  handleError(generation, payload) {
    if (!this.enabled || generation !== this.generation || (this.activeAttemptId && payload.attemptId !== this.activeAttemptId)) return;
    const code = payload.code || 'unknown';
    if (FATAL_ERRORS.has(code)) {
      this.enabled = false;
      this.generation += 1;
      this.adapter.abort({ silent: true });
      this.activeAttemptId = null;
      const message = code === SPEECH_ERROR_CODES.NOT_ALLOWED
        ? 'Microphone permission was denied. Voice Mode is off.'
        : 'No microphone was available. Voice Mode is off.';
      this.setState(VOICE_STATES.ERROR, message, code);
      return;
    }
    this.setState(VOICE_STATES.RESTARTING, `Recognition ${code}; retrying…`, code);
    this.scheduleRestart(generation);
  }

  handleEnd(generation, payload) {
    if (generation !== this.generation) return;
    this.activeAttemptId = null;
    this.pendingEnd = true;
    if (!this.enabled) return;
    if (payload.code && FATAL_ERRORS.has(payload.code)) return;
    if (!this.processing) this.scheduleRestart(generation);
  }

  scheduleRestart(generation) {
    if (!this.enabled || generation !== this.generation || this.restartTimer !== null) return;
    const delay = Math.min(this.restartMaxMs, this.restartBaseMs * (2 ** Math.min(this.retryCount, 4)));
    this.retryCount += 1;
    this.setState(VOICE_STATES.RESTARTING, `Listening will resume in ${delay} ms…`, this.lastError);
    this.restartTimer = this.setTimer(() => {
      this.restartTimer = null;
      if (this.enabled && generation === this.generation) this.startRecognition(generation);
    }, delay);
  }
}
