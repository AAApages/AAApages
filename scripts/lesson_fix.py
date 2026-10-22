#!/usr/bin/env python3
"""
Apply the lesson-check fixes that have exactly one right answer.

Usage:
    python3 scripts/lesson_fix.py [PATH ...]            # dry run: list fixes
    python3 scripts/lesson_fix.py [PATH ...] --confirm  # apply them
    make lesson-fix LESSONS="<paths>" [CONFIRM=1]

Fixes:
  - misspelled assignment keys with one known meaning (assignmentcreator_uids)
  - frontmatter kept in a code cell is moved to a raw cell, so Run All can't execute it

Everything else lesson-check reports needs a person's decision (a week, a
description, a creator's GitHub login) and is left alone.
"""

import argparse
import sys
from pathlib import Path

try:
    import lesson_check
    from lesson_frontmatter import FrontmatterEditError, NotebookFrontmatter
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent))
    import lesson_check
    from lesson_frontmatter import FrontmatterEditError, NotebookFrontmatter

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
# Only spellings seen in this repo whose intended key is certain. `assignment_submission_uids`
# is not here: it could mean either creators or submission type.
KEY_CORRECTIONS = {"assignmentcreator_uids": "assignment_creator_uids"}


def planned_fixes(path: Path):
    """Human-readable descriptions of the fixes `apply_fixes` would make to one notebook."""
    if path.suffix != ".ipynb":
        return []
    frontmatter = NotebookFrontmatter(path)
    fixes = [f"rename `{wrong}` to `{right}`" for wrong, right in KEY_CORRECTIONS.items()
             if wrong in frontmatter.data()]
    if frontmatter.first_cell.get("cell_type") == "code":
        fixes.append("move frontmatter from a code cell to a raw cell")
    return fixes


def apply_fixes(path: Path):
    frontmatter = NotebookFrontmatter(path)
    for wrong, right in KEY_CORRECTIONS.items():
        if wrong in frontmatter.data():
            frontmatter.rename(wrong, right)
    cell = frontmatter.first_cell
    if cell.get("cell_type") == "code":
        cell["cell_type"] = "raw"
        cell.pop("outputs", None)
        cell.pop("execution_count", None)
        # A YAML/JS languageId would make VS Code keep treating it as code.
        cell.get("metadata", {}).pop("vscode", None)
    frontmatter.save()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", default=list(lesson_check.DEFAULT_PATHS))
    parser.add_argument("--confirm", action="store_true", help="apply the fixes; without it this is a dry run")
    args = parser.parse_args(argv)

    total = 0
    for path in lesson_check.lesson_files(REPOSITORY_ROOT, args.paths):
        try:
            fixes = planned_fixes(path)
            if fixes and args.confirm:
                apply_fixes(path)
        except FrontmatterEditError as error:
            print(f"skipped {path.relative_to(REPOSITORY_ROOT)}: {error}")
            continue
        for fix in fixes:
            print(f"{path.relative_to(REPOSITORY_ROOT)}: {fix}")
        total += len(fixes)

    if args.confirm:
        print(f"\nApplied {total} fix(es). Rebuild with make, then run make lesson-check.")
    else:
        print(f"\nDry run: {total} fix(es) available. Re-run with --confirm (make: CONFIRM=1) to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
