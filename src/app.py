"""Flask web app for the verbal quiz generator.

  GET  /              -> the quiz form (grade + per-type counts)
  POST /api/generate  -> JSON quiz for the requested grade/counts

The synonym + antonym generators are reused directly from generators.py.
Analogy is stubbed until the user adds the generation logic.
"""
import os

from flask import Flask, jsonify, render_template, request

from generators import QuizGenerator
from wordbank import GRADES

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(
    __name__,
    template_folder=os.path.join(_ROOT, "templates"),
    static_folder=os.path.join(_ROOT, "static"),
)

GEN = QuizGenerator()
MAX_PER_TYPE = 50


def _clamp_count(raw):
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(0, min(n, MAX_PER_TYPE))


@app.route("/")
def index():
    return render_template("index.html", grades=GRADES)


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json(silent=True) or {}
    grade = data.get("grade")
    if grade not in GRADES and str(grade) not in [str(g) for g in GRADES]:
        return jsonify({"error": "invalid grade"}), 400
    grade = int(grade)

    n_syn = _clamp_count(data.get("n_synonym"))
    n_ant = _clamp_count(data.get("n_antonym"))
    n_ana = _clamp_count(data.get("n_analogy"))
    seed = data.get("seed")  # optional, for reproducible quizzes

    synonym = GEN.synonym_quiz(n_syn, grade, seed=seed)
    antonym = GEN.antonym_quiz(n_ant, grade, seed=seed)
    analogy = GEN.analogy_quiz(n_ana, grade, seed=seed)

    resp = {
        "grade": grade,
        "synonym": synonym,
        "antonym": antonym,
        "analogy": analogy,
        "requested": {"synonym": n_syn, "antonym": n_ant, "analogy": n_ana},
        "served": {"synonym": len(synonym), "antonym": len(antonym), "analogy": len(analogy)},
    }
    return jsonify(resp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))  # 5000 is taken by macOS AirPlay
    app.run(debug=True, port=port)
