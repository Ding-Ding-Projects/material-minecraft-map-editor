"""Live GitHub state for the Memory Console's Operations and Changelog views.

Everything here reads this repository's *real* state through the local ``gh``
CLI and ``git`` -- never a mock, never a fixture pretending to be one.  The
module stays wx-free so it can be unit tested without a display, and every
call that reaches a process is a thin wrapper around an injectable
``runner``, so tests exercise the real parsing and formatting logic against a
fake process result instead of actually shelling out to ``gh``.

Degradation is explicit rather than silent: when ``gh`` is missing, signed
out, rate-limited, or offline, :func:`gh_status` says which of those it is,
and every fetch function returns that status alongside whatever it could
still read (git status never depends on ``gh`` at all) rather than an empty
list that could be mistaken for "no issues".

The one write path this module exposes is :func:`post_discussion_comment`,
which posts one Markdown body to one already-selected Discussion through
``gh api graphql``.  It is never called on a timer or on startup -- only in
direct response to a user pressing a button with a body they typed.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

from amulet_map_editor.api import process as process_api

#: Seconds to wait for one ``gh``/``git`` invocation before giving up.  Every
#: call here is read-only or a single small mutation, so this is generous
#: without risking the UI thread hanging on a stalled network call.
COMMAND_TIMEOUT = 20.0

#: A short commit SHA, the shape every changelog entry and release body links.
_COMMIT_RE = re.compile(r"\b([0-9a-f]{7,40})\b")

RunResult = Tuple[bool, str, str]
Runner = Callable[[Sequence[str], Optional[str], float], RunResult]


def _default_runner(
    argv: Sequence[str], cwd: Optional[str], timeout: float
) -> RunResult:
    """Run one child process with the console-suppression contract.

    Returns ``(ok, stdout, stderr)``.  ``ok`` is ``False`` for a nonzero exit,
    a timeout, or an executable that could not be found -- the caller decides
    what each of those means rather than this function guessing.
    """
    executable = shutil.which(argv[0])
    if executable is None:
        return False, "", f"{argv[0]} is not installed or not on PATH"
    try:
        result = subprocess.run(
            [executable, *argv[1:]],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **process_api.no_window_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return False, "", f"{argv[0]} timed out after {timeout:g}s"
    except OSError as exc:  # pragma: no cover - platform dependent
        return False, "", str(exc)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        return False, result.stdout, message or f"{argv[0]} exited {result.returncode}"
    return True, result.stdout, ""


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ControlPlaneStatus:
    """Whether ``gh``-backed reads can run right now, and why not.

    ``available`` is ``False`` for every reason a read might be honestly
    incomplete: not installed, not authenticated, rate-limited, offline, or
    some other refusal ``gh`` reported.  ``reason`` is the sentence the
    console shows in place of a card full of live data.
    """

    available: bool
    reason: str = ""


def gh_status(
    cwd: Optional[str] = None, *, runner: Runner = _default_runner
) -> ControlPlaneStatus:
    """Probe whether ``gh`` is installed, signed in, and reachable."""
    ok, _out, err = runner(["gh", "auth", "status"], cwd, COMMAND_TIMEOUT)
    if ok:
        return ControlPlaneStatus(True)
    low = err.lower()
    if "not installed" in low or "not on path" in low:
        return ControlPlaneStatus(False, "The gh CLI is not installed on this machine.")
    if "not logged" in low or "no oauth token" in low or "authentication" in low:
        return ControlPlaneStatus(
            False, "gh is not signed in. Run `gh auth login` to connect an account."
        )
    if "rate limit" in low or "api rate limit" in low:
        return ControlPlaneStatus(False, "The GitHub API rate limit was reached.")
    if (
        "could not resolve host" in low
        or "network" in low
        or "timed out" in low
        or "connection" in low
    ):
        return ControlPlaneStatus(False, "This machine appears to be offline.")
    return ControlPlaneStatus(False, err or "gh reported a failure with no message.")


# ---------------------------------------------------------------------------
# git (never depends on gh)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GitStatus:
    """A one-line summary of the local working tree, read with plain git."""

    available: bool
    branch: str = ""
    dirty_files: int = 0
    reason: str = ""

    def summary(self) -> str:
        if not self.available:
            return self.reason or "Git status is unavailable."
        state = (
            "clean" if self.dirty_files == 0 else f"{self.dirty_files} file(s) dirty"
        )
        return f"{self.branch or '(detached)'} -- {state}"


def git_status_summary(
    cwd: Optional[str] = None, *, runner: Runner = _default_runner
) -> GitStatus:
    """Read the local branch name and dirty-file count."""
    ok, out, err = runner(
        ["git", "status", "--porcelain=v1", "--branch"], cwd, COMMAND_TIMEOUT
    )
    if not ok:
        return GitStatus(False, reason=err or "git status failed.")
    lines = out.splitlines()
    branch = ""
    dirty = 0
    for line in lines:
        if line.startswith("##"):
            header = line[2:].strip()
            branch = header.split("...", 1)[0].split(" ", 1)[0]
        elif line.strip():
            dirty += 1
    return GitStatus(True, branch=branch, dirty_files=dirty)


# ---------------------------------------------------------------------------
# operations: issues, workflow runs, discussions, project items
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IssueSummary:
    number: int
    title: str
    url: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class RunSummary:
    name: str
    status: str
    conclusion: str
    branch: str = ""
    url: str = ""


@dataclass(frozen=True)
class DiscussionSummary:
    number: int
    title: str
    category: str = ""
    url: str = ""
    node_id: str = ""


@dataclass(frozen=True)
class ProjectItemSummary:
    title: str
    status: str = ""


@dataclass(frozen=True)
class OperationsSnapshot:
    """Everything the Operations view shows, or the reason some part is missing."""

    status: ControlPlaneStatus
    git: GitStatus = field(default_factory=lambda: GitStatus(False))
    issues: Tuple[IssueSummary, ...] = ()
    runs: Tuple[RunSummary, ...] = ()
    discussions: Tuple[DiscussionSummary, ...] = ()
    project_items: Tuple[ProjectItemSummary, ...] = ()
    issues_reason: str = ""
    runs_reason: str = ""
    discussions_reason: str = ""
    project_reason: str = ""


def _gh_json(
    args: Sequence[str], cwd: Optional[str], runner: Runner
) -> Tuple[bool, object, str]:
    ok, out, err = runner(["gh", *args], cwd, COMMAND_TIMEOUT)
    if not ok:
        return False, None, err
    try:
        return True, json.loads(out or "null"), ""
    except json.JSONDecodeError as exc:
        return False, None, f"gh returned unparseable JSON: {exc}"


def fetch_operations_snapshot(
    cwd: Optional[str] = None, *, runner: Runner = _default_runner
) -> OperationsSnapshot:
    """Read local git status plus every read-only GitHub surface Operations shows."""
    git = git_status_summary(cwd, runner=runner)
    status = gh_status(cwd, runner=runner)
    if not status.available:
        return OperationsSnapshot(status=status, git=git)

    issues: Tuple[IssueSummary, ...] = ()
    issues_reason = ""
    ok, data, err = _gh_json(
        [
            "issue",
            "list",
            "--state",
            "open",
            "--json",
            "number,title,url,updatedAt",
            "--limit",
            "50",
        ],
        cwd,
        runner,
    )
    if ok and isinstance(data, list):
        issues = tuple(
            IssueSummary(
                number=int(row.get("number", 0)),
                title=str(row.get("title", "")),
                url=str(row.get("url", "")),
                updated_at=str(row.get("updatedAt", "")),
            )
            for row in data
        )
    else:
        issues_reason = err or "Could not read open issues."

    runs: Tuple[RunSummary, ...] = ()
    runs_reason = ""
    ok, data, err = _gh_json(
        [
            "run",
            "list",
            "--json",
            "name,status,conclusion,headBranch,url",
            "--limit",
            "20",
        ],
        cwd,
        runner,
    )
    if ok and isinstance(data, list):
        runs = tuple(
            RunSummary(
                name=str(row.get("name", "")),
                status=str(row.get("status", "")),
                conclusion=str(row.get("conclusion", "") or ""),
                branch=str(row.get("headBranch", "")),
                url=str(row.get("url", "")),
            )
            for row in data
        )
    else:
        runs_reason = err or "Could not read workflow runs."

    discussions: Tuple[DiscussionSummary, ...] = ()
    discussions_reason = ""
    owner, name = repo_owner_and_name(cwd, runner=runner)
    if owner and name:
        query = (
            "query($owner:String!,$name:String!){repository(owner:$owner,name:$name){"
            "discussions(first:20, orderBy:{field:UPDATED_AT, direction:DESC}){nodes{"
            "id number title url category{name}}}}}"
        )
        ok, out, err = runner(
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-f",
                f"owner={owner}",
                "-f",
                f"name={name}",
            ],
            cwd,
            COMMAND_TIMEOUT,
        )
        if ok:
            try:
                payload = json.loads(out or "{}")
                nodes = (
                    payload.get("data", {})
                    .get("repository", {})
                    .get("discussions", {})
                    .get("nodes", [])
                )
                discussions = tuple(
                    DiscussionSummary(
                        number=int(node.get("number", 0)),
                        title=str(node.get("title", "")),
                        category=str((node.get("category") or {}).get("name", "")),
                        url=str(node.get("url", "")),
                        node_id=str(node.get("id", "")),
                    )
                    for node in nodes
                )
            except (json.JSONDecodeError, AttributeError, TypeError) as exc:
                discussions_reason = f"Could not parse Discussions: {exc}"
        else:
            discussions_reason = err or "Could not read Discussions."
    else:
        discussions_reason = "Could not resolve the repository owner and name."

    project_items: Tuple[ProjectItemSummary, ...] = ()
    project_reason = ""
    ok, out, err = runner(
        ["gh", "project", "list", "--owner", owner or "@me"], cwd, COMMAND_TIMEOUT
    )
    if ok:
        rows = [line for line in out.splitlines()[1:] if line.strip()]
        project_items = tuple(
            ProjectItemSummary(title=row.strip()) for row in rows[:20]
        )
    else:
        project_reason = err or "Could not read Project items."

    return OperationsSnapshot(
        status=status,
        git=git,
        issues=issues,
        runs=runs,
        discussions=discussions,
        project_items=project_items,
        issues_reason=issues_reason,
        runs_reason=runs_reason,
        discussions_reason=discussions_reason,
        project_reason=project_reason,
    )


def repo_owner_and_name(
    cwd: Optional[str] = None, *, runner: Runner = _default_runner
) -> Tuple[str, str]:
    """Return this checkout's ``(owner, name)`` as gh sees it, or ``("", "")``."""
    ok, data, _err = _gh_json(["repo", "view", "--json", "owner,name"], cwd, runner)
    if not ok or not isinstance(data, dict):
        return "", ""
    owner = data.get("owner") or {}
    return str(owner.get("login", "")), str(data.get("name", ""))


