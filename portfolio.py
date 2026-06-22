#!/usr/bin/env python3
"""
보유 종목(portfolio.json) 관리 모듈 + CLI.
텔레그램 /add, /list, /remove 명령과 분석 스케줄러가 함께 사용한다.

portfolio.json 구조:
{
  "positions": [
    {"ticker": "AAPL", "shares": 10, "avg_price": 180.0}
  ]
}
"""
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_PATH = os.path.join(BASE_DIR, "portfolio.json")


def load():
    if not os.path.exists(PORTFOLIO_PATH):
        return {"positions": []}
    with open(PORTFOLIO_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save(data):
    tmp = PORTFOLIO_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PORTFOLIO_PATH)


def add(ticker, shares, avg_price):
    """종목 추가/갱신. 같은 티커가 있으면 덮어쓴다(값을 새로 설정)."""
    ticker = ticker.upper().strip()
    data = load()
    for p in data["positions"]:
        if p["ticker"] == ticker:
            p["shares"] = float(shares)
            p["avg_price"] = float(avg_price)
            save(data)
            return f"🔁 {ticker} 갱신: {shares}주 @ ${avg_price}"
    data["positions"].append({"ticker": ticker, "shares": float(shares), "avg_price": float(avg_price)})
    save(data)
    return f"➕ {ticker} 추가: {shares}주 @ ${avg_price}"


def remove(ticker):
    ticker = ticker.upper().strip()
    data = load()
    before = len(data["positions"])
    data["positions"] = [p for p in data["positions"] if p["ticker"] != ticker]
    save(data)
    if len(data["positions"]) < before:
        return f"🗑️ {ticker} 삭제됨"
    return f"❓ {ticker} 은 보유 목록에 없어요"


def format_list():
    data = load()
    if not data["positions"]:
        return "📭 보유 종목이 없습니다.\n/add 티커 수량 평단  (예: /add AAPL 10 180)"
    lines = ["📋 보유 종목"]
    for p in data["positions"]:
        lines.append(f"• {p['ticker']}: {p['shares']:g}주 @ ${p['avg_price']:g}")
    return "\n".join(lines)


# ---- CLI (수동 테스트용) ----
def main():
    if len(sys.argv) < 2:
        print("usage: portfolio.py [list | add TICKER SHARES PRICE | remove TICKER]")
        return
    cmd = sys.argv[1]
    if cmd == "list":
        print(format_list())
    elif cmd == "add" and len(sys.argv) >= 5:
        print(add(sys.argv[2], sys.argv[3], sys.argv[4]))
    elif cmd == "remove" and len(sys.argv) >= 3:
        print(remove(sys.argv[2]))
    else:
        print("usage: portfolio.py [list | add TICKER SHARES PRICE | remove TICKER]")


if __name__ == "__main__":
    main()
