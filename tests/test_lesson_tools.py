"""Behavior tests for scripts/lesson_check.py and scripts/lesson_delete.py."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import lesson_check, lesson_delete

GOOD_FRONTMATTER = """---
layout: post
title: Arrays
description: Learn arrays
permalink: /js/arrays/2027
lesson_type: lesson
courses: { csse: { week: 6 } }
assignment: true
assignment_submission_type: code
assignment_creator_uids:
    - "student1"
---
"""


def notebook(frontmatter, *cells, frontmatter_cell="raw"):
    return json.dumps({
        "cells": [{"cell_type": frontmatter_cell, "metadata": {}, "source": frontmatter}]
        + [{"cell_type": cell_type, "metadata": {}, "source": source} for cell_type, source in cells],
        "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
    })


class RepositoryTestCase(unittest.TestCase):
    """A throwaway git repository, because both tools only act on tracked files."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)

    def write(self, relative, text, track=True):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if track:
            subprocess.run(["git", "add", relative], cwd=self.root, check=True)
        return path

    def codes(self, relative="_projects/lessons/js/notebooks/lesson.ipynb"):
        _, findings = lesson_check.run(self.root, [str(Path(relative).parent)])
        return [f.code for f in findings if f.path == self.root / relative]


class LessonCheckTests(RepositoryTestCase):
    LESSON = "_projects/lessons/js/notebooks/lesson.ipynb"

    def test_complete_lesson_has_no_findings(self):
        self.write(self.LESSON, notebook(GOOD_FRONTMATTER))
        self.assertEqual(self.codes(), [])

    def test_misspelled_creator_key_is_an_error(self):
        # The #29 bug: the sync ignores the key and assigns the lesson to the test user.
        self.write(self.LESSON, notebook(GOOD_FRONTMATTER.replace("assignment_creator_uids", "assignmentcreator_uids")))
        self.assertIn("unknown-assignment-key", self.codes())
        self.assertIn("assignment-without-creators", self.codes())

    def test_string_courses_is_an_error(self):
        self.write(self.LESSON, notebook(GOOD_FRONTMATTER.replace("courses: { csse: { week: 6 } }", "courses: csse")))
        self.assertIn("malformed-courses", self.codes())

    def test_missing_permalink_is_an_error(self):
        self.write(self.LESSON, notebook(GOOD_FRONTMATTER.replace("permalink: /js/arrays/2027\n", "")))
        self.assertIn("missing-field", self.codes())

    def test_hash_in_description_is_an_error(self):
        self.write(self.LESSON, notebook(GOOD_FRONTMATTER.replace("Learn arrays", '"AP FRQ #1 - Arrays"')))
        self.assertIn("unsafe-description", self.codes())

    def test_homework_sample_without_delimiters_in_code_cell_is_two_errors(self):
        # The #30/#31 bug: no --- and a JavaScript code cell.
        sample = "layout: post\ntitle: Arrays HW\npermalink: /js/arrays/hw\nauthor: you"
        self.write(self.LESSON, notebook(GOOD_FRONTMATTER, ("code", sample)))
        self.assertEqual(sorted(self.codes()), ["sample-in-code-cell", "sample-without-delimiters"])

    def test_fenced_homework_sample_with_delimiters_passes(self):
        sample = "```yaml\n---\nlayout: post\ntitle: Arrays HW\npermalink: /js/arrays/hw\n---\n```"
        self.write(self.LESSON, notebook(GOOD_FRONTMATTER, ("markdown", sample)))
        self.assertEqual(self.codes(), [])

    def test_escaped_and_html_delimiters_count_as_rendered_dashes(self):
        escaped = "\\--- \\\nlayout: post \\\ntitle: HW \\\npermalink: /csa/hw \\\n\\---"
        html = "<pre>---\nlayout: post\ntitle: HW\npermalink: /py/hw\n---</pre>"
        self.write(self.LESSON, notebook(GOOD_FRONTMATTER, ("markdown", escaped), ("markdown", html)))
        self.assertEqual(self.codes(), [])

    def test_frontmatter_in_code_cell_is_only_a_warning(self):
        self.write(self.LESSON, notebook(GOOD_FRONTMATTER, frontmatter_cell="code"))
        _, findings = lesson_check.run(self.root, ["_projects/lessons"])
        self.assertEqual([(f.severity, f.code) for f in findings], [("warning", "frontmatter-not-raw")])

    def test_duplicate_permalinks_flag_both_lessons(self):
        self.write(self.LESSON, notebook(GOOD_FRONTMATTER))
        self.write("_projects/lessons/js/notebooks/copy.ipynb", notebook(GOOD_FRONTMATTER.replace("2027", "2027/")))
        _, findings = lesson_check.run(self.root, ["_projects/lessons"])
        self.assertEqual(sum(f.code == "duplicate-permalink" for f in findings), 2)

    def test_ignored_generated_copies_are_not_checked(self):
        self.write(".gitignore", "*_csse.ipynb\n")
        self.write("_projects/lessons/js/notebooks/lesson_csse.ipynb", notebook("no frontmatter"), track=False)
        lessons, _ = lesson_check.run(self.root, ["_projects/lessons"])
        self.assertEqual(lessons, [])

    def test_missing_path_fails_fast(self):
        with self.assertRaises(FileNotFoundError):
            lesson_check.run(self.root, ["_projects/does-not-exist"])


