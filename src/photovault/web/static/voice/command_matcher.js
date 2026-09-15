import { normalizeTranscript } from './transcript_normalizer.js';

export function matchVoiceCommand(registry, transcript, {
  context,
  state,
  confidence,
  minimumConfidence = 0.60,
} = {}) {
  const normalized = normalizeTranscript(transcript);
  if (!normalized) return { status: 'unknown', normalized, reason: 'empty transcript' };

  const candidates = registry.lookup(normalized, context);
  if (!candidates.length) return { status: 'unknown', normalized, reason: 'no registered phrase' };

  const available = candidates.filter((command) => {
    if (!command.when) return true;
    try {
      return command.when({ context, state }) !== false;
    } catch {
      return false;
    }
  });
  if (!available.length) {
    return {
      status: 'unavailable',
      normalized,
      commandIds: candidates.map((command) => command.id),
      reason: 'command is unavailable in the current state',
    };
  }

  const numericConfidence = Number(confidence);
  if (Number.isFinite(numericConfidence) && numericConfidence > 0 && numericConfidence < minimumConfidence) {
    return {
      status: 'low-confidence',
      normalized,
      confidence: numericConfidence,
      commandIds: available.map((command) => command.id),
      reason: `confidence ${numericConfidence.toFixed(2)} is below ${minimumConfidence.toFixed(2)}`,
    };
  }

  if (available.length > 1) {
    return {
      status: 'ambiguous',
      normalized,
      commandIds: available.map((command) => command.id),
      reason: 'more than one available command matches this phrase',
    };
  }

  return {
    status: 'matched',
    normalized,
    confidence: Number.isFinite(numericConfidence) ? numericConfidence : null,
    command: available[0],
    commandId: available[0].id,
  };
}
