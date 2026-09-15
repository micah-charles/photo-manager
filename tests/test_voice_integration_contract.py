import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "photovault" / "web" / "static"


class VoiceIntegrationContractTests(unittest.TestCase):
    def test_viewer_loads_voice_controls_and_module_after_culling(self):
        html = (STATIC / "topic_workspace.html").read_text()

        self.assertIn('id="voice-toggle"', html)
        self.assertIn('id="voice-status"', html)
        self.assertIn('id="voice-help"', html)
        culling_pos = html.index('/culling.js?')
        voice_pos = html.index('culling_voice.js?')
        self.assertLess(culling_pos, voice_pos)

    def test_voice_module_uses_semantic_adapter_without_click_bridge(self):
        voice = (STATIC / "culling_voice.js").read_text()
        culling = (STATIC / "culling.js").read_text()

        self.assertIn("new VoiceController", voice)
        self.assertIn("SpeechRecognitionAdapter", voice)
        self.assertNotIn(".click(", voice)
        self.assertIn("PhotoManagerCullingVoicePrimitives", culling)
        adapter = (STATIC / "voice" / "culling_adapter.js").read_text()
        self.assertIn("winner(0)", adapter)
        self.assertIn("winner(1)", adapter)


if __name__ == "__main__":
    unittest.main()
