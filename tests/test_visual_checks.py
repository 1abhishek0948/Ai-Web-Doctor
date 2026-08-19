"""Tests for the deterministic visual-design checks (scanner/visual.py).

Each detector is a pure function over ``page.evaluate`` results, so tests use
a fake page object returning fixture JSON — no browser required.
"""

from __future__ import annotations

import unittest

from scanner import visual


class FakePage:
    """Minimal page stand-in: returns a canned value for every evaluate call."""

    def __init__(self, value) -> None:
        self._value = value

    def evaluate(self, _script: str):
        return self._value


def _metrics(width: int = 1440) -> dict[str, int]:
    return {"innerWidth": width, "innerHeight": 900}


def _element(**overrides) -> dict:
    el = {
        "tag": "span",
        "id": "",
        "classes": [],
        "text": "Some text",
        "fontSize": "10px",
        "box": {"x": 0, "y": 0, "width": 100, "height": 20},
    }
    el.update(overrides)
    return el


class TinyTextTests(unittest.TestCase):
    def test_flags_small_text(self):
        findings = visual.detect_tiny_text(FakePage([_element()]), _metrics())
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["check"], "tiny_text")
        self.assertEqual(findings[0]["category"], "typography")
        self.assertEqual(findings[0]["severity"], "medium")
        self.assertEqual(findings[0]["viewport_width"], 1440)

    def test_clean_when_no_small_text(self):
        self.assertEqual(visual.detect_tiny_text(FakePage([]), _metrics()), [])

    def test_script_error_is_graceful(self):
        page = FakePage(None)
        page.evaluate = lambda _s: (_ for _ in ()).throw(ValueError("boom"))
        self.assertEqual(visual.detect_tiny_text(page, _metrics()), [])


class FontScaleTests(unittest.TestCase):
    def test_flags_many_distinct_sizes(self):
        data = {"count": 20, "sizes": [10, 12, 16, 20, 24, 28, 32, 36, 40, 48, 56, 64, 72, 80, 96]}
        findings = visual.detect_font_scale(FakePage(data), _metrics())
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["check"], "font_scale_inconsistency")
        self.assertEqual(findings[0]["category"], "typography")
        self.assertEqual(findings[0]["severity"], "low")

    def test_clean_when_scale_coherent(self):
        data = {"count": 8, "sizes": [12, 14, 16, 20, 24, 32, 40, 48]}
        self.assertEqual(visual.detect_font_scale(FakePage(data), _metrics()), [])


class InvisibleTextTests(unittest.TestCase):
    def test_flags_matching_colors(self):
        el = _element(color="rgb(255, 255, 255)", backgroundColor="rgb(255, 255, 255)")
        findings = visual.detect_invisible_text(FakePage([el]), _metrics())
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["check"], "invisible_text")
        self.assertEqual(findings[0]["category"], "color")
        self.assertEqual(findings[0]["severity"], "high")

    def test_clean_when_colors_differ(self):
        self.assertEqual(visual.detect_invisible_text(FakePage([]), _metrics()), [])


class OverlappingSiblingsTests(unittest.TestCase):
    def test_flags_overlap(self):
        pair = {
            "parent": _element(tag="div"),
            "a": _element(tag="p"),
            "b": _element(tag="button"),
            "overlap": {"x": 12, "y": 20},
        }
        findings = visual.detect_overlapping_siblings(FakePage([pair]), _metrics())
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["check"], "overlapping_siblings")
        self.assertEqual(findings[0]["category"], "spacing")
        self.assertEqual(findings[0]["severity"], "medium")

    def test_clean_when_no_overlap(self):
        self.assertEqual(visual.detect_overlapping_siblings(FakePage([]), _metrics()), [])


class SmallTargetTests(unittest.TestCase):
    def test_flags_small_control(self):
        el = _element(tag="button", box={"x": 0, "y": 0, "width": 30, "height": 20})
        findings = visual.detect_small_touch_targets(FakePage([el]), _metrics())
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["check"], "small_touch_target")
        self.assertEqual(findings[0]["category"], "interaction")
        self.assertEqual(findings[0]["severity"], "medium")

    def test_clean_when_targets_adequate(self):
        self.assertEqual(visual.detect_small_touch_targets(FakePage([]), _metrics()), [])


class PointerCursorTests(unittest.TestCase):
    def test_flags_missing_cursor(self):
        el = _element(tag="button")
        findings = visual.detect_missing_pointer_cursor(FakePage([el]), _metrics())
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["check"], "missing_pointer_cursor")
        self.assertEqual(findings[0]["category"], "interaction")
        self.assertEqual(findings[0]["severity"], "low")

    def test_clean_when_all_pointer(self):
        self.assertEqual(visual.detect_missing_pointer_cursor(FakePage([]), _metrics()), [])


