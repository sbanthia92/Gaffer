#!/usr/bin/env python3
"""
Three-tier PR review: Haiku classifies every file, reviews minor ones itself,
escalates significant files to Sonnet. Prompt caching on the shared system
prompt + REVIEW.md cuts repeat token cost across all per-file calls.
"""

import json
import os
import re
import subprocess

import anthropic

# ---------------------------------------------------------------------------
# Models & limits
# ---------------------------------------------------------------------------
HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"
MAX_DIFF_CHARS = 16_000  # ~4 000 tokens at 4 chars/token
CACHE_BETA = {"anthropic-beta": "prompt-caching-2024-07-31"}

# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------
SKIP_PATTERNS = [
    "package-lock.json",
    "yarn.lock",
    "Gemfile.lock",
    "poetry.lock",
    "pnpm-lock.yaml",
    "composer.lock",
    "Cargo.lock",
    "tests/fixtures/",
    "db/migrations/",
    "terraform/",
    "k8s/",
    "infra/",
    "pipeline/",
]
SKIP_EXTENSIONS = {
    ".lock",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".webp",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp4",
    ".pdf",
    ".zip",
}
SKIP_SUFFIXES = (".min.js", ".min.css")
DOCS_EXTENSIONS = {".md", ".txt", ".rst", ".mdx"}


def should_skip(filename: str) -> bool:
    lower = filename.lower()
    ext = os.path.splitext(lower)[1]
    if ext in SKIP_EXTENSIONS:
        return True
    if lower.endswith(SKIP_SUFFIXES):
        return True
    return any(pat in filename for pat in SKIP_PATTERNS)


def is_docs(filename: str) -> bool:
    return os.path.splitext(filename)[1].lower() in DOCS_EXTENSIONS


# ---------------------------------------------------------------------------
# Anthropic helpers
# ---------------------------------------------------------------------------
def build_system(review_md: str) -> list[dict]:
    """Two cached blocks: base instructions + review rubric."""
    return [
        {
            "type": "text",
            "text": (
                "You are a senior engineer reviewing pull requests for The Gaffer — "
                "an AI-powered Fantasy Premier League analyst built with FastAPI, "
                "Claude tool-use, and React."
            ),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"Apply these review conventions exactly:\n\n{review_md}",
            "cache_control": {"type": "ephemeral"},
        },
    ]


def truncate(diff: str) -> tuple[str, bool]:
    if len(diff) <= MAX_DIFF_CHARS:
        return diff, False
    return diff[:MAX_DIFF_CHARS] + "\n\n[… diff truncated at ~4 000 tokens …]", True


def classify(
    filename: str, diff: str, system: list[dict], client: anthropic.Anthropic
) -> tuple[str, str]:
    """Return (tier, one_liner). Tier is TRIVIAL | MINOR | SIGNIFICANT."""
    d, _ = truncate(diff)
    resp = client.messages.create(
        model=HAIKU,
        max_tokens=60,
        system=system,
        messages=[
            {
                "role": "user",
                "content": (
                    "Classify this diff into exactly one tier, then give a one-line verdict.\n\n"
                    "Tiers:\n"
                    "- TRIVIAL: whitespace, comments, minor renames, README tweaks, version bumps\n"
                    "- MINOR: small logic changes, simple refactors, "
                    "test additions, config changes\n"
                    "- SIGNIFICANT: complex logic, new features, security-relevant, "
                    "API/schema changes, new dependencies\n\n"
                    f"File: `{filename}`\n\n"
                    f"```diff\n{d}\n```\n\n"
                    "Reply in this exact format (two lines, nothing else):\n"
                    "TIER: <TRIVIAL|MINOR|SIGNIFICANT>\n"
                    "VERDICT: <one sentence>"
                ),
            }
        ],
        extra_headers=CACHE_BETA,
    )
    text = resp.content[0].text.strip()
    tier_m = re.search(r"TIER:\s*(TRIVIAL|MINOR|SIGNIFICANT)", text, re.I)
    verdict_m = re.search(r"VERDICT:\s*(.+)", text)
    tier = tier_m.group(1).upper() if tier_m else "SIGNIFICANT"
    verdict = verdict_m.group(1).strip() if verdict_m else "Reviewed."
    return tier, verdict


def review_file(
    filename: str, diff: str, model: str, system: list[dict], client: anthropic.Anthropic
) -> str:
    d, truncated = truncate(diff)
    note = "\n\n⚠️ Diff truncated — review may be incomplete." if truncated else ""
    resp = client.messages.create(
        model=model,
        max_tokens=800,
        system=system,
        messages=[
            {
                "role": "user",
                "content": (
                    "Review this file diff. List every finding:\n"
                    "- Important 🔴: [issue] — [why it matters] — Fix: [suggestion]\n"
                    "- Nit 🟡: [issue]\n\n"
                    "Or respond with exactly 'No findings.' if nothing to flag.\n\n"
                    f"File: `{filename}`{note}\n\n"
                    f"```diff\n{d}\n```"
                ),
            }
        ],
        extra_headers=CACHE_BETA,
    )
    return resp.content[0].text.strip()


