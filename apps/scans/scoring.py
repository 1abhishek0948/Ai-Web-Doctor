"""UI Health scoring service.

The dashboard must truthfully reflect what was actually analyzed, so scoring
happens here from the persisted issues + scan state — never from hardcoded
counts:

* Severity penalties: critical 12, high 6, medium 3, low 1, info 0.
* Category groups (weights sum to 100): Responsive 25, Accessibility 20,
  Visual 20, Layout 15, Typography 10, UX 10.
* The same root defect detected at several viewports counts **once** at its
  highest severity, so scanning 9 viewports never multiplies the penalty.
* Every category is analyzed by deterministic checks as soon as the scan
  completes, so a completed scan always has full coverage; AI analysis is an
  optional enrichment source whose findings merge into the same categories.
* The overall score is normalized to the weight that was actually analyzed
  (``earned / analyzed_weight * 100``), so a clean site scores 100.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Count

from apps.issues.models import Category, SEVERITIES
from apps.scans.categories import (
    GROUP_ORDER,
    category_group,
    group_label,
    group_weight,
    members,
)
from apps.scans.models import ProgressStage, ScanStatus

# Severity -> points deducted from a category's weight per root defect.
SEVERITY_PENALTIES = {
    "critical": 12,
    "high": 6,
    "medium": 3,
    "low": 1,
    "info": 0,
}

# Analysis states surfaced to the dashboard.
ANALYZED = "analyzed"
NOT_ANALYZED = "not_analyzed"
FAILED = "failed"
PARTIAL = "partial"

STATE_LABELS = {
    ANALYZED: "Analyzed",
    NOT_ANALYZED: "Not analyzed",
    FAILED: "Analysis failed",
    PARTIAL: "Partially analyzed",
}

COMPLETED_STATUSES = (ScanStatus.COMPLETED, ScanStatus.PARTIAL)


@dataclass
class CategoryScore:
    """Per-raw-category analysis state for the dashboard cards."""

    key: str
    label: str
    group: str
    group_label: str
    weight: int
    count: int
    severity_counts: dict[str, int]
    state: str
    reason: str = ""


@dataclass
class GroupScore:
    """Per-group score and analysis state for the score breakdown."""

    key: str
    label: str
    weight: int
    categories: tuple[str, ...]
    count: int
    root_count: int
    severity_counts: dict[str, int]
    penalty: int
    raw_score: int
    state: str
    reason: str = ""


@dataclass
class ScoreSummary:
    """Overall UI Health score plus everything needed to explain it."""

    score: int | None
    coverage_weight: int
    total_weight: int
    coverage_percent: int
    groups: list[GroupScore] = field(default_factory=list)
    category_states: list[CategoryScore] = field(default_factory=list)

    @property
    def total_roots(self) -> int:
        return sum(g.root_count for g in self.groups)

    @property
    def full_coverage(self) -> bool:
        return self.coverage_weight >= self.total_weight


def _derive_check(evidence: dict) -> str:
    """Best-effort check name for evidence stored before checks were persisted."""
    if evidence.get("rule_id"):
        return f"axe:{evidence['rule_id']}"
    if "clipped_px" in evidence:
        return "text_overflow"
    if evidence.get("image"):
        return "image_issue"
    if "overflow_px" in evidence and evidence.get("element"):
        return "navigation_overflow"
    if evidence.get("element"):
        return "element_outside_viewport"
    if "overflow_px" in evidence:
        return "horizontal_overflow"
    return ""


def _root_key(issue) -> tuple[str, str, str, str]:
    """Collapse issues that represent the same root defect.

    Same category + same check/rule + same element (selector) is one defect,
    no matter how many viewports re-detected it. AI findings carry no check or
    selector, so they are kept apart by title.
    """
    evidence = issue.evidence or {}
    check = str(evidence.get("check") or evidence.get("rule_id") or "")
    if not check:
        check = _derive_check(evidence)
    selector = issue.selector or ""
    if not check and not selector:
        element = evidence.get("element")
        if isinstance(element, dict):
            selector = "{}:{}:{}".format(
                element.get("tag", ""),
                element.get("id", ""),
                ":".join(element.get("classes") or []),
            )
        image = evidence.get("image")
        if isinstance(image, dict):
            selector = f"img:{str(image.get('src', ''))[:80]}"
        if not selector:
            check = f"title:{issue.title[:80]}"
    return (issue.category, issue.source, check, selector)


def _category_state(scan, category: str) -> tuple[str, str]:
    """State + reason for a single raw category.

    Deterministic checks cover all ten categories, so a category counts as
    analyzed once the deterministic pass has finished (completed/partial
    status, or progress at REPORTING while the health score is being computed
    mid-execution). A failed scan never yields a score, whatever a stale
    ``ai_status`` says.
    """
    if scan.status == ScanStatus.FAILED:
        return FAILED, "The scan could not be completed."
    if scan.status in COMPLETED_STATUSES or scan.progress_stage in (
        ProgressStage.REPORTING,
        ProgressStage.COMPLETE,
    ):
        return ANALYZED, ""
    return NOT_ANALYZED, "The scan has not completed yet."


def _group_state(scan, group: str, member_states: list[tuple[str, str]]) -> tuple[str, str]:
    """Aggregate member-category states into one group state."""
    if all(state == ANALYZED for state, _ in member_states):
        return ANALYZED, ""
    if not any(state == ANALYZED for state, _ in member_states):
        failed = next((reason for state, reason in member_states if state == FAILED), "")
        if failed:
            return FAILED, failed
        return NOT_ANALYZED, next(
            (reason for state, reason in member_states if state == NOT_ANALYZED), ""
        )
    return PARTIAL, "Only some checks in this group were analyzed."


def _issue_counts(scan) -> dict[str, dict[str, int]]:
    """Rows of {category: {severity: count}} from one grouped query."""
    rows = (
        scan.issues.values("category", "severity")
        .annotate(count=Count("id"))
        .order_by()
    )
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        counts.setdefault(row["category"], {}).setdefault(row["severity"], 0)
        counts[row["category"]][row["severity"]] += row["count"]
    return counts


def compute_category_states(scan) -> list[CategoryScore]:
    """Per-raw-category states (counts + analyzed status) for dashboard cards."""
    counts = _issue_counts(scan)
    # Iterate the canonical category order from apps.issues.models.
    states: list[CategoryScore] = []
    for key, label in Category.choices:
        severity_counts = counts.get(key, {})
        total = sum(severity_counts.values())
        state, reason = _category_state(scan, key)
        group = category_group(key)
        states.append(
            CategoryScore(
                key=key,
                label=label,
                group=group,
                group_label=group_label(group),
                weight=group_weight(group),
                count=total,
                severity_counts=severity_counts,
                state=state,
                reason=reason,
            )
        )
    return states


def compute_score_summary(scan) -> ScoreSummary:
    """Compute the overall UI Health score and its full breakdown."""
    category_states = compute_category_states(scan)
    state_by_category = {cs.key: cs for cs in category_states}

    # Collapse issues into root defects, charging each root's max severity once.
    roots: dict[tuple[str, str, str, str], int] = {}
    for issue in scan.issues.all():
        key = _root_key(issue)
        penalty = SEVERITY_PENALTIES.get(issue.severity, 0)
        roots[key] = max(roots.get(key, 0), penalty)

    groups: list[GroupScore] = []
    analyzed_weight = 0
    earned = 0

    for group in GROUP_ORDER:
        weight = group_weight(group)
        member_categories = members(group)
        severity_counts: dict[str, int] = {sev: 0 for sev in SEVERITIES}
        total = 0
        penalty = 0
        root_count = 0
        member_states: list[tuple[str, str]] = []
        for category in member_categories:
            cs = state_by_category[category]
            member_states.append((cs.state, cs.reason))
            total += cs.count
            for severity, count in cs.severity_counts.items():
                severity_counts[severity] = severity_counts.get(severity, 0) + count
        for (category, _source, _check, _selector), root_penalty in roots.items():
            if category_group(category) != group:
                continue
            root_count += 1
            penalty += root_penalty
        state, reason = _group_state(scan, group, member_states)
        scorable = state in (ANALYZED, PARTIAL)
        raw_score = max(0, weight - penalty) if scorable else 0
        if scorable:
            analyzed_weight += weight
            earned += raw_score
        groups.append(
            GroupScore(
                key=group,
                label=group_label(group),
                weight=weight,
                categories=member_categories,
                count=total,
                root_count=root_count,
                severity_counts=severity_counts,
                penalty=penalty,
                raw_score=raw_score,
                state=state,
                reason=reason,
            )
        )

    total_weight = sum(group_weight(g) for g in GROUP_ORDER)
    if analyzed_weight:
        score = round(earned / analyzed_weight * 100)
    else:
        score = None
    return ScoreSummary(
        score=score,
        coverage_weight=analyzed_weight,
        total_weight=total_weight,
        coverage_percent=round(analyzed_weight / total_weight * 100) if analyzed_weight else 0,
        groups=groups,
        category_states=category_states,
    )


def compute_health_score(scan) -> int | None:
    """Return the 0-100 UI Health score for a scan (None when nothing analyzed)."""
    return compute_score_summary(scan).score