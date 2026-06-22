# 맥미니에서 텔레그램 봇 24시간 구동 가이드

이 문서는 **다른 맥미니**에서 `@Kkaostock_bot` 을 24시간 돌려서,
Claude 창을 닫아도 텔레그램으로 대화/원격조종할 수 있게 만드는 절차입니다.

- 두뇌: 맥미니에 설치한 **Claude Code CLI** (당신의 **구독** 인증 사용, 추가 API 과금 없음)
- 상시 구동: macOS **launchd LaunchAgent** (부팅 시 자동 실행 + 죽으면 재시작)

> ⚠️ 같은 봇을 두 곳에서 동시에 폴링하면 충돌(409)납니다.
> 맥미니 데몬을 켜기 전에, 지금 쓰던 Claude 창의 자동 루프는 꺼주세요(그냥 창 닫으면 됨).

---

## 0. 준비물
- 24시간 켜둘 맥미니 (인터넷 연결)
- 당신의 Claude **구독**(Pro/Max) 계정
- 텔레그램 봇 토큰: 이미 발급됨 → `8887549440:...` (이 채팅에서 만든 것)

---

## 1. Claude Code CLI 설치 (맥미니에서)
맥미니 터미널에서:
```bash
curl -fsSL https://claude.ai/install.sh | bash
```
설치 후 경로 확인 (나중에 설정에 넣음):
```bash
which claude
# 예: /Users/내이름/.local/bin/claude
```

## 2. 구독으로 로그인 (1회, 대화형)
```bash
claude
```
실행되면 `/login` 입력 → 브라우저로 구독 계정 로그인.
한 번 로그인하면 자격증명이 **맥미니 키체인**에 저장되어,
이후 `claude -p` 헤드리스 호출이 자동으로 재사용합니다 (API 키 불필요).

로그인 확인:
```bash
claude -p "1+1은?" 
# 답이 나오면 OK
```

## 3. 프로젝트 git 으로 가져오기 (맥미니로)
맥미니 터미널에서 `claude` 브랜치를 클론:
```bash
git clone -b claude https://github.com/kylejeon/kakaostk.git ~/kakaostk
cd ~/kakaostk
```
> `telegram_config.json` (토큰 들어있는 실제 설정)은 git에 안 올라갑니다(.gitignore).
> 맥미니에서 4번에서 새로 만듭니다. → 토큰이 깃허브에 노출되지 않음.

### 나중에 코드 업데이트할 때
bridge.py 등을 고쳐서 push 하면, 맥미니에서는:
```bash
cd ~/kakaostk
git pull
# 데몬 재시작 (변경 반영)
launchctl unload ~/Library/LaunchAgents/com.kakaostk.telegram-bridge.plist
launchctl load   ~/Library/LaunchAgents/com.kakaostk.telegram-bridge.plist
```
`git pull` 해도 `telegram_config.json` 은 그대로 유지됩니다(추적 안 하므로).

## 4. 설정 파일 만들기
프로젝트 폴더(예: `~/kakaostk`)에서:
```bash
cp telegram_config.example.json telegram_config.json
```
`telegram_config.json` 을 편집기로 열어 채웁니다:
```json
{
  "bot_token": "8887549440:AAGivYMHFETF-9ZyKxIeGMra4MbCK8e1Mig",
  "allowed_chat_id": 1050566686,
  "offset": 0,
  "project_dir": "/Users/내이름/kakaostk",
  "claude_bin": "/Users/내이름/.local/bin/claude",
  "permission_mode": "acceptEdits",
  "claude_session_id": null
}
```
- `bot_token`: 봇 토큰
- `allowed_chat_id`: **당신만 허용**. 이미 알아낸 값 `1050566686` 을 넣으세요.
  (모르면 `null`로 두면, 봇에 첫 메시지 보낸 사람으로 자동 잠금됩니다.)
- `project_dir`: 맥미니에서의 kakaostk 절대경로 (`pwd`로 확인)
- `claude_bin`: 1번에서 확인한 `which claude` 절대경로
- `permission_mode`: `acceptEdits`(파일수정 자동) / 더 자율적으로 하려면 `bypassPermissions`

