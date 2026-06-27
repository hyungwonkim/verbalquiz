"""Step 4 — recall-first analogy candidate mining.

Builds per-grade analogy questions of the form `A : B :: C : D`, where the
stem pair (A,B) and the correct answer pair (C,D) hold the *same* relation R,
and the three distractor pairs are plausible word pairs that do NOT hold R.
All eight words come from the word bank at grade <= G.

Relation sources (all directed pairs, single-token, words in-bank):
  synonym / antonym  — reused from data/verified_mapping.json (already double-
    verified in step 2); stored both directions (symmetric).
  is-a               — (hyponym, hypernym) from WordNet, nouns, restricted to
    the hyponym's top-1 dominant synset (the polysemy guard from verify_mapping).
  part-whole         — (part, whole) from part/member/substance meronyms, nouns,
    top-1 sense.

Recall is prioritized: over-generate to OVERGEN x the per-grade minimum so the
step-5 critique can cull freely. Synonym/antonym pairs alone exceed the minimum
many times over, so structural (is-a / part-whole) questions are capped at
STRUCTURAL_CAP of each grade for variety only.

Output: data/analogy_source.json
  { "<grade>": [ {id, relation, grade, stem, answer, distractors:[{pair,relation,transform}]} ] }
"""
import json
import os
import random
import sys
from collections import defaultdict

import nltk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wordbank import load_wordbank, GRADES, _DATA_DIR

MAPPING_PATH = os.path.join(_DATA_DIR, "verified_mapping.json")
OUT_PATH = os.path.join(_DATA_DIR, "analogy_source.json")

SEED = 12345
MIN_PER_GRADE = {1: 50, 2: 100, 3: 150, 4: 200, 5: 250, 6: 300}
OVERGEN = 3                       # target = OVERGEN x minimum (critique culls down)
STRUCTURAL_CAP = 0.30            # <= 30% of a grade's questions are is-a/part-whole
SYMMETRIC = {"synonym", "antonym"}
RELATIONS = ["synonym", "antonym", "is-a", "part-whole"]
SHORT = {"synonym": "syn", "antonym": "ant", "is-a": "isa", "part-whole": "pw"}
N_DISTRACTORS = 3


def _ensure_corpus():
    for c in ("wordnet", "omw-1.4"):
        try:
            nltk.data.find(f"corpora/{c}")
        except LookupError:
            nltk.download(c, quiet=True)


def _single_token(name):
    """WordNet lemma names use '_' for phrases; keep single words only."""
    return name.replace("-", "").isalpha() and "_" not in name


# -- pair mining -----------------------------------------------------------

def build_word_min_grade(wb):
    """word -> lowest grade it appears at (across any category)."""
    mg = {}
    for r in wb.records:
        w, g = r["word"], r["grade"]
        if w not in mg or g < mg[w]:
            mg[w] = g
    return mg


def _structural_pairs(wb):
    """is-a and part-whole noun pairs from WordNet, top-1 dominant sense."""
    from nltk.corpus import wordnet as wn

    noun_words = {r["word"] for r in wb.records if r["category"] == "Noun"}
    isa, pw = set(), set()
    for w in noun_words:
        for s in wn.synsets(w, pos="n")[:1]:        # top-1 dominant sense only
            for h in s.hypernyms():
                for lem in h.lemmas():
                    name = lem.name().lower()
                    if name != w and _single_token(name) and name in noun_words:
                        isa.add((w, name))           # hyponym -> hypernym
            for m in s.part_meronyms() + s.member_meronyms() + s.substance_meronyms():
                for lem in m.lemmas():
                    name = lem.name().lower()
                    if name != w and _single_token(name) and name in noun_words:
                        pw.add((name, w))            # part -> whole
    return isa, pw


def build_pairs(wb, mapping):
    """relation -> set of directed (a, b) pairs. Syn/ant stored both ways."""
    syn, ant = set(), set()
    for entries in mapping.values():
        for word, e in entries.items():
            for s in e["synonyms"]:
                syn.add((word, s)); syn.add((s, word))
            for a in e["antonyms"]:
                ant.add((word, a)); ant.add((a, word))
    isa, pw = _structural_pairs(wb)
    return {"synonym": syn, "antonym": ant, "is-a": isa, "part-whole": pw}


def pairs_at_grade(buckets, min_grade, grade):
    """Filter every bucket to pairs whose both words are available at grade<=G."""
    out = {}
    for R, pairs in buckets.items():
        out[R] = {
            (a, b) for (a, b) in pairs
            if max(min_grade.get(a, 99), min_grade.get(b, 99)) <= grade
        }
    return out


# -- question assembly -----------------------------------------------------

def _relation_holds(R, x, y, buckets_at_grade):
    """Directed pair (x, y) is present in relation R's bucket at this grade."""
    return (x, y) in buckets_at_grade[R]