# ---------------------------------------------------------------------------
# Summary assembly
# ---------------------------------------------------------------------------
def count_findings(text: str) -> tuple[int, int]:
    return (
        len(re.findall(r"Important 🔴", text)),
        len(re.findall(r"Nit 🟡", text)),
    )


def build_summary(
    skipped: list[str],
    trivial: list[tuple[str, str]],  # (filename, one_liner)
    minor: list[tuple[str, str]],  # (filename, review_text)
    significant: list[tuple[str, str]],  # (filename, review_text)
) -> str:
    """Assemble the roll-up PR Review Summary comment from per-file review results."""
    total_imp = total_nit = 0
    for _, rev in significant + minor:
        i, n = count_findings(rev)
        total_imp += i
        total_nit += n

    if total_imp > 0:
        verdict = "🔴 Must fix before merge"
    elif total_nit > 0:
        verdict = "⚠️ Needs changes"
    else:
        verdict = "✅ Looks good"

    lines = [
        "## PR Review Summary",
        "",
        f"**Important 🔴 findings:** {total_imp}",
        f"**Nit 🟡 findings:** {total_nit}",
        f"**Verdict:** {verdict}",
        "",
    ]

    if significant:
        lines += ["---", "### Significant files — reviewed by Sonnet", ""]
        for filename, rev in significant:
            lines += [f"#### `{filename}`", rev, ""]

    if minor:
        lines += ["---", "### Minor files — reviewed by Haiku", ""]
        for filename, rev in minor:
            lines += [f"#### `{filename}`", rev, ""]

    # Collapsed section: trivial verdicts + skipped files
    if trivial or skipped:
        collapsed = []
        if trivial:
            collapsed.append("**Trivial — no detailed review needed:**")
            for fn, v in trivial:
                collapsed.append(f"- `{fn}` — {v}")
            collapsed.append("")
        if skipped:
            collapsed.append("**Skipped — lock files / generated / binary / docs:**")
            for fn in skipped:
                collapsed.append(f"- `{fn}`")

        lines += [
            "---",
            "<details>",
            "<summary>Files not requiring full review</summary>",
            "",
            *collapsed,
            "</details>",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GitHub posting
# ---------------------------------------------------------------------------
def post_comment(body: str, pr_number: str, repo: str) -> None:
    owner, repo_name = repo.split("/", 1)
    subprocess.run(
        ["gh", "api", f"/repos/{owner}/{repo_name}/issues/{pr_number}/comments", "--input", "-"],
        input=json.dumps({"body": body}),
        text=True,
        check=True,
    )


# ---------------------------------------------------------------------------
# Diff parsing
# ---------------------------------------------------------------------------
def get_diff() -> str:
    return subprocess.run(
        ["git", "diff", "origin/main...HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def parse_file_diffs(diff: str) -> dict[str, str]:
    files: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []

    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current is not None:
                files[current] = "".join(lines)
            m = re.search(r" b/(.+)$", line.rstrip())
            current = m.group(1) if m else None
            lines = [line]
        elif current is not None:
            lines.append(line)

    if current is not None:
        files[current] = "".join(lines)

    return files


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    pr_number = os.environ["PR_NUMBER"]
    repo = os.environ["REPO"]
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    try:
        with open("REVIEW.md") as f:
            review_md = f.read()
    except FileNotFoundError:
        review_md = ""

    system = build_system(review_md)

    raw_diff = get_diff()
    if not raw_diff.strip():
        print("Empty diff — nothing to review.")
        return

    file_diffs = parse_file_diffs(raw_diff)
    skipped: list[str] = []
    reviewable: dict[str, str] = {}

    for filename, diff in file_diffs.items():
        if should_skip(filename):
            skipped.append(filename)
        else:
            reviewable[filename] = diff

    # Entire PR is docs/comments/formatting — no code to review
    if reviewable and all(is_docs(f) for f in reviewable):
        body = (
            "## PR Review Summary\n\n"
            "**Important 🔴 findings:** 0\n"
            "**Nit 🟡 findings:** 0\n"
            "**Verdict:** ✅ Looks good\n\n"
            "Docs/comments/formatting only — no code review needed."
        )
        if skipped:
            body += "\n\n<details><summary>Skipped files</summary>\n\n"
            body += "\n".join(f"- `{f}`" for f in skipped)
            body += "\n\n</details>"
        post_comment(body, pr_number, repo)
        return

    trivial: list[tuple[str, str]] = []
    minor: list[tuple[str, str]] = []
    significant: list[tuple[str, str]] = []

    for filename, diff in reviewable.items():
        print(f"Classifying {filename} …", flush=True)
        tier, verdict_text = classify(filename, diff, system, client)
        print(f"  {tier}: {verdict_text}", flush=True)

        if tier == "TRIVIAL":
            trivial.append((filename, verdict_text))
        elif tier == "MINOR":
            print("  → Haiku review …", flush=True)
            minor.append((filename, review_file(filename, diff, HAIKU, system, client)))
        else:
            print("  → Sonnet review …", flush=True)
            significant.append((filename, review_file(filename, diff, SONNET, system, client)))

    summary = build_summary(skipped, trivial, minor, significant)
    post_comment(summary, pr_number, repo)
    print("Review posted.", flush=True)


if __name__ == "__main__":
    main()