# ---------------------------------------------------------------------------
# changelog: published releases
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReleaseSummary:
    tag: str
    name: str
    published_at: str
    url: str = ""
    body: str = ""
    commit: str = ""

    def source_commit(self) -> str:
        """Return the first commit-shaped token in this release's body, if any."""
        if self.commit:
            return self.commit
        match = _COMMIT_RE.search(self.body)
        return match.group(1) if match else ""


@dataclass(frozen=True)
class ChangelogSnapshot:
    status: ControlPlaneStatus
    releases: Tuple[ReleaseSummary, ...] = ()
    reason: str = ""


def fetch_changelog_snapshot(
    cwd: Optional[str] = None, *, runner: Runner = _default_runner, limit: int = 30
) -> ChangelogSnapshot:
    """Read every published release this repository has, newest first."""
    status = gh_status(cwd, runner=runner)
    if not status.available:
        return ChangelogSnapshot(status=status)
    ok, data, err = _gh_json(
        [
            "release",
            "list",
            "--json",
            "tagName,name,publishedAt,isDraft",
            "--limit",
            str(limit),
        ],
        cwd,
        runner,
    )
    if not ok or not isinstance(data, list):
        return ChangelogSnapshot(
            status=status, reason=err or "Could not read releases."
        )
    releases = []
    for row in data:
        if row.get("isDraft"):
            continue
        tag = str(row.get("tagName", ""))
        ok2, body, _err2 = runner(
            ["gh", "release", "view", tag, "--json", "body,url"], cwd, COMMAND_TIMEOUT
        )
        body_text = ""
        url_text = ""
        if ok2:
            try:
                payload = json.loads(body or "{}")
                body_text = str(payload.get("body", ""))
                url_text = str(payload.get("url", ""))
            except json.JSONDecodeError:
                body_text = ""
        releases.append(
            ReleaseSummary(
                tag=tag,
                name=str(row.get("name", "") or tag),
                published_at=str(row.get("publishedAt", "")),
                url=url_text,
                body=body_text,
            )
        )
    return ChangelogSnapshot(status=status, releases=tuple(releases))


