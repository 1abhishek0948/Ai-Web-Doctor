"""Views for the scans application.

Part 2 ships the real scan lifecycle. Part 5 adds the results dashboard and
issue detail pages. Part 7 adds the on-demand AI fix endpoint.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.db.models import Count
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.ai.service import generate_fix
from apps.issues.models import Category, Issue
from apps.issues.queryservice import IssueQueryService
from apps.issues.services import verify_issue
from apps.scans.models import ProgressStage, Scan, ScanStatus
from apps.scans.ratelimit import get_client_ip, quota_exceeded
from apps.scans.scoring import compute_score_summary
from apps.scans.services import ScanCreationError, create_scan, dispatch_scan

VALID_SEVERITIES = ("critical", "high", "medium", "low", "info")


def health_view(request):
    """Return basic application health information."""
    return JsonResponse(
        {
            "status": "ok",
            "service": "ai-web-doctor",
            "debug": settings.DEBUG,
            "version": 1,
        }
    )


METRIC_LABELS = [
    ("innerWidth", "Viewport width"),
    ("innerHeight", "Viewport height"),
    ("documentWidth", "Document width"),
    ("documentHeight", "Document height"),
    ("scrollWidth", "Scroll width"),
    ("scrollHeight", "Scroll height"),
]


def _stage_context(scan: Scan) -> dict:
    ordered = ProgressStage.ordered()
    labels = dict(ProgressStage.choices)
    current = scan.progress_stage if scan.progress_stage in ordered else ordered[0]
    current_index = ordered.index(current)
    return {
        "stage_labels": [(stage, labels[stage]) for stage in ordered],
        "done_stages": ordered[:current_index],
    }


def scan_list_view(request: HttpRequest) -> HttpResponse:
    """GET /scans/: list recent scans. POST /scans/: create and start a scan."""
    if request.method == "POST":
        return _create_and_dispatch(request)

    scans = Scan.objects.annotate(issue_count=Count("issues"))[:50]
    return render(request, "pages/scans.html", {"scans": scans})


def _create_and_dispatch(request: HttpRequest) -> HttpResponse:
    raw_url = request.POST.get("url", "")
    client_ip = get_client_ip(request)

    # Daily quota (Part 9): anonymous and authenticated limits are configurable.
    exceeded, used, limit = quota_exceeded(request, user=request.user)
    if exceeded:
        return render(
            request,
            "429.html",
            {"limit": limit, "used": used, "is_authenticated": request.user.is_authenticated},
            status=429,
        )

    # Resource limit: never queue more scans than MAX_CONCURRENT_SCANS.
    running = Scan.objects.filter(
        status__in=(ScanStatus.QUEUED, ScanStatus.RUNNING)
    ).count()
    if running >= settings.MAX_CONCURRENT_SCANS:
        messages.error(
            request,
            "The scanner is busy right now. Please try again in a moment.",
        )
        return redirect("landing")

    try:
        scan = create_scan(raw_url, user=request.user, client_ip=client_ip)
    except ScanCreationError as exc:
        messages.error(request, str(exc))
        return redirect("landing")

    dispatch_scan(scan)
    return redirect("scans:scan-detail", scan_id=scan.pk)


def scan_detail_view(request: HttpRequest, scan_id: int) -> HttpResponse:
    """Render the scan status/result page."""
    scan = get_object_or_404(Scan, pk=scan_id)
    context = _stage_context(scan)
    context["scan"] = scan
    context["metrics"] = {m.key: m.value for m in scan.metrics.all()}
    context["screenshot"] = scan.screenshots.first()
    context["metric_labels"] = METRIC_LABELS
    return render(request, "pages/scan_detail.html", context)


def scan_progress_view(request: HttpRequest, scan_id: int) -> HttpResponse:
    """Return an HTMX partial reflecting the scan's real progress/result."""
    scan = get_object_or_404(Scan, pk=scan_id)
    context = _stage_context(scan)
    context["scan"] = scan
    context["metrics"] = {m.key: m.value for m in scan.metrics.all()}
    context["screenshot"] = scan.screenshots.first()
    context["metric_labels"] = METRIC_LABELS
    return render(request, "partials/scan_progress.html", context)


