from __future__ import annotations

import hashlib
import html
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "config/queries.yaml").read_text(encoding="utf-8"))
SEED = ROOT / "papers/seed.csv"
OUT_CSV = ROOT / "papers/papers.csv"
OUT_JSON = ROOT / "papers/papers.json"
README = ROOT / "README.md"

KST = ZoneInfo("Asia/Seoul")
UA = {"User-Agent": "affective-llm-research-watch/3.0 (research bot; GitHub Actions)"}

SYSTEM_ORDER = ["LLM", "Agent", "Multimodal"]
CONTRIB_ORDER = [
    "Evaluation-Benchmark",
    "Framework-Architecture",
    "Training-Tuning",
    "Alignment-Steering",
    "Dataset-Resource",
    "Representation-Mechanism",
]

SYSTEM_EMOJI = {"LLM": "💬", "Agent": "🤖", "Multimodal": "🎧"}
CONTRIB_EMOJI = {
    "Evaluation-Benchmark": "📊",
    "Framework-Architecture": "🏗️",
    "Training-Tuning": "🛠️",
    "Alignment-Steering": "🧭",
    "Dataset-Resource": "🗂️",
    "Representation-Mechanism": "🧠",
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


def norm_title(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def split_labels(value: object) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    return [x.strip() for x in str(value).split(";") if x.strip() and x.strip() != "Uncategorized"]


def score_text(title: str, abstract: str) -> tuple[int, list[str]]:
    text = f"{title} {abstract}".lower()
    score = 0
    hits = []
    for _, terms in CFG["keywords"].items():
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
    import feedparser
    rows = []
    seen_at = now_utc().isoformat()
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
                "first_seen": seen_at,
                "last_seen": seen_at,
                **cats,
            })
        time.sleep(3)
    return rows


def invert_abstract(index: dict | None) -> str:
    if not index:
        return ""
    positioned = []
    for token, positions in index.items():
        for pos in positions:
            positioned.append((pos, token))
    return " ".join(token for _, token in sorted(positioned))


def fetch_openalex(per_query: int = 30) -> list[dict]:
    rows = []
    seen_at = now_utc().isoformat()
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
            abstract = clean(invert_abstract(w.get("abstract_inverted_index")))
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
                "why_it_matters": abstract[:700] if abstract else "Auto-discovered via OpenAlex.",
                "source": "OpenAlex",
                "first_seen": seen_at,
                "last_seen": seen_at,
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
        x.setdefault("score", 999 if x.get("relevance") == "A" else 500)
        x.setdefault("matched_terms", "manual seed")
        x.setdefault("source", "manual seed")
        # Seed papers are considered present from the repository's initial date.
        x.setdefault("first_seen", "2026-09-21T00:00:00+00:00")
        x.setdefault("last_seen", now_utc().isoformat())
    return rows


def load_existing() -> dict[str, dict]:
    if not OUT_CSV.exists():
        return {}
    try:
        df = pd.read_csv(OUT_CSV)
    except Exception:
        return {}
    result = {}
    for row in df.to_dict("records"):
        key = norm_title(str(row.get("title", "")))
        if not key:
            continue
        # Backward-compatible migration from the original discovered_at field.
        if not row.get("first_seen") or pd.isna(row.get("first_seen")):
            row["first_seen"] = row.get("discovered_at") or "2026-09-21T00:00:00+00:00"
        result[key] = row
    return result


def preserve_history(rows: list[dict], existing: dict[str, dict]) -> list[dict]:
    seen_now = now_utc().isoformat()
    out = []
    for row in rows:
        key = norm_title(str(row.get("title", "")))
        prev = existing.get(key)
        if prev:
            row["first_seen"] = prev.get("first_seen") or prev.get("discovered_at") or row.get("first_seen")
            # Preserve human curation if an AUTO rediscovery matches a curated item.
            if prev.get("relevance") in {"A", "B"} and row.get("relevance") == "AUTO":
                row["relevance"] = prev["relevance"]
            row["last_seen"] = seen_now
        else:
            row.setdefault("first_seen", seen_now)
            row["last_seen"] = seen_now
        out.append(row)
    return out


