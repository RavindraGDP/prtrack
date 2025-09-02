from __future__ import annotations

from collections.abc import Iterable

from ..github import PullRequest


def write_prs_markdown(prs: Iterable[PullRequest], outfile: str) -> None:
    """Write selected PRs to a markdown file in the required format.

    Each line format:
      "N. [n/2 Approval] [Title](URL)"
    where n is the current approval count.
    """
    # Sort stable by repo then number for predictability
    prs_list = list(prs)
    prs_list.sort(key=lambda p: (p.repo, p.number))
    lines: list[str] = []
    for idx, pr in enumerate(prs_list, start=1):
        lines.append(f"{idx}. [{pr.approvals}/2 Approval] [{pr.title}]({pr.html_url})")
    content = "\n".join(lines) + ("\n" if lines else "")
    with open(outfile, "w", encoding="utf-8") as f:
        f.write(content)
