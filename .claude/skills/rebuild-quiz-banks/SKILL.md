---
name: rebuild-quiz-banks
description: Regenerate the verbal quiz question banks (Project Execution Steps 1-6) after editing data/verbal_word_bank.csv or any pipeline logic. Runs build_mapping -> verify_mapping -> build_analogies -> critique_analogies in order, validates the served artifacts, and offers to rebuild + redeploy the static site. Use whenever the vocabulary pool changes.
---

# Rebuild quiz banks

Regenerates the served question banks from `data/verbal_word_bank.csv`. Run this
after editing the CSV or any of the mapping/analogy logic. The pipeline is
**precision-first** (see CLAUDE.md): empty synonym/antonym lists and questions
culled by the critique are expected, not bugs.

## Preconditions

1. **Run everything from the repo root** (the directory containing `src/` and
   `data/`), never from inside `src/`. `python3 src/app.py` and the build
   scripts resolve `data/` by absolute path, but must be invoked with that exact
   `src/...` relative path.
2. **Dependencies.** The build needs `nltk` (WordNet auto-downloads on first
   run). If `python3 -c "import nltk"` fails, run `pip install -r requirements.txt`.
3. Confirm the CSV actually changed if the user expected it to (`git status
   data/verbal_word_bank.csv`).

## Pipeline — run in order, stop on any failure

Each command prints per-grade stats. Read them; do not blindly continue if a
script errors or a count looks wrong.

**Steps 1-2 — synonym/antonym mapping (recall then precision):**
```bash
python3 src/build_mapping.py     # step 1: recall pool   -> data/static_vocab_source.json
python3 src/verify_mapping.py    # step 2: precision trim -> data/verified_mapping.json (served)
```
If the user wants *more* synonym/antonym questions, raise `TOP_SENSES` in
`src/verify_mapping.py` before loosening anything else, then re-run step 2. Do
**not** reintroduce `path_similarity` (see CLAUDE.md — it readmits noise).

**Step 3 is code, not a build** (`src/generators.py`). Nothing to run here; it is
validated below.

**Steps 4-5 — analogy mining then critique:**
```bash
python3 src/build_analogies.py   # step 4: mine candidates -> data/analogy_source.json
python3 src/critique_analogies.py  # step 5: critique       -> data/analogy_bank.json (served)
```

### Layer B (LLM critique) decision — ask the user first

`critique_analogies.py` always runs deterministic Layer A. The Layer B LLM solve
pass runs **only** if the `anthropic` SDK is installed **and** `ANTHROPIC_API_KEY`
is set. **Layer B is billed per run** (Batches API, `claude-opus-4-8`). Before
running step 5:

- Check availability: `python3 -c "import anthropic" 2>/dev/null` and whether
  `ANTHROPIC_API_KEY` is set.
- If both are available, **ask the user** whether to run the (billed) LLM
  critique this time. If yes, run step 5 as above. If no, run
  `ANALOGY_NO_LLM=1 python3 src/critique_analogies.py` to force Layer A only.
- If the SDK/key are missing, Layer B is skipped automatically — just run step 5
  and note that only Layer A (deterministic) pruning was applied.

Layer B decisions are cached to `data/analogy_critique.jsonl` keyed by question
id, so re-running does not re-bill already-judged questions.

### If a minimum-count assertion fails

`critique_analogies.py` asserts each grade still meets its minimum (G1:50 … G6:300)
and fails loudly otherwise. If it does: raise `OVERGEN` or relax `STRUCTURAL_CAP`
in `src/build_analogies.py`, re-run step 4, then step 5.

## Validate (steps 3 + 6)

```bash
python3 src/generators.py   # smoke test: prints sample synonym/antonym/analogy quizzes
```
Then sanity-check the served counts and invariants:
```bash
python3 - <<'PY'
import json
m = json.load(open("data/verified_mapping.json"))
a = json.load(open("data/analogy_bank.json"))
MIN = {1:50,2:100,3:150,4:200,5:250,6:300}
for g in map(str, range(1,7)):
    syn = sum(1 for e in m[g].values() if e["synonyms"])
    ant = sum(1 for e in m[g].values() if e["antonyms"])
    na  = len(a.get(g, []))
    flag = "" if na >= MIN[int(g)] else "  *** BELOW MIN ***"
    print(f"grade {g}: words-with-syn={syn} words-with-ant={ant} analogies={na}{flag}")
PY
```
Report the per-grade table to the user. Every grade must meet its analogy
minimum; synonym/antonym counts vary with the vocabulary and may legitimately be
low for some grades.

## Publish (redeploy the family-facing site)

The served site is the static bundle in `docs/` (GitHub Pages, served from
`/docs`). After the banks are regenerated and validated, offer to publish:

```bash
python3 src/build_static.py   # step 7: rebuild docs/ from web/ + the fresh data
```
Then, **with the user's confirmation** (this publishes publicly):
```bash
git add -A
git commit -m "Refresh quiz banks from updated vocabulary"
git push origin main
```
GitHub Pages auto-rebuilds in ~1 minute at
https://hyungwonkim.github.io/verbalquiz/ . The served `app.js` is behind a CDN
cache; tell the user to hard-refresh (close + reopen the tab on mobile) to pick
up new data.

## Notes

- `static_vocab_source.json` and `analogy_source.json` are regenerable, git-ignored
  intermediates. `verified_mapping.json` and `analogy_bank.json` are the served,
  committed artifacts.
- Keep `web/app.js` (client-side generator) and `src/generators.py` in sync if
  you change question shape — both must emit `{type, stem, choices[4], answer,
  answer_index}`.
