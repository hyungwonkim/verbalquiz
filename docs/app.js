"use strict";

/* Client-side verbal quiz generator — a direct port of src/generators.py.
 *
 * The Flask backend is gone in the static build: this file fetches the same
 * three data artifacts the Python generator read (verified_mapping.json,
 * wordbank.json, analogy_bank.json) and does the sampling/shuffling in the
 * browser. No server, no API call. Question shape is identical to the Flask
 * response so the render code below is unchanged from the original app.js.
 *
 * Reproducible seeds are intentionally dropped — the dev-only feature for
 * deterministic quizzes does not survive a Python->JS RNG and the family use
 * case just wants fresh random quizzes. Everything else mirrors generators.py.
 */

const N_CHOICES = 4; // 1 answer + 3 distractors

// loaded at startup by loadData()
let MAPPING = {};     // grade -> word -> {category, synonyms[], antonyms[]}
let WORDBANK = {};    // category -> grade -> [words]   (string grade keys)
let ANALOGIES = {};   // grade -> [{stem, answer, distractors}]

// -- tiny random helpers (Math.random; no seeding) -------------------------
function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}
function sample(arr, k) {
  return shuffle(arr.slice()).slice(0, k);
}
function choice(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

// -- pools (port of WordBank.same_grade_pool / widened_pool) ----------------
function sameGradePool(grade, category) {
  return new Set(((WORDBANK[category] || {})[grade]) || []);
}
function widenedPool(grade, category) {
  const out = new Set();
  for (let g = 1; g <= Number(grade); g++) {
    for (const w of (((WORDBANK[category] || {})[String(g)]) || [])) out.add(w);
  }
  return out;
}

// -- synonym / antonym (port of QuizGenerator._generate) --------------------
function distractors(grade, category, exclude) {
  const need = N_CHOICES - 1;
  let pool = [...sameGradePool(grade, category)].filter((w) => !exclude.has(w));
  if (pool.length < need) {
    pool = [...widenedPool(grade, category)].filter((w) => !exclude.has(w));
  }
  if (pool.length < need) return null; // cannot build a clean question
  return sample(pool, need);
}

function buildQuestion(qtype, relation, grade, word) {
  const entry = MAPPING[grade][word];
  const related = entry[relation]; // synonyms or antonyms (non-empty)
  const answer = choice(related);
  // never let a distractor be the word, the answer, or any listed related word
  const exclude = new Set([word, answer, ...related]);
  const dist = distractors(grade, entry.category, exclude);
  if (dist === null) return null;
  const choices = shuffle([...dist, answer]);
  return {
    type: qtype,
    stem: word.toUpperCase(),
    choices,
    answer,
    answer_index: choices.indexOf(answer),
  };
}

function generate(qtype, relation, n, grade) {
  const entries = MAPPING[grade] || {};
  const eligible = shuffle(Object.keys(entries).filter((w) => entries[w][relation].length));
  const out = [];
  for (const word of eligible) {
    if (out.length >= n) break;
    const q = buildQuestion(qtype, relation, grade, word);
    if (q) out.push(q);
  }
  return out;
}

function synonymQuiz(n, grade) { return generate("synonym", "synonyms", n, grade); }
function antonymQuiz(n, grade) { return generate("antonym", "antonyms", n, grade); }

// -- analogy (port of QuizGenerator.analogy_quiz) ---------------------------
function analogyQuiz(n, grade) {
  const pool = ANALOGIES[grade] || [];
  const k = n >= pool.length ? pool.length : n;
  return sample(pool, k).map(buildAnalogy);
}
function buildAnalogy(q) {
  const pairs = shuffle([q.answer, ...q.distractors]);
  const fmt = (p) => `${p[0].toUpperCase()} : ${p[1].toUpperCase()}`;
  const choices = pairs.map(fmt);
  const answer = fmt(q.answer);
  return {
    type: "analogy",
    stem: `${q.stem[0].toUpperCase()} : ${q.stem[1].toUpperCase()} ::`,
    choices,
    answer,
    answer_index: choices.indexOf(answer),
  };
}

// ==========================================================================
// UI (unchanged behaviour from the original Flask app.js)
// ==========================================================================

const LETTERS = ["A", "B", "C", "D", "E", "F"];
const form = document.getElementById("quiz-form");
const quizEl = document.getElementById("quiz");
const answerKeyEl = document.getElementById("answer-key");
const statusEl = document.getElementById("status");
const toggleBtn = document.getElementById("toggle-answers");
const printBtn = document.getElementById("print-quiz");

const PROMPTS = {
  synonym: (w) => `Choose the word closest in meaning to ${w}:`,
  antonym: (w) => `Choose the word that is the opposite of ${w}:`,
  analogy: () => "Choose the pair whose relationship best matches the pair above:",
};

function questionNode(q, n) {
  const wrap = document.createElement("div");
  wrap.className = "q";

  const stem = document.createElement("div");
  stem.className = "stem";
  stem.textContent = `${n}. ${q.stem}`;
  wrap.appendChild(stem);

  const prompt = PROMPTS[q.type] ? PROMPTS[q.type](q.stem) : "";
  if (prompt) {
    const p = document.createElement("div");
    p.className = "prompt";
    p.textContent = prompt;
    wrap.appendChild(p);
  }

  const ul = document.createElement("ul");
  ul.className = "choices";
  q.choices.forEach((c, i) => {
    const li = document.createElement("li");
    if (i === q.answer_index) li.classList.add("correct");
    const key = document.createElement("span");
    key.className = "key";
    key.textContent = `(${LETTERS[i]})`;
    li.appendChild(key);
    li.appendChild(document.createTextNode(" " + c));
    ul.appendChild(li);
  });
  wrap.appendChild(ul);
  return wrap;
}

function renderGroup(title, questions) {
  const h = document.createElement("h2");
  h.className = "group-title";
  h.textContent = title;
  quizEl.appendChild(h);

  if (!questions.length) {
    const p = document.createElement("p");
    p.className = "note";
    p.textContent = "No questions available for this selection.";
    quizEl.appendChild(p);
    return;
  }
  questions.forEach((q, i) => quizEl.appendChild(questionNode(q, i + 1)));
}

// Answer key (print-only via CSS) — one line per group: "1-C  2-A  3-D".
function renderAnswerKey(groups) {
  answerKeyEl.innerHTML = "";
  if (!groups.some((g) => g.questions.length)) return;
  const h = document.createElement("h2");
  h.className = "group-title";
  h.textContent = "Answer Key";
  answerKeyEl.appendChild(h);
  for (const g of groups) {
    if (!g.questions.length) continue;
    const p = document.createElement("p");
    p.className = "ak-line";
    const label = document.createElement("strong");
    label.textContent = g.title + ": ";
    p.appendChild(label);
    p.appendChild(document.createTextNode(
      g.questions.map((q, i) => `${i + 1}-${LETTERS[q.answer_index]}`).join(" ")
    ));
    answerKeyEl.appendChild(p);
  }
}

// -- data load -------------------------------------------------------------
async function loadData() {
  const [mapping, wordbank, analogies] = await Promise.all([
    fetch("data/verified_mapping.json").then((r) => r.json()),
    fetch("data/wordbank.json").then((r) => r.json()),
    fetch("data/analogy_bank.json").then((r) => r.json()),
  ]);
  MAPPING = mapping;
  WORDBANK = wordbank;
  ANALOGIES = analogies;
}

const dataReady = loadData().then(
  () => { statusEl.textContent = "Ready. Choose a grade and generate."; },
  (err) => { statusEl.textContent = "Failed to load quiz data: " + err.message; }
);

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  await dataReady;

  const grade = document.getElementById("grade").value; // string key
  const nSyn = parseInt(document.getElementById("n_synonym").value, 10) || 0;
  const nAnt = parseInt(document.getElementById("n_antonym").value, 10) || 0;
  const nAna = parseInt(document.getElementById("n_analogy").value, 10) || 0;

  quizEl.innerHTML = "";
  answerKeyEl.innerHTML = "";
  quizEl.classList.remove("reveal");
  toggleBtn.hidden = true;
  printBtn.hidden = true;
  toggleBtn.textContent = "Show answers";

  const synonym = nSyn ? synonymQuiz(nSyn, grade) : [];
  const antonym = nAnt ? antonymQuiz(nAnt, grade) : [];
  const analogy = nAna ? analogyQuiz(nAna, grade) : [];

  const groups = [];
  if (nSyn) groups.push({ title: "Synonyms", questions: synonym });
  if (nAnt) groups.push({ title: "Antonyms", questions: antonym });
  if (nAna) groups.push({ title: "Analogies", questions: analogy });

  for (const g of groups) renderGroup(g.title, g.questions);
  renderAnswerKey(groups);
  lastGroups = groups;
  lastGrade = grade;

  const totalServed = synonym.length + antonym.length + analogy.length;
  statusEl.textContent = totalServed
    ? `Generated ${totalServed} question(s) for grade ${grade}.`
    : "No questions generated — try a different grade or counts.";
  toggleBtn.hidden = totalServed === 0;
  printBtn.hidden = totalServed === 0;
});