def filter_releases_by_date(
    releases: Sequence[ReleaseSummary], start: str = "", end: str = ""
) -> Tuple[ReleaseSummary, ...]:
    """Keep releases whose ISO ``publishedAt`` falls within ``[start, end]``.

    ``start``/``end`` are ISO date strings (``YYYY-MM-DD``); an empty bound is
    open-ended.  A release with no parseable date is kept, since excluding it
    silently would look identical to it simply not existing.
    """
    kept = []
    for release in releases:
        stamp = release.published_at[:10]
        if not stamp:
            kept.append(release)
            continue
        if start and stamp < start:
            continue
        if end and stamp > end:
            continue
        kept.append(release)
    return tuple(kept)


def export_releases_markdown(releases: Sequence[ReleaseSummary]) -> str:
    """Render the given releases as one Markdown changelog document."""
    lines = ["# Changelog", ""]
    for release in releases:
        date = release.published_at[:10] or "(unknown date)"
        commit = release.source_commit()
        heading = f"## {release.name or release.tag} -- {date}"
        lines.append(heading)
        if commit:
            lines.append(f"Source commit: `{commit}`")
        if release.url:
            lines.append(f"Release: {release.url}")
        if release.body.strip():
            lines.append("")
            lines.append(release.body.strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# the one write path: post a progress comment to a Discussion
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommentResult:
    ok: bool
    message: str
    url: str = ""


def post_discussion_comment(
    discussion_node_id: str,
    body: str,
    *,
    cwd: Optional[str] = None,
    runner: Runner = _default_runner,
) -> CommentResult:
    """Post ``body`` as a comment on the Discussion identified by its node id.

    This is the console's one explicit write path.  It never runs on a timer
    or automatically; it runs only when a user has selected a Discussion,
    typed a body, and pressed the button.  The request goes straight to the
    local ``gh`` CLI's own credentials -- this module never sees a token.
    """
    text = body.strip()
    if not text:
        return CommentResult(False, "Nothing was typed, so nothing was posted.")
    if not discussion_node_id:
        return CommentResult(False, "No Discussion is selected.")
    mutation = (
        "mutation($id:ID!,$body:String!){addDiscussionComment(input:{discussionId:$id,"
        "body:$body}){comment{id url}}}"
    )
    ok, out, err = runner(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={mutation}",
            "-f",
            f"id={discussion_node_id}",
            "-f",
            f"body={text}",
        ],
        cwd,
        COMMAND_TIMEOUT,
    )
    if not ok:
        return CommentResult(False, err or "gh refused to post the comment.")
    try:
        payload = json.loads(out or "{}")
        comment = (
            payload.get("data", {}).get("addDiscussionComment", {}).get("comment", {})
        )
        url = str(comment.get("url", ""))
    except (json.JSONDecodeError, AttributeError, TypeError):
        url = ""
    if not url:
        return CommentResult(
            False, "gh accepted the request but returned no comment URL."
        )
    return CommentResult(True, "Posted.", url=url)
