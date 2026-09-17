from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
EDITOR_JS = ROOT / "src/photovault/web/static/fabric_spike_v3.js"
RENDER_VALIDATION_JS = ROOT / "src/photovault/web/static/collage_render_validation.js"
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

    def test_shared_render_space_validation_is_called_after_fabric_render(self):
        source = EDITOR_JS.read_text(encoding="utf-8")
        helper = RENDER_VALIDATION_JS.read_text(encoding="utf-8")
        self.assertIn("targetCanvas.renderAll();", source)
        self.assertIn("validateRenderedComposition", source)
        self.assertIn("renderedObjectsByElement(targetCanvas)", source)
        self.assertIn('object.setCoords?.();', source)
        for code in (
            "FABRIC_TEXT_DECLARED_BOX_OVERFLOW",
            "FABRIC_TEXT_PHOTO_COLLISION",
            "FABRIC_TEXT_COVERED_BY_PHOTO",
            "FABRIC_TEXT_PHOTO_CLEARANCE",
            "FABRIC_TEXT_TEXT_COLLISION",
        ):
            self.assertIn(code, helper)

    def test_intentional_overlap_contract_is_explicit_and_backwards_compatible(self):
        source = RENDER_VALIDATION_JS.read_text(encoding="utf-8")
        schema = (ROOT / "src/photovault/collage/schemas/design-spec-v2.json").read_text(encoding="utf-8")
        self.assertIn("allow_photo_overlap", source)
        self.assertIn("allow_text_overlap", source)
        self.assertIn("allow_photo_overlap", schema)
        self.assertIn("allow_text_overlap", schema)

    def test_layered_template_uses_shared_fabric_renderer_and_debug_controls(self):
        source = EDITOR_JS.read_text(encoding="utf-8")
        html = (ROOT / "src/photovault/web/static/fabric_spike_v2.html").read_text(encoding="utf-8")
        for phrase in (
            "loadTemplateMask(element, context)",
            "absolutePositioned: true",
            "template_mask_url",
            "addLayeredDebugOverlay",
            "excludeFromExport = true",
            "layeredDebug: state.layeredDebug",
        ):
            self.assertIn(phrase, source)
        for phrase in ("show-template-guides", "show-template-masks", "hide-template-foreground"):
            self.assertIn(phrase, html)
        self.assertIn("layered-template", (ROOT / "docs/ai-layered-collage-template.md").read_text(encoding="utf-8"))

    def test_photo_panel_exposes_package_photos_not_used_by_current_alternative(self):
        source = EDITOR_JS.read_text(encoding="utf-8")
        html = (ROOT / "src/photovault/web/static/fabric_spike_v2.html").read_text(encoding="utf-8")
        for phrase in (
            "function selectedPhotoIds()",
            "selection_asset_ids",
            "function updatePhotoUsageIndicators()",
            "Selected · not used",
            "photo-usage-summary",
        ):
            self.assertIn(phrase, source + html)
        self.assertIn("state.aiSpec?.assets", source)
        self.assertIn("data-id=\"${esc(id)}\"", source)
