"""Render a GitHub-native research map from the curated catalog."""
from __future__ import annotations

import html
import re
import textwrap

ROLES = {
    'foundation': '기초',
    'development': '접근 확장',
    'benchmark': '평가',
    'counterpoint': '반례·한계',
    'recent': '최근',
}


def label(value):
    """Keep text inside quoted Mermaid labels and tooltip strings."""
    value = re.sub(r'\s+', ' ', str(value))
    for old, new in [('&', '#38;'), ('"', '#34;'), ('<', '#60;'), ('>', '#62;')]:
        value = value.replace(old, new)
    return value


def md(value):
    value = html.escape(str(value)).replace('\\', '\\\\')
    for char in ['|', '[', ']', '`']:
        value = value.replace(char, '\\' + char)
    return value.replace('\n', ' ')


def venue(paper):
    pid = paper['id']
    if pid.startswith('P19-') or re.match(r'^\d{4}\.acl-', pid):
        return 'ACL'
    if re.match(r'^\d{4}\.emnlp-', pid):
        return 'EMNLP'
    return re.sub(r'\s*' + str(paper['year']), '', paper.get('venue') or '학회 미확인').strip()


def paper_order(p):
    return (p['role'] != 'foundation', p['year'], p['title'])


def paper_name(p):
    title = p['title'].split(':', 1)[0]
    return textwrap.shorten(title, width=48, placeholder='…')


def overview(topics):
    lines = ['```mermaid', 'flowchart LR', '  root["LLM 감정·정렬 연구"]']
    for t in topics:
        lines.append(f'  root --> t_{t["id"]}["{label(t["label"])}"]')
    return lines + ['```']


def topic_map(topic, papers):
    lines = ['```mermaid', 'flowchart LR', f'  topic["{label(topic["label"])}"]']
    paper_ids = {p['id']: f'p{i}' for i, p in enumerate(papers)}
    for i, sub in enumerate(topic['subtopics']):
        lines.append(f'  topic --> s{i}["{label(sub["label"])}"]')
    for p in papers:
        name = label(paper_name(p))
        meta = label(f'{venue(p)} · {p["year"]}')
        node = paper_ids[p['id']]
        lines.append(f'  {node}["{name}<br/>{meta}"]')
        for i, sub in enumerate(topic['subtopics']):
            if sub['id'] in p['subtopics']:
                lines.append(f'  s{i} --> {node}')
    # GitHub may restrict Mermaid interactions. Full Markdown links in the table
    # below remain usable regardless of the renderer's security configuration.
    for p in papers:
        tooltip = label(f'{p["title"]} · {venue(p)} · {p["year"]}')
        lines.append(f'  click {paper_ids[p["id"]]} href "{p["url"]}" "{tooltip}" _blank')
    return lines + ['```']


def relationship_map(catalog):
    edges = catalog['edges']
    if not edges:
        return []
    papers = {p['id']: p for p in catalog['papers']}
    endpoints = sorted({e[k] for e in edges for k in ('from', 'to')})
    nodes = {pid: f'r{i}' for i, pid in enumerate(endpoints)}
    lines = ['## 논문 관계', '', '```mermaid', 'flowchart LR']
    for pid in endpoints:
        p = papers[pid]
        lines.append(f'  {nodes[pid]}["{label(paper_name(p))}<br/>{p["year"]}"]')
    labels = {'cites': '인용', 'extends': '내용상 확장', 'challenges': '반론', 'reading_path': '읽기 제안'}
    for e in edges:
        arrow = '-->' if e['relation'] == 'cites' else '-.->'
        lines.append(f'  {nodes[e["from"]]} {arrow}|{labels[e["relation"]]}| {nodes[e["to"]]}')
    lines += ['```', '', '| 출발 논문 | 관계 | 대상 논문 | 근거 |', '|---|---|---|---|']
    for e in edges:
        a, b = papers[e['from']], papers[e['to']]
        lines.append(f'| [{md(a["title"])}]({a["url"]}) | {labels[e["relation"]]} | [{md(b["title"])}]({b["url"]}) | [{md(e["evidence"])}]({e["source"]}) |')
    return lines + ['']


def render_readme(catalog, topics):
    nsubs = sum(len(t['subtopics']) for t in topics)
    lines = [
        '# LLM 감정·정렬 연구 지도', '',
        '[분야별 문헌·근거](research/REVIEW.md) · [선정·검증 기준](research/METHODOLOGY.md) · [개발 환경](research/DEVELOPMENT.md)', '',
        f'**{len(topics)}개 분야 · {nsubs}개 세부 주제 · {len(catalog["papers"])}편** · {catalog["as_of"]}', '',
        '분야 → 세부 주제 → 논문 순서의 분류 지도. 논문 제목·학회·연도는 각 도식 아래 표에 제공한다.', '',
        '**인용 데이터:** '+('출처와 조회일을 기록한 관계만 표시.' if catalog['edges'] else '직접 인용 관계와 인용 수 미수집. 현재 연결은 주제 분류 기준.'), '',
        '## 분야 개요', '',
    ]
    lines += overview(topics) + ['']
    lines += [' · '.join(f'[{md(t["label"])}](#{t["id"]})' for t in topics), '']
    for t in topics:
        papers = sorted([p for p in catalog['papers'] if any(s.startswith(t['id']+'.') for s in p['subtopics'])], key=paper_order)
        lines += [f'<a id="{t["id"]}"></a>', '', f'## {t["label"]}', '']
        lines += topic_map(t, papers) + ['', '| 논문 | 학회 | 연도 | 검토 역할 |', '|---|---|---:|---|']
        for p in papers:
            lines.append(f'| [{md(p["title"])}]({p["url"]}) | {md(venue(p))} | {p["year"]} | {ROLES.get(p["role"], "미검토")} |')
        lines += ['']
    lines += relationship_map(catalog)
    lines += [
        '## 자료', '',
        '- [논문별 초록·출처·가설·검토 질문](research/REVIEW.md)',
        '- [대·소분류](research/taxonomy.json) · [논문 데이터](research/catalog.json) · [CSV](docs/data/catalog.csv)',
        '- [기존 발견 보고서](papers/discovery.md) · [기존 수동 등록](papers/seed.csv)',
        '- [외부 도구 비교](research/TOOLS.md) · [Local Citation Network용 데이터](docs/data/local-citation-network.json)', '',
        '<details>', '<summary>검증 범위</summary>', '',
        '출판사 메타데이터·초록 또는 저자 저장소를 확인한 초기 문헌 지도다. 역할은 편집상 분류이며 인용 수 순위가 아니다. 전문 독해·재현과 학회별 균형 있는 확장은 진행 중이다. 학회를 확인하지 못한 항목은 미확인으로 표시한다. [검증 기준과 남은 조사](research/METHODOLOGY.md)에 확인 범위를 기록한다.', '',
        '</details>', '',
        '<details>', '<summary>선택 도구</summary>', '',
        'README만으로 분야별 지도와 논문 목록을 열람할 수 있다. 확대·검색이 필요한 경우 로컬 웹 지도와 기존 인용망 도구를 사용할 수 있다. 별도 사이트 배포는 필요하지 않다. 실행 방법은 [개발 환경](research/DEVELOPMENT.md)에 있다.', '',
        '</details>', '',
    ]
    return '\n'.join(lines)
