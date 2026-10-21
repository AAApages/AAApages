#!/usr/bin/env python3
"""
Check lesson frontmatter so mistakes fail loudly instead of publishing silently.

Usage:
    python3 scripts/lesson_check.py                       # default: _projects/lessons _notebooks
    python3 scripts/lesson_check.py PATH [PATH ...]       # files or directories
    make lesson-check LESSONS="_projects/lessons/java"

Errors break something students see (a missing Submit panel creator, a lesson
missing from its course, a homework sample Jekyll ignores) and exit 1.
Warnings are consistency problems and never fail the run.

Only files git tracks or would track are checked, so generated copies
(`_posts/`, split `*_<course>.ipynb` files) are skipped automatically.
"""

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

try:
    from sync_assignments import parse_frontmatter
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent))
    from sync_assignments import parse_frontmatter

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATHS = ("_projects/lessons", "_notebooks")
LESSON_EXTENSIONS = {".ipynb", ".md"}

REQUIRED_FIELDS = ("layout", "title", "description", "permalink")
# Keys read by _layouts/post.html and scripts/sync_assignments.py. Anything else
# starting with "assignment" is a typo the sync would silently ignore.
KNOWN_ASSIGNMENT_KEYS = {
    "assignment",
    "assignment_submission_type",
    "assignment_creator_uids",
    "assignment_id",
    "assignment_name",
}
SAMPLE_KEY_LINE = re.compile(r"^\s*(?:[A-Za-z_][\w-]*\s*:|-\s)")
SAMPLE_MARKER = re.compile(r"^\s*permalink\s*:", re.M)


@dataclass(frozen=True)
class Finding:
    path: Path
    severity: str  # "error" or "warning"
    code: str
    message: str

    def describe(self, root: Path) -> str:
        return f"{self.path.relative_to(root)}: {self.severity} [{self.code}] {self.message}"


@dataclass
class Lesson:
    """One lesson source: its frontmatter, and the body cells that follow it."""
    path: Path
    frontmatter: dict | None
    frontmatter_cell_type: str | None
    body_cells: list  # [(cell_type, source_text)]

    @classmethod
    def load(cls, path: Path) -> "Lesson":
        text = path.read_text(encoding="utf-8")
        if path.suffix != ".ipynb":
            return cls(path, parse_frontmatter(text), None, [("markdown", text)])

        try:
            cells = json.loads(text).get("cells", [])
        except ValueError as error:
            raise ValueError(f"{path} is not valid notebook JSON: {error}") from error
        sources = [(cell.get("cell_type"), _cell_text(cell)) for cell in cells]
        if not sources:
            return cls(path, None, None, [])
        first_type, first_text = sources[0]
        return cls(path, parse_frontmatter(first_text), first_type, sources[1:])


def _cell_text(cell) -> str:
    source = cell.get("source", "")
    return "".join(source) if isinstance(source, list) else str(source)


# ---- Rules: each takes one Lesson and yields Findings.

def check_frontmatter_present(lesson):
    if lesson.frontmatter is None:
        yield Finding(lesson.path, "error", "no-frontmatter",
                      "first cell has no --- delimited YAML frontmatter (or it does not parse)")


def check_required_fields(lesson):
    for field in REQUIRED_FIELDS:
        if not lesson.frontmatter.get(field):
            yield Finding(lesson.path, "error", "missing-field", f"missing `{field}`")


def check_description_is_plain_text(lesson):
    # Cards don't render Liquid, and an unquoted `#` is truncated as a YAML comment.
    description = lesson.frontmatter.get("description")
    if isinstance(description, str) and re.search(r"\{\{|\{%|#", description):
        yield Finding(lesson.path, "error", "unsafe-description",
                      "description must be plain text with no Liquid and no `#`")


def check_courses_shape(lesson):
    courses = lesson.frontmatter.get("courses")
    if courses is None:
        return
    well_formed = isinstance(courses, dict) and courses and all(
        isinstance(entry, dict) and isinstance(entry.get("week"), int) for entry in courses.values()
    )
    if not well_formed:
        yield Finding(lesson.path, "error", "malformed-courses",
                      f"`courses` must look like {{ csse: {{ week: 6 }} }}, got {courses!r}")


def check_assignment_keys(lesson):
    for key in lesson.frontmatter:
        if str(key).startswith("assignment") and key not in KNOWN_ASSIGNMENT_KEYS:
            yield Finding(lesson.path, "error", "unknown-assignment-key",
                          f"`{key}` is not read by the assignment sync; "
                          f"expected one of {', '.join(sorted(KNOWN_ASSIGNMENT_KEYS))}")


def check_assignment_complete(lesson):
    if not lesson.frontmatter.get("assignment"):
        return
    if not lesson.frontmatter.get("assignment_creator_uids"):
        yield Finding(lesson.path, "error", "assignment-without-creators",
                      "`assignment: true` without `assignment_creator_uids` syncs under the test user `toby`")
    if not lesson.frontmatter.get("assignment_submission_type"):
        yield Finding(lesson.path, "warning", "assignment-without-submission-type",
                      "no `assignment_submission_type`; the Submit panel defaults to `file`")


