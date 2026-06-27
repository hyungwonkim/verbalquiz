# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A grade-leveled verbal quiz generator (synonym + antonym multiple-choice questions) served by a Flask web app. Analogy questions are intentionally stubbed — the generation logic is added later by the user.

## Commands

```bash
pip install -r requirements.txt          # nltk + flask (WordNet corpus auto-downloads on first build)

python3 src/build_mapping.py             # step 1: recall-heavy mapping -> data/static_vocab_source.json
python3 src/verify_mapping.py            # step 2: precision filter      -> data/verified_mapping.json
python3 src/build_analogies.py           # step 4: mine analogy candidates -> data/analogy_source.json
python3 src/critique_analogies.py        # step 5: invariants + LLM solve  -> data/analogy_bank.json
python3 src/build_static.py              # step 7: assemble server-less bundle -> docs/
python3 src/app.py                       # web app (PORT env overrides; default 5001)

python3 src/generators.py                # smoke test: prints sample synonym/antonym/analogy quizzes
python3 src/wordbank.py                  # smoke test: loader + pool sizes
```

`critique_analogies.py` runs deterministic invariant checks always; the LLM solve pass (Layer B) runs
only if the `anthropic` SDK + `ANTHROPIC_API_KEY` are available (else it is skipped, Layer A only).
Set `ANALOGY_NO_LLM=1` to force-skip the LLM pass. LLM decisions are cached to
`data/analogy_critique.jsonl` (keyed by question id) for reproducibility.

There is no test framework. Validation is done by running the `__main__` block of each module and by ad-hoc invariant-checking scripts (instantiate `QuizGenerator`, generate across grades/seeds, assert choices/answer/distractor properties).

Run scripts from the repo root, not from `src/`. Every module resolves `data/` via an absolute path derived from its own location (`wordbank._DATA_DIR`), so cwd doesn't affect data loading — but `python3 src/app.py` must be invoked with that exact relative path.

## Architecture

Two parallel offline pipelines feed a thin Flask layer. The hard parts are **stages 1→2** (syn/ant precision) and **stages 4→5** (analogy distractor quality); everything downstream is mechanical.

**Data flows one direction:**
- syn/ant: `verbal_word_bank.csv` → `build_mapping.py` → `static_vocab_source.json` → `verify_mapping.py` → `verified_mapping.json`
- analogy: `verbal_word_bank.csv` + `verified_mapping.json` → `build_analogies.py` → `analogy_source.json` → `critique_analogies.py` → `analogy_bank.json`
- both feed `generators.py` → `app.py` → browser.
- static deploy: `verified_mapping.json` + `analogy_bank.json` + `verbal_word_bank.csv` → `build_static.py` → `docs/` (browser does the sampling; no server).

**Two ways to serve the same data:**
- **Flask** (`app.py`) — local dev; `generators.py` samples server-side, returns JSON to `static/app.js`.
- **Static** (`docs/`) — published deploy; `web/app.js` is a JS port of `generators.py` that fetches the data artifacts and samples in-browser. No Python at runtime. `build_static.py` bundles `web/index.html` + `web/app.js` + `static/style.css` + the data (CSV → `docs/data/wordbank.json`, the two JSON banks copied verbatim) into `docs/`. GitHub Pages serves from `/docs`. Re-run `build_static.py` after any pipeline change, then commit `docs/` and push. **`web/app.js` and `generators.py` must stay in sync** — same question shape `{type, stem, choices[4], answer, answer_index}`; seeds are intentionally dropped client-side (family use, not reproducibility).

- **`src/wordbank.py`** — the only CSV reader. `WordBank.pool(grade, cat)` returns same-category words at grade ≤ G (the step-1 recall pool); `same_grade_pool` returns exactly grade G (step-3 distractors). `CATEGORY_TO_POS` maps the CSV's Noun/Verb/Adjective to WordNet POS tags (`a` + `s` for adjectives — satellites matter).

- **`src/build_mapping.py`** (step 1, recall-first) — for each word, pulls WordNet synonym candidates (synset lemmas + adjective `similar_to`) and antonym candidates (lemma antonyms + derivational + similar_to), then **intersects with the same-category pool at grade ≤ G**. Single-token words only. Empty lists are allowed and expected.

