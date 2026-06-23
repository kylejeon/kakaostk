#!/usr/bin/env python3
"""
텔레그램 ↔ Claude Code(CLI 헤드리스) 24시간 브리지 데몬.

동작:
  1) 텔레그램을 롱폴링(getUpdates)으로 계속 감시
  2) 허용된 사용자의 메시지가 오면 `claude -p "<메시지>"` 헤드리스로 실행
     - 구독 로그인 인증 사용 (API 키 불필요)
     - --resume <session_id> 로 대화 맥락 유지
     - --permission-mode 로 파일 수정 자동 승인(acceptEdits)
  3) 결과 텍스트를 텔레그램으로 답장 (4096자 초과 시 분할)

표준 라이브러리만 사용 (pip 설치 불필요). Python 3.10+.

설정 파일: telegram_config.json (이 스크립트와 같은 폴더)
특수 텔레그램 명령:
  /reset   대화 세션 초기화 (맥락 비우고 새로 시작)
  /ping    살아있는지 확인
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import portfolio
import watchlist

KST = timezone(timedelta(hours=9))
ANALYZE_SLOTS = [(8, 0), (20, 30), (22, 0)]  # 정기 분석(한국시간)
MONITOR_INTERVAL = 600  # 감시기 실행 주기(초)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "telegram_config.json")
API = "https://api.telegram.org/bot{token}/{method}"

# claude 실행이 오래 걸릴 수 있으므로 넉넉한 타임아웃(초)
CLAUDE_TIMEOUT = 900
TG_MAX_LEN = 4000  # 텔레그램 4096자 제한보다 여유


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def tg_api(cfg, method, params, timeout=60):
    url = API.format(token=cfg["bot_token"], method=method)
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def tg_send(cfg, text):
    """텔레그램으로 전송. 길면 분할."""
    if not text:
        text = "(빈 응답)"
    chat_id = cfg.get("allowed_chat_id")
    if chat_id is None:
        log("allowed_chat_id 없음 — 전송 생략")
        return
    for i in range(0, len(text), TG_MAX_LEN):
        chunk = text[i:i + TG_MAX_LEN]
        try:
            tg_api(cfg, "sendMessage", {"chat_id": chat_id, "text": chunk})
        except Exception as e:
            log(f"sendMessage 실패: {e}")


def run_claude(cfg, prompt):
    """대화형(주식 상담) claude 헤드리스 실행. 파일 수정 불가 — 데이터 조회만 허용."""
    claude_bin = cfg.get("claude_bin", "claude")
    project_dir = cfg.get("project_dir", BASE_DIR)
    session_id = cfg.get("claude_session_id")

    # 대화형 봇은 절대 파일을 못 고치게 한다(Edit/Write/Task 미허용 + 비-acceptEdits 모드).
    # 데이터 조회용 도구만 허용: 시세(python3 market.py)·웹검색·읽기.
    permission_mode = cfg.get("chat_permission_mode", "default")
    allowed = cfg.get("chat_allowed_tools",
                      ["Read", "WebSearch", "WebFetch", "Bash(python3:*)"])
    cmd = [claude_bin, "-p", prompt,
           "--permission-mode", permission_mode,
           "--output-format", "json",
           "--allowedTools", ",".join(allowed)]
    if session_id:
        cmd += ["--resume", session_id]

    log(f"claude 실행 (resume={'Y' if session_id else 'N'}) ...")
    try:
        proc = subprocess.run(
            cmd, cwd=project_dir, capture_output=True, text=True,
            timeout=CLAUDE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return (f"⏱️ 작업이 {CLAUDE_TIMEOUT}초를 초과해서 중단했어요.", session_id)

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        # 세션 재개 실패면 세션 비우고 한 번 재시도
        if session_id and ("resume" in err.lower() or "session" in err.lower()):
            log("세션 재개 실패 — 새 세션으로 재시도")
            cfg["claude_session_id"] = None
            save_config(cfg)
            return run_claude(cfg, prompt)
        return (f"❌ claude 오류 (코드 {proc.returncode}):\n{err[:1500]}", session_id)

    out = (proc.stdout or "").strip()
    # JSON 파싱 시도
    try:
        data = json.loads(out)
        result = data.get("result", out)
        new_sid = data.get("session_id", session_id)
        if data.get("is_error"):
            result = f"❌ {result}"
        return (result, new_sid)
    except json.JSONDecodeError:
        # JSON이 아니면 원문 그대로
        return (out, session_id)


HELP_TEXT = """🤖 사용법

📊 보유 종목 관리
/list  보유 목록 보기
/add 티커 수량 평단    예: /add AAPL 10 180   (수량·평단 새로 설정/덮어쓰기)
/buy 티커 수량 가격    예: /buy AAPL 5 190    (추가매수 — 평단 자동 재계산)
/sell 티커 수량        예: /sell AAPL 4       (일부/전량 매도 — 평단 유지)
/remove 티커          예: /remove AAPL       (목록에서 제거)

