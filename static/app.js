"use strict";

const LETTERS = ["A", "B", "C", "D", "E", "F"];
const form = document.getElementById("quiz-form");
const quizEl = document.getElementById("quiz");
const statusEl = document.getElementById("status");
const toggleBtn = document.getElementById("toggle-answers");

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

function renderGroup(title, questions, note) {
  const h = document.createElement("h2");
  h.className = "group-title";
  h.textContent = title;
  quizEl.appendChild(h);

  if (note) {
    const p = document.createElement("p");
    p.className = "note";
    p.textContent = note;
    quizEl.appendChild(p);
  }
  if (!questions.length && !note) {
    const p = document.createElement("p");
    p.className = "note";
    p.textContent = "No questions available for this selection.";
    quizEl.appendChild(p);
    return;
  }
  questions.forEach((q, i) => quizEl.appendChild(questionNode(q, i + 1)));
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {
    grade: parseInt(document.getElementById("grade").value, 10),
    n_synonym: parseInt(document.getElementById("n_synonym").value, 10) || 0,
    n_antonym: parseInt(document.getElementById("n_antonym").value, 10) || 0,
    n_analogy: parseInt(document.getElementById("n_analogy").value, 10) || 0,
  };

  statusEl.textContent = "Generating…";
  quizEl.innerHTML = "";
  quizEl.classList.remove("reveal");
  toggleBtn.hidden = true;

  let data;
  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    data = await res.json();
    if (!res.ok) throw new Error(data.error || "request failed");
  } catch (err) {
    statusEl.textContent = "Error: " + err.message;
    return;
  }

  if (body.n_synonym) renderGroup("Synonyms", data.synonym);
  if (body.n_antonym) renderGroup("Antonyms", data.antonym);
  if (body.n_analogy) renderGroup("Analogies", data.analogy, data.analogy_note);

  const totalServed = data.synonym.length + data.antonym.length + data.analogy.length;
  statusEl.textContent = totalServed
    ? `Generated ${totalServed} question(s) for grade ${data.grade}.`
    : "No questions generated — try a different grade or counts.";
  toggleBtn.hidden = totalServed === 0;
});

toggleBtn.addEventListener("click", () => {
  const revealed = quizEl.classList.toggle("reveal");
  toggleBtn.textContent = revealed ? "Hide answers" : "Show answers";
});
