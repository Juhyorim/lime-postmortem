# 2단계 수집기 이해도 퀴즈

- 날짜: 2026-10-18
- 범위: `ingest/`, `scripts/run_collect.sh`, 관련 설정·테스트 (커밋 `1d3470e` 기준 + 재시도 표시 버그 수정)
- 결과: 10문항 + 보너스 중 **부분 정답 1개**(2번), 나머지는 "모름" → 아래 정답과 근거 코드로 복습

---

## A. 무엇을 만들었나

### 1. 실행하면 `data/raw/` 아래에 생기는 것 4가지와 역할

- 라임의 답: 모름
- 정답:
  - `crawl.db`: URL마다 수집 상태(성공/실패, 사유, 시도 횟수, 받은 날짜)를 기록하는 SQLite 파일
  - `sources/`: 받은 README 사본(`danluu-YYYYMMDD.md`). 같은 날에는 다시 받지 않고, README를 못 받으면 이전 사본으로 진행
  - `html/`: 원본 HTML(`<doc_id>.html.gz`). 다시 요청하지 않고도 재추출(`--extract-only`)할 수 있게 보관
  - `text/`: 정제 본문 + 메타데이터(`<doc_id>.json`). 3단계 인덱서의 입력
- 근거: `ingest/collect.py:37` (`RawPaths`), `ingest/collect.py:70` (`load_readme`)

### 2. 2단계에 **없는** 것을 모두 고르기: (a) crawl.db (b) index.db (c) 외부 수집 API (d) 원본 HTML 저장 (e) 임베딩

- 라임의 답: (e) 임베딩 → **부분 정답**
- 정답: **(b), (c), (e)**
  - (b) `index.db`는 3단계 인덱서에서 만든다
  - (c) 수집기는 서버 안에서 명령으로 실행하는 배치라 API가 없다. 외부에 열린 것은 basic_auth 뒤의 `/health`뿐
  - (e) 임베딩은 3단계

## B. 이런 상황이면 어떻게 되나

### 3. 매번 503을 돌려주는 URL. 수집기를 5번 실행하면?

- 라임의 답: 모름
- 정답: 요청은 **3번**뿐이다. 그 뒤로는 요청하지 않는다. `status='failed'`, `attempts=3`, `permanent=0`
  - 503은 일시 실패라 `permanent=0`이지만, 다시 받을 대상은 `attempts < 3`인 행만 고른다
- 근거: `ingest/fetch.py:163` (5xx·408·429만 일시 실패), `ingest/state.py:84-85` (`due()` 조건), `ingest/collect.py:33` (`MAX_ATTEMPTS = 3`), 테스트 `tests/test_collect.py:108`

### 4. robots.txt가 (가) 404일 때 (나) 503일 때

- 라임의 답: 모름
- 정답:
  - (가) 404: robots.txt가 없다는 뜻 → **전체 허용**하고 수집 (RFC 9309 표준 해석)
  - (나) 503: 허용 여부를 알 수 없음 → **이번엔 수집하지 않고** `robots_unavailable:http_503`으로 기록. 일시 실패라 다음 실행에서 다시 시도
  - 이유: "없음"은 제한이 없다는 확실한 신호지만, "서버 오류"는 막혀 있을 수도 있다. 모를 때는 보수적으로 수집하지 않는다
- 근거: `ingest/fetch.py:116-118`, 테스트 `tests/test_fetch.py:75`

### 5. `CRAWL_DELAY_SEC=3`일 때 같은 호스트 요청 간격

- 라임의 답: 모름
- 정답: (가) **3초** (나) **10초** (다) **5초**
  - 간격 = max(설정값, 호스트별 최소값, robots의 Crawl-delay)
- 근거: `ingest/fetch.py:29` (`HOST_MIN_DELAY`), `ingest/fetch.py:80` (`_host_delay`), 테스트 `tests/test_fetch.py:92`

### 6. Wayback 링크 `https://web.archive.org/web/20211006135542/https://blog.cloudflare.com/outage/`

- 라임의 답: 모름
- 정답:
  - (가) 실제 요청: `.../web/20211006135542id_/https://blog.cloudflare.com/outage/`. `id_`를 붙이면 Wayback 툴바와 주소 변환이 없는 **원본 HTML**을 받아서 본문 추출이 깨끗해진다
  - (나) `crawl.db`의 `url`에는 **README에 적힌 원래 링크**(`id_` 없음)가 저장된다. 원래 블로그 주소는 텍스트 JSON의 `original_url`에 들어간다
- 근거: `ingest/sources.py:43-48`, `ingest/collect.py:129`, 테스트 `tests/test_collect.py:153`