## 5. 손으로 한 번 테스트
데몬으로 등록하기 전에 직접 실행해 확인:
```bash
cd ~/kakaostk
python3 bridge.py
```
- 터미널에 `브리지 시작...` 이 뜨면, 텔레그램에서 봇에게 메시지 보내기 (예: `/ping`)
- `🟢 살아있어요` 답장이 오면 성공. 이어서 `progress.txt 읽어줘` 같은 실제 작업도 시켜보세요.
- 확인 끝나면 `Ctrl+C` 로 중지.

## 6. launchd 데몬으로 등록 (24시간 자동)
1) plist 템플릿의 `__PLACEHOLDER__` 를 실제 경로로 치환:
```bash
cd ~/kakaostk
PY=$(which python3)
sed -e "s#__PYTHON3_PATH__#$PY#g" \
    -e "s#__PROJECT_DIR__#$HOME/kakaostk#g" \
    -e "s#__HOME__#$HOME#g" \
    com.kakaostk.telegram-bridge.plist > ~/Library/LaunchAgents/com.kakaostk.telegram-bridge.plist
```
2) 로드(시작):
```bash
launchctl load ~/Library/LaunchAgents/com.kakaostk.telegram-bridge.plist
```
3) 동작 확인:
```bash
launchctl list | grep kakaostk      # 떠 있으면 등록됨
tail -f ~/kakaostk/bridge.log       # 로그 실시간 보기
```
텔레그램으로 `/ping` 보내서 응답 오면 완료! 🎉

## 7. 맥미니가 잠들지 않게 (중요)
24시간 응답하려면 맥미니가 잠들거나 꺼지면 안 됩니다.
**시스템 설정 → 에너지(또는 배터리)** 에서:
- "디스플레이가 꺼졌을 때 자동으로 잠자기 방지" 켜기
- "정전 후 자동으로 시작" 켜기
- (선택) 자동 로그인 켜기: 재부팅 후 사용자 로그인 없이도 LaunchAgent가 키체인에 접근하려면
  자동 로그인이 편합니다. **시스템 설정 → 사용자 및 그룹 → 자동 로그인**.

---

## 운영 / 관리 명령
| 작업 | 명령 |
|------|------|
| 중지 | `launchctl unload ~/Library/LaunchAgents/com.kakaostk.telegram-bridge.plist` |
| 시작 | `launchctl load ~/Library/LaunchAgents/com.kakaostk.telegram-bridge.plist` |
| 재시작 | unload 후 load |
| 로그 보기 | `tail -f ~/kakaostk/bridge.log` |
| 에러 로그 | `tail -f ~/kakaostk/bridge.error.log` |
| 상태 확인 | 텔레그램에 `/ping` |
| 대화 초기화 | 텔레그램에 `/reset` |

## 텔레그램 특수 명령
- `/ping` — 봇이 살아있는지 확인
- `/reset` — 대화 맥락 초기화(새 세션 시작)
- 그 외 모든 메시지 → Claude가 kakaostk 안에서 처리 후 답장

---

## 주의 / 한계
- **구독 사용량 공유**: 봇으로 보낸 요청도 당신 구독 한도를 같이 씁니다. 과하면 일시적으로 한도 초과될 수 있어요.
- **보안**: `allowed_chat_id` 로 당신만 사용 가능하게 잠겨 있습니다. `telegram_config.json`(토큰 포함)은 절대 공유/커밋 금지.
- **권한**: `acceptEdits`는 파일 수정은 자동이지만 위험한 bash는 막혀서, 일부 작업은 거부될 수 있어요. 더 자율적으로 하려면 `permission_mode`를 `bypassPermissions`로 바꾸되 위험을 감수해야 합니다.
- **동시 폴링 금지**: 맥미니 데몬이 도는 동안에는 다른 곳(이 Claude 세션 등)에서 같은 봇을 폴링하지 마세요(409 충돌).
