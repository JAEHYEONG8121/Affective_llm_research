"""Resolve exact titles/DOIs and collect bounded, source-backed OpenAlex citations.

No API key is required by this program. If your OpenAlex account requires one,
provide OPENALEX_API_KEY through environment settings, never a command argument.
Unknown counts remain null. This does not verify venue acceptance or substantive
follow-up claims. A citation is not evidence of endorsement.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
import unicodedata
import requests
from build_research_map import ROOT, validate

API = 'https://api.openalex.org/works'


def normalized(title):
    return ''.join(c for c in unicodedata.normalize('NFKC', title).casefold() if c.isalnum())


def resolve_exact(paper, results):
    doi = (paper.get('doi') or '').lower().removeprefix('https://doi.org/')
    if doi:
        matches = [w for w in results if (w.get('doi') or '').lower().removeprefix('https://doi.org/') == doi]
    else:
        matches = [w for w in results if normalized(w.get('display_name') or '') == normalized(paper['title']) and abs((w.get('publication_year') or 0) - paper['year']) <= 1]
    if len(matches) != 1:
        raise ValueError(f'Expected one exact bibliographic match for {paper["id"]}; got {len(matches)}. Review manually.')
    return matches[0]


def abstract_of(work):
    index = work.get('abstract_inverted_index') or {}
    pairs = sorted((pos, word) for word, positions in index.items() for pos in positions)
    return ' '.join(word for _,word in pairs) or None


class Client:
    def __init__(self):
        self.session = requests.Session()
        self.base_params = {}
        if os.environ.get('OPENALEX_API_KEY'):
            self.base_params['api_key'] = os.environ['OPENALEX_API_KEY']

    def get(self, params):
        # Do not print request URLs or exceptions containing API key query strings.
        try:
            r = self.session.get(API, params={**params, **self.base_params}, timeout=30, headers={'User-Agent':'AffectiveAtlas/1.0 (academic literature mapping)'})
        except requests.RequestException:
            raise RuntimeError('OpenAlex connection failed; inspect network policy and TLS trust. No catalog changes were written.') from None
        if r.status_code != 200:
            raise RuntimeError(f'OpenAlex HTTP {r.status_code}; no catalog changes were written. Check service policy/authentication in environment settings.')
        return r.json(), API


def enrich(catalog, client, max_citing=20, add_citing=False):
    # Work on a copy. A failed batch must never partially replace the curated file.
    result = json.loads(json.dumps(catalog))
    now = datetime.now(timezone.utc).isoformat()
    records = list(result['papers'])
    works = {}
    snapshots = []
    for p in records:
        params = {'filter':'doi:'+p['doi'], 'per-page':10} if p.get('doi') else {'search':p['title'], 'per-page':10}
        payload, _ = client.get(params)
        w = resolve_exact(p, payload.get('results', []))
        works[p['id']] = w
        p.update(openalex_id=w['id'], citations=w['cited_by_count'], citation_source=API+'/'+w['id'].rsplit('/',1)[-1], citation_observed_at=now[:10])
        snapshots.append({'paper_id':p['id'],'operation':'resolve','retrieved_at':now,'response':payload})
        time.sleep(.15)
    # Refresh only machine-derived direct citations; preserve human-reviewed edges.
    edges = [e for e in result['edges'] if e.get('provider') != 'OpenAlex']
    oa_to_local = {w['id']:pid for pid,w in works.items()}
    for pid,w in works.items():
        for ref in w.get('referenced_works', []):
            if ref in oa_to_local:
                edges.append(dict(**{'from':pid,'to':oa_to_local[ref]},relation='cites',provider='OpenAlex',source=API+'/'+w['id'].rsplit('/',1)[-1],evidence='The citing work referenced_works contains '+ref,observed_at=now))
    if add_citing and max_citing:
        by_id = {p['id']:p for p in result['papers']}
        for p in records:
            short = works[p['id']]['id'].rsplit('/',1)[-1]
            payload, _ = client.get({'filter':'cites:'+short,'sort':'cited_by_count:desc','per-page':min(max_citing,200)})
            snapshots.append({'paper_id':p['id'],'operation':'cited_by','retrieved_at':now,'response':payload})
            for w in payload.get('results', [])[:max_citing]:
                # Enforce the returned relation, not just the query's promise.
                if works[p['id']]['id'] not in w.get('referenced_works', []):
                    raise ValueError('Citing result lacks the claimed reference')
                wid = oa_to_local.get(w['id'], w['id'].rsplit('/',1)[-1])
                if wid not in by_id:
                    q = dict(id=wid,title=w['display_name'],year=w['publication_year'],venue=None,url=w.get('doi') or w['id'],doi=w.get('doi'),authors=[a['author']['display_name'] for a in w.get('authorships', [])],abstract=abstract_of(w),subtopics=p['subtopics'],role='recent',metadata_status='index_unverified',review_status='unreviewed',citations=w['cited_by_count'],citation_source=API+'/'+wid,citation_observed_at=now[:10],pivot_basis='citation_neighbor_not_curated',notes='직접 인용을 통해 발견한 미검토 후보. 주제는 출발 논문에서 임시 상속했으며 관련성·게재 학회·내용상 후속 관계는 검증하지 않았다.',sources=[{'url':API+'/'+wid,'retrieved_at':now[:10],'kind':'bibliographic_index'}])
                    by_id[wid]=q; result['papers'].append(q)
                edges.append(dict(**{'from':wid,'to':p['id']},relation='cites',provider='OpenAlex',source=API+'/'+w['id'].rsplit('/',1)[-1],evidence='The citing work referenced_works contains '+works[p['id']]['id'],observed_at=now))
            time.sleep(.15)
    unique = {(e['from'], e['to'], e['relation']): e for e in edges}
    result['edges'] = list(unique.values())
    result['as_of'] = now[:10]
    result['citation_sampling'] = {'provider':'OpenAlex','observed_at':now,'max_citing_per_seed':max_citing if add_citing else 0,'ordering':'cited_by_count descending','complete':False,'note':'Bounded neighborhood, not a complete citation network or a field-wide ranking.'}
    return result,snapshots


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--add-citing', action='store_true', help='Add unreviewed citation neighbors; their topic labels are provisional')
    ap.add_argument('--max-citing',type=int,default=20)
    args=ap.parse_args()
    if not 0 <= args.max_citing <= 200: ap.error('--max-citing must be between 0 and 200')
    catalog_path=ROOT/'research/catalog.json'
    try:
        result,snapshots=enrich(json.loads(catalog_path.read_text()),Client(),args.max_citing,args.add_citing)
        validate(result,json.loads((ROOT/'research/taxonomy.json').read_text()))
    except (RuntimeError,ValueError,KeyError) as e:
        raise SystemExit(str(e)) from None
    archive=ROOT/'research/citation-snapshots';archive.mkdir(exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    (archive/(stamp+'.json')).write_text(json.dumps(snapshots,ensure_ascii=False,indent=2)+'\n')
    tmp=catalog_path.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');tmp.replace(catalog_path)
    print(f'Updated {len(result["papers"])} papers and {len(result["edges"])} relationships. Run build_research_map.py.')


if __name__=='__main__': main()
