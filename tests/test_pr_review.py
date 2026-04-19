import importlib.util
import pathlib
from unittest.mock import MagicMock

import pytest

_spec = importlib.util.spec_from_file_location(
    "pr_review",
    pathlib.Path(__file__).parent.parent / ".github" / "scripts" / "pr_review.py",
)
pr_review = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pr_review)


# ---------------------------------------------------------------------------
# should_skip
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "filename",
    [
        "package-lock.json",
        "yarn.lock",
        "Gemfile.lock",
        "poetry.lock",
        "frontend/yarn.lock",
        "tests/fixtures/player.json",
        "db/migrations/0001_init.sql",
        "infra/main.tf",
        "image.png",
        "bundle.min.js",
        "font.woff2",
    ],
)
def test_should_skip_returns_true(filename):
    assert pr_review.should_skip(filename) is True


@pytest.mark.parametrize(
    "filename",
    [
        "server/main.py",
        "server/tools/fpl.py",
        "ui/src/App.tsx",
        "tests/test_main.py",
        "REVIEW.md",
    ],
)
def test_should_skip_returns_false(filename):
    assert pr_review.should_skip(filename) is False


# ---------------------------------------------------------------------------
# is_docs
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("filename", ["README.md", "CHANGELOG.md", "REVIEW.md", "docs/setup.rst"])
def test_is_docs_true(filename):
    assert pr_review.is_docs(filename) is True


@pytest.mark.parametrize("filename", ["server/main.py", "ui/src/App.tsx", "tests/test_main.py"])
def test_is_docs_false(filename):
    assert pr_review.is_docs(filename) is False


# ---------------------------------------------------------------------------
# truncate
# ---------------------------------------------------------------------------
def test_truncate_short_diff_unchanged():
    diff = "x" * 100
    out, was_truncated = pr_review.truncate(diff)
    assert out == diff
    assert was_truncated is False


def test_truncate_long_diff_cut():
    diff = "x" * (pr_review.MAX_DIFF_CHARS + 500)
    out, was_truncated = pr_review.truncate(diff)
    assert was_truncated is True
    assert len(out) < len(diff)
    assert "truncated" in out


# ---------------------------------------------------------------------------
# parse_file_diffs
# ---------------------------------------------------------------------------
SAMPLE_DIFF = """\
diff --git a/server/main.py b/server/main.py
index abc..def 100644
--- a/server/main.py
+++ b/server/main.py
@@ -1,3 +1,4 @@
+import os
 import json
diff --git a/README.md b/README.md
index 111..222 100644
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-old
+new
"""


def test_parse_file_diffs_keys():
    files = pr_review.parse_file_diffs(SAMPLE_DIFF)
    assert set(files.keys()) == {"server/main.py", "README.md"}


def test_parse_file_diffs_content_starts_with_diff():
    files = pr_review.parse_file_diffs(SAMPLE_DIFF)
    assert files["server/main.py"].startswith("diff --git")
    assert files["README.md"].startswith("diff --git")


def test_parse_file_diffs_empty():
    assert pr_review.parse_file_diffs("") == {}


# ---------------------------------------------------------------------------
# count_findings
# ---------------------------------------------------------------------------
def test_count_findings_mixed():
    text = "Important 🔴: bad thing\nNit 🟡: minor\nNit 🟡: also minor"
    assert pr_review.count_findings(text) == (1, 2)


def test_count_findings_clean():
    assert pr_review.count_findings("No findings.") == (0, 0)


# ---------------------------------------------------------------------------
# build_summary — verdict line
# ---------------------------------------------------------------------------
def test_build_summary_clean_verdict():
    body = pr_review.build_summary([], [], [], [])
    assert "✅ Looks good" in body
    assert "## PR Review Summary" in body


def test_build_summary_important_verdict():
    body = pr_review.build_summary(
        [],
        [],
        [],
        [("server/main.py", "Important 🔴: bad thing — why — Fix: do X")],
    )
    assert "Must fix before merge" in body
    assert "🔴" in body


def test_build_summary_nit_only_verdict():
    body = pr_review.build_summary(
        [],
        [],
        [("server/tools/fpl.py", "Nit 🟡: minor issue")],
        [],
    )
    assert "⚠️ Needs changes" in body


def test_build_summary_skipped_files_in_collapsed_section():
    body = pr_review.build_summary(["package-lock.json"], [], [], [])
    assert "<details>" in body
    assert "package-lock.json" in body


def test_build_summary_trivial_in_collapsed_section():
    body = pr_review.build_summary([], [("CHANGELOG.md", "Version bump only.")], [], [])
    assert "<details>" in body
    assert "CHANGELOG.md" in body
    assert "Version bump only." in body


def test_build_summary_significant_in_main_body():
    body = pr_review.build_summary(
        [],
        [],
        [],
        [("server/main.py", "Important 🔴: something bad")],
    )
    assert "### Significant files" in body
    assert "server/main.py" in body


# ---------------------------------------------------------------------------
# classify — mocked Anthropic client
# ---------------------------------------------------------------------------
def _make_client(text: str) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[MagicMock(text=text)])
    return client


def test_classify_returns_trivial():
    client = _make_client("TIER: TRIVIAL\nVERDICT: Whitespace change only.")
    tier, verdict = pr_review.classify("README.md", "diff", [], client)
    assert tier == "TRIVIAL"
    assert "Whitespace" in verdict


def test_classify_returns_significant():
    client = _make_client("TIER: SIGNIFICANT\nVERDICT: New API endpoint added.")
    tier, verdict = pr_review.classify("server/main.py", "diff", [], client)
    assert tier == "SIGNIFICANT"


def test_classify_defaults_to_significant_on_bad_response():
    client = _make_client("I cannot classify this.")
    tier, _ = pr_review.classify("server/main.py", "diff", [], client)
    assert tier == "SIGNIFICANT"


# ---------------------------------------------------------------------------
# review_file — mocked
# ---------------------------------------------------------------------------
def test_review_file_returns_text():
    client = _make_client("Important 🔴: missing input validation — Fix: add check.")
    result = pr_review.review_file("server/main.py", "diff", pr_review.SONNET, [], client)
    assert "Important 🔴" in result


def test_review_file_truncation_note_added_for_large_diff():
    large_diff = "x" * (pr_review.MAX_DIFF_CHARS + 1000)
    client = _make_client("No findings.")
    # The call should succeed; verify truncation note was injected into the prompt
    call_content = []

    def capture(*args, **kwargs):
        call_content.append(kwargs.get("messages", []))
        return MagicMock(content=[MagicMock(text="No findings.")])

    client.messages.create.side_effect = capture
    pr_review.review_file("f.py", large_diff, pr_review.HAIKU, [], client)
    prompt_text = call_content[0][0]["content"]
    assert "truncated" in prompt_text
