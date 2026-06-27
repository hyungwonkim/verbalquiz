"""Word bank loader + pool helpers shared across the pipeline.

Loads data/verbal_word_bank.csv (columns: Word, Grade, Category) and exposes
lookups used by step 1 (recall pool: grade <= G) and step 3 (distractor pool:
same grade G). All words are normalized to lowercase.
"""
import csv
import os
from collections import defaultdict

# nltk POS tags are imported lazily so non-WordNet consumers (generators, app)
# don't pay the import cost.
CATEGORY_TO_POS = {
    "Noun": ["n"],
    "Verb": ["v"],
    "Adjective": ["a", "s"],  # 'a' = adjective, 's' = adjective satellite
}

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DEFAULT_CSV = os.path.join(_DATA_DIR, "verbal_word_bank.csv")
GRADES = [1, 2, 3, 4, 5, 6]


class WordBank:
    def __init__(self, records):
        # records: list of dicts {word, grade, category}
        self.records = records
        # (grade, category) -> set(words)  exact grade
        self._by_grade_cat = defaultdict(set)
        # word -> category (a word may appear once per category; keep set)
        self._word_categories = defaultdict(set)
        # word -> min grade it appears at (for any category)
        for r in records:
            self._by_grade_cat[(r["grade"], r["category"])].add(r["word"])
            self._word_categories[r["word"]].add(r["category"])

    def categories_of(self, word):
        return self._word_categories.get(word, set())

    def same_grade_pool(self, grade, category):
        """Words of `category` at exactly `grade` (step 3 distractor pool)."""
        return set(self._by_grade_cat.get((grade, category), set()))

    def pool(self, grade, category):
        """Words of `category` at any grade <= `grade` (step 1 recall pool)."""
        out = set()
        for g in GRADES:
            if g > grade:
                break
            out |= self._by_grade_cat.get((g, category), set())
        return out

    def widened_pool(self, grade, category):
        """Same as pool() — used as step-3 fallback when same-grade is too small."""
        return self.pool(grade, category)


def load_words(csv_path=DEFAULT_CSV):
    records = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            word = (row.get("Word") or "").strip().lower()
            cat = (row.get("Category") or "").strip()
            graderaw = (row.get("Grade") or "").strip()
            if not word or not cat or not graderaw.isdigit():
                continue
            records.append({"word": word, "grade": int(graderaw), "category": cat})
    return records


def load_wordbank(csv_path=DEFAULT_CSV):
    return WordBank(load_words(csv_path))


if __name__ == "__main__":
    wb = load_wordbank()
    print(f"loaded {len(wb.records)} records")
    print("grade-2 adjectives sample:", sorted(wb.same_grade_pool(2, "Adjective"))[:10])
    print("grade<=2 adjective pool size:", len(wb.pool(2, "Adjective")))