class LessonDeleteTests(RepositoryTestCase):
    SOURCE = "_projects/lessons/js/notebooks/2026-01-01-arrays.ipynb"
    POST = "_posts/projects/js/2026-01-01-arrays_IPYNB_2_.md"

    def setUp(self):
        super().setUp()
        self.write(self.SOURCE, notebook(GOOD_FRONTMATTER))
        self.write(self.POST, "generated", track=False)

    def test_dry_run_plans_source_and_post_without_deleting(self):
        plan = lesson_delete.plan_delete(self.root, Path(self.SOURCE))
        self.assertEqual(plan.files, [self.root / self.SOURCE, self.root / self.POST])
        self.assertEqual(plan.assignment_url, "js/arrays/2027")
        self.assertTrue((self.root / self.SOURCE).exists())

    def test_confirmed_delete_removes_source_and_post(self):
        lesson_delete.apply_delete(lesson_delete.plan_delete(self.root, Path(self.SOURCE)), force=False)
        self.assertFalse((self.root / self.SOURCE).exists())
        self.assertFalse((self.root / self.POST).exists())

    def test_links_from_other_files_block_the_delete(self):
        self.write("_includes/nav.html", '<a href="{{ site.baseurl }}/js/arrays/2027">Arrays</a>\n')
        plan = lesson_delete.plan_delete(self.root, Path(self.SOURCE))
        self.assertEqual(len(plan.references), 1)
        with self.assertRaises(lesson_delete.LessonDeleteError):
            lesson_delete.apply_delete(plan, force=False)
        self.assertTrue((self.root / self.SOURCE).exists())

    def test_force_deletes_despite_links(self):
        self.write("_includes/nav.html", '<a href="/js/arrays/2027">Arrays</a>\n')
        lesson_delete.apply_delete(lesson_delete.plan_delete(self.root, Path(self.SOURCE)), force=True)
        self.assertFalse((self.root / self.SOURCE).exists())

    def test_only_whole_urls_count_as_links(self):
        self.write("other.md", "/csse/js/arrays/2027 and /js/arrays/2027-hw are different pages\n")
        self.assertEqual(lesson_delete.plan_delete(self.root, Path(self.SOURCE)).references, [])

    def test_multi_course_split_copies_are_removed(self):
        multi = GOOD_FRONTMATTER.replace("{ csse: { week: 6 } }", "{ csse: { week: 6 }, csp: { week: 6 } }")
        self.write(self.SOURCE, notebook(multi))
        split = [
            "_projects/lessons/js/notebooks/2026-01-01-arrays_csse.ipynb",
            "_posts/projects/js/2026-01-01-arrays_IPYNB_2__csp.md",
            "_posts/projects/js/2026-01-01-arrays_IPYNB_2__content.md",
        ]
        for path in split:
            self.write(path, "generated", track=False)
        planned = lesson_delete.plan_delete(self.root, Path(self.SOURCE)).files
        for path in split:
            self.assertIn(self.root / path, planned)

    def test_untracked_or_non_notebook_sources_are_refused(self):
        self.write("_projects/lessons/js/notebooks/untracked.ipynb", notebook(GOOD_FRONTMATTER), track=False)
        self.write("_projects/lessons/js/navigation/page.md", GOOD_FRONTMATTER)
        for path in ("_projects/lessons/js/notebooks/untracked.ipynb", "_projects/lessons/js/navigation/page.md"):
            with self.assertRaises(lesson_delete.LessonDeleteError):
                lesson_delete.plan_delete(self.root, Path(path))


if __name__ == "__main__":
    unittest.main()
