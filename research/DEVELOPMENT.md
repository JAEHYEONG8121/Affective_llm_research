# 개발 환경

## 설치

Python 3.11(CI) 또는 검증된 3.12를 사용한다. 별도 서버나 GPU, LLM API 키는 필요하지 않다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/build_research_map.py
python -m unittest discover -s tests -v
python -m http.server 8000 --directory docs
```

브라우저 검증은 Node.js 24와 Playwright를 사용한다. README 도식은 Mermaid 11.12.0으로 별도 배포 없이 렌더링 검증한다. 설치된 시스템 Chromium이
있으면 사용하고, 없으면 Playwright Chromium을 설치한다.

```bash
npm ci --ignore-scripts
npx playwright install chromium  # 시스템 Chromium이 없는 경우
npm run test:browser
```

학술 API 접근 복구 후 인용 데이터를 갱신한다. `--add-citing`은 후보별 최대 20편의 미검토 피인용 이웃을 추가한다. 발견 경로를 주제 관련성이나 내용상 계승의 증거로 해석하지 않는다.

```bash
python scripts/enrich_citations.py --add-citing --max-citing 20
python scripts/build_research_map.py
```

필요한 외부 도메인은 `api.openalex.org`, `export.arxiv.org`다. 본문·출판사 대조에는 `aclanthology.org`, `proceedings.mlr.press`, `proceedings.neurips.cc`, `openreview.net`, `ojs.aaai.org` 등이 추가로 필요하다. 환경 설정에서 기존 규칙을 보존하며 추가한다. 서비스가 인증을 요구하는지는 실제 응답으로 확인한다.

## 데이터와 자동화

| 경로 | 용도 |
|---|---|
| `research/taxonomy.json` | 대·소분류, 검증할 가설과 연구 질문 |
| `research/catalog.json` | 선별 후보, 서지·초록·출처·검토 상태와 논문 관계 |
| `research/REVIEW.md` | 같은 데이터에서 생성한 분야별 검토 문서 |
| `research/sources/` | 저자·출판사 저장소의 확인한 자료 사본 |
| `docs/data/` | 웹 지도, CSV, 외부 도구용 파일 |
| `web/index.template.html` | 화면 문구·구조의 원본. 빌드 시 데이터를 포함한 `docs/index.html` 생성 |
| `papers/papers.csv`, `papers/papers.json` | 기존 키워드 기반 발견 후보. 검증된 연구 지도와 구분 |
| `papers/seed.csv` | 기존 수동 등록 13편. 재검증 전까지 출판 정보 확정에 사용하지 않음 |
| `papers/discovery.md` | 기존 수집기의 발견 보고서 |

기존 GitHub Actions는 매일 06:00 KST에 발견 보고서를 갱신한다. 발견 수집기는 `papers/discovery.md`를 갱신하고, README는 선별 논문 데이터에서 지도 빌드가 재생성한다. 출처 오류가 나면 실패로 처리하고 기존 결과를 보존한다. 정적 지도 빌드는 네트워크 없이 실행된다. [Pages 워크플로](.github/workflows/pages.yml)는 수동 실행용이며, GitHub 저장소의 Pages 소스를 GitHub Actions로 설정해야 한다.


README는 `scripts/readme_map.py`가 `research/catalog.json`과 `research/taxonomy.json`에서 생성한다. 화면 원본은 `web/index.template.html`이다. `python scripts/build_research_map.py` 실행 시 README·웹 지도·교환 파일을 함께 갱신한다.
