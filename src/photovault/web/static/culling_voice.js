import { createCommandRegistry } from './voice/command_registry.js';
import { createCullingVoiceAdapter } from './voice/culling_adapter.js';
import { SpeechRecognitionAdapter } from './voice/speech_recognition.js';
import { VoiceController } from './voice/voice_controller.js';

const adapter = window.PhotoManagerCullingVoicePrimitives && createCullingVoiceAdapter(window.PhotoManagerCullingVoicePrimitives);
const toggle = document.getElementById('voice-toggle');
const statusNode = document.getElementById('voice-status');
const helpNode = document.getElementById('voice-help-list');

if (adapter && toggle && statusNode && helpNode) {
  const registry = createCommandRegistry();
  const canUse = (commandId) => adapter.isAvailable(commandId);
  const register = (id, contexts, phrases, description, action) => registry.register({
    id, contexts, phrases, description, execute: action, when: () => canUse(id),
  });

  register('next', ['culling.viewer', 'culling.compare'], ['next', 'next photo', 'next picture'], 'next photo', () => adapter.actions.navigate(1));
  register('previous', ['culling.viewer', 'culling.compare'], ['previous', 'previous photo', 'back'], 'previous photo', () => adapter.actions.navigate(-1));
  register('pick', 'culling.viewer', ['pick', 'pick this', 'choose this'], 'pick this photo', () => adapter.actions.pick());
  register('reject', 'culling.viewer', ['reject', 'reject this'], 'reject this photo', () => adapter.actions.reject());
  register('prefer_left', 'culling.compare', ['left', 'pick left', 'choose left', 'keep left', 'keep best', 'current best'], 'keep the current best', () => adapter.actions.preferLeft());
  register('prefer_right', 'culling.compare', ['right', 'pick right', 'prefer right', 'keep right', 'challenger'], 'prefer the challenger', () => adapter.actions.preferRight());
  register('zoom_in', ['culling.viewer', 'culling.compare'], ['zoom in', 'closer'], 'zoom in', () => adapter.actions.zoomIn());
  register('zoom_out', ['culling.viewer', 'culling.compare'], ['zoom out'], 'zoom out', () => adapter.actions.zoomOut());
  register('fit', ['culling.viewer', 'culling.compare'], ['fit', 'fit image', 'reset zoom'], 'fit image', () => adapter.actions.fit());
  register('original', ['culling.viewer', 'culling.compare'], ['original', 'show original'], 'show original detail', () => adapter.actions.original());
  register('close', ['culling.viewer', 'culling.compare'], ['close', 'close viewer', 'exit'], 'close viewer', () => adapter.actions.close());

  const controller = new VoiceController({
    adapter: new SpeechRecognitionAdapter({ scope: window, defaultLanguage: 'en-GB' }),
    registry,
    contextProvider: () => adapter.getContext(),
    contextAllowed: (context) => context === 'culling.viewer' || context === 'culling.compare',
    language: 'en-GB',
    onChange: render,
  });

  function render(snapshot) {
    toggle.setAttribute('aria-pressed', String(snapshot.enabled));
    toggle.textContent = snapshot.enabled ? 'Turn Voice Mode off' : 'Enable Voice Mode';
    statusNode.dataset.state = snapshot.state;
    const heard = snapshot.transcript ? ` Heard: “${snapshot.transcript}”.` : '';
    const interim = snapshot.interimTranscript && !snapshot.transcript ? ` Heard: “${snapshot.interimTranscript}”…` : '';
    statusNode.textContent = `${snapshot.feedback}${heard || interim}`;
    helpNode.replaceChildren(...registry.list(snapshot.context, adapter.getState()).map((command) => {
      const item = document.createElement('span');
      item.textContent = `${command.phrases[0]} — ${command.description}`;
      return item;
    }));
  }

  toggle.addEventListener('click', () => {
    if (controller.enabled) controller.disable();
    else controller.enable();
  });
  window.addEventListener('photo-manager-culling-context', (event) => controller.setContext(event.detail?.context));
  window.addEventListener('pagehide', () => controller.disable('Voice is off.'));
  window.PhotoManagerVoice = { controller, registry };
  render(controller.snapshot());
} else {
  console.warn('Photo Manager voice UI could not initialize: culling adapter or toolbar is missing.');
}
