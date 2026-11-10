from __future__ import annotations
import copy
import importlib.util
import json
import re
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_research_map as build
import enrich_citations as enrich
import update_papers as discovery


class ResearchMapTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((ROOT/'research/catalog.json').read_text())
        self.topics = json.loads((ROOT/'research/taxonomy.json').read_text())

    def test_catalog_covers_each_subtopic_with_provenance_and_valid_links(self):
        build.validate(self.catalog, self.topics)
        actual={s for p in self.catalog['papers'] for s in p['subtopics']}
        self.assertEqual(actual,{s['id'] for t in self.topics for s in t['subtopics']})
        for p in self.catalog['papers']:
            if p['url'].startswith('https://aclanthology.org/'):
                self.assertNotIn('10.18653',p['url'])
                self.assertEqual(p['url'],f'https://aclanthology.org/{p["id"]}/')

    def test_unknown_counts_cannot_masquerade_as_sourced_rankings(self):
        self.catalog['papers'][0]['citations']=25
        with self.assertRaises(ValueError):build.validate(self.catalog,self.topics)

    def test_interpretive_edge_requires_a_reviewer(self):
        a,b=self.catalog['papers'][:2]
        self.catalog['edges']=[{'from':a['id'],'to':b['id'],'relation':'extends','source':b['url'],'evidence':'Proposed extension'}]
        with self.assertRaises(ValueError):build.validate(self.catalog,self.topics)

    def test_static_and_native_exports_are_reproducible_and_preserve_unknown_counts(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'research').mkdir()
            (root/'research/catalog.json').write_text(json.dumps(self.catalog))
            (root/'research/taxonomy.json').write_text(json.dumps(self.topics))
            (root/'web').mkdir()
            (root/'web/index.template.html').write_text((ROOT/'web/index.template.html').read_text())
            build.build(root)
            first={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            build.build(root)
            second={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(first,second)
            native=json.loads((root/'docs/data/local-citation-network.json').read_text())[0]
            self.assertEqual(len(native['seedArticles']),len(self.catalog['papers']))
            self.assertIsNone(native['seedArticles'][0]['citationsCount'])
            self.assertEqual(native['localCitationNetworkVersion'],1.32)

    def test_embedded_catalog_escapes_script_delimiters_and_round_trips(self):
        self.catalog['papers'][0]['title'] = '</script><script>alert("title")</script> & < >'
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'research').mkdir();(root/'web').mkdir()
            (root/'research/catalog.json').write_text(json.dumps(self.catalog))
            (root/'research/taxonomy.json').write_text(json.dumps(self.topics))
            (root/'web/index.template.html').write_text((ROOT/'web/index.template.html').read_text())
            build.build(root)
            page=(root/'docs/index.html').read_text()
            embedded=re.search(r'<script id="research-map-data" type="application/json">(.*?)</script>',page,re.S).group(1)
            self.assertNotIn('<',embedded)
            self.assertEqual(json.loads(embedded),json.loads((root/'docs/data/map.json').read_text()))

    def test_resolution_rejects_similar_titles_and_ambiguous_matches(self):
        p={'id':'a','title':'Social emotion reasoning','year':2024}
        with self.assertRaises(ValueError):enrich.resolve_exact(p,[{'display_name':'Social emotion recognition','publication_year':2024}])
        w={'display_name':p['title'],'publication_year':2024}
        with self.assertRaises(ValueError):enrich.resolve_exact(p,[w,w])
        self.assertEqual(enrich.resolve_exact(p,[w]),w)

    def test_doi_match_takes_precedence_over_similar_titles(self):
        p={'id':'a','title':'Example','year':2024,'doi':'10.1234/right'}
        wrong={'doi':'https://doi.org/10.1234/wrong','display_name':'Example'}
        right={'doi':'https://doi.org/10.1234/right','display_name':'Different punctuation'}
        self.assertIs(enrich.resolve_exact(p,[wrong,right]),right)

    @patch.object(enrich.time,'sleep')
    def test_enrichment_preserves_directed_citations_and_observation_provenance(self,_sleep):
        papers=copy.deepcopy(self.catalog['papers'][:2])
        for p in papers:p['doi']=None
        def w(p,n,refs):return {'id':f'https://openalex.org/W{n}','display_name':p['title'],'publication_year':p['year'],'referenced_works':refs,'cited_by_count':n}
        c=Mock();c.get.side_effect=[({'results':[w(papers[0],1,[])]},'public'),({'results':[w(papers[1],2,['https://openalex.org/W1'])]},'public')]
        result,snapshots=enrich.enrich({'papers':papers,'edges':[]},c)
        self.assertEqual(result['edges'][0]['from'],papers[1]['id'])
        self.assertEqual(result['edges'][0]['to'],papers[0]['id'])
        self.assertEqual(result['edges'][0]['relation'],'cites')
        self.assertTrue(result['papers'][0]['citation_observed_at'])
        self.assertEqual(len(snapshots),2)
        self.assertIsNone(papers[0]['citations'])

    @patch.object(enrich.time,'sleep')
    def test_failed_batch_never_mutates_input_catalog(self,_sleep):
        before=copy.deepcopy(self.catalog)
        c=Mock();c.get.side_effect=RuntimeError('HTTP 403')
        with self.assertRaises(RuntimeError):enrich.enrich(self.catalog,c)
        self.assertEqual(self.catalog,before)

    def test_discovery_failure_preserves_every_output_byte(self):
        with tempfile.TemporaryDirectory() as d:
            out=[Path(d)/n for n in ['papers.csv','papers.json','discovery.md']]
            for f in out:f.write_text('Existing user data')
            with patch.multiple(discovery,OUT_CSV=out[0],OUT_JSON=out[1],README=out[2]),patch.object(discovery,'load_existing',return_value={}),patch.object(discovery,'load_seed',return_value=[]),patch.object(discovery,'fetch_arxiv',side_effect=RuntimeError('blocked'),__name__='fetch_arxiv'),patch.object(discovery,'fetch_openalex',return_value=[]):
                with self.assertRaisesRegex(RuntimeError,'existing outputs were preserved'):discovery.main()
            self.assertTrue(all(f.read_text()=='Existing user data' for f in out))

    def test_discovery_keeps_absent_papers_without_inventing_rediscovery(self):
        old={'title':'Old empathy LLM paper','year':2023,'relevance':'AUTO','score':20,'first_seen':'2023-01-01T00:00:00+00:00','last_seen':'2023-01-02T00:00:00+00:00','url':'https://example.org/old'}
        new={**old,'title':'New empathy LLM paper','first_seen':'2026-01-01T00:00:00+00:00'}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with patch.multiple(discovery,OUT_CSV=root/'out.csv',OUT_JSON=root/'out.json',README=root/'out.md'),patch.object(discovery,'load_existing',return_value={discovery.norm_title(old['title']):old}),patch.object(discovery,'load_seed',return_value=[]),patch.object(discovery,'fetch_arxiv',return_value=[new]),patch.object(discovery,'fetch_openalex',return_value=[]):
                discovery.main()
            rows=json.loads((root/'out.json').read_text())
            self.assertEqual(len(rows),2)
            retained=next(x for x in rows if x['title']==old['title'])
            self.assertEqual(retained['first_seen'],old['first_seen'])
            self.assertEqual(retained['last_seen'],old['last_seen'])

    def test_arxiv_http_denial_is_not_an_empty_successful_feed(self):
        r=Mock();r.raise_for_status.side_effect=RuntimeError('403')
        with patch.object(discovery.requests,'get',return_value=r),patch.object(discovery.time,'sleep'):
            with self.assertRaisesRegex(RuntimeError,'403'):discovery.fetch_arxiv()


if __name__=='__main__':unittest.main()
