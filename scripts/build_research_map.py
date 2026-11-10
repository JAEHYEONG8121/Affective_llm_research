"""Build the static map and the Local Citation Network exchange file, offline."""
from __future__ import annotations
import csv
from datetime import datetime, timezone
import io
import json
import html
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLE = {'foundation': '기초 읽기', 'development': '접근 확장', 'benchmark': '평가', 'counterpoint': '반례·한계 검토', 'recent': '최근 검토'}


def validate(catalog, topics):
    subids = {s['id'] for t in topics for s in t['subtopics']}
    ids = [p['id'] for p in catalog['papers']]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate paper id')
    for p in catalog['papers']:
        if not p['title'] or not p['sources'] or not p['url'].startswith('https://'):
            raise ValueError(f'Missing provenance: {p["id"]}')
        if not set(p['subtopics']) <= subids:
            raise ValueError(f'Unknown subtopic: {p["id"]}')
        if p['citations'] is not None and (not p['citation_source'] or not p['citation_observed_at']):
            raise ValueError('Citation counts need a source and observation date')
    for e in catalog['edges']:
        if e['from'] not in ids or e['to'] not in ids or e['from'] == e['to']:
            raise ValueError('Invalid edge endpoints')
        if e['relation'] not in {'cites', 'extends', 'challenges', 'reading_path'}:
            raise ValueError('Unknown relation')
        if not e.get('source') or not e.get('evidence'):
            raise ValueError('Paper relationships need evidence')
        if e['relation'] in {'extends', 'challenges'} and not e.get('reviewer'):
            raise ValueError('Interpretive relationships need a reviewer')