// -- print: open a self-contained worksheet in a new tab ------------------
// window.print() on the live page is unreliable on mobile (esp. iOS Safari).
// Instead we open a clean, standalone worksheet document the user can print or
// save via the browser's native Share -> Print. It auto-prints on desktop and
// carries its own Print button + answer key (own page) as a fallback.
let lastGroups = [];
let lastGrade = "";

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]
  ));
}

function worksheetHTML(groups, grade) {
  const promptFor = { synonym: PROMPTS.synonym, antonym: PROMPTS.antonym, analogy: PROMPTS.analogy };
  let body = `<h1>Verbal Quiz — Grade ${esc(grade)}</h1>`;
  for (const g of groups) {
    if (!g.questions.length) continue;
    body += `<h2>${esc(g.title)}</h2>`;
    g.questions.forEach((q, i) => {
      const prompt = promptFor[q.type] ? promptFor[q.type](q.stem) : "";
      body += `<div class="q"><div class="stem">${i + 1}. ${esc(q.stem)}</div>`;
      if (prompt) body += `<div class="prompt">${esc(prompt)}</div>`;
      body += `<ul>` + q.choices.map((c, j) =>
        `<li><span class="key">(${LETTERS[j]})</span> ${esc(c)}</li>`).join("") + `</ul></div>`;
    });
  }
  // answer key on its own page
  let key = `<div class="answer-key"><h2>Answer Key</h2>`;
  for (const g of groups) {
    if (!g.questions.length) continue;
    const line = g.questions.map((q, i) => `${i + 1}-${LETTERS[q.answer_index]}`).join("  ");
    key += `<p><strong>${esc(g.title)}:</strong> ${line}</p>`;
  }
  key += `</div>`;

  return `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Verbal Quiz — Grade ${esc(grade)}</title>
<style>
  body { font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color:#000; line-height:1.5; max-width:720px; margin:0 auto; padding:1rem 1.25rem 3rem; }
  h1 { font-size:1.4rem; margin:0 0 1rem; }
  h2 { font-size:1.15rem; border-bottom:1px solid #000; padding-bottom:.2rem; margin:1.5rem 0 .5rem; }
  .q { border:1px solid #999; border-radius:8px; padding:.7rem .9rem; margin:.5rem 0; }
  .stem { font-weight:700; letter-spacing:.02em; }
  .prompt { color:#555; font-size:.9rem; }
  ul { list-style:none; margin:.4rem 0 0; padding:0; }
  li { padding:.15rem 0; }
  .key { display:inline-block; width:1.6rem; color:#555; font-weight:600; }
  .answer-key { break-before:page; page-break-before:always; margin-top:2rem; }
  .answer-key p { letter-spacing:.05em; margin:.25rem 0; }
  .toolbar { position:sticky; top:0; background:#fff; padding:.5rem 0 1rem; border-bottom:1px solid #ddd; margin-bottom:1rem; }
  .toolbar button { font-size:1rem; padding:.55rem 1.1rem; border:0; border-radius:8px; background:#3b5bdb; color:#fff; cursor:pointer; }
  .toolbar .hint { display:block; color:#555; font-size:.8rem; margin-top:.4rem; }
  @media print { .toolbar { display:none; } body { padding:0; } }
</style></head>
<body>
  <div class="toolbar">
    <button onclick="window.print()">Print / Save as PDF</button>
    <span class="hint">On a phone: tap the browser Share button, then Print.</span>
  </div>
  ${body}
  ${key}
  <script>window.addEventListener("load",function(){setTimeout(function(){try{window.print();}catch(e){}},300);});<\/script>
</body></html>`;
}

printBtn.addEventListener("click", () => {
  if (!lastGroups.some((g) => g.questions.length)) return;
  const html = worksheetHTML(lastGroups, lastGrade);
  const w = window.open("", "_blank");
  if (w) {
    w.document.open();
    w.document.write(html);
    w.document.close();
  } else {
    // popup blocked -> fall back to printing the current page
    window.print();
  }
});

toggleBtn.addEventListener("click", () => {
  const revealed = quizEl.classList.toggle("reveal");
  toggleBtn.textContent = revealed ? "Hide answers" : "Show answers";
});
