"""Reject private or unresolved links in tracked public Markdown."""

from __future__ import annotations

import argparse
import posixpath
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PATHS = frozenset(
    {
        "docs/maintenance-progress.md",
        "docs/mcp-architecture.md",
    }
)
PRIVATE_PREFIXES = (
    "docs/reviews/",
    "docs/internal/",
    ".local-notes/",
    "check-results/",
    "graphify-out/",
)
_FENCE_OPEN = re.compile(r" {0,3}(`{3,}|~{3,})")
_INLINE_CODE = re.compile(r"(?<!`)(`+)(?!`)(.*?)(?<!`)\1(?!`)", re.DOTALL)
_REFERENCE = re.compile(
    r"^ {0,3}\[[^\]]+\]:[ \t]*(?:<([^<>]*)>|([^\s]+))", re.MULTILINE
)
_URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def _without_code(markdown: str) -> str:
    """Remove fenced and inline code while preserving text boundaries."""
    lines: list[str] = []
    fence_char: str | None = None
    fence_size = 0
    for line in markdown.splitlines(keepends=True):
        if fence_char is not None:
            closing = re.match(
                rf" {{0,3}}{re.escape(fence_char)}{{{fence_size},}}[ \t]*(?:\r?\n)?$",
                line,
            )
            lines.append("\n" if line.endswith("\n") else "")
            if closing:
                fence_char = None
                fence_size = 0
            continue

        opening = _FENCE_OPEN.match(line)
        if opening:
            run = opening.group(1)
            # CommonMark forbids backticks in a backtick fence's info string.
            if run[0] == "~" or "`" not in line[opening.end() :]:
                fence_char = run[0]
                fence_size = len(run)
                lines.append("\n" if line.endswith("\n") else "")
                continue
        lines.append(line)

    code_free = "".join(lines)

    def blank_code(match: re.Match[str]) -> str:
        return "".join("\n" if char == "\n" else " " for char in match.group())

    return _INLINE_CODE.sub(blank_code, code_free)


def _escaped(text: str, position: int) -> bool:
    backslashes = 0
    position -= 1
    while position >= 0 and text[position] == "\\":
        backslashes += 1
        position -= 1
    return backslashes % 2 == 1


def _matching_link_bracket(text: str, closing: int) -> int | None:
    depth = 1
    position = closing - 1
    while position >= 0:
        char = text[position]
        if char in "[]" and not _escaped(text, position):
            if char == "]":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    return position
        position -= 1
    return None


def _inline_destinations(markdown: str) -> list[str]:
    destinations: list[str] = []
    search_from = 0
    while True:
        closing = markdown.find("](", search_from)
        if closing < 0:
            return destinations
        search_from = closing + 2
        if _escaped(markdown, closing):
            continue
        if _matching_link_bracket(markdown, closing) is None:
            continue

        position = closing + 2
        while position < len(markdown) and markdown[position].isspace():
            position += 1
        if position >= len(markdown):
            continue

        if markdown[position] == "<":
            start = position + 1
            position = start
            while position < len(markdown):
                if markdown[position] == ">" and not _escaped(markdown, position):
                    destinations.append(markdown_unescape(markdown[start:position]))
                    break
                position += 1
            continue

        start = position
        nested = 0
        while position < len(markdown):
            char = markdown[position]
            if _escaped(markdown, position):
                position += 1
                continue
            if char == "(":
                nested += 1
            elif char == ")":
                if nested == 0:
                    destinations.append(markdown_unescape(markdown[start:position]))
                    break
                nested -= 1
            elif char.isspace() and nested == 0:
                destinations.append(markdown_unescape(markdown[start:position]))
                break
            position += 1


def markdown_unescape(value: str) -> str:
    """Decode Markdown backslash escapes in a link destination."""
    return re.sub(r"\\(.)", r"\1", value, flags=re.DOTALL)


def _destinations(markdown: str) -> list[str]:
    code_free = _without_code(markdown)
    references = [
        markdown_unescape(bare if bare else angle)
        for angle, bare in _REFERENCE.findall(code_free)
    ]
    return [*_inline_destinations(code_free), *references]


def _is_private(path: str) -> bool:
    normalized = posixpath.normpath(path)
    if normalized in PRIVATE_PATHS:
        return True
    return any(
        normalized == prefix.rstrip("/") or normalized.startswith(prefix)
        for prefix in PRIVATE_PREFIXES
    )


def _tracked_path(value: str) -> str:
    return posixpath.normpath(value)


def _local_target(
    root: Path, document: str, destination: str
) -> tuple[str | None, str | None]:
    """Return (normalized repo path, error) for a local destination."""
    value = destination.strip()
    if not value or value.startswith("#"):
        return None, None
    if _URI_SCHEME.match(value) or value.startswith("//"):
        return None, None

    # Query strings and fragments are navigation state, not part of the path.
    path_text = re.split(r"[?#]", value, maxsplit=1)[0]
    if not path_text:
        return None, None
    decoded = unquote(path_text)
    if "\x00" in decoded:
        return None, "invalid local path"

    if decoded.startswith("/"):
        relative = posixpath.normpath(decoded.lstrip("/"))
    else:
        relative = posixpath.normpath(
            posixpath.join(posixpath.dirname(document), decoded)
        )
    if relative == ".." or relative.startswith("../"):
        return None, "path escapes repository root"

    try:
        (root / relative).resolve(strict=False).relative_to(root)
    except (OSError, ValueError):
        return None, "path escapes repository root"
    return relative, None


def public_docs_errors(root: Path, tracked: Sequence[str]) -> list[str]:
    """Return sorted diagnostics for private and unresolved tracked Markdown."""
    root = root.resolve()
    normalized_tracked = {_tracked_path(item) for item in tracked}
    errors = [
        f"{path}: tracked path is private"
        for path in normalized_tracked
        if _is_private(path)
    ]

    for document in sorted(path for path in normalized_tracked if path.endswith(".md")):
        source = root / Path(document)
        try:
            source.resolve(strict=False).relative_to(root)
        except (OSError, ValueError):
            errors.append(f"{document}: tracked Markdown path escapes repository root")
            continue
        try:
            markdown = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            # Keep diagnostics limited to paths; decoder errors can expose bytes.
            raise OSError(f"cannot read tracked Markdown file {document}") from exc

        for destination in _destinations(markdown):
            target, target_error = _local_target(root, document, destination)
            if target_error:
                errors.append(f"{document}: {target_error}")
                continue
            if target is None:
                continue
            if _is_private(target):
                errors.append(f"{document}: {target}: link targets a private path")
                continue
            if target in normalized_tracked:
                continue
            if any(
                path.startswith(target.rstrip("/") + "/") for path in normalized_tracked
            ):
                continue
            errors.append(f"{document}: {target}: link target is not tracked")

    return sorted(errors)


def _tracked_from_index(root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise OSError("unable to run git ls-files") from exc
    if result.returncode:
        raise RuntimeError("git ls-files failed")
    return result.stdout.decode("utf-8", errors="surrogateescape").split("\0")[:-1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Git repository root")
    args = parser.parse_args()

    try:
        root = args.root.resolve()
        tracked = _tracked_from_index(root)
        errors = public_docs_errors(root, tracked)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Public documentation check could not run: {exc}", file=sys.stderr)
        return 2

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    markdown_count = sum(path.endswith(".md") for path in tracked)
    print(
        f"Public documentation check passed ({markdown_count} tracked Markdown files)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