def check_frontmatter_cell_is_raw(lesson):
    if lesson.frontmatter_cell_type not in (None, "raw"):
        yield Finding(lesson.path, "warning", "frontmatter-not-raw",
                      f"frontmatter is in a {lesson.frontmatter_cell_type} cell; "
                      "Run All in Jupyter or VS Code tries to execute it")


def check_lesson_type(lesson):
    if not lesson.frontmatter.get("lesson_type"):
        yield Finding(lesson.path, "warning", "missing-lesson-type", "missing `lesson_type`")


def check_homework_samples(lesson):
    """Frontmatter samples students copy must be wrapped in --- and must not be runnable code."""
    for index, (cell_type, text) in enumerate(lesson.body_cells, start=1):
        for start, end, lines in _sample_blocks(text):
            where = f"sample frontmatter in cell {index}" if lesson.path.suffix == ".ipynb" else "sample frontmatter"
            before = _nearest_line(lines, start - 1, step=-1)
            after = _nearest_line(lines, end + 1, step=1)
            if before != "---" or after != "---":
                yield Finding(lesson.path, "error", "sample-without-delimiters",
                              f"{where} has no --- lines around it, so Jekyll ignores the student's copy")
            if cell_type == "code":
                yield Finding(lesson.path, "error", "sample-in-code-cell",
                              f"{where} is a code cell, so the page shows YAML as runnable code")


def _sample_blocks(text):
    """Yield (first_line, last_line, lines) for each run of YAML-like lines that contains a permalink."""
    if not SAMPLE_MARKER.search(text):
        return
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if not SAMPLE_KEY_LINE.match(lines[index]):
            index += 1
            continue
        start = index
        while index < len(lines) and SAMPLE_KEY_LINE.match(lines[index]):
            index += 1
        block = lines[start:index]
        if any(SAMPLE_MARKER.match(line) for line in block) and any(
            re.match(r"^\s*(layout|title)\s*:", line) for line in block
        ):
            yield start, index - 1, lines


def _nearest_line(lines, index, step):
    """Nearest non-blank line as it renders: `\\---  \\` (escaped, Markdown line break) and `<pre>---` are `---`."""
    while 0 <= index < len(lines):
        rendered = re.sub(r"<[^>]+>", "", lines[index]).strip().removesuffix("\\").strip().removeprefix("\\")
        if rendered:
            return rendered
        index += step
    return None


LESSON_RULES = (
    check_required_fields,
    check_description_is_plain_text,
    check_courses_shape,
    check_assignment_keys,
    check_assignment_complete,
    check_frontmatter_cell_is_raw,
    check_lesson_type,
    check_homework_samples,
)


def check_lesson(lesson):
    missing = list(check_frontmatter_present(lesson))
    if missing:
        return missing
    return [finding for rule in LESSON_RULES for finding in rule(lesson)]


def check_duplicate_permalinks(lessons):
    owners = defaultdict(list)
    for lesson in lessons:
        permalink = (lesson.frontmatter or {}).get("permalink")
        if permalink:
            owners[str(permalink).strip().rstrip("/") or "/"].append(lesson.path)
    for permalink, paths in owners.items():
        if len(paths) > 1:
            for path in paths:
                others = ", ".join(str(other.name) for other in paths if other != path)
                yield Finding(path, "error", "duplicate-permalink", f"`{permalink}` is also used by {others}")


# ---- Finding the files

def lesson_files(root: Path, paths):
    """Tracked or trackable lesson sources under `paths`; generated and ignored files are skipped."""
    for path in paths:
        if not (root / path).exists():
            raise FileNotFoundError(f"lesson path does not exist: {path}")
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *paths],
        cwd=root, check=True, capture_output=True, text=True,
    ).stdout.split("\0")
    for name in sorted(set(filter(None, listed))):
        path = root / name
        if path.suffix in LESSON_EXTENSIONS and ".ipynb_checkpoints" not in path.parts and path.is_file():
            if path.suffix == ".md" and parse_frontmatter(path.read_text(encoding="utf-8")) is None:
                continue  # READMEs and docs without frontmatter are not lessons
            yield path


def run(root: Path, paths):
    lessons = [Lesson.load(path) for path in lesson_files(root, paths)]
    findings = [finding for lesson in lessons for finding in check_lesson(lesson)]
    findings += check_duplicate_permalinks(lessons)
    return lessons, sorted(findings, key=lambda f: (str(f.path), f.severity, f.code))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", default=list(DEFAULT_PATHS))
    parser.add_argument("--errors-only", action="store_true", help="hide warnings")
    args = parser.parse_args(argv)

    lessons, findings = run(REPOSITORY_ROOT, args.paths)
    shown = [f for f in findings if f.severity == "error"] if args.errors_only else findings
    for finding in shown:
        print(finding.describe(REPOSITORY_ROOT))

    errors = sum(f.severity == "error" for f in findings)
    warnings = len(findings) - errors
    print(f"\nChecked {len(lessons)} lessons: {errors} errors, {warnings} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
