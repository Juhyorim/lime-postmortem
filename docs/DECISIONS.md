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