def dedupe(rows: list[dict]) -> pd.DataFrame:
    best = {}
    rank = {"A": 3, "B": 2, "AUTO": 1}
    for row in rows:
        key = norm_title(str(row.get("title", "")))
        if not key:
            continue
        prev = best.get(key)
        if prev is None:
            best[key] = row
            continue
        row_key = (rank.get(str(row.get("relevance")), 0), float(row.get("score", 0) or 0))
        prev_key = (rank.get(str(prev.get("relevance")), 0), float(prev.get("score", 0) or 0))
        if row_key > prev_key:
            # Never lose the original first-seen timestamp during deduplication.
            row["first_seen"] = prev.get("first_seen") or row.get("first_seen")
            best[key] = row
    df = pd.DataFrame(best.values())
    if not df.empty:
        df["score"] = pd.to_numeric(df.get("score", 0), errors="coerce").fillna(0)
        df["year"] = pd.to_numeric(df.get("year", 0), errors="coerce").fillna(0).astype(int)
        df = df.sort_values(["year", "score"], ascending=[False, False])
    return df


def md_escape(value: object) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def short_tags(value: object, emoji_map: dict[str, str] | None = None) -> str:
    labels = split_labels(value)
    if not labels:
        return "—"
    parts = []
    for label in labels:
        emoji = (emoji_map or {}).get(label, "")
        parts.append(f"{emoji} `{label}`".strip())
    return " ".join(parts)


def parse_dt(value: object) -> datetime | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def paper_table(x: pd.DataFrame, compact: bool = False) -> str:
    if x.empty:
        return "_No papers yet._"
    if compact:
        lines = [
            "| Paper | Venue | Focus | Method / Contribution |",
            "|---|---|---|---|",
        ]
        for _, r in x.iterrows():
            title = md_escape(r.get("title", ""))
            star = " ⭐" if str(r.get("relevance")) in {"A", "B"} else ""
            venue = md_escape(r.get("venue", ""))
            year = md_escape(r.get("year", ""))
            lines.append(
                f"| [{title}]({r.get('url', '')}){star} | {venue} · {year} | "
                f"{short_tags(r.get('affect_focus'))} | {short_tags(r.get('contribution_type'), CONTRIB_EMOJI)} |"
            )
        return "\n".join(lines)

    lines = [
        "| Year | Venue | Paper | Contribution | Affect | Psychology / Theory |",
        "|---:|---|---|---|---|---|",
    ]
    for _, r in x.iterrows():
        title = md_escape(r.get("title", ""))
        star = " ⭐" if str(r.get("relevance")) in {"A", "B"} else ""
        lines.append(
            f"| {md_escape(r.get('year', ''))} | {md_escape(r.get('venue', ''))} | "
            f"[{title}]({r.get('url', '')}){star} | "
            f"{short_tags(r.get('contribution_type'), CONTRIB_EMOJI)} | "
            f"{short_tags(r.get('affect_focus'))} | {short_tags(r.get('theory'))} |"
        )
    return "\n".join(lines)


def count_label(df: pd.DataFrame, column: str, label: str) -> int:
    if df.empty or column not in df.columns:
        return 0
    return sum(label in split_labels(v) for v in df[column])


