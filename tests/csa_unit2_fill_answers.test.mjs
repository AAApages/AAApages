// Short-answer matching in assets/js/csa-lessons/unit2-interactives.js.
// Run: node --test tests/csa_unit2_fill_answers.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

function loadU2() {
  const source = readFileSync(new URL('../assets/js/csa-lessons/unit2-interactives.js', import.meta.url), 'utf8');
  // readyState "loading" defers DOM wiring, so only the pure matcher runs here.
  const document = { readyState: 'loading', addEventListener() {} };
  const window = {};
  vm.runInNewContext(source, { window, document });
  return window.U2;
}

const { answerMatches } = loadU2();

// The 2.6 Activity 4 question 3 key, as published: rewrite !(age >= 18 && hasId).
const DE_MORGAN_KEY = 'age < 18 || !hasId|age<18 || !hasId|age<18||!hasId|!hasId || age < 18|!hasId||age<18';

test('accepts both correct De Morgan rewrites, with any spacing', () => {
  for (const answer of ['age < 18 || !hasId', '!hasId || age < 18', 'age<18||!hasId', '  !hasId  ||  age < 18 ']) {
    assert.equal(answerMatches(answer, DE_MORGAN_KEY), true, answer);
  }
});

test('rejects empty, partial and wrong rewrites that the old | split accepted or missed', () => {
  for (const answer of ['', '   ', '!hasId', 'age < 18', 'age < 18 && !hasId', 'age >= 18 || !hasId', 'age < 18 | !hasId']) {
    assert.equal(answerMatches(answer, DE_MORGAN_KEY), false, JSON.stringify(answer));
  }
});

test('keeps Java identifiers case-sensitive', () => {
  assert.equal(answerMatches('age < 18 || !hasid', DE_MORGAN_KEY), false);
  assert.equal(answerMatches('AGE < 18 || !HASID', DE_MORGAN_KEY), false);
  assert.equal(answerMatches('x != 0 && y != 0', 'x != 0 && y != 0|y != 0 && x != 0'), true);
  assert.equal(answerMatches('X != 0 && Y != 0', 'x != 0 && y != 0|y != 0 && x != 0'), false);
});

test('leaves other Unit 2 answers as they were', () => {
  assert.equal(answerMatches('warm', 'Warm'), true);
  assert.equal(answerMatches('No', 'no'), true);
  assert.equal(answerMatches('true', 'true'), true);
  assert.equal(answerMatches('b>=a', 'a <= b|a<=b|b >= a|b>=a'), true);
  assert.equal(answerMatches('5.0', '5'), true);
  assert.equal(answerMatches('6', '5'), false);
});
