"""Step 5 — critique/refine analogy candidates into the served bank.

Reads data/analogy_source.json (step-4 recall output) and trims it down to a
trustworthy served pool, in two layers:

  Layer A — deterministic invariants (no API): drop any candidate unless all
    words exist in-bank at grade <= G, the 5 pairs use 10 distinct words, stem &
    answer satisfy the relation, every distractor does NOT satisfy it (both
    orderings for symmetric relations), and the question is unique within grade.
    Fully reproducible; this alone yields a structurally sound bank.

  Layer B — LLM solve pass: an independent Claude pass sees each question as a
    human would (stem + 4 shuffled choices, no answer key) and returns
    {chosen_index, verdict, reason}. A question is removed if the solver picks
    the wrong choice (ambiguous/unsolvable) or flags it remove (niche/wrong
    sense). Decisions are cached to data/analogy_critique.jsonl keyed by id so
    re-runs don't re-call the API. If the API/SDK is unavailable, Layer B is
    skipped and the pipeline runs on Layer A alone.

Guarantees each grade still meets its minimum after culling (asserts, fails
loudly otherwise). Output: data/analogy_bank.json (the served artifact).
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wordbank import load_wordbank, GRADES, _DATA_DIR
import build_analogies as ba

SRC_PATH = os.path.join(_DATA_DIR, "analogy_source.json")
OUT_PATH = os.path.join(_DATA_DIR, "analogy_bank.json")
CACHE_PATH = os.path.join(_DATA_DIR, "analogy_critique.jsonl")

MODEL = "claude-opus-4-8"
USE_LLM = os.environ.get("ANALOGY_NO_LLM") != "1"


# -- Layer A: deterministic invariants -------------------------------------

def layer_a(source, wb, mapping):
    buckets = ba.build_pairs(wb, mapping)
    min_grade = ba.build_word_min_grade(wb)
    kept = {}
    dropped = 0
    for g in GRADES:
        at_g = ba.pairs_at_grade(buckets, min_grade, g)
        seen = set()
        out = []
        for q in source.get(str(g), []):
            stem = tuple(q["stem"])
            answer = tuple(q["answer"])
            dists = [tuple(d["pair"]) for d in q["distractors"]]
            R = q["relation"]
            words = [*stem, *answer]
            for d in dists:
                words.extend(d)
            if len(set(words)) != 10:                         # 5 pairs, 10 distinct words
                dropped += 1; continue
            if any(min_grade.get(w, 99) > g for w in words):  # all in-bank <= G
                dropped += 1; continue
            if not (ba._relation_holds(R, *stem, at_g) and
                    ba._relation_holds(R, *answer, at_g)):     # stem/answer hold R
                dropped += 1; continue
            bad = False
            for (x, y) in dists:                               # distractors break R
                if ba._relation_holds(R, x, y, at_g):
                    bad = True; break
                if R in ba.SYMMETRIC and ba._relation_holds(R, y, x, at_g):
                    bad = True; break
            if bad:
                dropped += 1; continue
            key = ba._dedupe_key(R, stem, answer)
            if key in seen:
                dropped += 1; continue
            seen.add(key)
            out.append({
                "id": q["id"], "relation": R,
                "stem": list(stem), "answer": list(answer),
                "distractors": [list(d) for d in dists],
            })
        kept[str(g)] = out
    return kept, dropped


# -- Layer B: LLM solve pass ------------------------------------------------

_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "chosen_index": {"type": "integer", "enum": [0, 1, 2, 3]},
            "verdict": {"type": "string", "enum": ["keep", "remove"]},
            "reason": {"type": "string"},
        },
        "required": ["chosen_index", "verdict", "reason"],
        "additionalProperties": False,
    },
}
_SYSTEM = (
    "You solve grade-school multiple-choice verbal analogy questions. For each "
    "question, the stem is a word pair with some relationship (synonyms, antonyms, "
    "category/is-a, or part-whole). Choose the single answer pair (by index) whose "
    "two words share that SAME relationship. Then judge the question: verdict "
    "'keep' if it is sensible, fair, and has exactly one defensible answer; "
    "'remove' if it is nonsensical, too niche/obscure for a child, ambiguous, or "
    "has zero or multiple defensible answers."
)


def _question_text(q, rng):
    """Render a question for the solver with a deterministic choice order."""
    pairs = [q["answer"]] + q["distractors"]
    rng.shuffle(pairs)
    answer_index = pairs.index(q["answer"])
    lines = [f"Analogy stem:  {q['stem'][0]} : {q['stem'][1]}",
             "Which pair has the SAME relationship as the stem?"]
    for i, p in enumerate(pairs):
        lines.append(f"({i}) {p[0]} : {p[1]}")
    return "\n".join(lines), answer_index


def _load_cache():
    cache = {}
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    cache[rec["id"]] = rec
    return cache


def _append_cache(records):
    with open(CACHE_PATH, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def layer_b(kept, seed=ba.SEED):
    """Annotate each kept question with a solver decision; return id->record.

    Returns {} (skip Layer B) if the SDK/key is unavailable.
    """
    try:
        import anthropic
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request
    except Exception as e:
        print(f"[Layer B] anthropic SDK unavailable ({e}); skipping LLM critique.")
        return {}

    cache = _load_cache()
    rng = random.Random(seed)
    # Build the solver view for every kept question; reuse cache where present.
    answer_index = {}
    pending = []
    for g in GRADES:
        for q in kept[str(g)]:
            text, ai = _question_text(q, rng)
            answer_index[q["id"]] = ai
            if q["id"] not in cache:
                pending.append((q["id"], text))

    if pending:
        try:
            client = anthropic.Anthropic()
        except Exception as e:
            print(f"[Layer B] no API client ({e}); skipping LLM critique.")
            return {}
        print(f"[Layer B] submitting {len(pending)} questions to the Batches API…")
        requests = [
            Request(
                custom_id=qid,
                params=MessageCreateParamsNonStreaming(
                    model=MODEL,
                    max_tokens=256,
                    system=_SYSTEM,
                    output_config={"effort": "low", "format": _FORMAT},
                    messages=[{"role": "user", "content": text}],
                ),
            )
            for qid, text in pending
        ]
        batch = client.messages.batches.create(requests=requests)
        print(f"[Layer B] batch {batch.id}; polling…")
        import time
        while True:
            b = client.messages.batches.retrieve(batch.id)
            if b.processing_status == "ended":
                break
            time.sleep(30)
        new = []
        for result in client.messages.batches.results(batch.id):
            if result.result.type != "succeeded":
                continue
            msg = result.result.message
            text = next((blk.text for blk in msg.content if blk.type == "text"), "")
            try:
                data = json.loads(text)
            except Exception:
                continue
            new.append({"id": result.custom_id,
                        "chosen_index": data["chosen_index"],
                        "verdict": data["verdict"],
                        "reason": data.get("reason", "")})
        _append_cache(new)
        for rec in new:
            cache[rec["id"]] = rec
        print(f"[Layer B] received {len(new)} decisions.")

    # attach the answer_index used so the merge can compare
    for qid, rec in cache.items():
        if qid in answer_index:
            rec["answer_index"] = answer_index[qid]
    return cache


def merge(kept, decisions):
    """Drop questions the solver got wrong or flagged remove. No-op if empty."""
    if not decisions:
        return kept, 0
    out = {}
    removed = 0
    for g in GRADES:
        survivors = []
        for q in kept[str(g)]:
            rec = decisions.get(q["id"])
            if rec is None:                       # un-graded (e.g. batch error) -> keep
                survivors.append(q); continue
            if rec["verdict"] == "remove" or rec.get("chosen_index") != rec.get("answer_index"):
                removed += 1; continue
            survivors.append(q)
        out[str(g)] = survivors
    return out, removed


# -- driver -----------------------------------------------------------------

def print_stats(bank, dropped_a, removed_b):
    print(f"\nLayer A dropped {dropped_a}; Layer B removed {removed_b}.")
    print("Served analogy questions per grade (min required / kept):")
    print(f"{'grade':>5} {'min':>5} {'kept':>6}")
    for g in GRADES:
        n = len(bank[str(g)])
        flag = "" if n >= ba.MIN_PER_GRADE[g] else "  *** BELOW MIN ***"
        print(f"{g:>5} {ba.MIN_PER_GRADE[g]:>5} {n:>6}{flag}")


def main():
    with open(SRC_PATH, encoding="utf-8") as f:
        source = json.load(f)
    wb = load_wordbank()
    with open(ba.MAPPING_PATH, encoding="utf-8") as f:
        mapping = json.load(f)

    kept, dropped_a = layer_a(source, wb, mapping)
    decisions = layer_b(kept) if USE_LLM else {}
    bank, removed_b = merge(kept, decisions)

    for g in GRADES:
        n = len(bank[str(g)])
        assert n >= ba.MIN_PER_GRADE[g], (
            f"grade {g}: only {n} kept, need {ba.MIN_PER_GRADE[g]} — "
            f"raise OVERGEN/relax STRUCTURAL_CAP in build_analogies and re-run step 4")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"wrote {OUT_PATH}")
    print_stats(bank, dropped_a, removed_b)


if __name__ == "__main__":
    main()
