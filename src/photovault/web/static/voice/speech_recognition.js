/* Browser speech adapter. It is deliberately one-utterance-at-a-time; the controller owns looping. */

export const SPEECH_ERROR_CODES = Object.freeze({
  NOT_ALLOWED: 'not-allowed',
  AUDIO_CAPTURE: 'audio-capture',
  NO_SPEECH: 'no-speech',
  NETWORK: 'network',
  ABORTED: 'aborted',
  UNKNOWN: 'unknown',
});

export function mapRecognitionError(error) {
  const code = String(error?.error ?? error?.message ?? error ?? '').toLowerCase();
  if (code === 'not-allowed' || code === 'service-not-allowed') return SPEECH_ERROR_CODES.NOT_ALLOWED;
  if (code === 'audio-capture') return SPEECH_ERROR_CODES.AUDIO_CAPTURE;
  if (code === 'no-speech') return SPEECH_ERROR_CODES.NO_SPEECH;
  if (code === 'network') return SPEECH_ERROR_CODES.NETWORK;
  if (code === 'aborted') return SPEECH_ERROR_CODES.ABORTED;
  return SPEECH_ERROR_CODES.UNKNOWN;
}

export function recognitionConstructor(scope = globalThis) {
  return scope?.SpeechRecognition || scope?.webkitSpeechRecognition || null;
}

export function isSpeechRecognitionSupported(scope = globalThis) {
  return typeof recognitionConstructor(scope) === 'function';
}

function resultPayload(attemptId, event, finalTranscript, interimTranscript, confidence, alternatives, isFinal) {
  return {
    attemptId,
    transcript: (finalTranscript || interimTranscript || '').trim(),
    finalTranscript: finalTranscript.trim(),
    interimTranscript: interimTranscript.trim(),
    confidence: Number.isFinite(confidence) ? confidence : null,
    alternatives,
    language: event?.target?.lang || null,
    isFinal,
    rawEvent: event,
  };
}

function readResults(event) {
  const results = event?.results || [];
  const start = Number.isInteger(event?.resultIndex) ? event.resultIndex : 0;
  let finalTranscript = '';
  let interimTranscript = '';
  let confidence = null;
  const alternatives = [];
  for (let index = start; index < results.length; index += 1) {
    const result = results[index];
    const top = result?.[0];
    if (!top) continue;
    const transcript = String(top.transcript ?? '').trim();
    if (result.isFinal) finalTranscript += `${finalTranscript ? ' ' : ''}${transcript}`;
    else interimTranscript += `${interimTranscript ? ' ' : ''}${transcript}`;
    if (confidence === null && Number.isFinite(Number(top.confidence))) confidence = Number(top.confidence);
    if (index === start) {
      for (let alternativeIndex = 0; alternativeIndex < result.length; alternativeIndex += 1) {
        const alternative = result[alternativeIndex];
        alternatives.push({
          transcript: String(alternative?.transcript ?? '').trim(),
          confidence: Number.isFinite(Number(alternative?.confidence)) ? Number(alternative.confidence) : null,
        });
      }
    }
  }
  return { finalTranscript, interimTranscript, confidence, alternatives };
}

export class SpeechRecognitionAdapter {
  constructor({ scope = globalThis, RecognitionCtor = null, defaultLanguage = 'en-GB' } = {}) {
    this.scope = scope;
    this.RecognitionCtor = RecognitionCtor || recognitionConstructor(scope);
    this.defaultLanguage = defaultLanguage;
    this.recognizer = null;
    this.active = null;
    this.running = false;
    this.sequence = 0;
  }

  isSupported() {
    return typeof this.RecognitionCtor === 'function';
  }

  getStatus() {
    return { supported: this.isSupported(), running: this.running, attemptId: this.active?.attemptId ?? null };
  }

  getRecognizer() {
    if (!this.isSupported()) return null;
    if (!this.recognizer) this.recognizer = new this.RecognitionCtor();
    return this.recognizer;
  }

  start({
    language = this.defaultLanguage,
    interimResults = true,
    maxAlternatives = 5,
    onInterim = () => {},
    onFinal = () => {},
    onError = () => {},
    onEnd = () => {},
  } = {}) {
    if (!this.isSupported()) return null;
    this.abort({ silent: true });
    const recognizer = this.getRecognizer();
    const attemptId = `voice-attempt-${++this.sequence}`;
    const active = {
      attemptId,
      recognizer,
      onInterim,
      onFinal,
      onError,
      onEnd,
      finalEmitted: false,
      stopRequested: false,
      error: null,
    };
    this.active = active;
    this.running = true;

    recognizer.lang = String(language || this.defaultLanguage);
    recognizer.continuous = false;
    recognizer.interimResults = Boolean(interimResults);
    recognizer.maxAlternatives = Math.max(1, Math.min(10, Number(maxAlternatives) || 1));
    recognizer.onresult = (event) => {
      if (this.active !== active) return;
      const parsed = readResults(event);
      if (parsed.interimTranscript) {
        active.onInterim(resultPayload(attemptId, event, '', parsed.interimTranscript, parsed.confidence, parsed.alternatives, false));
      }
      if (parsed.finalTranscript && !active.finalEmitted) {
        active.finalEmitted = true;
        active.onFinal(resultPayload(attemptId, event, parsed.finalTranscript, '', parsed.confidence, parsed.alternatives, true));
      }
    };
    recognizer.onerror = (event) => {
      if (this.active !== active) return;
      active.error = mapRecognitionError(event);
      active.onError({ attemptId, code: active.error, rawEvent: event });
    };
    recognizer.onend = (event) => {
      if (this.active !== active) return;
      this.active = null;
      this.running = false;
      active.onEnd({
        attemptId,
        code: active.error,
        stopRequested: active.stopRequested,
        rawEvent: event,
      });
    };
    try {
      recognizer.start();
    } catch (error) {
      if (this.active === active) {
        this.active = null;
        this.running = false;
        active.error = mapRecognitionError(error);
        active.onError({ attemptId, code: active.error, rawEvent: error });
        active.onEnd({ attemptId, code: active.error, stopRequested: false, rawEvent: error });
      }
      return null;
    }
    return attemptId;
  }

  stop() {
    const active = this.active;
    if (!active) return false;
    active.stopRequested = true;
    try { active.recognizer.stop(); } catch { /* Browser may already have ended. */ }
    return true;
  }

  abort({ silent = false } = {}) {
    const active = this.active;
    if (!active) return false;
    this.active = null;
    this.running = false;
    active.stopRequested = true;
    try { active.recognizer.abort(); } catch { /* Browser may already have ended. */ }
    if (!silent) active.onEnd({ attemptId: active.attemptId, code: SPEECH_ERROR_CODES.ABORTED, stopRequested: true });
    return true;
  }
}
