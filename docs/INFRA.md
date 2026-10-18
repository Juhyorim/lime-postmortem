# 인프라 기록

## 현재 (AWS)

| 항목 | 값 |
| --- | --- |
| 인스턴스 | EC2 t4g.small (2 vCPU, 2GB, ARM64), 서울 리전 |
| OS | Debian 13 arm64 (기본 사용자 `admin`) — 실제 사용 OS 확인 필요 |
| 디스크 | gp3 20GB |
| 주소 | Elastic IP + Cloudflare DNS A 레코드 (프록시 끔, DNS only) |
| 보안 그룹 | 22: 내 IP만, 80/443: 전체. 8000은 열지 않음 |
| 기본 설정 | unattended-upgrades(보안 패치 자동, 자동 재부팅 끔), 타임존 Asia/Seoul, swap 2GB |
| HTTPS | Caddy(공식 apt 저장소) + Let's Encrypt 자동 발급/갱신 |
| 앱 | `/etc/systemd/system/rag.service` → `scripts/run_api.sh` (`scripts/install_service.sh`로 생성) |
| 접근 제어 | Caddy `basic_auth` |
| 설정 위치 | 레포 밖 `~/.config/postmortem-rag/rag.env`, 실제 Caddyfile은 `/etc/caddy/Caddyfile` (둘 다 git에 없음) |

## 배포 방법

권장: GitHub(비공개 저장소) 경유

```bash
# 서버에서
cd ~/postmortem-rag && git pull
uv sync --frozen --no-dev
sudo systemctl restart rag
curl -s http://127.0.0.1:8000/health
```

## 시행착오

- `apt upgrade` 중 `sshd_config` 덮어쓰기 질문 → **keep the local version**. cloud-init이 넣은 보안 설정(키 로그인 전용)이 로컬 변경으로 잡힌 것.
- Ubuntu는 proot에서 snap 등이 동작하지 않음 → 폰 이전을 고려해 Debian으로 통일.
- Caddy 인증서 발급 실패 시 reload 반복 금지 (Let's Encrypt rate limit). 흔한 원인: DNS 미전파, 80 포트 막힘, Cloudflare 주황 구름.

## 갤럭시폰(Termux) 이전 요약

1. Termux, Termux:Boot는 F-Droid/GitHub판. 배터리 "제한 없음", 배터리 보호(충전 제한) 켜고 상시 충전. Android 12+ 팬텀 프로세스 킬러 해제.
2. `pkg install proot-distro termux-services cronie cloudflared` → `proot-distro install debian`, Debian 안에 uv 설치.
3. 코드는 git, 데이터는 `data/raw/`, `data/cache.db` 복사. 설정 폴더 `~/.config/postmortem-rag/`도 복사(권한 700/600 유지). index.db는 재구성 가능.
4. termux-services의 `run` 스크립트가 `proot-distro login debian -- .../scripts/run_api.sh` 호출.
5. 배치는 Termux의 cronie에서 `proot-distro login debian -- .../scripts/run_batch.sh`.
6. Cloudflare Tunnel로 HTTPS(→ localhost:8000). basic_auth 대신 Cloudflare Access.
7. 기존 A 레코드 삭제 후 `cloudflared tunnel route dns`. 안정화 후 EC2 종료, Elastic IP Release.