class ImageDimensionTests(unittest.TestCase):
    def test_flags_missing_width(self):
        img = {"src": "/hero.png", "hasWidth": True, "hasHeight": False}
        findings = visual.detect_missing_image_dimensions(FakePage([img]), _metrics())
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["check"], "missing_image_dimensions")
        self.assertEqual(findings[0]["category"], "performance")
        self.assertEqual(findings[0]["severity"], "low")

    def test_clean_when_dimensions_present(self):
        self.assertEqual(visual.detect_missing_image_dimensions(FakePage([]), _metrics()), [])


class OversizedImageTests(unittest.TestCase):
    def test_flags_huge_image(self):
        img = {"src": "/big.png", "naturalWidth": 4000, "naturalHeight": 3000, "pixels": 12_000_000}
        findings = visual.detect_oversized_images(FakePage([img]), _metrics())
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["check"], "oversized_image")
        self.assertEqual(findings[0]["category"], "performance")
        self.assertEqual(findings[0]["severity"], "low")

    def test_clean_when_images_small(self):
        self.assertEqual(visual.detect_oversized_images(FakePage([]), _metrics()), [])


class GenericLinkTests(unittest.TestCase):
    def test_flags_vague_label(self):
        link = {"text": "click here", "href": "/docs"}
        findings = visual.detect_generic_link_text(FakePage([link]), _metrics())
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["check"], "generic_link_text")
        self.assertEqual(findings[0]["category"], "ux")
        self.assertEqual(findings[0]["severity"], "low")

    def test_clean_when_labels_descriptive(self):
        self.assertEqual(visual.detect_generic_link_text(FakePage([]), _metrics()), [])


class EmptyLinkTests(unittest.TestCase):
    def test_flags_unlabeled_anchor(self):
        findings = visual.detect_empty_links(FakePage([{"href": "/x"}]), _metrics())
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["check"], "empty_link")
        self.assertEqual(findings[0]["category"], "ux")
        self.assertEqual(findings[0]["severity"], "medium")

    def test_clean_when_links_labeled(self):
        self.assertEqual(visual.detect_empty_links(FakePage([]), _metrics()), [])


class BlankTargetTests(unittest.TestCase):
    def test_flags_missing_noopener(self):
        link = {"text": "Docs", "href": "/docs", "rel": ""}
        findings = visual.detect_blank_target_without_rel(FakePage([link]), _metrics())
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["check"], "blank_target_without_rel")
        self.assertEqual(findings[0]["category"], "ux")
        self.assertEqual(findings[0]["severity"], "low")

    def test_clean_with_noopener(self):
        self.assertEqual(visual.detect_blank_target_without_rel(FakePage([]), _metrics()), [])


class DetectVisualTests(unittest.TestCase):
    def test_combines_all_detectors(self):
        self.assertEqual(visual.detect_visual(FakePage([]), _metrics()), [])

    def test_every_detector_reports_a_visual_category(self):
        cases = [
            (visual.detect_tiny_text, [_element()]),
            (visual.detect_font_scale, {"count": 20, "sizes": [10, 12, 16]}),
            (visual.detect_invisible_text, [_element(color="rgb(0, 0, 0)", backgroundColor="rgb(0, 0, 0)")]),
            (
                visual.detect_overlapping_siblings,
                [{"parent": _element(tag="div"), "a": _element(tag="p"), "b": _element(tag="button"), "overlap": {"x": 10, "y": 10}}],
            ),
            (visual.detect_small_touch_targets, [_element(tag="button")]),
            (visual.detect_missing_pointer_cursor, [_element(tag="button")]),
            (
                visual.detect_missing_image_dimensions,
                [{"src": "/a.png", "hasWidth": True, "hasHeight": False}],
            ),
            (
                visual.detect_oversized_images,
                [{"src": "/a.png", "naturalWidth": 4000, "naturalHeight": 3000, "pixels": 12_000_000}],
            ),
            (visual.detect_generic_link_text, [{"text": "click here", "href": "/"}]),
            (visual.detect_empty_links, [{"href": "/"}]),
            (visual.detect_blank_target_without_rel, [{"text": "x", "href": "/", "rel": ""}]),
        ]
        expected = {"typography", "color", "spacing", "interaction", "performance", "ux"}
        for detector, fixture in cases:
            categories = {f["category"] for f in detector(FakePage(fixture), _metrics())}
            self.assertTrue(categories, f"{detector.__name__} produced no finding")
            self.assertLessEqual(categories, expected, f"{detector.__name__} category: {categories}")

    def test_finding_shape_is_consistent(self):
        finding = visual.detect_tiny_text(FakePage([_element()]), _metrics())[0]
        for key in (
            "check",
            "category",
            "title",
            "severity",
            "viewport_width",
            "description",
            "evidence",
            "confidence",
            "source",
        ):
            self.assertIn(key, finding)
        self.assertEqual(finding["confidence"], 1.0)
        self.assertEqual(finding["source"], "deterministic")


if __name__ == "__main__":
    unittest.main()