- **`src/verify_mapping.py`** (step 2, precision-first) — the precision logic, and the file most likely to need tuning. Reduces each word to its **top-`TOP_SENSES` dominant WordNet senses** (frequency-ordered) plus adjective `similar_to` satellites, cached in `_CLUSTER_CACHE`. A synonym survives only if the candidate's *own* dominant cluster overlaps the word's cluster (**symmetric** check — this is what kills asymmetric junk like `old`→gray). Antonyms survive only via direct antonym links reachable from the dominant cluster. **Do not reintroduce `path_similarity`**: adjective satellites return a near-constant ~0.33 to almost anything, so any threshold there just readmits noise. `TOP_SENSES` is the precision/recall knob (higher = more questions, more noise).

- **`src/build_analogies.py`** (step 4, recall-first) — mines `A:B :: C:D` candidates per grade. Relation buckets (directed, in-bank, single-token): `synonym`/`antonym` reused from `verified_mapping.json` (stored both directions); `is-a` (hyponym→hypernym) and `part-whole` (meronym→holonym) from WordNet, nouns, restricted to the word's **top-1 dominant synset** (the polysemy guard from `verify_mapping`). A question = stem pair + answer pair of the same relation R + 3 distractor pairs that do NOT hold R (`make_distractors`); reversed-R distractors only for asymmetric relations. Over-generates to `OVERGEN`× the per-grade minimum; structural (is-a/part-whole) capped at `STRUCTURAL_CAP`. 10 distinct words per question. Output `analogy_source.json`.

- **`src/critique_analogies.py`** (step 5, precision-first) — Layer A re-checks every invariant deterministically (10 distinct in-bank words, stem/answer hold R, distractors break R, within-grade unique). Layer B is an independent Claude solve pass (Batches API, `claude-opus-4-8`, low effort) that sees each question with **no answer key** and returns `{chosen_index, verdict, reason}`; a question is dropped if the solver picks wrong or flags `remove`. Asserts each grade still meets its minimum. Output `analogy_bank.json` (served).

- **`src/generators.py`** (step 3 + 6) — `QuizGenerator` loads `verified_mapping.json`, `analogy_bank.json`, + the word bank. `synonym_quiz` / `antonym_quiz` pick words with a non-empty list, choose one related word as the answer, and add 3 distractors that are same-category, same-grade, and excluded from the word's entire syn/ant set (so no distractor can also be "correct"). Falls back to the grade-≤G pool if same-grade is too thin; returns fewer than `n` rather than failing. `analogy_quiz` samples N from the grade's bank (no repeats; all if N ≥ pool) and shuffles the 4 pairs per-serving, emitting the same `{type, stem, choices[4], answer, answer_index}` shape (`analogy_bank.json` missing → empty pool, graceful).

- **`src/app.py`** — Flask. `GET /` renders the form; `POST /api/generate` clamps counts to `MAX_PER_TYPE` and returns `{grade, synonym, antonym, analogy, served, requested}`. `templates/` and `static/` live at the repo root and are wired via absolute `template_folder`/`static_folder` (the app file is under `src/`). The browser JS (`static/app.js`) depends on the response shape `{type, stem, choices[4], answer, answer_index}` — keep generator output and JS in sync.

## Design stance

Precision is deliberately favored over recall: a wrong answer key is worse than fewer questions. Many words end up with empty synonym/antonym lists — that is correct, not a bug. If asked to "add more questions," reach for `TOP_SENSES` in `verify_mapping.py` before loosening the generators. For analogies, the syn/ant relations are the clean backbone (reused verified pairs); the WordNet `is-a`/`part-whole` relations add variety but carry sense noise — the Layer-B LLM critique is what removes the wrong-sense and ambiguous ones, so prefer running it over loosening `make_distractors`.

Re-run `build_mapping.py` then `verify_mapping.py` after any edit to the CSV or the mapping logic; re-run `build_analogies.py` then `critique_analogies.py` after any edit to the CSV, the mapping, or the analogy logic. `verified_mapping.json` and `analogy_bank.json` are the served artifacts; `static_vocab_source.json` and `analogy_source.json` are regenerable (git-ignored) intermediates.

## Environment note

Port 5000 is taken by macOS AirPlay Receiver (returns 403), so the app defaults to 5001.