### 7. 앞선 실행이 안 끝났는데 cron이 또 실행하면?

- 라임의 답: 모름
- 정답: 두 번째 실행은 `data/raw/.collect.lock` 잠금을 얻지 못해 "다른 수집 프로세스가 실행 중입니다"를 출력하고 **바로 종료**(종료 코드 1)한다. 같은 URL을 두 프로세스가 동시에 받거나 DB에 동시에 쓰는 일을 막는다
- 근거: `ingest/collect.py:184-186` (`fcntl.flock`)

## C. 왜 이렇게 만들었나

### 8. 리다이렉트를 직접 따라가는 이유

- 라임의 답: 모름
- 정답: 리다이렉트로 **다른 호스트**로 넘어가면 그 호스트의 robots.txt와 요청 간격을 따로 지켜야 하기 때문이다. 자동 따라가기를 쓰면 중간 호스트를 확인할 수 없다
  - 실제 예: `googleblog.blogspot.com` → `blog.google`, `blog.heroku.com` → `www.heroku.com`
  - `<meta http-equiv="refresh">`로 넘기는 빈 페이지도 같은 방식으로 따라간다 (allegro, Rust 블로그)
- 근거: `ingest/fetch.py:130-133` (홉마다 `_get_robots`), `ingest/fetch.py:150` (`follow_redirects=False`), 테스트 `tests/test_fetch.py:175`

### 9. 보조 링크를 기본으로 수집하지 않는 이유

- 라임의 답: 모름
- 정답: README 설명 문장 안의 링크는 대부분 **포스트모템이 아니다**. 회사 홈페이지(`allegro.pl`)나 용어 설명 Wikipedia(`Shellshock_(software_bug)`) 같은 것들이라, 검색 결과에 섞이면 품질이 떨어진다. 필요하면 `--include-secondary`로 켤 수 있다
- 근거: `ingest/sources.py:87` (첫 링크 외에는 `is_secondary`), `ingest/state.py:89`, 테스트 `tests/test_sources.py:52`

### 10. `CRAWL_CONTACT` 실제 이메일은 어디에?

- 라임의 답: 모름
- 정답:
  - 레포 밖 **`~/.config/postmortem-rag/rag.env`**(권한 600)에 쓴다. `rag.env.example`은 git에 커밋되는 템플릿이라 빈 값으로 둔다 (CLAUDE.md 비공개 정보 규칙)
  - 실수로 썼을 때: 커밋하면 pre-commit 훅 `scripts/check_secrets.sh`가 검사한다. 다만 이메일은 API 키처럼 정해진 형식이 없어서, **`secret-patterns` 파일에 내 이메일을 적어 둬야** 걸러진다
- 근거: `app/config.py:38`, `rag.env.example:13`, `scripts/check_secrets.sh:33-44`

### 보너스. cron을 쓰는 이유와 `nice -n 10`

- 라임의 답: 모름
- 정답:
  - cron: 나중에 옮길 갤럭시폰(Termux + proot)에는 **systemd가 없다**. 양쪽에서 같은 방식으로 돌리려고 배치는 cron으로 정했다 (CLAUDE.md 하드 제약)
  - `nice -n 10`: 배치의 CPU 우선순위를 낮춰서, 2GB 서버에서 같이 도는 **API 응답이 느려지지 않게** 한다
- 근거: `scripts/run_collect.sh:27`

---

## 퀴즈 중 발견한 버그 (수정함)

- **증상:** 일시 실패(503 등)가 3회 시도를 다 써서 더는 요청하지 않는데도, 로그와 `--report`에 계속 "(재시도 예정)"으로 표시됐다. 3번 문제의 정답과 표시가 어긋나는 문제였다
- **원인:** 표시할 때 `permanent`(영구 실패 여부)만 보고 `attempts`(시도 횟수)는 보지 않았다
- **수정:** "다음 실행에서 실제로 다시 요청하는지"(`permanent = 0 AND attempts < 3`)를 기준으로 표시한다. `ingest/state.py`의 `report()`, `ingest/collect.py`의 실패 로그
- **테스트:** `tests/test_collect.py`의 `test_report_retry_label`
- 수집 동작(무엇을 다시 받는지)은 원래도 맞았고, 표시만 틀렸다

## 다음 퀴즈에서 다시 확인할 개념

- 일시 실패와 영구 실패의 구분, 재시도 횟수 상한 (3번)
- robots.txt 4xx와 5xx의 차이 (4번)
- 비밀값 위치와 `secret-patterns`의 역할 (10번)