def make_distractors(R, stem, answer, buckets_at_grade, rng):
    """3 plausible pairs that do NOT hold R and don't reuse any word so far.

    Candidates are pairs from every *other* relation, plus — for asymmetric R
    only — reversed R pairs (reversing a synonym/antonym is still valid, so it
    is never used as a distractor). Each candidate is rejected if it shares a
    word already in play (=> 10 distinct words across the 5 pairs) or if it
    would itself satisfy R (=> a second correct answer).
    """
    used = set(stem) | set(answer)
    candidates = []
    for R2, pairs in buckets_at_grade.items():
        if R2 == R:
            continue
        candidates += [(p, R2, "other-relation") for p in pairs]
    if R not in SYMMETRIC:
        candidates += [((b, a), R, "reversed") for (a, b) in buckets_at_grade[R]]
    rng.shuffle(candidates)

    out = []
    for pair, R2, transform in candidates:
        x, y = pair
        if x in used or y in used:
            continue
        if _relation_holds(R, x, y, buckets_at_grade):
            continue
        if R in SYMMETRIC and _relation_holds(R, y, x, buckets_at_grade):
            continue
        out.append({"pair": [x, y], "relation": R2, "transform": transform})
        used.add(x); used.add(y)
        if len(out) == N_DISTRACTORS:
            return out
    return None


def _dedupe_key(R, stem, answer):
    return (R, frozenset({frozenset(stem), frozenset(answer)}))


def emit_relation(R, grade, buckets_at_grade, rng, max_count, seen):
    """Up to `max_count` questions for relation R, skipping `seen` dedupe keys."""
    if max_count <= 0:
        return []
    pool = list(buckets_at_grade[R])
    rng.shuffle(pool)
    res = []
    for stem in pool:
        if len(res) >= max_count:
            break
        # pick an answer pair of the same relation, disjoint from the stem
        answer = None
        idxs = list(range(len(pool)))
        rng.shuffle(idxs)
        for j in idxs[:50]:
            cand = pool[j]
            if set(cand) & set(stem):
                continue
            if _dedupe_key(R, stem, cand) in seen:
                continue
            answer = cand
            break
        if answer is None:
            continue
        dist = make_distractors(R, stem, answer, buckets_at_grade, rng)
        if dist is None:
            continue
        seen.add(_dedupe_key(R, stem, answer))
        res.append({
            "relation": R,
            "grade": grade,
            "stem": [stem[0], stem[1]],
            "answer": [answer[0], answer[1]],
            "distractors": dist,
        })
    return res


def generate_for_grade(grade, buckets_at_grade, rng, target):
    seen = set()
    out = []
    # structural questions first, capped (variety only — minimums come from syn/ant)
    struct_cap = int(STRUCTURAL_CAP * target)
    for R in ("is-a", "part-whole"):
        if len(out) >= struct_cap:
            break
        out += emit_relation(R, grade, buckets_at_grade, rng, struct_cap - len(out), seen)
    # fill the rest with antonym (smaller pool, ensure presence) then synonym
    rem = target - len(out)
    out += emit_relation("antonym", grade, buckets_at_grade, rng, rem // 2, seen)
    out += emit_relation("synonym", grade, buckets_at_grade, rng, target - len(out), seen)
    if len(out) < target:                       # synonym exhausted -> top up antonym
        out += emit_relation("antonym", grade, buckets_at_grade, rng, target - len(out), seen)
    out = out[:target]
    for i, q in enumerate(out):
        q["id"] = f"g{grade}-{SHORT[q['relation']]}-{i:05d}"
    return out


def build(wb, mapping, seed=SEED):
    buckets = build_pairs(wb, mapping)
    min_grade = build_word_min_grade(wb)
    result = {}
    for g in GRADES:
        rng = random.Random(seed + g)
        at_g = pairs_at_grade(buckets, min_grade, g)
        target = OVERGEN * MIN_PER_GRADE[g]
        result[str(g)] = generate_for_grade(g, at_g, rng, target)
    return result


def print_stats(result):
    print("\nCandidate analogy questions per grade (min required / generated):")
    print(f"{'grade':>5} {'min':>5} {'gen':>6}   by relation")
    for g in GRADES:
        qs = result[str(g)]
        by = defaultdict(int)
        for q in qs:
            by[q["relation"]] += 1
        breakdown = " ".join(f"{SHORT[r]}={by[r]}" for r in RELATIONS)
        flag = "" if len(qs) >= MIN_PER_GRADE[g] else "  *** BELOW MIN ***"
        print(f"{g:>5} {MIN_PER_GRADE[g]:>5} {len(qs):>6}   {breakdown}{flag}")


def main():
    _ensure_corpus()
    wb = load_wordbank()
    with open(MAPPING_PATH, encoding="utf-8") as f:
        mapping = json.load(f)
    result = build(wb, mapping)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"wrote {OUT_PATH}")
    print_stats(result)
    sample = result["3"][0] if result.get("3") else None
    print("\nsample grade-3 question:", json.dumps(sample, ensure_ascii=False))


if __name__ == "__main__":
    main()
