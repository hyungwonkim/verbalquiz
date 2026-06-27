"""Step 7 — assemble the static, server-less web bundle into docs/.

The static deploy (GitHub Pages / Cloudflare Pages) runs no Python: the browser
fetches the same data artifacts the Flask generator read and does all
sampling/shuffling client-side (web/app.js is the JS port of generators.py).
This script just collects the published files into docs/:

  web/index.html  web/app.js  static/style.css   -> docs/
  data/verified_mapping.json  data/analogy_bank.json -> docs/data/
  data/verbal_word_bank.csv   --(convert)-->        -> docs/data/wordbank.json

GitHub Pages: repo Settings -> Pages -> Deploy from branch -> /docs.

Re-run after any pipeline change (build_mapping/verify_mapping/build_analogies/
critique_analogies) to refresh the published data, then commit docs/ and push.
"""
import csv
import json
import os
import shutil
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
WEB = os.path.join(ROOT, "web")
STATIC = os.path.join(ROOT, "static")
DOCS = os.path.join(ROOT, "docs")
DOCS_DATA = os.path.join(DOCS, "data")

CSV_PATH = os.path.join(DATA, "verbal_word_bank.csv")


def wordbank_json():
    """CSV -> {category: {grade(str): [words]}} — the browser's distractor pools."""
    seen = defaultdict(set)  # (category, grade) -> set(words)
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            w = (row.get("Word") or "").strip().lower()
            c = (row.get("Category") or "").strip()
            g = (row.get("Grade") or "").strip()
            if not w or not c or not g.isdigit():
                continue
            seen[(c, g)].add(w)
    out = defaultdict(dict)
    for (c, g), words in seen.items():
        out[c][g] = sorted(words)
    return dict(out)


def main():
    os.makedirs(DOCS_DATA, exist_ok=True)

    # 1. web sources + stylesheet
    shutil.copy2(os.path.join(WEB, "index.html"), os.path.join(DOCS, "index.html"))
    shutil.copy2(os.path.join(WEB, "app.js"), os.path.join(DOCS, "app.js"))
    shutil.copy2(os.path.join(STATIC, "style.css"), os.path.join(DOCS, "style.css"))

    # 2. served data artifacts (verbatim copies)
    for name in ("verified_mapping.json", "analogy_bank.json"):
        shutil.copy2(os.path.join(DATA, name), os.path.join(DOCS_DATA, name))

    # 3. word bank: CSV -> compact JSON pools
    wb = wordbank_json()
    with open(os.path.join(DOCS_DATA, "wordbank.json"), "w", encoding="utf-8") as f:
        json.dump(wb, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    # 4. .nojekyll so Pages serves files verbatim (no Jekyll processing)
    open(os.path.join(DOCS, ".nojekyll"), "w").close()

    total = sum(len(v) for cat in wb.values() for v in cat.values())
    print(f"wrote {DOCS}")
    print(f"  index.html, app.js, style.css")
    print(f"  data/verified_mapping.json, data/analogy_bank.json")
    print(f"  data/wordbank.json  ({total} word-grade-category entries)")
    print("\nNext: commit docs/ and push; enable GitHub Pages from /docs.")


if __name__ == "__main__":
    main()