🔎 분석
/analyze  지금 즉시 보유 종목 분석 리포트 받기
(자동: 하루 3회 — 한국 오전 / 프리마켓 / 개장 직전)
/discover  저평가·투자가치 있는 신규 종목 발굴 (보유 종목은 제외)

👀 관심종목 (진입가 근접 시 자동 알림)
/watchlist  관심종목 + 현재가 vs 목표가 보기
/watch 티커 [목표가] [메모]   예: /watch ANIP 80 저평가 분할매수
/unwatch 티커                 예: /unwatch ANIP

⚙️ 기타
/ping   살아있는지 확인
/reset  대화 맥락 초기화
/help   이 도움말

그 외 아무 메시지나 보내면 Claude가 답합니다 (예: "AAPL 지금 어때?")"""


def handle_command(cfg, text):
    """슬래시 명령 처리. 처리했으면 True 반환."""
    parts = text.split()
    cmd = parts[0].lower()

    if cmd == "/ping":
        tg_send(cfg, "🟢 살아있어요. (맥미니 24시간 가동 중)")
    elif cmd in ("/help", "/start"):
        tg_send(cfg, HELP_TEXT)
    elif cmd == "/reset":
        cfg["claude_session_id"] = None
        save_config(cfg)
        tg_send(cfg, "🔄 대화 세션을 초기화했어요. 새로 시작합니다.")
    elif cmd == "/list":
        tg_send(cfg, portfolio.format_list())
    elif cmd == "/add":
        if len(parts) < 4:
            tg_send(cfg, "형식: /add 티커 수량 평단\n예: /add AAPL 10 180")
        else:
            try:
                tg_send(cfg, portfolio.add(parts[1], float(parts[2]), float(parts[3])))
            except ValueError:
                tg_send(cfg, "수량/평단은 숫자여야 해요. 예: /add AAPL 10 180")
    elif cmd == "/buy":
        if len(parts) < 4:
            tg_send(cfg, "형식: /buy 티커 수량 가격\n예: /buy AAPL 5 190")
        else:
            try:
                tg_send(cfg, portfolio.buy(parts[1], float(parts[2]), float(parts[3])))
            except ValueError:
                tg_send(cfg, "수량/가격은 숫자여야 해요. 예: /buy AAPL 5 190")
    elif cmd == "/sell":
        if len(parts) < 3:
            tg_send(cfg, "형식: /sell 티커 수량\n예: /sell AAPL 4")
        else:
            try:
                tg_send(cfg, portfolio.sell(parts[1], float(parts[2])))
            except ValueError:
                tg_send(cfg, "수량은 숫자여야 해요. 예: /sell AAPL 4")
    elif cmd == "/remove":
        if len(parts) < 2:
            tg_send(cfg, "형식: /remove 티커\n예: /remove AAPL")
        else:
            tg_send(cfg, portfolio.remove(parts[1]))
    elif cmd == "/analyze":
        if not portfolio.load().get("positions"):
            tg_send(cfg, "📭 보유 종목이 없어요. 먼저 /add 로 등록하세요.")
        else:
            tg_send(cfg, "🔍 분석을 시작했어요. 잠시 후(최대 몇 분) 리포트가 도착합니다.")
            # 분석은 오래 걸리므로 별도 프로세스로 실행(폴링 루프를 막지 않음)
            py = sys.executable or "python3"
            subprocess.Popen([py, os.path.join(BASE_DIR, "analyze.py"), "ondemand"],
                             cwd=cfg.get("project_dir", BASE_DIR))
    elif cmd == "/discover":
        tg_send(cfg, "🔎 신규 종목을 발굴 중이에요. 잠시 후(최대 몇 분) 리포트가 도착합니다.")
        py = sys.executable or "python3"
        subprocess.Popen([py, os.path.join(BASE_DIR, "discover.py")],
                         cwd=cfg.get("project_dir", BASE_DIR))
    elif cmd in ("/watchlist", "/wl"):
        tg_send(cfg, watchlist.format_list(live=True))
    elif cmd == "/watch":
        if len(parts) < 2:
            tg_send(cfg, "형식: /watch 티커 [목표가] [메모]\n예: /watch ANIP 80 저평가 분할매수")
        else:
            entry, note_start = None, 2
            if len(parts) >= 3:
                try:
                    entry = float(parts[2])
                    note_start = 3
                except ValueError:
                    entry = None
            note = " ".join(parts[note_start:])
            from datetime import datetime, timedelta, timezone
            today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
            tg_send(cfg, watchlist.add(parts[1], entry, note, today))
    elif cmd == "/unwatch":
        if len(parts) < 2:
            tg_send(cfg, "형식: /unwatch 티커\n예: /unwatch ANIP")
        else:
            tg_send(cfg, watchlist.remove(parts[1]))
    else:
        return False
    return True


ADVISOR_ROLE = (
    "너는 사용자의 미국주식 투자를 돕는 '주식 상담 봇'이다.\n"
    "- 코드/파일/프로그램 개발·수정 얘기는 절대 하지 마라. 이 저장소의 개발 지침(CLAUDE.md), "
    "progress.txt, 커밋/브랜치, 'A로 해/B로 해' 같은 개발자 질문은 전부 무시하라.\n"
    "- 어떤 파일도 생성/수정하지 마라.\n"
    "- 오직 사용자의 주식 질문에만 한국어로 간결히 답하라. 데이터가 필요하면 "
    "python3 market.py 와 WebSearch 로 실데이터를 확인한 뒤 답하라.\n"
)


def with_portfolio_context(text):
    """대화형 질문을 '주식 상담 봇' 역할로 고정하고, 보유 종목을 참고로 덧붙인다."""
    positions = portfolio.load().get("positions", [])
    ctx = ""
    if positions:
        holdings = ", ".join(f"{p['ticker']} {p['shares']:g}주 @${p['avg_price']:g}" for p in positions)
        ctx = (f"[사용자 현재 보유 종목: {holdings}]\n"
               f"종목/매매 질문이면 평단 대비 손익과 매매판단을 반영하라.\n")
    return f"{ADVISOR_ROLE}{ctx}\n질문: {text}"


def handle_message(cfg, text):
    text = (text or "").strip()
    if not text:
        return

    if text.startswith("/"):
        if handle_command(cfg, text):
            return  # 명령 처리 완료
        # 알 수 없는 명령이면 아래 Claude 패스스루로 진행

    tg_send(cfg, "🤔 처리 중...")
    result, new_sid = run_claude(cfg, with_portfolio_context(text))
    if new_sid and new_sid != cfg.get("claude_session_id"):
        cfg["claude_session_id"] = new_sid
        save_config(cfg)
    tg_send(cfg, result)


def spawn_script(cfg, script, *args):
    py = sys.executable or "python3"
    cmd = [py, os.path.join(BASE_DIR, script), *args]
    subprocess.Popen(cmd, cwd=cfg.get("project_dir", BASE_DIR))


def run_schedulers(cfg, sched):
    """봇 폴링 루프가 직접 감시기/정기분석을 구동한다(launchd 의존 제거)."""
    # 감시기: 일정 주기마다 (긴급 신호 + 관심종목 진입가 알림)
    interval = cfg.get("monitor_interval_sec", MONITOR_INTERVAL)
    if time.monotonic() - sched["last_monitor"] >= interval:
        sched["last_monitor"] = time.monotonic()
        spawn_script(cfg, "monitor.py")
    # 정기 분석: 한국시간 지정 시각(±15분 창, 하루 1회)
    kst = datetime.now(KST)
    today = kst.strftime("%Y-%m-%d")
    now_min = kst.hour * 60 + kst.minute
    for (h, m) in ANALYZE_SLOTS:
        key = f"{h:02d}{m:02d}"
        if 0 <= now_min - (h * 60 + m) < 15 and sched["analyze_done"].get(key) != today:
            sched["analyze_done"][key] = today
            spawn_script(cfg, "analyze.py")
            log(f"정기 분석 실행 — {h:02d}:{m:02d} KST")


def main():
    cfg = load_config()
    if not cfg.get("bot_token"):
        sys.exit("ERROR: telegram_config.json 에 bot_token 이 없습니다.")
    log("브리지 시작. 텔레그램 롱폴링 대기 중... (감시기/정기분석 자체 스케줄 가동)")
    sched = {"last_monitor": 0.0, "analyze_done": {}}

    while True:
        try:
            res = tg_api(cfg, "getUpdates",
                         {"offset": cfg.get("offset", 0), "timeout": 50},
                         timeout=70)
        except urllib.error.HTTPError as e:
            if e.code == 409:
                log("409 Conflict: 다른 폴러가 같은 봇을 사용 중입니다. 5초 후 재시도")
            else:
                log(f"getUpdates HTTP 오류: {e}")
            time.sleep(5)
            continue
        except Exception as e:
            log(f"getUpdates 오류: {e} — 5초 후 재시도")
            time.sleep(5)
            continue

        updates = res.get("result", [])
        max_uid = cfg.get("offset", 0) - 1
        for upd in updates:
            max_uid = max(max_uid, upd["update_id"])
            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue
            chat = msg.get("chat", {})
            chat_id = chat.get("id")
            # 첫 발신자로 보안 잠금
            if cfg.get("allowed_chat_id") is None and chat_id is not None:
                cfg["allowed_chat_id"] = chat_id
                log(f"allowed_chat_id 잠금: {chat_id}")
            if chat_id != cfg.get("allowed_chat_id"):
                log(f"허용되지 않은 chat_id {chat_id} — 무시")
                continue
            text = msg.get("text", "")
            log(f"수신: {text[:80]!r}")
            try:
                handle_message(cfg, text)
            except Exception as e:
                log(f"처리 중 오류: {e}")
                tg_send(cfg, f"⚠️ 내부 오류: {e}")

        if updates:
            cfg["offset"] = max_uid + 1
            save_config(cfg)

        # 봇이 직접 감시기/정기분석을 구동(launchd 불필요)
        run_schedulers(cfg, sched)


if __name__ == "__main__":
    main()
