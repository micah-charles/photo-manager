import { normalizeTranscript } from './transcript_normalizer.js';

function asContexts(value) {
  const contexts = Array.isArray(value) ? value : [value];
  const result = contexts.map((context) => String(context ?? '').trim()).filter(Boolean);
  if (!result.length) throw new TypeError('A voice command needs at least one context');
  return [...new Set(result)];
}
function asPhrases(value) {
  const phrases = Array.isArray(value) ? value : [value];
  const result = phrases.map((phrase) => normalizeTranscript(phrase)).filter(Boolean);
  if (!result.length) throw new TypeError('A voice command needs at least one phrase');
  return [...new Set(result)];
}

function copyCommand(command) {
  return {
    ...command,
    contexts: [...command.contexts],
    phrases: [...command.phrases],
  };
}

export function createCommandRegistry() {
  const commands = new Map();
  const phraseIndex = new Map();

  function register(input) {
    if (!input || typeof input !== 'object') throw new TypeError('Voice command must be an object');
    const id = String(input.id ?? '').trim();
    if (!id) throw new TypeError('Voice command needs a unique id');
    if (commands.has(id)) throw new Error(`Voice command already registered: ${id}`);
    if (typeof input.execute !== 'function') throw new TypeError(`Voice command ${id} needs execute()`);

    const command = {
      id,
      contexts: asContexts(input.contexts ?? input.context),
      phrases: asPhrases(input.phrases ?? input.aliases),
      description: String(input.description ?? id),
      execute: input.execute,
      when: typeof input.when === 'function' ? input.when : null,
    };
    commands.set(id, command);
    for (const context of command.contexts) {
      for (const phrase of command.phrases) {
        const key = `${context}\u0000${phrase}`;
        const entries = phraseIndex.get(key) ?? [];
        entries.push(command);
        phraseIndex.set(key, entries);
      }
    }
    return copyCommand(command);
  }

  function unregister(id) {
    const command = commands.get(id);
    if (!command) return false;
    commands.delete(id);
    for (const context of command.contexts) {
      for (const phrase of command.phrases) {
        const key = `${context}\u0000${phrase}`;
        const entries = (phraseIndex.get(key) ?? []).filter((item) => item.id !== id);
        if (entries.length) phraseIndex.set(key, entries);
        else phraseIndex.delete(key);
      }
    }
    return true;
  }

  function registerMany(items) {
    return items.map(register);
  }

  function lookup(phrase, context) {
    const key = `${String(context ?? '').trim()}\u0000${normalizeTranscript(phrase)}`;
    return [...(phraseIndex.get(key) ?? [])].map(copyCommand);
  }

  function list(context, state) {
    return [...commands.values()]
      .filter((command) => command.contexts.includes(context))
      .filter((command) => !command.when || safelyAvailable(command, context, state))
      .map(copyCommand);
  }

  function get(id) {
    const command = commands.get(id);
    return command ? copyCommand(command) : null;
  }

  return { register, registerMany, unregister, lookup, list, get, size: () => commands.size };
}

function safelyAvailable(command, context, state) {
  try {
    return command.when({ context, state }) !== false;
  } catch {
    return false;
  }
}
