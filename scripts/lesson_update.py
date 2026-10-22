#!/usr/bin/env python3
"""
Change a notebook lesson's frontmatter without breaking it or its links.

Usage:
    python3 scripts/lesson_update.py FILE --set "key=value" [--set ...] [--unset key ...]
    make lesson-update FILE=<notebook> SET="title=Arrays;courses={ csse: { week: 6 } }" [UNSET="key ..."]

Values are YAML. Changing `permalink` adds the old URL to `redirect_from` (served by
jekyll-redirect-from), so existing links and bookmarks keep working; pass
--no-redirect to skip that. The update is refused if it would add a lesson-check
error the lesson did not already have.
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import lesson_check
    from lesson_delete import find_references
    from lesson_frontmatter import FrontmatterEditError, NotebookFrontmatter
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent))
    import lesson_check
    from lesson_delete import find_references
    from lesson_frontmatter import FrontmatterEditError, NotebookFrontmatter

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def parse_assignment(text: str):
    key, separator, value = text.partition("=")
    if not separator or not key.strip():
        raise FrontmatterEditError(f"expected key=value, got {text!r}")
    return key.strip(), value.strip()


def update_lesson(path: Path, sets, unsets, redirect=True):
    """Apply the edits and save. Returns (old_permalink, new_permalink) when the permalink changed."""
    before_errors = _error_codes(path)
    frontmatter = NotebookFrontmatter(path)
    old_permalink = frontmatter.data().get("permalink")

    for key in unsets:
        frontmatter.unset(key)
    for key, value in sets:
        frontmatter.set(key, value)

    new_permalink = frontmatter.data().get("permalink")
    moved = redirect and old_permalink and new_permalink and str(old_permalink) != str(new_permalink)
    if moved:
        _add_redirect(frontmatter, str(old_permalink), str(new_permalink))

    original = path.read_text(encoding="utf-8")
    frontmatter.save()
    introduced = _error_codes(path) - before_errors
    if introduced:
        path.write_text(original, encoding="utf-8")
        details = "; ".join(f"[{code}] {message}" for code, message in sorted(introduced))
        raise FrontmatterEditError(f"update refused, it would add lesson-check errors: {details}")
    return (str(old_permalink), str(new_permalink)) if moved else None


def _add_redirect(frontmatter, old_permalink, new_permalink):
    existing = frontmatter.data().get("redirect_from") or []
    existing = [existing] if isinstance(existing, str) else list(existing)
    # Moving back to an earlier URL must drop it from redirect_from, or the page redirects to itself.
    sources = [url for url in existing if not _same_url(url, new_permalink)] + [old_permalink]
    frontmatter.set("redirect_from", json.dumps(list(dict.fromkeys(sources))))


def _same_url(first, second):
    return str(first).rstrip("/") == str(second).rstrip("/")


def _error_codes(path):
    return {(f.code, f.message) for f in lesson_check.check_lesson(lesson_check.Lesson.load(path))
            if f.severity == "error"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=Path)
    parser.add_argument("--set", dest="sets", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--sets", dest="set_list", default="", metavar="'K=V;K=V'",
                        help="several --set values separated by `;` (what make SET= passes)")
    parser.add_argument("--unset", dest="unsets", action="append", default=[], metavar="KEY")
    parser.add_argument("--no-redirect", action="store_true", help="do not add the old permalink to redirect_from")
    args = parser.parse_args(argv)

    path = (REPOSITORY_ROOT / args.path).resolve()
    args.sets += [part for part in args.set_list.split(";") if part.strip()]
    try:
        if not args.sets and not args.unsets:
            raise FrontmatterEditError("nothing to change; pass --set key=value or --unset key")
        moved = update_lesson(path, [parse_assignment(s) for s in args.sets], args.unsets,
                              redirect=not args.no_redirect)
    except (FrontmatterEditError, FileNotFoundError, ValueError) as error:
        print(f"lesson-update: {error}", file=sys.stderr)
        return 1

    print(f"Updated {path.relative_to(REPOSITORY_ROOT)}")
    if moved:
        old, new = moved
        print(f"Permalink {old} -> {new}; {old} now redirects there.")
        for reference in find_references(REPOSITORY_ROOT, old, exclude=path):
            print(f"  still links to the old URL (works via redirect, update when convenient): {reference}")
    print("Rebuild with: make convert-single NOTEBOOK_FILE=" + str(path.relative_to(REPOSITORY_ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