def build(root=ROOT):
    catalog = json.loads((root / 'research/catalog.json').read_text())
    topics = json.loads((root / 'research/taxonomy.json').read_text())
    validate(catalog, topics)
    out = root / 'docs/data'
    out.mkdir(parents=True, exist_ok=True)
    map_data = dict(**catalog, topics=topics)
    (out / 'map.json').write_text(json.dumps(map_data, ensure_ascii=False, indent=2) + '\n')
    # Include the same catalog in the page so static previews and file:// do not
    # depend on an independently served JSON route. Escape HTML delimiters: even
    # application/json script elements are terminated by a literal </script>.
    embedded = json.dumps(map_data, ensure_ascii=False, separators=(',', ':'))
    for char, escaped in [('&', r'\u0026'), ('<', r'\u003c'), ('>', r'\u003e')]:
        embedded = embedded.replace(char, escaped)
    template = (root / 'web/index.template.html').read_text()
    marker = '<!-- RESEARCH_MAP_DATA -->'
    if template.count(marker) != 1:
        raise ValueError('The page template must have exactly one map data marker')
    (root / 'docs/index.html').write_text(template.replace(marker, '<script id="research-map-data" type="application/json">' + embedded + '</script>'))
    # Native import format of Local Citation Network v1.32. Unknown counts stay null.
    citations = {p['id']: [] for p in catalog['papers']}
    for e in catalog['edges']:
        if e['relation'] == 'cites':
            citations[e['from']].append(e['to'])
    articles = [dict(id=p['id'], doi=p.get('doi'), title=p['title'], authors=[{'name': a, 'LN': a, 'FN': ''} for a in p.get('authors', [])], year=p['year'], journal=p.get('venue') or 'Venue not verified', abstract=p.get('abstract'), references=citations[p['id']], citationsCount=p['citations'], referencesCount=None) for p in catalog['papers']]
    timestamp = int(datetime.fromisoformat(catalog['as_of']).replace(tzinfo=timezone.utc).timestamp() * 1000)
    exchange = [dict(source={'references': [p['id'] for p in articles]}, seedArticles=articles, citedArticles=[], citingArticles=[], tabLabel='Affective research — verified edges only', tabTitle='Curated reading candidates; unknown references are not zero references', API='Curated offline catalog', allCited=False, allCiting=False, timestamp=timestamp, localCitationNetworkVersion=1.32)]
    (out / 'local-citation-network.json').write_text(json.dumps(exchange, ensure_ascii=False, indent=2) + '\n')
    # Only DOI-bearing papers can be passed to live DOI lookup without guessing IDs.
    (out / 'pivots-dois.txt').write_text('\n'.join(p['doi'] for p in catalog['papers'] if p.get('doi')) + '\n')
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=['id', 'title', 'year', 'venue', 'url', 'role', 'metadata_status', 'review_status', 'citations', 'citation_observed_at'], lineterminator='\n')
    w.writeheader()
    w.writerows({k:p.get(k) for k in w.fieldnames} for p in catalog['papers'])
    (out / 'catalog.csv').write_text(buf.getvalue())
    lines = ['# 연구 지도: 근거와 검토 질문', '', f'기준일: {catalog["as_of"]}. {len(articles)}편의 편집상 후보, 8개 대분류, 24개 소분류.', '', '이 문서는 전체 원문 검토를 마친 systematic review가 아니다. 출판사 메타데이터·초록 또는 저자 저장소를 확인한 범위를 표시한다. 아래 “검토할 공백”은 검토자의 연구 질문이며, 저자가 증명한 한계나 아직 아무도 연구하지 않았다는 주장이 아니다.', '', '## 범위와 출처', '']
    lines += [f'- **{k}**: {v}' for k,v in catalog['coverage'].items()]
    lines += ['', '논문 간 인용 관계와 인용 수는 학술 API 접근이 복구된 뒤 확장한다. 현재의 주제 분류선은 인용선이 아니다. “최근”은 이 후보군의 출판 연도를 뜻하며 학계 전체의 유행 순위를 뜻하지 않는다.', '']
    for t in topics:
        lines += [f'## {t["label"]}', '', t['scope'], '']
        for s in t['subtopics']:
            lines += [f'### {s["label"]}', '', '**검증할 가설**: '+s['question'], '', '**검토할 공백·실험**: '+s['review_gap'], '']
            ps = [p for p in catalog['papers'] if s['id'] in p['subtopics']]
            for p in sorted(ps, key=lambda p:(p['role'] != 'foundation', p['year'], p['title'])):
                lines += [f'#### [{p["title"]}]({p["url"]})', '', f'{p["year"]} · {p.get("venue") or "게재 학회 미검증"} · {ROLE.get(p["role"], p["role"])}', '', f'서지 확인: `{p["metadata_status"]}` · 독해 범위: `{p["review_status"]}` · 인용 수: '+(str(p['citations']) if p['citations'] is not None else '미조회'), '']
                if p.get('abstract'):
                    lines += ['**보고된 주장·결과의 근거 — 원문 초록**:', '', '> '+p['abstract'].replace('\n',' '), '']
                else:
                    lines += ['초록·실험 결과를 이 지도에서 독립 검토하지 않았다. 저자 저장소에서 확인한 서지 후보이다.', '']
                lines += [p['notes'], '', '**출처**: '+ ' · '.join(f'[{x["kind"]}]({x["url"]}) (확인 {x["retrieved_at"]})' for x in p['sources']), '']
    (root / 'research/REVIEW.md').write_text('\n'.join(lines))
    h = html.escape
    page = ['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>문헌 검토 · Affective Atlas</title><link rel="stylesheet" href="style.css"><body><header><a class="brand" href="./">← Affective Atlas</a></header><article style="max-width:950px;margin:40px auto;padding:24px"><h1>분야별 문헌과 검토 질문</h1><p>초록·서지 수준의 초기 지도입니다. 원문 전체 검토, 학계 전체의 인용 순위, 전수 문헌고찰은 완료되지 않았습니다.</p>']
    for t in topics:
        page += [f'<h2>{h(t["label"])}</h2><p>{h(t["scope"])}</p>']
        for s in t['subtopics']:
            page += [f'<h3>{h(s["label"])}</h3><p>검증할 가설: {h(s["question"])}</p><p>검토자의 연구 질문: {h(s["review_gap"])}</p>']
            for p in catalog['papers']:
                if s['id'] not in p['subtopics']:
                    continue
                page += [f'<section style="border-top:1px solid #dce4df;padding:20px 0"><h3><a href="{h(p["url"], quote=True)}">{h(p["title"])}</a></h3><p>{p["year"]} · {h(p.get("venue") or "학회 미검증")} · {h(p["metadata_status"])} · {h(p["review_status"])}</p><p>{h(p["notes"])}</p><blockquote lang="en">{h(p.get("abstract") or "초록·결과 미검토")}</blockquote>']
                page += [f'<p><a href="{h(x["url"], quote=True)}">{h(x["kind"])}</a> · {h(x["retrieved_at"])}</p>' for x in p['sources']]
                page += ['</section>']
    page += ['</article></body></html>']
    (root / 'docs/review.html').write_text('\n'.join(page))
    print(f'Built {len(articles)} papers, {len(topics)} domains, {len(catalog["edges"])} evidence-bearing paper edges')


if __name__ == '__main__':
    build()