def render_readme(df: pd.DataFrame) -> str:
    now = now_utc()
    now_kst = now.astimezone(KST)
    total = len(df)
    curated_n = int(df["relevance"].isin(["A", "B"]).sum()) if not df.empty else 0
    auto_n = int((df["relevance"] == "AUTO").sum()) if not df.empty else 0

    first_seen = df.get("first_seen", pd.Series(index=df.index, dtype=object)).map(parse_dt)
    today_kst = now_kst.date()
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)

    latest24 = df[[d is not None and d >= day_ago for d in first_seen]].copy()
    latest7 = df[[d is not None and d >= week_ago for d in first_seen]].copy()
    if not latest7.empty:
        latest7["_first_dt"] = [d for d in first_seen if d is not None and d >= week_ago]
        latest7 = latest7.sort_values("_first_dt", ascending=False)

    system_counts = {label: count_label(df, "system_type", label) for label in SYSTEM_ORDER}
    contrib_counts = {label: count_label(df, "contribution_type", label) for label in CONTRIB_ORDER}

    # Research map matrix: system x contribution counts.
    matrix_header = "| System ↓ / Contribution → | " + " | ".join(f"{CONTRIB_EMOJI[c]} {c}" for c in CONTRIB_ORDER) + " |"
    matrix_sep = "|---|" + "|".join(["---:"] * len(CONTRIB_ORDER)) + "|"
    matrix_rows = [matrix_header, matrix_sep]
    for s in SYSTEM_ORDER:
        row = [f"{SYSTEM_EMOJI[s]} **{s}**"]
        for c in CONTRIB_ORDER:
            n = 0
            for _, r in df.iterrows():
                if s in split_labels(r.get("system_type")) and c in split_labels(r.get("contribution_type")):
                    n += 1
            row.append(str(n))
        matrix_rows.append("| " + " | ".join(row) + " |")
    matrix = "\n".join(matrix_rows)

    system_sections = []
    for s in SYSTEM_ORDER:
        subset = df[[s in split_labels(v) for v in df.get("system_type", pd.Series(index=df.index, dtype=object))]].copy()
        if subset.empty:
            continue
        subset = subset.sort_values(["year", "score"], ascending=[False, False])
        system_sections.append(
            f"<details>\n<summary><b>{SYSTEM_EMOJI[s]} {s} research ({len(subset)})</b></summary>\n\n"
            f"{paper_table(subset)}\n\n</details>"
        )

    contribution_sections = []
    for c in CONTRIB_ORDER:
        subset = df[[c in split_labels(v) for v in df.get("contribution_type", pd.Series(index=df.index, dtype=object))]].copy()
        if subset.empty:
            continue
        subset = subset.sort_values(["year", "score"], ascending=[False, False]).head(50)
        contribution_sections.append(
            f"<details>\n<summary><b>{CONTRIB_EMOJI[c]} {c} ({len(subset)})</b></summary>\n\n"
            f"{paper_table(subset, compact=True)}\n\n</details>"
        )

    if latest7.empty:
        weekly = "_No papers have been newly added in the last 7 days._"
    else:
        blocks = []
        latest7 = latest7.copy()
        latest7["_kst_date"] = latest7["_first_dt"].map(lambda d: d.astimezone(KST).strftime("%Y-%m-%d"))
        for date, group in latest7.groupby("_kst_date", sort=False):
            blocks.append(f"### {date}\n\n{paper_table(group, compact=True)}")
        weekly = "\n\n".join(blocks)

    system_badges = " · ".join(f"{SYSTEM_EMOJI[s]} **{s} {system_counts[s]}**" for s in SYSTEM_ORDER)
    contrib_badges = " · ".join(f"{CONTRIB_EMOJI[c]} **{c.replace('-', ' ')} {contrib_counts[c]}**" for c in CONTRIB_ORDER)

    return f"""<div align=\"center\">\n\n# 💓 Affective LLM Research Watch\n\n### A living map of how LLMs and agents **understand, reason about, represent, generate, regulate, and align with human affect**\n\n[![Daily Update](https://img.shields.io/badge/update-daily%2006%3A00%20KST-2ea44f)](#-latest-updates)\n[![Papers](https://img.shields.io/badge/papers-{total}-blue)](#-research-map)\n[![Curated](https://img.shields.io/badge/curated-{curated_n}-8a2be2)](#-browse-by-system)\n[![Sources](https://img.shields.io/badge/sources-arXiv%20%7C%20OpenAlex-orange)](#-automation)\n\n**Last refreshed:** {now_kst.strftime('%Y-%m-%d %H:%M KST')} · **Owner:** [JAEHYEONG8121](https://github.com/JAEHYEONG8121)\n\n</div>\n\n---\n\n## 🔥 Latest Updates\n\n> New papers are tracked by their **first appearance in this repository**. Existing papers no longer reappear as \"new\" on every daily run.\n\n### New in the last 24 hours · {len(latest24)} papers\n\n{paper_table(latest24.sort_values(['year','score'], ascending=[False,False]), compact=True) if not latest24.empty else '_No new papers in the last 24 hours._'}\n\n<details>\n<summary><b>🗓️ Show the last 7 days of additions</b></summary>\n\n{weekly}\n\n</details>\n\n---\n\n## 🧭 Research Map\n\nThis repository deliberately treats **appraisal × RL as one branch of a larger affective-computing landscape**, not as a search requirement. Papers are multi-labeled, so one work may appear in several views.\n\n**By system:** {system_badges}\n\n**By contribution:** {contrib_badges}\n\n{matrix}\n\n### What we track\n\n| Lens | Examples |\n|---|---|\n| **System** | 💬 LLM · 🤖 Agent / Multi-Agent · 🎧 Multimodal / Omnimodal |\n| **Contribution** | 📊 Evaluation · 🏗️ Framework · 🛠️ Training/Tuning · 🧭 Alignment/Steering · 🗂️ Dataset · 🧠 Representation/Mechanism |\n| **Affect** | Emotion understanding · empathy/support · emotional intelligence · generation · regulation · dynamic affect · personality/individual differences |\n| **Psychology / Theory** | Appraisal/CPM · Theory of Mind · empathy theory · emotional-intelligence theory · personality · emotion-regulation theory · dual-process theory · no explicit theory |\n\n---\n\n## 💬🤖 Browse by System\n\n⭐ = manually curated high-relevance paper. Auto-discovered papers remain candidates until manually promoted.\n\n{chr(10).join(system_sections) if system_sections else '_No categorized papers yet._'}\n\n---\n\n## 🔬 Browse by Research Contribution\n\n{chr(10).join(contribution_sections) if contribution_sections else '_No categorized papers yet._'}\n\n---\n\n## 🧠 Questions this radar is designed to support\n\n- **Understanding:** Do LLMs actually understand affect, or mainly recognize labels and reproduce emotional language?\n- **Reasoning:** Can models infer causes, appraisals, latent mental states, and emotion transitions?\n- **Representation:** What affective information exists in hidden states, memory, or explicit cognitive variables?\n- **Learning:** How do SFT, preference optimization, reward modeling, RL, process supervision, or agent learning change affective capabilities?\n- **Alignment:** How can emotionally appropriate behavior be steered without reducing affect to surface style?\n- **Interaction:** How do affective states evolve in long-horizon dialogue and agent-environment loops?\n- **Psychological grounding:** When do constructs such as appraisal, empathy, emotional intelligence, personality, or emotion regulation add value beyond generic latent state?\n\n---\n\n## ⚙️ Automation\n\n```text\nEvery day at 06:00 KST\n        │\n        ├── arXiv search\n        ├── OpenAlex search\n        │\n        ▼\n relevance + taxonomy filtering\n        │\n        ▼\n preserve first_seen / update last_seen\n        │\n        ▼\n papers.csv + papers.json + README.md\n        │\n        ▼\n GitHub Actions commit\n```\n\nThe daily workflow runs from `.github/workflows/daily-update.yml`. Search terms and taxonomy rules live in `config/queries.yaml`.\n\n```bash\npip install -r requirements.txt\npython scripts/update_papers.py\n```\n\n### Data files\n\n- `papers/papers.csv` — spreadsheet-friendly master table\n- `papers/papers.json` — machine-readable version\n- `papers/seed.csv` — manually curated starting papers\n- `config/queries.yaml` — discovery queries, weights, and taxonomy rules\n\n---\n\n## ⚠️ Research-use note\n\nThis is a **high-recall research radar**, not a systematic-review ground truth. Automatic labels are currently keyword-derived. Venue status, psychological-theory usage, and substantive relevance should be verified from the paper before citation.\n\nA future semantic-classification stage can add LLM-based screening for `method`, `psychological grounding`, `novelty threat`, `dataset`, and `relation to our research` without changing the discovery pipeline.\n"""


def main():
    existing = load_existing()
    rows = load_seed()
    errors = []
    for fn in (fetch_arxiv, fetch_openalex):
        try:
            rows.extend(fn())
        except Exception as e:
            errors.append(f"{fn.__name__}: {e}")

    rows = preserve_history(rows, existing)
    df = dedupe(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    OUT_JSON.write_text(json.dumps(df.to_dict("records"), ensure_ascii=False, indent=2), encoding="utf-8")
    README.write_text(render_readme(df), encoding="utf-8")

    if errors:
        print("Completed with source errors:")
        for e in errors:
            print(" -", e)
    print(f"Wrote {len(df)} papers to {OUT_CSV}")


if __name__ == "__main__":
    main()
