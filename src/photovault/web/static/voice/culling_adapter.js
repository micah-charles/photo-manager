/* Pure semantic bridge between the culling page and the voice command layer. */

export function createCullingVoiceAdapter(primitives) {
  if (!primitives || typeof primitives !== 'object') {
    throw new TypeError('Culling voice adapter needs semantic primitives');
  }
  const available = (commandId) => {
    try {
      return Boolean(primitives.isAvailable(commandId));
    } catch {
      return false;
    }
  };
  const activeDecision = (decision) => {
    if (!available(decision)) return false;
    const photo = primitives.getActivePhoto();
    return photo ? primitives.decide(photo, decision) : false;
  };

  return {
    getContext: () => primitives.getContext(),
    getState: () => primitives.getState(),
    isAvailable: available,
    actions: {
      navigate: (delta) => {
        const commandId = delta > 0 ? 'next' : 'previous';
        return available(commandId) ? primitives.navigate(delta) : false;
      },
      pick: () => activeDecision('pick'),
      reject: () => activeDecision('reject'),
      preferLeft: () => available('prefer_left') ? primitives.winner(0) : false,
      preferRight: () => available('prefer_right') ? primitives.winner(1) : false,
      zoomIn: () => available('zoom_in') ? primitives.zoom(0.25) : false,
      zoomOut: () => available('zoom_out') ? primitives.zoom(-0.25) : false,
      fit: () => available('fit') ? primitives.fit() : false,
      original: () => available('original') ? primitives.original() : false,
      close: () => available('close') ? primitives.close() : false,
    },
  };
}
