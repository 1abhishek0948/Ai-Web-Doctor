"""Tests for the UI Health scoring service and category mapping.

The score must truthfully reflect what was actually analyzed: analyzed
categories with zero issues contribute their full weight, AI-only categories
never contribute when AI did not run, and a scan that failed entirely has no
score at all.
"""

from __future__ import annotations

from django.test import TestCase

from apps.issues.models import Issue
from apps.scans.categories import (
    AI_ONLY_CATEGORIES,
    CATEGORY_GROUPS,
    CATEGORY_TO_GROUP,
    DETERMINISTIC_CATEGORIES,
    category_group,
    group_weight,
    members,
)
from apps.scans.models import AIStatus, Scan, ScanStatus
from apps.scans.scoring import (
    FAILED,
    NOT_ANALYZED,
    PARTIAL,
    SEVERITY_PENALTIES,
    compute_category_states,
    compute_health_score,
    compute_score_summary,
)


def _scan(**kwargs) -> Scan:
    defaults = {
        "url": "https://example.com",
        "normalized_url": "https://example.com/",
        "status": ScanStatus.COMPLETED,
        "ai_status": AIStatus.COMPLETED,
    }
    defaults.update(kwargs)
    return Scan.objects.create(**defaults)


def _issue(scan: Scan, severity: str, category: str) -> Issue:
    return Issue.objects.create(scan=scan, title=f"{severity} {category}", severity=severity, category=category)


class CategoryMappingTests(TestCase):
    def test_group_weights_sum_to_100(self):
        self.assertEqual(sum(group_weight(g) for g in CATEGORY_GROUPS), 100)

    def test_every_category_is_mapped(self):
        for category in CATEGORY_TO_GROUP:
            self.assertIn(category_group(category), CATEGORY_GROUPS)

    def test_suggested_mapping(self):
        self.assertEqual(category_group("spacing"), "visual")
        self.assertEqual(category_group("color"), "visual")
        self.assertEqual(category_group("interaction"), "visual")
        self.assertEqual(category_group("performance"), "visual")
        self.assertEqual(category_group("navigation"), "ux")
        self.assertEqual(category_group("ux"), "ux")
        self.assertEqual(category_group("responsive"), "responsive")

    def test_no_category_is_dropped(self):
        mapped = set(CATEGORY_TO_GROUP)
        self.assertEqual(mapped, AI_ONLY_CATEGORIES | DETERMINISTIC_CATEGORIES)

    def test_members_cover_group(self):
        self.assertEqual(set(members("visual")), {"spacing", "color", "interaction", "performance"})
        self.assertEqual(set(members("ux")), {"navigation", "ux"})


