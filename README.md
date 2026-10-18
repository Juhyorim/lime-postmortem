# Postmortem RAG

공개 장애 리포트(포스트모템)를 하이브리드 검색(BM25 + 벡터)으로 찾고, 한국어로 답하는 RAG 서비스.

## 디렉터리 구조

```
postmortem-rag/
├── app/
│   ├── main.py              # FastAPI 앱 (/health)
│   └── config.py            # 환경 변수 설정
├── scripts/
│   ├── run_api.sh           # API 실행 (systemd / Termux 공통 진입점)
│   ├── init_config.sh       # 레포 밖 설정 폴더 생성
│   ├── install_service.sh   # AWS용 systemd 등록
│   ├── check_secrets.sh     # 커밋 전 비공개 정보 검사
│   └── install_git_hooks.sh # 위 검사를 pre-commit 훅으로 설치
├── deploy/
│   ├── rag.service.template # systemd 유닛 템플릿
│   └── Caddyfile.example    # HTTPS + basic_auth + reverse_proxy (템플릿, 실제 값 없음)
├── tests/
├── data/                    # raw/, cache.db, index.db (git 제외)
├── rag.env.example          # 설정 템플릿 (실제 값 없음)
├── secret-patterns.example  # 커밋 금지 문자열 템플릿
├── pyproject.toml / uv.lock
```

## 설정은 레포 밖에

비공개 정보는 레포 폴더 안에 두지 않는다. 레포에는 템플릿만 있다.

```
~/.config/postmortem-rag/        (권한 700)
├── rag.env                      앱 설정, LLM 키   (권한 600)
└── secret-patterns              커밋 금지 문자열   (권한 600)
/etc/caddy/Caddyfile             실제 도메인, 이메일, 비밀번호 해시 (서버)
```

다른 위치를 쓰려면 `RAG_CONFIG_DIR` 환경 변수로 지정한다.

## 1단계 서버 배포 (AWS EC2)

아래 예시는 Debian 사용자 `admin` 기준. Ubuntu라면 `admin`을 `ubuntu`로 바꾼다.

### 1. 코드 올리기 (내 PC에서)

```bash
scp -i 키.pem postmortem-rag.tar.gz admin@<Elastic IP>:~
```

### 2. 압축 풀기와 uv 설치 (서버에서)

```bash
tar xzf postmortem-rag.tar.gz && cd postmortem-rag
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env        # 현재 셸에서 uv 사용
uv sync --frozen --no-dev      # Python 3.12 + 의존성 설치
```

### 3. 설정 파일

```bash
bash scripts/init_config.sh    # ~/.config/postmortem-rag/rag.env 생성
```

`rag.env`는 지금 수정 없이 그대로 둬도 된다. LLM 키는 6단계에서 넣는다.

### 4. 로컬에서 먼저 실행해 보기

```bash
bash scripts/run_api.sh
# 다른 터미널에서
curl -s http://127.0.0.1:8000/health
```

`{"status":"ok",...}`가 나오면 Ctrl+C로 끈다.

### 5. systemd 서비스 등록

```bash
bash scripts/install_service.sh
curl -s http://127.0.0.1:8000/health
```

재부팅 후에도 자동으로 실행된다. 로그는 `journalctl -u rag -f`.

### 6. Caddy를 reverse_proxy + basic_auth로 전환

```bash
caddy hash-password            # 비밀번호 입력 → $2a$... 해시 복사
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak
sudo nano /etc/caddy/Caddyfile # deploy/Caddyfile.example 내용으로 교체 후 이메일·도메인·해시 수정
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl reload caddy
```

### 7. 완료 확인

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://rag.example.com/health      # 401
curl -s -u lime:비밀번호 https://rag.example.com/health                         # {"status":"ok",...}
```

브라우저로 열면 로그인 창이 뜨고, 로그인하면 JSON이 보인다.

## 자주 쓰는 명령

| 목적 | 명령 |
| --- | --- |
| 서비스 상태 | `systemctl status rag` |
| 재시작 | `sudo systemctl restart rag` |
| 앱 로그 | `journalctl -u rag -f` |
| Caddy 로그 | `journalctl -u caddy -f` |
| 테스트 | `uv run pytest -q` |

## 갤럭시폰(Termux) 이전 시

`scripts/run_api.sh`를 termux-services가 호출하도록 하면 된다. systemd와 Caddy는 쓰지 않는다.
