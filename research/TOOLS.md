# 기존 도구 비교와 재사용

2026-11-10에 아래 세 저장소를 실제로 clone해 README·코드·라이선스를 비교했다. 각 도구 전체의 실행 비교를 완료한 것은 아니며, 선택한 Local Citation Network만 이 프로젝트에 포함해 브라우저 검증한다.

| 도구 | 확인한 HEAD | 판단 |
|---|---|---|
| [CiteWeb / Citation Graph](https://github.com/amirzenoozi/citation-graph) | `66fd989be072e6fde346d95afc4d6720e208a2aa` | React/Vite, DOI·저자·주제 확장, OpenAlex/Crossref/Semantic Scholar, 그래프 분석. 해당 checkout에 라이선스 파일이 없어 코드 복사·재배포를 보류했다. |
| [Citation Network Explorer](https://github.com/UoA-eResearch/citations) | `e22020eafe2581030b413d79f4d0110cea1e8293` | MIT. GPU 기반 2D/3D·지리·다양한 데이터 및 AI 기능. 우리 지도보다 범위가 넓어 현재 통합 대상으로 선택하지 않았다. |
| [Local Citation Network](https://github.com/LocalCitationNetwork/LocalCitationNetwork.github.io) | `6a21efc4b946b3ec098bb29e7d039731848e93a6` | GPL-3.0, 정적 배포, DOI seed·직접 인용·Top Cited/Top Citing·CSV/RIS/JSON. 정적 사이트와 함께 보존하고 native JSON 어댑터를 제공하기에 적합하다. |

## 실제 통합 범위

`docs/tools/local-citation-network/`에 upstream의 index.html, index.js, lib, img, examples.json, README, LICENSE를 수정 없이 포함했다. 테스트·개발용 파일과 Git 메타데이터는 포함하지 않았다. GPL-3.0 원문과 저작권을 보존한다. 현재 웹 배포에 필요한 원본 소스는 같은 디렉터리에 있으며 수정한 upstream 파일은 없다. 저장소 전체에 임의로 새 라이선스를 적용하지 않는다.

연구 지도의 캔버스 렌더링·레이아웃·줌·hover·선택에는 이 도구에 동봉된 **vis-network**를 그대로 재사용한다. 라이브러리 파일의 Apache-2.0/MIT 이중 라이선스 고지를 보존했다. 주제 계층, 출처 상태, 검토 질문, 필터 UI와 어댑터는 이 프로젝트에서 추가한 부분이다.

Local Citation Network에서 파일 열기로 `docs/data/local-citation-network.json`을 가져오면 선별 후보의 서지 정보를 읽을 수 있다. 참조가 미조회인 상태에서 내보낸 빈 reference 배열을 “실제 참고문헌 0편”으로 해석해서는 안 된다. 확인된 직접 인용만 전달하므로 현재 캔버스가 비어 있어도 논문 표에는 후보가 표시될 수 있다. 라이브 탐색은 API 접근이 필요하다. DOI 목록은 `docs/data/pivots-dois.txt`로도 제공한다.

도구를 포함한 것과 실제 학술 API로 전수 인용망을 수집한 것은 다르다. 이 환경에서는 학술 API가 프록시에서 차단되어 후자는 검증하지 못했다. 결과를 임의의 관계선으로 대체하지 않았다.

## 업데이트

새 버전을 적용하기 전 upstream의 라이선스와 native JSON schema 변경을 확인한다. 기존 디렉터리의 변경 여부를 먼저 검사하고 필요한 파일만 교체한다. 출처 HEAD·해시를 갱신하고 브라우저에서 지도 탐색과 native JSON 가져오기를 재검증한다.