class ScoringTests(TestCase):
    def test_clean_scan_scores_100(self):
        scan = _scan()
        self.assertEqual(compute_health_score(scan), 100)

    def test_severity_penalties(self):
        scan = _scan()
        _issue(scan, "critical", "responsive")
        _issue(scan, "high", "responsive")
        _issue(scan, "medium", "accessibility")
        _issue(scan, "low", "layout")
        summary = compute_score_summary(scan)
        by_group = {g.key: g for g in summary.groups}
        self.assertEqual(
            by_group["responsive"].penalty,
            SEVERITY_PENALTIES["critical"] + SEVERITY_PENALTIES["high"],
        )
        self.assertEqual(by_group["accessibility"].penalty, SEVERITY_PENALTIES["medium"])
        self.assertEqual(by_group["layout"].penalty, SEVERITY_PENALTIES["low"])
        expected = (
            max(0, 25 - 18)
            + max(0, 20 - 3)
            + max(0, 15 - 1)
            + 20
            + 10
            + 10
        )
        self.assertEqual(summary.score, expected)

    def test_critical_issue_deducts_from_group(self):
        scan = _scan()
        _issue(scan, "critical", "responsive")
        summary = compute_score_summary(scan)
        self.assertEqual(summary.score, 88)

    def test_score_is_never_negative(self):
        scan = _scan()
        for index in range(5):
            Issue.objects.create(
                scan=scan,
                title=f"Critical issue {index}",
                severity="critical",
                category="responsive",
                selector=f"#el-{index}",
                evidence={"check": "horizontal_overflow", "overflow_px": 10},
            )
        self.assertEqual(compute_health_score(scan), 75)

    def test_same_defect_across_viewports_counts_once(self):
        scan = _scan()
        for width in (320, 375, 390):
            Issue.objects.create(
                scan=scan,
                title="Images must have alternate text",
                severity="critical",
                category="accessibility",
                source="accessibility",
                selector="img[src^='hero']",
                viewport_width=width,
                viewport_height=800,
                evidence={"check": "axe:image-alt", "rule_id": "image-alt"},
            )
        summary = compute_score_summary(scan)
        by_group = {g.key: g for g in summary.groups}
        self.assertEqual(by_group["accessibility"].count, 3)
        self.assertEqual(by_group["accessibility"].root_count, 1)
        self.assertEqual(by_group["accessibility"].penalty, SEVERITY_PENALTIES["critical"])
        self.assertEqual(by_group["accessibility"].raw_score, 8)
        self.assertEqual(summary.score, 88)

    def test_distinct_roots_stack_penalties(self):
        scan = _scan()
        for selector in ("img[src^='hero']", "button.cta", "nav.main"):
            Issue.objects.create(
                scan=scan,
                title="Buttons must have discernible text",
                severity="critical",
                category="accessibility",
                source="accessibility",
                selector=selector,
                viewport_width=375,
                viewport_height=812,
                evidence={"check": "axe:button-name", "rule_id": "button-name"},
            )
        summary = compute_score_summary(scan)
        by_group = {g.key: g for g in summary.groups}
        self.assertEqual(by_group["accessibility"].root_count, 3)
        self.assertEqual(by_group["accessibility"].penalty, 3 * SEVERITY_PENALTIES["critical"])
        self.assertEqual(summary.score, 80)

    def test_ai_duplicates_collapse_by_title(self):
        scan = _scan()
        for width in (375, 768, 1440):
            Issue.objects.create(
                scan=scan,
                title="Header overlaps content",
                severity="medium",
                category="layout",
                source="ai",
                viewport_width=width,
                viewport_height=812,
                evidence={"ai": {"title": "Header overlaps content"}},
            )
        summary = compute_score_summary(scan)
        by_group = {g.key: g for g in summary.groups}
        self.assertEqual(by_group["layout"].root_count, 1)
        self.assertEqual(by_group["layout"].penalty, SEVERITY_PENALTIES["medium"])

    def test_no_ai_scores_only_deterministic_analysis(self):
        scan = _scan(ai_status=AIStatus.UNAVAILABLE)
        summary = compute_score_summary(scan)
        self.assertEqual(summary.score, 100)
        self.assertFalse(summary.full_coverage)
        self.assertEqual(summary.coverage_weight, 70)
        self.assertEqual(summary.coverage_percent, 70)
        visual = next(g for g in summary.groups if g.key == "visual")
        self.assertEqual(visual.state, NOT_ANALYZED)
        self.assertEqual(visual.raw_score, 0)

    def test_ai_completed_contributes_full_weight(self):
        scan = _scan(ai_status=AIStatus.COMPLETED)
        summary = compute_score_summary(scan)
        self.assertTrue(summary.full_coverage)
        self.assertEqual(summary.score, 100)

    def test_ai_rate_limited_visual_groups_failed(self):
        scan = _scan(ai_status=AIStatus.RATE_LIMITED)
        summary = compute_score_summary(scan)
        visual = next(g for g in summary.groups if g.key == "visual")
        self.assertEqual(visual.state, FAILED)
        self.assertEqual(summary.score, 100)

    def test_failed_scan_has_no_score(self):
        scan = _scan(status=ScanStatus.FAILED, ai_status=AIStatus.PENDING)
        self.assertIsNone(compute_health_score(scan))
        self.assertEqual(compute_score_summary(scan).score, None)

    def test_queued_scan_has_no_score(self):
        scan = _scan(status=ScanStatus.QUEUED, ai_status=AIStatus.PENDING)
        self.assertIsNone(compute_health_score(scan))

    def test_category_states(self):
        scan = _scan(ai_status=AIStatus.UNAVAILABLE)
        states = {cs.key: cs for cs in compute_category_states(scan)}
        self.assertEqual(states["responsive"].state, "analyzed")
        self.assertEqual(states["navigation"].state, "analyzed")
        self.assertEqual(states["spacing"].state, NOT_ANALYZED)
        self.assertEqual(states["ux"].state, NOT_ANALYZED)
        self.assertEqual(states["responsive"].weight, 25)

    def test_ai_skipped_is_not_analyzed(self):
        scan = _scan(ai_status=AIStatus.SKIPPED)
        states = {cs.key: cs for cs in compute_category_states(scan)}
        self.assertEqual(states["typography"].state, NOT_ANALYZED)

    def test_ux_group_partial_without_ai(self):
        scan = _scan(ai_status=AIStatus.UNAVAILABLE)
        summary = compute_score_summary(scan)
        ux = next(g for g in summary.groups if g.key == "ux")
        self.assertEqual(ux.state, PARTIAL)
        self.assertEqual(ux.raw_score, ux.weight)