def results_view(request: HttpRequest, scan_id: int) -> HttpResponse:
    """Render the results dashboard for a completed scan.

    Every number on the page comes from the database through
    :class:`IssueQueryService` (issue counts) and ``compute_score_summary``
    (the UI Health score and its per-category breakdown). No values are
    hardcoded, and unanalyzed categories are clearly labeled instead of shown
    as a fake zero.
    """
    scan = get_object_or_404(Scan, pk=scan_id)
    severity = request.GET.get("severity", "")
    category = request.GET.get("category", "")

    query = IssueQueryService(scan)
    issues = query.filtered(severity, category)
    score_summary = compute_score_summary(scan)

    context = {
        "scan": scan,
        "issues": issues,
        "total_issues": query.total_count(),
        "severity_counts": query.severity_counts(),
        "severity_options": VALID_SEVERITIES,
        "selected_severity": severity if severity in VALID_SEVERITIES else "",
        "category_options": Category.choices,
        "selected_category": category if category in dict(Category.choices) else "",
        "score_summary": score_summary,
        "screenshots": scan.screenshots.all(),
        "ai_message": scan.ai_message,
        "ai_enabled": settings.AI_ENABLED,
    }
    return render(request, "pages/results.html", context)


def _evidence_rows(issue: Issue) -> list[tuple[str, str]]:
    """Flatten scalar issue evidence into (key, value) rows for display."""
    evidence = issue.evidence or {}
    rows: list[tuple[str, str]] = []
    for key, value in evidence.items():
        if key == "ai":
            continue
        if isinstance(value, (str, int, float, bool)) and str(value).strip():
            rows.append((key, str(value)))
        elif (
            isinstance(value, list) and value and all(isinstance(x, str) for x in value)
        ):
            rows.append((key, ", ".join(value)))
    return rows


def _evidence_snippet(issue: Issue) -> str:
    evidence = issue.evidence or {}
    return str(evidence.get("snippet") or evidence.get("html") or "")


def issue_detail_view(request: HttpRequest, scan_id: int, issue_id: int) -> HttpResponse:
    """Render a single issue with its evidence, screenshot and fix tools."""
    issue = get_object_or_404(Issue, pk=issue_id, scan_id=scan_id)
    screenshots = issue.scan.screenshots.all()
    screenshot = None
    if issue.viewport_width:
        screenshot = (
            screenshots.filter(
                viewport_width=issue.viewport_width,
                viewport_height=issue.viewport_height or 812,
            ).first()
            or screenshots.first()
        )
    if screenshot is None:
        screenshot = screenshots.first()
    return render(
        request,
        "pages/issue_detail.html",
        {
            "issue": issue,
            "screenshot": screenshot,
            "evidence_rows": _evidence_rows(issue),
            "evidence_snippet": _evidence_snippet(issue),
        },
    )


def issue_fix_view(request: HttpRequest, scan_id: int, issue_id: int) -> HttpResponse:
    """Generate an AI code fix for one issue and return an HTMX partial.

    The generated code is a suggestion only; it is never executed, injected,
    or deployed. The developer reviews and applies it manually.
    """
    issue = get_object_or_404(Issue, pk=issue_id, scan_id=scan_id)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    fix = generate_fix(issue)
    return render(request, "partials/fix_result.html", {"fix": fix, "issue": issue})


def issue_verify_view(request: HttpRequest, scan_id: int, issue_id: int) -> HttpResponse:
    """Re-check an issue against its live website (Verify Fix, Part 8).

    The deterministic scanner reloads the site at the issue's viewport and
    compares the measurable before/after result. Never asks the AI whether a
    measurable problem is fixed. Returns an HTMX partial.
    """
    issue = get_object_or_404(Issue, pk=issue_id, scan_id=scan_id)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    verification = verify_issue(issue)
    return render(
        request,
        "partials/verify_result.html",
        {"verification": verification, "issue": issue},
    )
