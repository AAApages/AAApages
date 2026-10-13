import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../assets/js/submissions/course-feedback.js", import.meta.url), "utf8");
const { renderCourseFeedbackSummary, summarizeCourseFeedback, validateCourseFeedback } = await import(
  `data:text/javascript;charset=utf-8,${encodeURIComponent(source)}`
);

const complete = { teachingQuality: 4, homeworkQuality: 3, pros: ["Clear demos", "Fast feedback"], grow: "More examples" };

test("a complete survey is valid", () => {
  assert.equal(validateCourseFeedback(complete), null);
});

test("a survey missing a rating, a pro, or the grow is rejected with a specific message", () => {
  assert.match(validateCourseFeedback({ ...complete, teachingQuality: null }), /Quality of teaching/);
  assert.match(validateCourseFeedback({ ...complete, homeworkQuality: 6 }), /Quality of homework/);
  assert.match(validateCourseFeedback({ ...complete, pros: ["Only one", "  "] }), /two pros/);
  assert.match(validateCourseFeedback({ ...complete, grow: "" }), /one grow/);
  assert.match(validateCourseFeedback(null), /course feedback/);
});

test("teachers see averages and a 1-5 distribution per question", () => {
  const summary = summarizeCourseFeedback([
    { submitterName: "Ana", content: { courseFeedback: complete } },
    { submitterName: "Ben", content: { courseFeedback: { ...complete, teachingQuality: 5, homeworkQuality: 2 } } },
  ]);
  assert.equal(summary.responses, 2);
  assert.deepEqual(summary.ratings.map((r) => r.average), [4.5, 2.5]);
  assert.deepEqual(summary.ratings[0].distribution, [0, 0, 0, 1, 1]);
});

test("pros and grows are attributed to the student who wrote them", () => {
  const summary = summarizeCourseFeedback([
    { submitterName: "Ana", assignmentName: "Pilot", content: { courseFeedback: complete } },
  ]);
  assert.deepEqual(summary.pros.map((p) => p.text), ["Clear demos", "Fast feedback"]);
  assert.deepEqual(summary.grows, [{ student: "Ana", assignment: "Pilot", text: "More examples" }]);
});

test("submissions from before the survey existed are ignored, not counted as zeros", () => {
  const summary = summarizeCourseFeedback([
    { submitterName: "Old", content: { type: "link" } },
    { submitterName: "Bad", content: { courseFeedback: { teachingQuality: "five" } } },
    { submitterName: "Ana", content: { courseFeedback: complete } },
  ]);
  assert.equal(summary.responses, 1);
  assert.equal(summary.ratings[0].average, 4);
});

test("no responses yields null averages rather than NaN", () => {
  const summary = summarizeCourseFeedback([]);
  assert.equal(summary.responses, 0);
  assert.deepEqual(summary.ratings.map((r) => r.average), [null, null]);
});

test("the teacher summary escapes student-written comments", () => {
  const escape = (text) => String(text).replace(/</g, "&lt;");
  const html = renderCourseFeedbackSummary(
    summarizeCourseFeedback([{ submitterName: "Ana", content: { courseFeedback: { ...complete, grow: "<script>x</script>" } } }]),
    escape,
  );
  assert.ok(html.includes("&lt;script>x&lt;/script>"));
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("4/5"));
});

test("the teacher summary says so when nothing has been collected", () => {
  assert.match(renderCourseFeedbackSummary(summarizeCourseFeedback([]), String), /No course feedback/);
});
