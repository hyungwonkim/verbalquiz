# Verbal Quiz Generator

Generates grade-leveled **synonym** and **antonym** multiple-choice questions
from a static vocabulary bank. Analogy questions are stubbed (logic added later).

All question words, answers, and distractors come from
`data/verbal_word_bank.csv` (columns `Word, Grade, Category`; grades 1–6;
categories Noun / Verb / Adjective).

## Pipeline

1. **`src/build_mapping.py`** (recall-first) — for each word, gather WordNet
   synonym/antonym candidates and intersect with the word-bank pool of the same
   category at grade ≤ the word's grade. Output: `data/static_vocab_source.json`.
2. **`src/verify_mapping.py`** (precision-first) — reduce each word to its top-N
   dominant WordNet senses and keep only pairs that survive a symmetric
   dominant-sense check (synonyms) / direct antonym links. Output:
   `data/verified_mapping.json` (this is what the app serves). Tune precision vs.
   recall via `TOP_SENSES`.
3. **`src/generators.py`** — `synonym_quiz(n, grade)` / `antonym_quiz(n, grade)`
   pull words with a non-empty list, pick a random correct answer, and add 3
   distractors of the same category + grade that are not themselves
   synonyms/antonyms of the word.

`src/wordbank.py` is the shared CSV loader + pool helpers.

## Setup

```bash
pip install -r requirements.txt
# WordNet corpus auto-downloads on first run of build_mapping.py
```

## Build the question bank

```bash
python3 src/build_mapping.py     # step 1 -> data/static_vocab_source.json
python3 src/verify_mapping.py    # step 2 -> data/verified_mapping.json
```

Both print per-grade coverage stats. Re-run after editing the CSV.

## Run the web app

```bash
python3 src/app.py               # http://127.0.0.1:5000
```

Pick a grade and how many synonym / antonym / analogy questions to generate.
"Show answers" highlights the correct choice. The analogy count is accepted but
returns an empty list with a "not implemented yet" note.

## API

`POST /api/generate`

```json
{ "grade": 3, "n_synonym": 5, "n_antonym": 5, "n_analogy": 0, "seed": 1 }
```

Returns `{ grade, synonym: [...], antonym: [...], analogy: [], served, requested }`.
Each question: `{ type, stem, choices: [4], answer, answer_index }`.
`seed` is optional and makes a quiz reproducible.

## Notes

- Precision is favored over recall (a clean answer key matters more than
  coverage), so many words have empty lists — that's expected. Generators simply
  draw from words that have entries; requesting more than available caps cleanly.
- `data/static_vocab_source.json` is a regenerable intermediate (git-ignored).
