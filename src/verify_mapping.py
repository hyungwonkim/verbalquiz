"""Step 2 — precision-first verification of the step-1 mapping.

Reads data/static_vocab_source.json (recall-heavy) and trims loosely-related
pairs so the served pool is trustworthy. Each word is reduced to its top-N
*dominant sense cluster* (TOP_SENSES) and relations are re-derived against it:

  Synonyms: keep candidate only if its OWN dominant cluster overlaps the word's
    cluster (symmetric membership). This drops asymmetric weak links from rare
    senses (old->gray, run->melt) while keeping true synonyms (tiny->small).
  Antonyms: keep only WordNet antonym links reachable from the word's dominant
    cluster (lemma.antonyms, incl. adjective similar_to satellites). The
    derivational expansions added for recall in step 1 are dropped.

Precision favors a clean answer key over coverage: many words end up with empty
lists, which is fine — generators simply draw from words that have entries.
TOP_SENSES is a module constant: raise for recall, lower for precision.

Output: data/verified_mapping.json (same shape as step 1).
"""
import json
import os
import sys
from collections import defaultdict

import nltk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wordbank import CATEGORY_TO_POS, GRADES, _DATA_DIR

IN_PATH = os.path.join(_DATA_DIR, "static_vocab_source.json")
OUT_PATH = os.path.join(_DATA_DIR, "verified_mapping.json")

# Polysemy guard: a synonym/antonym is only kept if it belongs to the word's
# top-N sense cluster — the N most-frequent synsets within the word's category
# (WordNet orders synsets() by frequency), plus their similar_to satellites for
# adjectives. N=2 keeps the dominant + one secondary common sense (so calm ->
# quiet/smooth and big -> large survive) while excluding the long tail of rare
# senses that readmit loose pairs (run -> melt, cold -> dead). Raise for recall,
# lower for precision.
TOP_SENSES = 2


def _ensure_corpus():
    for c in ("wordnet", "omw-1.4"):
        try:
            nltk.data.find(f"corpora/{c}")
        except LookupError:
            nltk.download(c, quiet=True)


_CLUSTER_CACHE = {}


def _dominant_cluster(wn, word, category):
    """Synset cluster for the word's top-N senses (polysemy guard).

    WordNet's `synsets()` is frequency-ordered, so the first synsets within the
    word's category are its common senses. We take the top TOP_SENSES of them
    (across the category's POS list as one ordered stream, so an adjective isn't
    double-counted from its 'a' and 's' lists). For adjectives each anchor's
    `similar_to` satellites are folded in, because adjective synonymy is encoded
    through similar_to links rather than shared membership (e.g. cold.a.01 ~ icy).
    The rare-sense tail is excluded — that is what churns loose pairs.
    Cached per (word, category).
    """
    key = (word, category)
    if key in _CLUSTER_CACHE:
        return _CLUSTER_CACHE[key]
    poss = set(CATEGORY_TO_POS[category])
    ordered = [s for s in wn.synsets(word) if s.pos() in poss][:TOP_SENSES]
    cluster = set(ordered)
    if category == "Adjective":
        for s in ordered:
            cluster.update(s.similar_tos())
    _CLUSTER_CACHE[key] = cluster
    return cluster


def verify_synonym(cluster, wn, cand, category):
    """Candidate is a synonym iff its OWN top-N cluster overlaps the word's
    cluster (symmetric / mutual dominant-sense membership).

    Requiring the shared sense to be common to *both* words kills asymmetric
    weak links: "gray" is similar_to a minor sense of "old", but old's sense
    isn't among gray's common senses (gray is dominantly the color), so the pair
    drops. "calm"<->"quiet" survive because the shared sense is dominant for
    both. WordNet path_similarity is deliberately NOT used — adjective satellites
    return a constant ~0.33 to nearly anything, which only readmits noise.
    """
    cand_cluster = _dominant_cluster(wn, cand, category)
    if not cluster or not cand_cluster:
        return False
    return bool(cluster & cand_cluster)


def _cluster_antonyms(cluster):
    """Antonyms reachable from the dominant-sense cluster only.

    The cluster already contains the adjective similar_to satellites, so their
    antonym links are covered. Restricting to the cluster keeps cold->hot,warm
    while dropping wrong-sense antonyms (cold->alive, near) from minor senses.
    """
    out = set()
    for s in cluster:
        for lem in s.lemmas():
            for ant in lem.antonyms():
                out.add(ant.name().lower())
    return out


def verify(mapping):
    from nltk.corpus import wordnet as wn

    out = defaultdict(dict)
    stats = {"syn_in": 0, "syn_out": 0, "ant_in": 0, "ant_out": 0}
    for grade, entries in mapping.items():
        for word, e in entries.items():
            cat = e["category"]
            cluster = _dominant_cluster(wn, word, cat)
            keep_syn = [c for c in e["synonyms"] if verify_synonym(cluster, wn, c, cat)]
            direct = _cluster_antonyms(cluster)
            keep_ant = [c for c in e["antonyms"] if c in direct]

            stats["syn_in"] += len(e["synonyms"]); stats["syn_out"] += len(keep_syn)
            stats["ant_in"] += len(e["antonyms"]); stats["ant_out"] += len(keep_ant)

            if keep_syn or keep_ant:
                out[grade][word] = {
                    "category": cat,
                    "synonyms": sorted(keep_syn),
                    "antonyms": sorted(keep_ant),
                }
    return out, stats


def print_stats(out, stats):
    print("\nPrecision filter (kept / input pairs):")
    print(f"  synonyms: {stats['syn_out']} / {stats['syn_in']}")
    print(f"  antonyms: {stats['ant_out']} / {stats['ant_in']}")
    print("\nServed words with >=1 synonym / >=1 antonym per grade:")
    print(f"{'grade':>5} {'has_syn':>8} {'has_ant':>8}")
    for g in GRADES:
        entries = out.get(str(g), {})
        ns = sum(1 for e in entries.values() if e["synonyms"])
        na = sum(1 for e in entries.values() if e["antonyms"])
        print(f"{g:>5} {ns:>8} {na:>8}")


def main():
    _ensure_corpus()
    with open(IN_PATH, encoding="utf-8") as f:
        mapping = json.load(f)
    out, stats = verify(mapping)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"wrote {OUT_PATH}")
    print_stats(out, stats)
    print("\nsample grade-2 'calm':", out.get("2", {}).get("calm"))


if __name__ == "__main__":
    main()
