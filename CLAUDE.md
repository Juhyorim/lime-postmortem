# CLAUDE.md

공개 장애 리포트(포스트모템)를 하이브리드 검색으로 찾고 한국어로 답하는 RAG 서비스.
사용자는 "라임", 응답은 한국어로. 단계별로 진행하며, 각 단계의 완료 기준을 확인한 뒤 다음으로 넘어간다.

자세한 계획은 `docs/PLAN.md`, 인프라 기록은 `docs/INFRA.md`, 결정 이력은 `docs/DECISIONS.md`.

## 현재 상태

- 1단계 완료: FastAPI `/health`, systemd 서비스, Caddy(HTTPS + basic_auth + reverse_proxy)
- 2단계 완료: 수집기 `ingest/` (`python -m ingest.collect`, cron용 `scripts/run_collect.sh`)
- **다음: 3단계 인덱서** (`docs/PLAN.md`의 3단계 참고)

## 하드 제약 (깨면 안 되는 것)

- **메모리 2GB 서버**(AWS EC2 t4g.small, ARM64)에서 돌아야 한다. 이후 **갤럭시폰 8GB(Termux + proot Debian, ARM64)**로 이전한다.
- **Docker 금지**: Termux에서 쓸 수 없다.
- **systemd 의존 금지**: proot에는 systemd가 없다. 앱 실행은 `scripts/run_api.sh` 하나로, systemd는 그 스크립트만 호출한다. 배치는 **cron**으로 실행한다 (systemd timer 쓰지 않음).
- 의존성은 **ARM64(aarch64) 리눅스 wheel이 있는 패키지**만 쓴다. 새 패키지를 추가할 때 확인한다.
- uvicorn **워커 1개** 고정 (임베딩 모델이 워커마다 로드됨).
- 데이터는 파일로만: `data/raw/`(원문, 정제 텍스트, 수집 상태 `crawl.db`), `data/cache.db`(임베딩 캐시), `data/index.db`(검색 인덱스). 별도 DB 서버를 띄우지 않는다.
- 앱은 `127.0.0.1:8000`에만 바인딩. 외부 노출은 Caddy(AWS) / Cloudflare Tunnel(폰)이 담당.
- 비밀값은 **레포 밖** `~/.config/postmortem-rag/rag.env`(권한 600)에만. 코드, 로그, 응답에 키를 노출하지 않는다.

## 비공개 정보 규칙 (중요)

- 실제 **도메인, 이메일, 서버 IP, API 키, 비밀번호 해시**는 git에 추적되는 어떤 파일(코드, 문서, CLAUDE.md 포함)에도 쓰지 않는다. 항상 placeholder를 쓴다: `rag.example.com`, `you@example.com`, `<Elastic IP>`.
- 실제 값이 필요한 설정은 템플릿(`*.example`)만 저장소에 두고, 실제 파일은 서버/로컬에만 둔다. 예: `deploy/Caddyfile.example` → 서버의 `/etc/caddy/Caddyfile`.
- 설정 파일은 레포 안에 만들지 않는다. 위치는 레포 밖 `~/.config/postmortem-rag/`(`RAG_CONFIG_DIR`로 변경 가능):
  - `rag.env`: 앱 설정 (템플릿 `rag.env.example`, `scripts/run_api.sh`가 읽음)
  - `secret-patterns`: 커밋 금지 문자열 (템플릿 `secret-patterns.example`, `scripts/check_secrets.sh`가 읽음)
  - 새 설정 항목이 필요하면 `rag.env.example`에 빈 값으로 추가하고, 실제 값은 라임이 넣도록 안내한다.
- 레포 안에 `.env` 같은 설정 파일을 만들거나, 코드가 레포 안의 설정 파일을 읽게 하지 않는다.
- 커밋 전 `scripts/check_secrets.sh`가 pre-commit 훅으로 검사한다. 훅을 우회(`--no-verify`)하지 않는다.

## 기술 스택

- Python 3.12, uv (`uv.lock` 커밋, 서버에서는 `uv sync --frozen --no-dev`)
- FastAPI + uvicorn
- SQLite: FTS5(BM25) + sqlite-vec(벡터) — 한 파일
- 임베딩: multilingual-e5-small (ONNX). 문서엔 `passage: `, 질문엔 `query: ` 접두어 필수
- 하이브리드: BM25 top50 + 벡터 top50 → RRF(k=60) + 식별자 정확 매칭 부스트
- 답변 생성: 외부 LLM API (제공자 미정)

## 명령

- 테스트: `uv run pytest -q`
- 로컬 실행: `uv run uvicorn app.main:app --reload` (또는 `bash scripts/run_api.sh`)
- 수집: `uv run python -m ingest.collect [--limit N | --dry-run | --extract-only | --report]`
- 서버 반영 후: `sudo systemctl restart rag`, 로그 `journalctl -u rag -f`

## 작업 방식

- 단계마다 테스트를 추가하고 `uv run pytest -q`가 통과해야 완료로 본다.
- 크롤링은 robots.txt 준수, 요청 간 간격, 이미 받은 문서 재요청 금지.
- 단계를 마치면 이 파일의 "현재 상태"와 `docs/PLAN.md` 체크박스를 갱신한다.
