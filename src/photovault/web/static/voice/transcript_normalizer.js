/* Small, deterministic transcript normalizer shared by the voice matcher and UI. */

export function normalizeTranscript(value) {
  return String(value ?? '')
    .normalize('NFKC')
    .toLocaleLowerCase('en-GB')
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim()
    .replace(/\s+/g, ' ');
}
