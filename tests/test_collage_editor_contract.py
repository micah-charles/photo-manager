from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
EDITOR_JS = ROOT / "src/photovault/web/static/fabric_spike_v3.js"
PROMPT = ROOT / "docs/CHATGPT_AI_COLLAGE_DESIGN_PROMPT.md"


class CollageEditorContractTests(unittest.TestCase):
    def test_collage_editor_uses_one_isolated_renderer_for_exports(self):
        source = EDITOR_JS.read_text(encoding="utf-8")
        self.assertIn("async function renderDocument(targetCanvas, doc, options = {})", source)
        self.assertIn("fabric.StaticCanvas || fabric.Canvas", source)
        self.assertIn("Promise.all([", source)
        self.assertIn("loadDesignAsset(element)", source)
        self.assertIn("strictAssets: true", source)
        self.assertIn("state.activeId = activeBeforeClear;", source)
        self.assertIn("state.savedDocumentUrl = documentUrl;", source)
        self.assertIn("function exifRotation(orientation)", source)
        self.assertIn("sourceRotation: sourceRotation(element, context, usedOriginal)", source)
        self.assertIn("const imageRotation = Number(loadedResult.sourceRotation || 0) + transform.rotation;", source)

        export_section = source[source.index("async function exportRenderedPng"):source.index("async function saveVariant")]
        self.assertNotIn("state.canvas.setDimensions", export_section)
        self.assertNotIn("state.canvas.setZoom", export_section)
        self.assertNotIn("state.canvas.viewportTransform", export_section)


    def test_standard_ai_prompt_contains_professional_art_direction_contract(self):
        source = PROMPT.read_text(encoding="utf-8")
        for phrase in (
            "professional photo-book art",
            "three passes",
            "one dominant hero",
            "hidden grid discipline",
            "no more than three intentional overlaps",
            "maximum of four decorative assets",
            "thumbnail size",
            "print size",
        ):
            self.assertIn(phrase, source)
