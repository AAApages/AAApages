"""Behavior tests for scripts/lesson_check.py and scripts/lesson_delete.py."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import lesson_check, lesson_delete, lesson_fix, lesson_new, lesson_update
# Use the classes the scripts raise: they import their siblings as top-level modules.
FrontmatterEditError = lesson_update.FrontmatterEditError
NotebookFrontmatter = lesson_update.NotebookFrontmatter

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

    def test_markdown_in_notebooks_folder_is_not_a_lesson(self):
        # Jekyll excludes _notebooks and the converter only reads .ipynb, so this never publishes.
        self.write("_notebooks/CSP/page.md", "---\ntitle: Unpublished\n---\n")
        lessons, _ = lesson_check.run(self.root, ["_notebooks"])
        self.assertEqual(lessons, [])

    def test_missing_path_fails_fast(self):
        with self.assertRaises(FileNotFoundError):
            lesson_check.run(self.root, ["_projects/does-not-exist"])


class LessonCheckChangedSinceTests(RepositoryTestCase):
    """The PR check: only lessons the branch touched can fail it."""
    OLD = "_projects/lessons/js/notebooks/old.ipynb"
    NEW = "_projects/lessons/js/notebooks/new.ipynb"

    def setUp(self):
        super().setUp()
        self.git("checkout", "-q", "-b", "main")
        self.write(self.OLD, notebook(GOOD_FRONTMATTER.replace("description: Learn arrays\n", "")))
        self.git("commit", "-q", "-m", "base with an existing error")
        self.git("checkout", "-q", "-b", "feature")

    def git(self, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=self.root, check=True)

    def findings(self):
        _, findings = lesson_check.run(self.root, ["_projects/lessons"], base_ref="main")
        return [(f.path.name, f.code) for f in findings]

    def test_errors_already_on_main_do_not_fail_an_unrelated_branch(self):
        self.write(self.NEW, notebook(GOOD_FRONTMATTER.replace("2027", "2028")))
        self.git("commit", "-q", "-m", "good lesson")
        self.assertEqual(self.findings(), [])

    def test_new_lesson_errors_are_reported_committed_or_not(self):
        self.write(self.NEW, notebook(GOOD_FRONTMATTER.replace("2027", "2028").replace(
            "courses: { csse: { week: 6 } }", "courses: csse")), track=False)
        self.assertEqual(self.findings(), [("new.ipynb", "malformed-courses")])

    def test_editing_an_old_lesson_requires_fixing_it(self):
        self.write(self.OLD, notebook(GOOD_FRONTMATTER.replace("description: Learn arrays\n", "").replace("Arrays", "Lists")))
        self.assertEqual(self.findings(), [("old.ipynb", "missing-field")])

    def test_new_permalink_clashing_with_an_unchanged_lesson_is_reported_on_the_new_one(self):
        self.write(self.NEW, notebook(GOOD_FRONTMATTER))
        self.assertEqual(self.findings(), [("new.ipynb", "duplicate-permalink")])

    def test_unknown_base_ref_fails_fast(self):
        with self.assertRaisesRegex(RuntimeError, "is `origin/nope` fetched"):
            lesson_check.run(self.root, ["_projects/lessons"], base_ref="origin/nope")


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


def first_cell(path):
    return json.loads(Path(path).read_text())["cells"][0]


def frontmatter_text(path):
    return "".join(first_cell(path)["source"])


class LessonUpdateTests(RepositoryTestCase):
    LESSON = "_projects/lessons/js/notebooks/lesson.ipynb"

    def setUp(self):
        super().setUp()
        self.path = self.write(self.LESSON, notebook(GOOD_FRONTMATTER))

    def test_set_changes_one_line_and_keeps_other_formatting(self):
        lesson_update.update_lesson(self.path, [("courses", "{ csse: { week: 7 } }")], [])
        text = frontmatter_text(self.path)
        self.assertIn("courses: { csse: { week: 7 } }\n", text)
        self.assertIn('    - "student1"\n', text)  # untouched block list keeps its form

    def test_edit_keeps_whether_the_cell_ended_with_a_newline(self):
        self.write(self.LESSON, notebook(GOOD_FRONTMATTER.rstrip("\n")))
        lesson_update.update_lesson(self.path, [("title", "Lists")], [])
        self.assertTrue(frontmatter_text(self.path).endswith("---"))

    def test_edit_keeps_the_files_json_indent(self):
        self.path.write_text(json.dumps(json.loads(self.path.read_text()), indent=2) + "\n")
        lesson_update.update_lesson(self.path, [("title", "Lists")], [])
        self.assertTrue(self.path.read_text().startswith('{\n  "cells"'))

    def test_edit_keeps_a_cell_indented_differently_from_the_file(self):
        # Hand-edited notebooks: the frontmatter cell is indented one space deeper than the file.
        parsed = json.loads(self.path.read_text())
        parsed["cells"][0]["source"] = parsed["cells"][0]["source"].splitlines(keepends=True)
        text = json.dumps(parsed, indent=1, ensure_ascii=False) + "\n"
        frontmatter_start = text.index('"source": [') + len('"source": [')
        frontmatter_end = text.index("]", frontmatter_start)
        irregular = (text[:frontmatter_start]
                     + text[frontmatter_start:frontmatter_end].replace("\n    ", "\n     ")
                     + text[frontmatter_end:])
        self.path.write_text(irregular)
        lesson_update.update_lesson(self.path, [("title", "Lists")], [])
        before, after = irregular.splitlines(), self.path.read_text().splitlines()
        self.assertEqual(len(before), len(after))
        changed = [(old, new) for old, new in zip(before, after) if old != new]
        self.assertEqual(changed, [('     "title: Arrays\\n",', '     "title: Lists\\n",')])

    def test_edit_keeps_a_compact_notebook_with_string_sources_compact(self):
        compact = '{"cells": [\n  ' + json.dumps({"cell_type": "raw", "metadata": {}, "source": GOOD_FRONTMATTER}) + '\n], "metadata": {}}\n'
        self.path.write_text(compact)
        lesson_update.update_lesson(self.path, [("title", "Lists")], [])
        self.assertEqual(self.path.read_text(), compact.replace("title: Arrays", "title: Lists"))

    def test_permalink_change_redirects_from_the_old_url(self):
        moved = lesson_update.update_lesson(self.path, [("permalink", "/js/lists/2027")], [])
        self.assertEqual(moved, ("/js/arrays/2027", "/js/lists/2027"))
        data = NotebookFrontmatter(self.path).data()
        self.assertEqual((data["permalink"], data["redirect_from"]), ("/js/lists/2027", ["/js/arrays/2027"]))

    def test_moving_back_never_redirects_a_page_to_itself(self):
        lesson_update.update_lesson(self.path, [("permalink", "/js/lists/2027")], [])
        lesson_update.update_lesson(self.path, [("permalink", "/js/arrays/2027")], [])
        self.assertEqual(NotebookFrontmatter(self.path).data()["redirect_from"], ["/js/lists/2027"])

    def test_no_redirect_option_leaves_redirect_from_out(self):
        lesson_update.update_lesson(self.path, [("permalink", "/js/lists/2027")], [], redirect=False)
        self.assertNotIn("redirect_from", NotebookFrontmatter(self.path).data())

    def test_update_that_adds_an_error_is_refused_and_file_is_unchanged(self):
        before = self.path.read_text()
        with self.assertRaises(FrontmatterEditError):
            lesson_update.update_lesson(self.path, [], ["permalink"])
        self.assertEqual(self.path.read_text(), before)

    def test_unquoted_hash_is_refused_instead_of_truncated(self):
        with self.assertRaises(FrontmatterEditError):
            lesson_update.update_lesson(self.path, [("description", "AP FRQ #1 practice")], [])
        lesson_update.update_lesson(self.path, [("title", '"Arrays #1"')], [])
        self.assertEqual(NotebookFrontmatter(self.path).data()["title"], "Arrays #1")


class LessonFixTests(RepositoryTestCase):
    LESSON = "_projects/lessons/js/notebooks/lesson.ipynb"

    def test_dry_run_lists_fixes_without_changing_the_file(self):
        path = self.write(self.LESSON, notebook(GOOD_FRONTMATTER.replace("assignment_creator_uids", "assignmentcreator_uids"),
                                                frontmatter_cell="code"))
        before = path.read_text()
        self.assertEqual(len(lesson_fix.planned_fixes(path)), 2)
        self.assertEqual(path.read_text(), before)

    def test_fixes_rename_the_key_and_move_frontmatter_to_a_raw_cell(self):
        path = self.write(self.LESSON, notebook(GOOD_FRONTMATTER.replace("assignment_creator_uids", "assignmentcreator_uids"),
                                                frontmatter_cell="code"))
        lesson_fix.apply_fixes(path)
        self.assertEqual(first_cell(path)["cell_type"], "raw")
        self.assertEqual(lesson_check.check_lesson(lesson_check.Lesson.load(path)), [])

    def test_ambiguous_misspelling_is_left_for_a_person(self):
        path = self.write(self.LESSON, notebook(GOOD_FRONTMATTER + "").replace(
            "assignment_creator_uids", "assignment_submission_uids"))
        self.assertEqual(lesson_fix.planned_fixes(path), [])


class LessonNewTests(RepositoryTestCase):
    CONVENTIONS = ("permalink: /js/{slug}/2027\nhomework_permalink: /js/{slug}/hw\nlesson_language: JavaScript\n"
                   "categories: [JavaScript]\nassignment: true\nassignment_submission_type: code\n")

    def setUp(self):
        super().setUp()
        self.write("_projects/lessons/js/lesson-conventions.yml", self.CONVENTIONS)
        (self.root / "_projects/lessons/js/notebooks").mkdir(parents=True)

    def create(self, topic="Object Literals", **options):
        options.setdefault("creators", ["student1"])
        options.setdefault("date", "2026-10-22")
        return lesson_new.create_lesson(self.root, "js", topic, "Learn objects", **options)

    def test_new_lesson_follows_conventions_and_passes_lesson_check(self):
        path = self.create(course="csse", week=6)
        self.assertEqual(path.name, "2026-10-22-object-literals.ipynb")
        data = NotebookFrontmatter(path).data()
        self.assertEqual(data["permalink"], "/js/object-literals/2027")
        self.assertEqual(data["categories"], ["JavaScript", "Object-Literals"])
        self.assertEqual(data["courses"], {"csse": {"week": 6}})
        self.assertIn("courses: { csse: { week: 6 } }\n", frontmatter_text(path))
        self.assertEqual(lesson_check.check_lesson(lesson_check.Lesson.load(path)), [])

    def test_homework_sample_uses_the_homework_permalink_and_delimiters(self):
        notebook_text = self.create().read_text()
        self.assertIn("permalink: /js/object-literals/hw", notebook_text)
        self.assertIn("```yaml\\n---\\n", notebook_text)

    def test_cell_ids_are_stable(self):
        ids = [cell["id"] for cell in json.loads(self.create().read_text())["cells"]]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual(ids[0], lesson_new._cell_id("/js/object-literals/2027", 0))

    def test_refusals(self):
        self.create()
        cases = {
            "duplicate permalink": dict(topic="Object Literals", date="2026-10-23"),
            "no creators for an assignment project": dict(topic="Maps", creators=[]),
            "course without week": dict(topic="Sets", course="csse"),
            "bad date": dict(topic="Sets", date="10/22/2026"),
        }
        for name, options in cases.items():
            with self.subTest(name), self.assertRaises(lesson_new.LessonNewError):
                self.create(**options)

    def test_project_without_conventions_is_refused(self):
        (self.root / "_projects/lessons/py/notebooks").mkdir(parents=True)
        with self.assertRaises(lesson_new.LessonNewError):
            lesson_new.create_lesson(self.root, "py", "Maps", "d", ["a"], date="2026-10-22")


if __name__ == "__main__":
    unittest.main()
