from __future__ import annotations

import tempfile
from pathlib import Path

from prtrack.github import PullRequest
from prtrack.utils.markdown import write_prs_markdown


def make_pr(
    repo: str,
    number: int,
    title: str = "Test PR",
    approvals: int = 0,
    html_url: str | None = None,
) -> PullRequest:
    """Create a test PullRequest object."""
    if html_url is None:
        html_url = f"https://github.com/{repo}/pull/{number}"
    return PullRequest(
        repo=repo,
        number=number,
        title=title,
        author="testuser",
        assignees=[],
        branch="main",
        draft=False,
        approvals=approvals,
        html_url=html_url,
    )


def test_write_prs_markdown_empty_list():
    """Test write_prs_markdown with an empty list."""
    with tempfile.TemporaryDirectory() as tmpdir:
        outfile = Path(tmpdir) / "test.md"

        write_prs_markdown([], str(outfile))

        # Check that file was created with just a newline
        content = outfile.read_text(encoding="utf-8")
        assert content == ""


def test_write_prs_markdown_single_pr():
    """Test write_prs_markdown with a single PR."""
    pr = make_pr("owner/repo", 1, "Test PR Title", 1, "https://github.com/owner/repo/pull/1")

    with tempfile.TemporaryDirectory() as tmpdir:
        outfile = Path(tmpdir) / "test.md"

        write_prs_markdown([pr], str(outfile))

        # Check the content
        content = outfile.read_text(encoding="utf-8")
        expected = "1. [1/2 Approval] [Test PR Title](https://github.com/owner/repo/pull/1)\n"
        assert content == expected


def test_write_prs_markdown_multiple_prs():
    """Test write_prs_markdown with multiple PRs."""
    pr1 = make_pr("owner/repo", 1, "First PR", 0, "https://github.com/owner/repo/pull/1")
    pr2 = make_pr("owner/repo", 2, "Second PR", 2, "https://github.com/owner/repo/pull/2")
    pr3 = make_pr("another/repo", 1, "Third PR", 1, "https://github.com/another/repo/pull/1")

    with tempfile.TemporaryDirectory() as tmpdir:
        outfile = Path(tmpdir) / "test.md"

        write_prs_markdown([pr1, pr2, pr3], str(outfile))

        # Check the content
        content = outfile.read_text(encoding="utf-8")
        lines = content.strip().split("\n")

        # Should have 3 lines
        assert len(lines) == 3

        # Check that PRs are sorted by repo then number
        # another/repo should come first, then owner/repo
        assert lines[0] == "1. [1/2 Approval] [Third PR](https://github.com/another/repo/pull/1)"
        assert lines[1] == "2. [0/2 Approval] [First PR](https://github.com/owner/repo/pull/1)"
        assert lines[2] == "3. [2/2 Approval] [Second PR](https://github.com/owner/repo/pull/2)"


def test_write_prs_markdown_prs_sorted_by_repo_and_number():
    """Test that PRs are sorted by repo then number."""
    # Create PRs in non-sorted order
    pr1 = make_pr("z/repo", 1, "Z Repo PR")
    pr2 = make_pr("a/repo", 2, "A Repo PR 2")
    pr3 = make_pr("a/repo", 1, "A Repo PR 1")

    with tempfile.TemporaryDirectory() as tmpdir:
        outfile = Path(tmpdir) / "test.md"

        write_prs_markdown([pr1, pr2, pr3], str(outfile))

        # Check the content
        content = outfile.read_text(encoding="utf-8")
        lines = content.strip().split("\n")

        # Should be sorted by repo then number
        assert lines[0] == "1. [0/2 Approval] [A Repo PR 1](https://github.com/a/repo/pull/1)"
        assert lines[1] == "2. [0/2 Approval] [A Repo PR 2](https://github.com/a/repo/pull/2)"
        assert lines[2] == "3. [0/2 Approval] [Z Repo PR](https://github.com/z/repo/pull/1)"


def test_write_prs_markdown_different_approval_counts():
    """Test write_prs_markdown with different approval counts."""
    pr1 = make_pr("owner/repo", 1, "No Approvals", 0)
    pr2 = make_pr("owner/repo", 2, "One Approval", 1)
    pr3 = make_pr("owner/repo", 3, "Two Approvals", 2)

    with tempfile.TemporaryDirectory() as tmpdir:
        outfile = Path(tmpdir) / "test.md"

        write_prs_markdown([pr1, pr2, pr3], str(outfile))

        # Check the content
        content = outfile.read_text(encoding="utf-8")
        lines = content.strip().split("\n")

        assert lines[0] == "1. [0/2 Approval] [No Approvals](https://github.com/owner/repo/pull/1)"
        assert lines[1] == "2. [1/2 Approval] [One Approval](https://github.com/owner/repo/pull/2)"
        assert lines[2] == "3. [2/2 Approval] [Two Approvals](https://github.com/owner/repo/pull/3)"
