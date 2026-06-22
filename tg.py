#!/usr/bin/env python3
"""
텔레그램 봇 브리지 헬퍼.
Anthropic API 없이, Claude Code 세션이 직접 텔레그램 메시지를 읽고/보내는 용도.
표준 라이브러리만 사용 (pip 설치 불필요).

설정 파일: telegram_config.json (이 스크립트와 같은 폴더, git 미추적)
  {
    "bot_token": "123456:ABC-...",   # @BotFather 발급 토큰
    "allowed_chat_id": null,          # 허용된 채팅 ID (보안 잠금). null이면 첫 메시지 발신자로 자동 설정
    "offset": 0                       # 마지막으로 읽은 update_id+1
  }

사용법:
  python3 tg.py init <BOT_TOKEN>     # 토큰 저장
  python3 tg.py whoami               # 최근 메시지 보낸 사람들의 chat_id 확인
  python3 tg.py poll                 # 새 메시지 읽기(JSON 라인 출력) + offset 갱신 + chat_id 잠금
  python3 tg.py send "보낼 메시지"    # allowed_chat_id 에게 답장 전송
"""
import json
import os
import sys
import urllib.parse
import urllib.request

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_config.json")
API = "https://api.telegram.org/bot{token}/{method}"


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {"bot_token": "", "allowed_chat_id": None, "offset": 0}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def api_call(cfg, method, params=None):
    token = cfg.get("bot_token", "")
    if not token:
        sys.exit("ERROR: bot_token 이 설정되지 않았습니다. 먼저 'python3 tg.py init <TOKEN>' 실행하세요.")
    url = API.format(token=token, method=method)
    data = urllib.parse.urlencode(params or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        sys.exit(f"ERROR: Telegram API {e.code}: {body}")


def cmd_init(token):
    cfg = load_config()
    cfg["bot_token"] = token.strip()
    save_config(cfg)
    print("OK: 토큰 저장됨. 이제 텔레그램에서 봇에게 아무 메시지나 보낸 뒤 'python3 tg.py whoami' 실행하세요.")


def cmd_whoami():
    cfg = load_config()
    res = api_call(cfg, "getUpdates", {"offset": cfg.get("offset", 0)})
    seen = {}
    for upd in res.get("result", []):
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat", {})
        if chat.get("id") is not None:
            seen[chat["id"]] = chat.get("username") or chat.get("first_name") or "?"
    if not seen:
        print("아직 받은 메시지가 없습니다. 텔레그램에서 봇에게 메시지를 보낸 뒤 다시 실행하세요.")
    else:
        print("최근 메시지를 보낸 chat_id 목록:")
        for cid, name in seen.items():
            print(f"  chat_id={cid}  ({name})")


def cmd_poll(wait=0):
    cfg = load_config()
    # wait>0 이면 롱폴링: 메시지가 올 때까지 최대 wait초 대기 후 즉시 반환
    res = api_call(cfg, "getUpdates", {"offset": cfg.get("offset", 0), "timeout": wait})
    updates = res.get("result", [])
    new_messages = []
    max_update_id = cfg.get("offset", 0) - 1
    for upd in updates:
        max_update_id = max(max_update_id, upd["update_id"])
        msg = upd.get("message") or upd.get("edited_message")
        if not msg:
            continue
        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        # 보안: allowed_chat_id 미설정이면 첫 발신자로 잠금
        if cfg.get("allowed_chat_id") is None and chat_id is not None:
            cfg["allowed_chat_id"] = chat_id
        # 허용된 사람만 통과
        if chat_id != cfg.get("allowed_chat_id"):
            continue
        text = msg.get("text", "")
        new_messages.append({"chat_id": chat_id, "text": text, "from": chat.get("username") or chat.get("first_name")})
    # offset 갱신 (읽은 메시지 ack)
    if updates:
        cfg["offset"] = max_update_id + 1
    save_config(cfg)
    for m in new_messages:
        print(json.dumps(m, ensure_ascii=False))
    if not new_messages:
        print("(새 메시지 없음)", file=sys.stderr)


def cmd_send(text):
    cfg = load_config()
    chat_id = cfg.get("allowed_chat_id")
    if chat_id is None:
        sys.exit("ERROR: allowed_chat_id 가 없습니다. 먼저 'python3 tg.py poll' 로 메시지를 한 번 받으세요.")
    api_call(cfg, "sendMessage", {"chat_id": chat_id, "text": text})
    print("OK: 전송됨")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "init" and len(sys.argv) >= 3:
        cmd_init(sys.argv[2])
    elif cmd == "whoami":
        cmd_whoami()
    elif cmd == "poll":
        wait = int(sys.argv[2]) if len(sys.argv) >= 3 and sys.argv[2].isdigit() else 0
        cmd_poll(wait)
    elif cmd == "send" and len(sys.argv) >= 3:
        cmd_send(" ".join(sys.argv[2:]))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
