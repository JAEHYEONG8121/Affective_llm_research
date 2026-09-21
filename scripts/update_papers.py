from __future__ import annotations

import hashlib
import html
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import feedparser
import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "config/queries.yaml").read_text())
SEED = ROOT / "papers/seed.csv"
OUT_CSV = ROOT / "papers/papers.csv"
OUT_JSON = ROOT / "papers/papers.json"
README = ROOT / "README.md"

UA = {"User-Agent": "affective-llm-research-watch/2.0 (research bot; GitHub Actions)"}


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


def norm_title(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def score_text(title: str, abstract: str) -> tuple[int, list[str]]:
    text = f"{title} {abstract}".lower()
    score = 0
    hits = []
    for group, terms in CFG["keywords"].items():
        for term, weight in terms.items():
            if term.lower() in text:
                score += int(weight)
                hits.append(term)
    return score, sorted(set(hits))


def classify_text(title: str, abstract: str) -> dict[str, str]:
    text = f" {title} {abstract} ".lower()
    out = {}
    for axis, labels in CFG.get("categories", {}).items():
        matched = []
        for label, terms in labels.items():
            if any(term.lower() in text for term in terms):
                matched.append(label)
        out[axis] = "; ".join(matched) if matched else "Uncategorized"
    return out


def fetch_arxiv(max_results: int = 40) -> list[dict]:
    rows = []
    for q in CFG["arxiv_queries"]:
        url = (
            "https://export.arxiv.org/api/query?search_query="
            + quote(q)
            + f"&start=0&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
        )
        feed = feedparser.parse(url)
        for e in feed.entries:
            title = clean(e.title)
            abstract = clean(getattr(e, "summary", ""))
            score, hits = score_text(title, abstract)
            cats = classify_text(title, abstract)
            if score < 10:
                continue
            arxiv_id = e.id.rsplit("/", 1)[-1]
            year = int(getattr(e, "published", "0000")[:4] or 0)
            if year < 2025:
                continue
            rows.append({
                "title": title,
                "year": year,
                "venue": "arXiv",
                "type": "preprint",
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "relevance": "AUTO",
                "score": score,
                "matched_terms": "; ".join(hits),
                "why_it_matters": abstract[:700],
                "source": "arXiv",
                "discovered_at": datetime.now(timezone.utc).isoformat(),
                **cats,
            })
        time.sleep(3)
    return rows


def fetch_openalex(per_query: int = 30) -> list[dict]:
    rows = []
    for q in CFG["openalex_searches"]:
        params = {
            "search": q,
            "filter": "from_publication_date:2025-01-01",
            "sort": "publication_date:desc",
            "per-page": per_query,
        }
        r = requests.get("https://api.openalex.org/works", params=params, headers=UA, timeout=30)
        r.raise_for_status()
        for w in r.json().get("results", []):
            title = clean(w.get("title", ""))
            abstract = ""  # OpenAlex abstracts are inverted-index encoded; title scoring keeps this robust.
            score, hits = score_text(title, abstract)
            cats = classify_text(title, abstract)
            if score < 8:
                continue
            loc = w.get("primary_location") or {}
            source = loc.get("source") or {}
            venue = source.get("display_name") or "OpenAlex"
            url = w.get("doi") or loc.get("landing_page_url") or w.get("id")
            rows.append({
                "title": title,
                "year": w.get("publication_year", ""),
                "venue": venue,
                "type": w.get("type", "work"),
                "url": url,
                "relevance": "AUTO",
                "score": score,
                "matched_terms": "; ".join(hits),
                "why_it_matters": "Auto-discovered via OpenAlex; inspect manually before promoting to relevance A/B.",
                "source": "OpenAlex",
                "discovered_at": datetime.now(timezone.utc).isoformat(),
                **cats,
            })
        time.sleep(1)
    return rows


def load_seed() -> list[dict]:
    df = pd.read_csv(SEED)
    rows = df.to_dict("records")
    for x in rows:
        cats = classify_text(str(x.get("title", "")), str(x.get("why_it_matters", "")))
        for k, v in cats.items():
            x.setdefault(k, v)
        x.setdefault("score", 999 if x["relevance"] == "A" else 500)
        x.setdefault("matched_terms", "manual seed")
        x.setdefault("source", "manual seed")
        x.setdefault("discovered_at", "2026-09-21")
    return rows


def dedupe(rows: list[dict]) -> pd.DataFrame:
    best = {}
    for row in rows:
        key = norm_title(str(row.get("title", "")))
        if not key:
            continue
        prev = best.get(key)
        if prev is None or float(row.get("score", 0) or 0) > float(prev.get("score", 0) or 0):
            best[key] = row
    df = pd.DataFrame(best.values())
    if not df.empty:
        df["score"] = pd.to_numeric(df.get("score", 0), errors="coerce").fillna(0)
        df = df.sort_values(["relevance", "score", "year"], ascending=[True, False, False])
    return df


def render_readme(df: pd.DataFrame) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    curated = df[df["relevance"].isin(["A", "B"])].copy()
    auto = df[df["relevance"] == "AUTO"].sort_values("score", ascending=False).head(60).copy()

    def rows_to_md(x: pd.DataFrame) -> str:
        if x.empty:
            return "_No papers yet._"
        lines = ["| Tier | Year | Venue | Paper | System | Contribution | Affect focus | Psychology/Theory |", "|---|---:|---|---|---|---|---|---|"]
        for _, r in x.iterrows():
            title = str(r["title"]).replace("|", "\\|")
            vals = [str(r.get(k, "Uncategorized")).replace("|", "\\|") for k in ["system_type","contribution_type","affect_focus","theory"]]
            lines.append(f"| {r['relevance']} | {r['year']} | {r['venue']} | [{title}]({r['url']}) | {vals[0]} | {vals[1]} | {vals[2]} | {vals[3]} |")
        return "\n".join(lines)

    return f"""# Affective LLM & Agent Research Watch

A broad, auto-maintained literature radar for **how LLMs and agents understand, represent, generate, regulate, align with, and adapt to human affect**. It intentionally goes beyond appraisal/RL and covers affective computing, emotional intelligence, empathy, social cognition, multimodal emotion, psychology-grounded modeling, alignment, training/tuning, and affective agents.

**Owner:** JAEHYEONG8121  
**Last automatic refresh (UTC):** {today}

## Taxonomy

Every discovered paper is multi-labeled on four axes:

1. **System** — `LLM`, `Agent`, `Multimodal`
2. **Contribution** — `Evaluation-Benchmark`, `Framework-Architecture`, `Training-Tuning`, `Alignment-Steering`, `Dataset-Resource`, `Representation-Mechanism`
3. **Affect focus** — `Emotion-Understanding`, `Empathy-Support`, `Emotional-Intelligence`, `Emotion-Generation`, `Emotion-Regulation`, `Dynamic-Affect`, `Personality-Individual-Differences`
4. **Psychology / theory** — `Appraisal-Theory`, `Theory-of-Mind`, `Empathy-Theory`, `Emotional-Intelligence-Theory`, `Personality-Theory`, `Emotion-Regulation-Theory`, `Dual-Process-Theory`

Labels are intentionally **multi-valued**. A paper can be, for example, `Agent + Framework + Empathy + Theory-of-Mind`.

## Curated starting set

{rows_to_md(curated)}

## Newly auto-discovered candidates

These are high-recall machine-filtered candidates, not automatically treated as verified related work.

{rows_to_md(auto)}

## Search scope

The daily watcher searches arXiv and OpenAlex across emotional intelligence, affective computing, emotion understanding/recognition/reasoning/generation, empathy and emotional support, emotion regulation, personality and individual differences, social cognition/Theory of Mind, affective agents, multimodal affect, psychology-grounded modeling, alignment/steering, RL/reward modeling, and appraisal.

Priority venues include ICLR, ICML, NeurIPS, ACL, EMNLP, NAACL, AAAI, IJCAI, AAMAS, CHI, CSCW, IUI, ACII, WASSA, LREC, and COLM. Venue metadata is rechecked through OpenAlex; official proceedings should be used for final citation/acceptance verification.

## Daily automation

GitHub Actions runs daily at **06:00 KST (21:00 UTC)**, executes `scripts/update_papers.py`, deduplicates by normalized title, updates CSV/JSON, rebuilds this README, and commits only when content changed.

```bash
pip install -r requirements.txt
python scripts/update_papers.py
```

Edit `config/queries.yaml` to add theories, emotions, tasks, or venues without changing Python code.

## Research-use warning

This repository is designed as a **high-recall discovery radar**. Automatic labels are keyword-derived and therefore should not be treated as claims about a paper without reading it. For a systematic review, add a human screening stage and record inclusion/exclusion decisions separately.
"""


def main():
    rows = load_seed()
    errors = []
    for fn in (fetch_arxiv, fetch_openalex):
        try:
            rows.extend(fn())
        except Exception as e:
            errors.append(f"{fn.__name__}: {e}")
    df = dedupe(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    OUT_JSON.write_text(json.dumps(df.to_dict("records"), ensure_ascii=False, indent=2), encoding="utf-8")
    README.write_text(render_readme(df), encoding="utf-8")
    if errors:
        print("Completed with source warnings:")
        for e in errors:
            print(" -", e)
    print(f"Wrote {len(df)} unique papers")


if __name__ == "__main__":
    main()
