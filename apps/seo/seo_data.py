"""SEO-related data shared by templates and structured data markup."""

from __future__ import annotations

SEO_FAQS = [
    {
        "question": "What is AI Web Doctor?",
        "answer": (
            "AI Web Doctor is a free website UI testing tool that loads your site in a real "
            "headless browser, checks it across mobile, tablet, and desktop viewports, and "
            "produces a UI health score with a prioritized list of broken elements, layout "
            "bugs, and accessibility issues."
        ),
    },
    {
        "question": "How does the UI health score work?",
        "answer": (
            "The UI health score is a 0-100 rating computed from six weighted categories: "
            "responsive layout, accessibility, visual design, layout structure, typography, "
            "and user experience. Critical defects hurt the score most, and identical defects "
            "found at multiple screen sizes are counted once."
        ),
    },
    {
        "question": "Which viewports does the website scanner test?",
        "answer": (
            "Every scan runs at nine viewport sizes, from 320px wide phones up to 1440px "
            "desktop, so you can catch horizontal overflow, clipped text, overlapping "
            "elements, and collapsed navigation at every screen size before your users do."
        ),
    },
    {
        "question": "Which accessibility issues does it detect?",
        "answer": (
            "The scanner runs axe-core accessibility rules for missing image alt text, "
            "buttons and links without accessible names, color contrast failures, and "
            "other WCAG-related problems, and explains each issue in plain language."
        ),
    },
    {
        "question": "How is AI used in the analysis?",
        "answer": (
            "Deterministic checks always run. Where visual reasoning matters, an AI model "
            "reviews screenshots to spot spacing, alignment, and color problems that rule "
            "based checks cannot see. If AI analysis is unavailable, your score reflects "
            "the deterministic checks that did run."
        ),
    },
    {
        "question": "How do I fix and verify the issues?",
        "answer": (
            "Each issue includes a fix suggestion with code. After you apply it, the Verify "
            "Fix feature re-checks the exact element and confirms whether the problem is "
            "actually resolved."
        ),
    },
]