/**
 * course-feedback.js — the Likert course survey students answer when they submit.
 *
 * Students rate the quality of teaching and of the homework (1-5) and leave two
 * pros and one grow. It is stored on the submission as `content.courseFeedback`
 * and summarized here for teachers, replacing the need for a separate microblog.
 *
 * Pure functions only (no DOM, no fetch) so the analysis is unit-testable.
 */

export const COURSE_FEEDBACK_RATINGS = [
  { field: "teachingQuality", label: "Quality of teaching" },
  { field: "homeworkQuality", label: "Quality of homework" },
];

const LIKERT_VALUES = [1, 2, 3, 4, 5];

function isLikert(value) {
  return Number.isInteger(value) && value >= 1 && value <= 5;
}

/** Returns an error message for an incomplete survey, or null when it is valid. */
export function validateCourseFeedback(feedback) {
  if (!feedback) return "Please complete the course feedback before submitting.";
  for (const { field, label } of COURSE_FEEDBACK_RATINGS) {
    if (!isLikert(feedback[field])) return `Please rate "${label}" from 1 to 5.`;
  }
  const pros = Array.isArray(feedback.pros) ? feedback.pros : [];
  if (pros.length !== 2 || pros.some((pro) => !String(pro || "").trim())) {
    return "Please list two pros in the course feedback.";
  }
  if (!String(feedback.grow || "").trim()) {
    return "Please add one grow in the course feedback.";
  }
  return null;
}

/**
 * Aggregate the course feedback across submissions. Submissions without (or with
 * malformed) feedback are skipped rather than counted as zeros.
 *
 * @returns {{responses: number, ratings: Array, pros: Array, grows: Array}}
 */
export function summarizeCourseFeedback(submissions) {
  const responses = (submissions || [])
    .map((submission) => ({ submission, feedback: submission?.content?.courseFeedback }))
    .filter(({ feedback }) => feedback && COURSE_FEEDBACK_RATINGS.every(({ field }) => isLikert(feedback[field])));

  const ratings = COURSE_FEEDBACK_RATINGS.map(({ field, label }) => {
    const values = responses.map(({ feedback }) => feedback[field]);
    const total = values.reduce((sum, value) => sum + value, 0);
    return {
      field,
      label,
      average: values.length ? Math.round((total / values.length) * 10) / 10 : null,
      distribution: LIKERT_VALUES.map((value) => values.filter((v) => v === value).length),
    };
  });

  const comment = (submission, text) => ({
    student: submission.submitterName || "Unknown",
    assignment: submission.assignmentName || "",
    text: String(text).trim(),
  });
  const pros = responses.flatMap(({ submission, feedback }) =>
    (Array.isArray(feedback.pros) ? feedback.pros : [])
      .filter((pro) => String(pro || "").trim())
      .map((pro) => comment(submission, pro)));
  const grows = responses
    .filter(({ feedback }) => String(feedback.grow || "").trim())
    .map(({ submission, feedback }) => comment(submission, feedback.grow));

  return { responses: responses.length, ratings, pros, grows };
}

/**
 * Teacher-facing HTML for a summary. `escapeHtml` is injected (like the other
 * submissions renderers) because every comment is student-written text.
 */
export function renderCourseFeedbackSummary(summary, escapeHtml) {
  if (!summary.responses) {
    return '<p class="course-feedback-summary__empty">No course feedback in the current selection yet.</p>';
  }
  const ratingRows = summary.ratings.map(({ label, average, distribution }) => {
    const total = distribution.reduce((sum, count) => sum + count, 0);
    const bars = distribution.map((count, index) => {
      const percent = total ? Math.round((count / total) * 100) : 0;
      return `<span class="course-feedback-summary__bar" title="${index + 1}: ${count} (${percent}%)" style="--bar-size:${percent}%">${count}</span>`;
    }).join("");
    return `<div class="course-feedback-summary__rating">
      <span class="course-feedback-summary__label">${escapeHtml(label)}</span>
      <strong class="course-feedback-summary__average">${average}/5</strong>
      <span class="course-feedback-summary__bars" aria-label="Responses for 1 through 5">${bars}</span>
    </div>`;
  }).join("");
  const list = (title, items) => `<div class="course-feedback-summary__comments">
      <h4>${title} (${items.length})</h4>
      <ul>${items.map(({ student, assignment, text }) =>
        `<li>${escapeHtml(text)} <span class="course-feedback-summary__by">— ${escapeHtml(student)}${assignment ? `, ${escapeHtml(assignment)}` : ""}</span></li>`).join("")}</ul>
    </div>`;
  return `<p class="course-feedback-summary__count">${summary.responses} response${summary.responses === 1 ? "" : "s"}</p>
    ${ratingRows}
    <div class="course-feedback-summary__columns">${list("Pros", summary.pros)}${list("Grows", summary.grows)}</div>`;
}
