#!/usr/bin/env python3
"""
Create a lesson notebook that follows its project's conventions and passes lesson-check.

Usage:
    python3 scripts/lesson_new.py PROJECT "TOPIC" --description "..." --creators uid1,uid2 \
        [--author "Names"] [--course csse --week 6] [--date YYYY-MM-DD]
    make lesson-new PROJECT=javascript TOPIC="Object Literals" DESCRIPTION="..." CREATORS=uid1,uid2 \
        [AUTHOR="..."] [COURSE=csse WEEK=6] [DATE=YYYY-MM-DD]

Conventions come from _projects/<category>/<PROJECT>/lesson-conventions.yml (permalink
pattern, homework permalink, language, categories, assignment settings). A project
without that file is refused, so conventions are agreed per project before lessons
are generated for it.
"""

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

try:
    import lesson_check
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent))
    import lesson_check

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
CONVENTIONS_FILE = "lesson-conventions.yml"
REQUIRED_CONVENTIONS = ("permalink", "homework_permalink", "lesson_language", "categories")


class LessonNewError(Exception):
    pass


def slug_for(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    if not slug:
        raise LessonNewError(f"topic {topic!r} has no letters or digits")
    return slug


def topic_tag(topic: str) -> str:
    """`Object Literals` -> `Object-Literals`, the lesson_topic/category form the lessons use."""
    return "-".join(word[:1].upper() + word[1:] for word in re.findall(r"[A-Za-z0-9]+", topic))


def find_project(root: Path, project: str) -> Path:
    matches = [path for path in (root / "_projects").glob(f"*/{project}") if (path / "notebooks").is_dir()]
    if len(matches) != 1:
        raise LessonNewError(f"expected one _projects/<category>/{project}/ with a notebooks/ folder, found {len(matches)}")
    return matches[0]


def load_conventions(project_dir: Path) -> dict:
    path = project_dir / CONVENTIONS_FILE
    if not path.is_file():
        raise LessonNewError(f"{project_dir.name} has no {CONVENTIONS_FILE}; agree its conventions and add {path}")
    conventions = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    missing = [key for key in REQUIRED_CONVENTIONS if not conventions.get(key)]
    if missing:
        raise LessonNewError(f"{path} is missing {', '.join(missing)}")
    return conventions


def build_frontmatter(conventions, topic, description, creators, author, course, week):
    slug, tag = slug_for(topic), topic_tag(topic)
    frontmatter = {
        "layout": "post",
        "title": topic,
        "description": description,
        "categories": list(conventions["categories"]) + [tag],
        "lesson_language": conventions["lesson_language"],
        "lesson_topic": tag,
        "lesson_type": "lesson",
        "permalink": conventions["permalink"].format(slug=slug),
    }
    for key in ("lesson_source", "codemirror", "microblog"):
        if key in conventions:
            frontmatter[key] = conventions[key]
    if course:
        frontmatter["courses"] = {course: {"week": week}}
    if conventions.get("assignment"):
        frontmatter["assignment"] = True
        frontmatter["assignment_submission_type"] = conventions.get("assignment_submission_type", "code")
        frontmatter["assignment_creator_uids"] = creators
    if author:
        frontmatter["author"] = author
    return frontmatter


def build_notebook(frontmatter, conventions, topic):
    homework = {
        "layout": "post",
        "codemirror": True,
        "title": f"{topic} HW",
        "categories": [conventions["lesson_language"]],
        "lesson_language": conventions["lesson_language"],
        "lesson_topic": f"{frontmatter['lesson_topic']} HW",
        "lesson_type": "lesson",
        "permalink": conventions["homework_permalink"].format(slug=slug_for(topic)),
        "author": "yourGithubID",
    }
    sections = [
        f"## {topic}\n\nWhat students will be able to do after this lesson.",
        "## Lesson\n\nExplanation and examples.",
        "## Popcorn Hack\n\nA short in-class exercise.",
        "## Homework Hack\n\nSave your homework as a notebook in your portfolio. "
        "Put this frontmatter in a raw cell at the top:\n\n"
        f"```yaml\n---\n{_yaml_block(homework)}---\n```",
    ]
    cells = [("raw", f"---\n{_yaml_block(frontmatter)}---\n")] + [("markdown", text) for text in sections]
    return {
        "cells": [{"cell_type": kind, "id": _cell_id(frontmatter["permalink"], index), "metadata": {}, "source": text}
                  for index, (kind, text) in enumerate(cells)],
        "metadata": {"language_info": {"name": conventions["lesson_language"].lower()}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def _cell_id(permalink, index):
    # nbformat 4.5 requires cell ids; derive them so the same lesson always gets the same ids.
    return hashlib.sha1(f"{permalink}#{index}".encode()).hexdigest()[:8]


def _yaml_block(data):
    """YAML one key per line, with `courses` in the `{ csse: { week: 6 } }` form the lessons use."""
    lines = []
    for key, value in data.items():
        if key == "courses":
            entries = ", ".join(f"{course}: {{ week: {entry['week']} }}" for course, entry in value.items())
            lines.append(f"courses: {{ {entries} }}\n")
        elif isinstance(value, list):
            lines.append(f"{key}: {yaml.safe_dump(value, allow_unicode=True, default_flow_style=True, width=1000).strip()}\n")
        else:
            lines.append(yaml.safe_dump({key: value}, allow_unicode=True, default_flow_style=False, width=1000))
    return "".join(lines)


def create_lesson(root: Path, project, topic, description, creators, author=None, course=None, week=None, date=None):
    if bool(course) != (week is not None):
        raise LessonNewError("give both COURSE and WEEK, or neither")
    project_dir = find_project(root, project)
    conventions = load_conventions(project_dir)
    if conventions.get("assignment") and not creators:
        raise LessonNewError("this project's lessons are assignments; pass the creators' GitHub logins (CREATORS=uid1,uid2)")

    frontmatter = build_frontmatter(conventions, topic, description, creators, author, course, week)
    try:
        date = datetime.date.fromisoformat(date).isoformat() if date else datetime.date.today().isoformat()
    except ValueError as error:
        raise LessonNewError(f"DATE must be YYYY-MM-DD, got {date!r}") from error
    path = project_dir / "notebooks" / f"{date}-{slug_for(topic)}.ipynb"
    if path.exists():
        raise LessonNewError(f"{path.relative_to(root)} already exists")
    taken = {str((lesson.frontmatter or {}).get("permalink", "")).rstrip("/")
             for lesson in map(lesson_check.Lesson.load, lesson_check.lesson_files(root, [str(project_dir.relative_to(root))]))}
    if frontmatter["permalink"].rstrip("/") in taken:
        raise LessonNewError(f"permalink {frontmatter['permalink']} is already used in {project_dir.name}")

    path.write_text(json.dumps(build_notebook(frontmatter, conventions, topic), indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    errors = [f for f in lesson_check.check_lesson(lesson_check.Lesson.load(path)) if f.severity == "error"]
    if errors:
        path.unlink()
        raise LessonNewError("generated lesson failed lesson-check: " + "; ".join(f.message for f in errors))
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project")
    parser.add_argument("topic")
    parser.add_argument("--description", required=True)
    parser.add_argument("--creators", default="", help="comma-separated GitHub logins")
    parser.add_argument("--author")
    parser.add_argument("--course")
    parser.add_argument("--week", type=int)
    parser.add_argument("--date", help="YYYY-MM-DD filename date; default today")
    args = parser.parse_args(argv)

    creators = [uid.strip() for uid in args.creators.split(",") if uid.strip()]
    try:
        path = create_lesson(REPOSITORY_ROOT, args.project, args.topic, args.description, creators,
                             args.author, args.course, args.week, args.date)
    except LessonNewError as error:
        print(f"lesson-new: {error}", file=sys.stderr)
        return 1
    relative = path.relative_to(REPOSITORY_ROOT)
    print(f"Created {relative}\nPreview with: make convert-single NOTEBOOK_FILE={relative}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
