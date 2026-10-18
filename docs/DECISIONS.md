# 결정 이력

| 결정 | 이유 |
| --- | --- |
| ARM64 인스턴스(t4g) | 갤럭시폰도 ARM64라 같은 패키지/바이너리 사용 |
| Debian (Ubuntu 아님) | proot에서 Ubuntu의 snap 등이 동작하지 않음 |
| Docker 미사용 | Termux에서 루팅 없이 Docker 불가 |
| systemd는 run_api.sh만 호출, 배치는 cron | proot에 systemd 없음. 양쪽 설정을 같게 |
| SQLite 하나(FTS5 + sqlite-vec) | DB 서버 메모리 0, 이전 시 파일 복사로 끝 |
| multilingual-e5-small ONNX | 한국어 질문 ↔ 영어 문서, 2GB에서 수백 MB로 동작. 폰에선 bge-m3로 상향 가능 |
| 하이브리드 + 식별자 정확 매칭 부스트 | 의미 검색만으로는 A101 질문에 A102 문서가 섞임. 한국어 질문은 영어 문서와 BM25 단어가 거의 안 겹치므로 BM25는 식별자 담당, 의미는 벡터 담당 |
| 임베딩 캐시(텍스트 해시 + 모델명) | "매일 처음부터 재구성"해도 새 청크만 임베딩 |
| index_new.db → os.replace | 무중단 재구성 |
| 외부 LLM API | 2GB/폰에서 로컬 LLM 품질 부족 |
| Caddy(AWS) / Cloudflare Tunnel(폰) | 인증서 자동. 폰은 포트포워딩·CGNAT 회피 |
| basic_auth를 1단계부터 | /ask 이후 LLM 비용 유출 방지 |
| uvicorn 워커 1개, MemoryMax=900M | 2GB 메모리 보호 |
| 출처: danluu/post-mortems README | 공개 포스트모템 링크 목록 중 가장 크고 정돈됨. 저장소에 LICENSE가 없어 원문은 개인 검색용으로만 로컬 보관하고 재배포하지 않음. 답변엔 출처 URL을 단다 |
| 수집 상태는 `data/raw/crawl.db` | 원문과 함께 백업·이전(폰). index.db처럼 재생성할 수 없는 데이터라 raw/ 아래에 둠 |
| 보조 링크 기본 제외 | README 설명 안의 링크는 회사 홈페이지·Wikipedia 등 포스트모템이 아닌 것이 대부분 |
| 리다이렉트를 직접 따라가며 홉마다 robots 확인 | 다른 호스트로 넘어가는 리다이렉트가 많음(blogspot → blog.google 등) |
| 추출 결과가 500자 미만이면 `too_short` | JS로 그리는 상태 페이지(Heroku, PagerDuty)는 본문이 비어 있음. 인덱서에서 제외 |
