"""Accuracy check: ask every test question of every sample document and score the answers.

    backend/.venv/Scripts/python eval/run_eval.py            # uses the configured model (or no-key mode)
    backend/.venv/Scripts/python eval/run_eval.py --no-llm   # force no-key (extractive) mode

Writes eval/results/latest.json (shown in the app's Accuracy tab) and latest.md.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"(?<=\d),(?=\d)", "", s)
    return re.sub(r"\s+", " ", s)


def answer_text(res: dict) -> str:
    return " ".join(s["text"] for s in res.get("sentences", []))


def run(no_llm: bool = False, delay: float = 0.0) -> dict:
    if no_llm:
        os.environ["LLM_PROVIDER"] = "none"
    from app import llm, store
    from app.answer import answer_question
    from app.retrieval import embedder

    spec = json.loads((HERE / "testset.json").read_text(encoding="utf-8"))
    store.ensure_samples()
    act = llm.active()
    report = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "mode": "llm" if act else "extractive",
        "provider": act[0] if act else None,
        "model": act[1] if act else None,
        "embeddings": embedder.ok,
        "runs": [],
    }
    for doc_id in spec["docs"]:
        doc = store.get(doc_id)
        items = []
        for t in spec["questions"]:
            answerable = t.get("answerable", True)
            t0 = time.perf_counter()
            res = answer_question(doc, t["q"])
            ms = int((time.perf_counter() - t0) * 1000)
            text = answer_text(res)
            expect_pages = {p - 1 for p in t.get("pages", [])}
            cited = [c for c in res.get("citations", []) if c["status"] != "unverified"]
            if answerable:
                correct = res["found"] and all(norm(e) in norm(text) for e in t["expect"])
            else:
                correct = not res["found"]
            item = {
                "q": t["q"], "answerable": answerable, "correct": bool(correct), "found": res["found"],
                "answer": text, "mode": res["mode"], "ms": ms, "note": res.get("note"),
                "retrieval_hit": (bool(expect_pages & {s["page"] for s in res["sources"]}) if answerable else None),
                "cited_pages": sorted({c["page"] + 1 for c in cited}),
                "citations": [{"n": c["n"], "page": c["page"] + 1, "score": c["score"], "label": c["label"],
                               "status": c["status"]} for c in res.get("citations", [])],
                "sentence_status": [s["status"] for s in res.get("sentences", [])],
                "citations_on_expected_pages": (sum(c["page"] in expect_pages for c in cited), len(cited))
                if answerable and expect_pages else None,
            }
            items.append(item)
            mark = "PASS" if correct else "FAIL"
            print(f"[{doc_id}] {mark} {t['q'][:60]!r} -> {text[:90]!r}")
            if delay:
                time.sleep(delay)
        report["runs"].append({"doc": doc_id, "doc_name": doc.meta["name"], "kind": doc.meta["kind"],
                               "summary": summarize(items), "items": items})
    return report


def summarize(items: list[dict]) -> dict:
    ans = [i for i in items if i["answerable"]]
    una = [i for i in items if not i["answerable"]]
    on = sum(i["citations_on_expected_pages"][0] for i in ans if i["citations_on_expected_pages"])
    tot = sum(i["citations_on_expected_pages"][1] for i in ans if i["citations_on_expected_pages"])
    sentences = [s for i in ans if i["found"] for s in i["sentence_status"]]
    grounded = sum(s in ("supported", "passage") for s in sentences)
    pct = lambda a, b: round(100 * a / b, 1) if b else None
    return {
        "questions": len(items),
        "correct": sum(i["correct"] for i in items),
        "accuracy": pct(sum(i["correct"] for i in items), len(items)),
        "answerable_accuracy": pct(sum(i["correct"] for i in ans), len(ans)),
        "refusal_accuracy": pct(sum(i["correct"] for i in una), len(una)),
        "retrieval_hit_rate": pct(sum(bool(i["retrieval_hit"]) for i in ans), len(ans)),
        "citation_page_precision": pct(on, tot),
        "grounded_sentences": pct(grounded, len(sentences)),
        "avg_ms": int(sum(i["ms"] for i in items) / max(len(items), 1)),
    }


def write(report: dict) -> None:
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    (out / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    stamp = report["generated_at"][:19].replace(":", "").replace("-", "")
    (out / f"run-{stamp}-{report['mode']}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                                             encoding="utf-8")
    lines = [f"# Accuracy check ({report['mode']}"
             + (f", {report['provider']} {report['model']}" if report["provider"] else "") + ")", "",
             f"Run {report['generated_at']}. Hybrid search embeddings: {'on' if report['embeddings'] else 'off'}.", "",
             "| Document | Correct | Answerable | Says \"not in document\" when it isn't | Retrieval hit | "
             "Citations on the right page | Grounded sentences | Avg time |",
             "|---|---|---|---|---|---|---|---|"]
    for r in report["runs"]:
        s = r["summary"]
        fmt = lambda v, unit="%": "n/a" if v is None else f"{v}{unit}"
        lines.append(f"| {r['kind']} | {s['correct']}/{s['questions']} ({fmt(s['accuracy'])}) | "
                     f"{fmt(s['answerable_accuracy'])} | {fmt(s['refusal_accuracy'])} | {fmt(s['retrieval_hit_rate'])} | "
                     f"{fmt(s['citation_page_precision'])} | {fmt(s['grounded_sentences'])} | {s['avg_ms']} ms |")
    lines += ["", "Failures:", ""]
    for r in report["runs"]:
        for i in r["items"]:
            if not i["correct"]:
                lines.append(f"- {r['kind']}: {i['q']} -> {i['answer'][:160] or '(not found)'}")
    (out / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true", help="force no-key (extractive) mode")
    ap.add_argument("--delay", type=float, default=0.0, help="seconds between questions (free-tier rate limits)")
    args = ap.parse_args()
    rep = run(args.no_llm, args.delay)
    write(rep)
    for r in rep["runs"]:
        print(r["kind"], json.dumps(r["summary"]))
