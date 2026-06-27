"""Step 3 — synonym & antonym question generators.

Pulls from data/verified_mapping.json (step 2 output) for question words +
correct answers, and from the word bank for distractors. No WordNet/Flask
dependency at runtime — just JSON + the CSV pools.

A question is:
  {
    "type": "synonym" | "antonym",
    "stem": "<WORD>",            # the prompt word (uppercased for display)
    "choices": ["..", ..],       # 4 options, shuffled
    "answer": "..",              # the correct option text
    "answer_index": 2,           # index of answer within choices
  }
"""
import json
import os
import random

from wordbank import load_wordbank, _DATA_DIR

MAPPING_PATH = os.path.join(_DATA_DIR, "verified_mapping.json")
ANALOGY_PATH = os.path.join(_DATA_DIR, "analogy_bank.json")
N_CHOICES = 4  # 1 answer + 3 distractors


def _load_mapping(path=MAPPING_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_analogies(path=ANALOGY_PATH):
    """Served analogy bank (step 5). Empty until the bank is built — graceful."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class QuizGenerator:
    def __init__(self, mapping_path=MAPPING_PATH, csv_path=None, analogy_path=ANALOGY_PATH):
        self.mapping = _load_mapping(mapping_path)
        self.wb = load_wordbank(csv_path) if csv_path else load_wordbank()
        self.analogies = _load_analogies(analogy_path)

    # -- internal -----------------------------------------------------------
    def _eligible(self, grade, relation):
        """Words at `grade` whose `relation` list is non-empty."""
        entries = self.mapping.get(str(grade), {})
        return [w for w, e in entries.items() if e[relation]]

    def _distractors(self, word, grade, category, exclude, rng):
        """3 distractors: same category, same grade, not in `exclude`.

        Falls back to the grade<=G pool if the same-grade pool is too small.
        """
        need = N_CHOICES - 1
        pool = self.wb.same_grade_pool(grade, category) - exclude
        if len(pool) < need:
            pool = self.wb.widened_pool(grade, category) - exclude
        if len(pool) < need:
            return None  # cannot build a clean question
        return rng.sample(sorted(pool), need)

    def _build_question(self, qtype, relation, grade, word, rng):
        entry = self.mapping[str(grade)][word]
        category = entry["category"]
        related = entry[relation]            # synonyms or antonyms (non-empty)
        answer = rng.choice(related)
        # never let a distractor be the word, the answer, or any listed
        # synonym/antonym of the word (those could also be "correct").
        exclude = {word, answer, *related}
        distractors = self._distractors(word, grade, category, exclude, rng)
        if distractors is None:
            return None
        choices = distractors + [answer]
        rng.shuffle(choices)
        return {
            "type": qtype,
            "stem": word.upper(),
            "choices": choices,
            "answer": answer,
            "answer_index": choices.index(answer),
        }

    def _generate(self, qtype, relation, n, grade, seed=None):
        rng = random.Random(seed)
        eligible = self._eligible(grade, relation)
        rng.shuffle(eligible)
        questions = []
        for word in eligible:
            if len(questions) >= n:
                break
            q = self._build_question(qtype, relation, grade, word, rng)
            if q is not None:
                questions.append(q)
        return questions

    # -- public API ---------------------------------------------------------
    def synonym_quiz(self, n, grade, seed=None):
        return self._generate("synonym", "synonyms", n, grade, seed)

    def antonym_quiz(self, n, grade, seed=None):
        return self._generate("antonym", "antonyms", n, grade, seed)

    def analogy_quiz(self, n, grade, seed=None):
        """N analogies from the grade-G bank, no repeats (all if n >= pool)."""
        pool = self.analogies.get(str(grade), [])
        rng = random.Random(seed)
        k = len(pool) if n >= len(pool) else n
        chosen = rng.sample(pool, k)
        return [self._build_analogy_question(q, rng) for q in chosen]

    def _build_analogy_question(self, q, rng):
        pairs = [q["answer"]] + q["distractors"]
        rng.shuffle(pairs)               # per-serving shuffle, seed-controlled
        fmt = lambda p: f"{p[0].upper()} : {p[1].upper()}"
        choices = [fmt(p) for p in pairs]
        answer = fmt(q["answer"])
        a, b = q["stem"]
        return {
            "type": "analogy",
            "stem": f"{a.upper()} : {b.upper()} ::",
            "choices": choices,
            "answer": answer,
            "answer_index": choices.index(answer),
        }


# Module-level singleton + thin wrappers (lazy-loaded) for convenience.
_GEN = None


def _gen():
    global _GEN
    if _GEN is None:
        _GEN = QuizGenerator()
    return _GEN


def synonym_quiz(n, grade, seed=None):
    return _gen().synonym_quiz(n, grade, seed)


def antonym_quiz(n, grade, seed=None):
    return _gen().antonym_quiz(n, grade, seed)


def analogy_quiz(n, grade, seed=None):
    return _gen().analogy_quiz(n, grade, seed)


if __name__ == "__main__":
    import sys
    print("=== synonym_quiz(3, 2, seed=1) ===")
    print(json.dumps(synonym_quiz(3, 2, seed=1), indent=2))
    print("=== antonym_quiz(3, 2, seed=1) ===")
    print(json.dumps(antonym_quiz(3, 2, seed=1), indent=2))
    print("=== analogy_quiz(3, 3, seed=1) ===")
    print(json.dumps(analogy_quiz(3, 3, seed=1), indent=2))
