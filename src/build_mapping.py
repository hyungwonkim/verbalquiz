"""Step 1 — recall-first synonym/antonym mapping.

For each word `w` (grade G, category C), gather WordNet synonym and antonym
candidates, then intersect with the word-bank pool of the *same category* at
*grade <= G*. Recall is prioritized: candidates are pulled broadly (synset
lemmas + adjective `similar_to`, antonym lemmas + derivational + similar_to),
and only the pool intersection survives.

Output: data/static_vocab_source.json
  { "<grade>": { "<word>": {"category": C, "synonyms": [...], "antonyms": [...]} } }
"""
import json
import os
import sys
from collections import defaultdict

import nltk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wordbank import load_wordbank, CATEGORY_TO_POS, GRADES, _DATA_DIR

OUT_PATH = os.path.join(_DATA_DIR, "static_vocab_source.json")


def _ensure_corpus():
    for c in ("wordnet", "omw-1.4"):
        try:
            nltk.data.find(f"corpora/{c}")
        except LookupError:
            nltk.download(c, quiet=True)


def _synsets_for(wn, word, category):
    syns = []
    for pos in CATEGORY_TO_POS[category]:
        syns.extend(wn.synsets(word, pos=pos))
    return syns


def _single_token(name):
    """WordNet lemma names use '_' for phrases; keep single words only."""
    return name.replace("-", "").isalpha() and "_" not in name


def synonym_candidates(wn, word, category):
    cands = set()
    for s in _synsets_for(wn, word, category):
        for lem in s.lemmas():
            cands.add(lem.name().lower())
        # adjective satellites: pull "similar to" head synsets for recall
        if category == "Adjective":
            for sim in s.similar_tos():
                for lem in sim.lemmas():
                    cands.add(lem.name().lower())
    cands.discard(word)
    return {c for c in cands if _single_token(c)}


def antonym_candidates(wn, word, category):
    cands = set()
    for s in _synsets_for(wn, word, category):
        for lem in s.lemmas():
            for ant in lem.antonyms():
                cands.add(ant.name().lower())
                # antonyms of derivationally related forms (recall boost)
                for drf in ant.derivationally_related_forms():
                    cands.add(drf.name().lower())
            # derivational-form antonyms of the word itself
            for drf in lem.derivationally_related_forms():
                for ant in drf.antonyms():
                    cands.add(ant.name().lower())
        if category == "Adjective":
            for sim in s.similar_tos():
                for lem in sim.lemmas():
                    for ant in lem.antonyms():
                        cands.add(ant.name().lower())
    cands.discard(word)
    return {c for c in cands if _single_token(c)}


def build(wb):
    from nltk.corpus import wordnet as wn

    mapping = defaultdict(dict)
    for r in wb.records:
        word, grade, cat = r["word"], r["grade"], r["category"]
        pool = wb.pool(grade, cat)  # same category, grade <= G
        syns = sorted((synonym_candidates(wn, word, cat) & pool))
        ants = sorted((antonym_candidates(wn, word, cat) & pool))
        mapping[str(grade)][word] = {
            "category": cat,
            "synonyms": syns,
            "antonyms": ants,
        }
    return mapping


def print_stats(mapping):
    print("\nRecall stats (words with >=1 synonym / >=1 antonym):")
    print(f"{'grade':>5} {'words':>7} {'has_syn':>8} {'has_ant':>8}")
    tot_w = tot_s = tot_a = 0
    for g in GRADES:
        entries = mapping.get(str(g), {})
        nw = len(entries)
        ns = sum(1 for e in entries.values() if e["synonyms"])
        na = sum(1 for e in entries.values() if e["antonyms"])
        tot_w += nw; tot_s += ns; tot_a += na
        print(f"{g:>5} {nw:>7} {ns:>8} {na:>8}")
    print(f"{'all':>5} {tot_w:>7} {tot_s:>8} {tot_a:>8}")


def main():
    _ensure_corpus()
    wb = load_wordbank()
    mapping = build(wb)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"wrote {OUT_PATH}")
    print_stats(mapping)
    # spot-check
    sample = mapping.get("2", {}).get("calm")
    print("\nsample grade-2 'calm':", sample)


if __name__ == "__main__":
    main()
