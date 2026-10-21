#!/usr/bin/env python3
"""
Delete a notebook lesson and everything generated from it, without leaving dead links behind.

Usage:
    python3 scripts/lesson_delete.py PATH                 # dry run: show what would be removed
    python3 scripts/lesson_delete.py PATH --confirm       # delete
    python3 scripts/lesson_delete.py PATH --confirm --force   # delete even though other files link to it
    make lesson-delete FILE=PATH [CONFIRM=1] [FORCE=1]

Removes the source notebook, its generated post, and any multi-course split copies
and their posts. Files that still link to the lesson's permalink (nav includes,
curriculum mappings, other lessons) block the delete until fixed or FORCE is given;
they are never edited automatically. The Spring assignment is not deleted, because
scripts/sync_assignments.py has no delete; its contentUrl is printed so it can be
retired by hand.
"""

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import convert_notebooks
    from sync_assignments import content_url_for, read_frontmatter
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent))
    import convert_notebooks
    from sync_assignments import content_url_for, read_frontmatter

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
# Generated output is never a reference worth keeping the lesson for.
REFERENCE_EXCLUDES = ("_posts", "_site", ".jekyll-cache", ".notebook-conversion-cache")


class LessonDeleteError(Exception):
    pass


@dataclass
class DeletePlan:
    source: Path
    permalink: str | None
    files: list = field(default_factory=list)       # existing files to remove, source first
    references: list = field(default_factory=list)  # "path:line: text" lines that link to the lesson
    assignment_url: str | None = None


def plan_delete(root: Path, source: Path) -> DeletePlan:
    source = _validated_source(root, source)
    frontmatter = read_frontmatter(source) or {}
    permalink = str(frontmatter["permalink"]).strip() if frontmatter.get("permalink") else None

    plan = DeletePlan(source=source, permalink=permalink)
    plan.files = [source] + [path for path in _generated_files(root, source, frontmatter) if path.exists()]
    plan.references = _references(root, permalink, exclude=source)
    if frontmatter.get("assignment"):
        plan.assignment_url = content_url_for(root, source, frontmatter)
    return plan


def _validated_source(root: Path, source: Path) -> Path:
    source = (root / source).resolve() if not source.is_absolute() else source.resolve()
    if not source.is_file():
        raise LessonDeleteError(f"lesson not found: {source}")
    if source.suffix != ".ipynb":
        raise LessonDeleteError(f"only notebook lessons (.ipynb) are supported, got {source.name}")
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(source)], cwd=root,
                             capture_output=True).returncode == 0
    if not tracked:
        raise LessonDeleteError(f"{source.relative_to(root)} is not tracked by git; "
                                "generated or split copies are removed by deleting their source")
    return source


def _generated_files(root: Path, source: Path, frontmatter: dict):
    """The converted post, plus the multi-course split copies scripts/split_multi_course_files.py
    makes of both the notebook and the post (`<stem>_<course>.*`, `<post>_content.md`)."""
    post = _converter_output(root, source)
    files = [post]
    courses = frontmatter.get("courses")
    if isinstance(courses, dict) and len(courses) > 1:
        for course in courses:
            notebook_copy = source.with_name(f"{source.stem}_{course}{source.suffix}")
            files += [notebook_copy, _converter_output(root, notebook_copy),
                      post.with_name(f"{post.stem}_{course}{post.suffix}")]
        files.append(post.with_name(f"{post.stem}_content{post.suffix}"))
    return files


def _converter_output(root: Path, notebook: Path) -> Path:
    # The converter resolves paths against a module-level root; point it at `root` only for this call.
    saved_root = convert_notebooks.repository_root
    convert_notebooks.repository_root = root
    try:
        return Path(convert_notebooks.get_relative_output_path(notebook))
    finally:
        convert_notebooks.repository_root = saved_root


def _references(root: Path, permalink: str | None, exclude: Path):
    if not permalink:
        return []
    needle = permalink.rstrip("/") or "/"
    excluded = [f":(exclude){path}" for path in REFERENCE_EXCLUDES]
    found = subprocess.run(
        ["git", "grep", "-n", "-I", "-F", "-e", needle, "--", ".", *excluded],
        cwd=root, capture_output=True, text=True,
    )
    if found.returncode not in (0, 1):  # 1 means no match
        raise LessonDeleteError(f"git grep failed: {found.stderr.strip()}")
    own = str(exclude.relative_to(root))
    return [line for line in found.stdout.splitlines()
            if not line.startswith(f"{own}:") and _links_exactly(line, needle)]


def _links_exactly(line: str, needle: str) -> bool:
    """Match whole URLs only: `/sprint2/objectives` is not `/csse/sprint2/objectives`
    or `/sprint2/objectives-hw`, but may follow `{{ site.baseurl }}` or a host."""
    start = line.find(needle)
    while start != -1:
        token_before = re.split(r"[\s\"'(=<>\[,]", line[:start])[-1]
        starts_url = token_before == "" or token_before.endswith("}}") or re.fullmatch(r"(https?:)?//[^/]+", token_before)
        following = line[start + len(needle):start + len(needle) + 1]
        ends_url = following in ("", "/", '"', "'", ")", " ", "#", "?", "\\", "<", ",", "]", "}")
        if starts_url and ends_url:
            return True
        start = line.find(needle, start + 1)
    return False


def apply_delete(plan: DeletePlan, force: bool):
    if plan.references and not force:
        raise LessonDeleteError(f"{len(plan.references)} reference(s) still link to {plan.permalink}; "
                                "fix them first or pass --force")
    for path in plan.files:
        path.unlink()


def describe(plan: DeletePlan, root: Path) -> str:
    lines = [f"Lesson: {plan.source.relative_to(root)}  (permalink: {plan.permalink or 'none'})", "Files:"]
    lines += [f"  - {path.relative_to(root)}" for path in plan.files]
    if plan.references:
        lines.append("Still linked from (fix these, they are not edited automatically):")
        lines += [f"  ! {reference}" for reference in plan.references]
    if plan.assignment_url:
        lines.append(f"Spring assignment to retire by hand: contentUrl={plan.assignment_url}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=Path)
    parser.add_argument("--confirm", action="store_true", help="delete; without it this is a dry run")
    parser.add_argument("--force", action="store_true", help="delete even if other files link to the lesson")
    args = parser.parse_args(argv)

    try:
        plan = plan_delete(REPOSITORY_ROOT, args.path)
        print(describe(plan, REPOSITORY_ROOT))
        if not args.confirm:
            print("\nDry run: nothing deleted. Re-run with --confirm (make: CONFIRM=1) to delete.")
            return 1 if plan.references and not args.force else 0
        apply_delete(plan, force=args.force)
    except LessonDeleteError as error:
        print(f"\nlesson-delete: {error}", file=sys.stderr)
        return 1
    print(f"\nDeleted {len(plan.files)} file(s). Commit the source removal; rebuild with make.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
