#!/usr/bin/env python3
"""
관심종목(워치리스트) 관리 모듈 + CLI.
발굴(/discover)하거나 점찍은 종목을 담아두고, 감시기(monitor.py)가 진입가 근접 시 알린다.

watchlist.json 구조:
{
  "items": [
    {"ticker": "ANIP", "entry": 80.0, "note": "저평가, 분할매수", "added": "2026-06-23"}
  ]
}
- entry: 목표 진입가(선택). 있으면 감시기가 근접 알림. 없으면 참고용으로만 보관.
"""
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(BASE_DIR, "watchlist.json")


def load():
    if not os.path.exists(WATCHLIST_PATH):
        return {"items": []}
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save(data):
    tmp = WATCHLIST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, WATCHLIST_PATH)


def items():
    return load().get("items", [])


def add(ticker, entry=None, note="", today=""):
    ticker = ticker.upper().strip()
    data = load()
    for it in data["items"]:
        if it["ticker"] == ticker:
            if entry is not None:
                it["entry"] = float(entry)
            if note:
                it["note"] = note
            save(data)
            return f"🔁 {ticker} 관심종목 갱신 (목표 ${it.get('entry', '-')})"
    data["items"].append({"ticker": ticker,
                          "entry": float(entry) if entry is not None else None,
                          "note": note, "added": today})
    save(data)
    tgt = f"목표 ${float(entry):g}" if entry is not None else "목표가 미설정"
    return f"👀 {ticker} 관심종목 추가 ({tgt})"


def remove(ticker):
    ticker = ticker.upper().strip()
    data = load()
    before = len(data["items"])
    data["items"] = [it for it in data["items"] if it["ticker"] != ticker]
    save(data)
    if len(data["items"]) < before:
        return f"🗑️ {ticker} 관심종목에서 제거"
    return f"❓ {ticker} 은 관심종목에 없어요"


def format_list(live=False):
    its = items()
    if not its:
        return "📭 관심종목이 없습니다.\n/watch 티커 [목표가] [메모]  (예: /watch ANIP 80 저평가 분할매수)"
    lines = ["👀 관심종목"]
    quote = None
    if live:
        import market
        quote = market.quote
    for it in its:
        t = it["ticker"]
        entry = it.get("entry")
        tgt = f"목표 ${entry:g}" if entry is not None else "목표 미설정"
        cur = ""
        if live and quote:
            q = quote(t)
            price = q.get("price")
            if price is not None:
                if entry:
                    gap = (price - entry) / entry * 100
                    cur = f" | 현재 ${price} ({gap:+.1f}%)"
                else:
                    cur = f" | 현재 ${price}"
        note = f" — {it['note']}" if it.get("note") else ""
        lines.append(f"• {t}: {tgt}{cur}{note}")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("usage: watchlist.py [list | add TICKER [ENTRY] [NOTE...] | remove TICKER]")
        return
    cmd = sys.argv[1]
    if cmd == "list":
        print(format_list(live=True))
    elif cmd == "add" and len(sys.argv) >= 3:
        entry = None
        note_start = 3
        if len(sys.argv) >= 4:
            try:
                entry = float(sys.argv[3])
                note_start = 4
            except ValueError:
                entry = None
        print(add(sys.argv[2], entry, " ".join(sys.argv[note_start:])))
    elif cmd == "remove" and len(sys.argv) >= 3:
        print(remove(sys.argv[2]))
    else:
        print("usage: watchlist.py [list | add TICKER [ENTRY] [NOTE...] | remove TICKER]")


if __name__ == "__main__":
    main()
