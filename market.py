#!/usr/bin/env python3
"""
시장 데이터 수집기. 에이전트들이 Bash 로 호출한다.
  python3 market.py all AAPL          # 시세+기술적+펀더멘털+뉴스 JSON
  python3 market.py quote AAPL
  python3 market.py technicals AAPL
  python3 market.py fundamentals AAPL
  python3 market.py news AAPL

설계:
- 시세/기술적 지표: 표준 라이브러리(urllib)로 야후 차트 API 직접 호출 → 의존성 0, 항상 동작.
- 펀더멘털/뉴스: yfinance 가 설치돼 있으면 사용, 없으면 안내 메시지(이 경우 펀더멘털은
  뉴스/웹검색 에이전트가 웹에서 보완). → 설치 실패해도 시스템 전체는 동작.
"""
import json
import sys
import urllib.request

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{t}?range={rng}&interval={iv}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _http_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_chart(ticker, rng="1y", iv="1d"):
    url = CHART_URL.format(t=ticker, rng=rng, iv=iv)
    data = _http_json(url)
    result = data["chart"]["result"][0]
    meta = result.get("meta", {})
    ts = result.get("timestamp", []) or []
    closes_raw = result["indicators"]["quote"][0].get("close", []) or []
    closes = [c for c in closes_raw if c is not None]
    return meta, ts, closes


def _sma(values, n):
    if len(values) < n:
        return None
    return round(sum(values[-n:]) / n, 2)


def _rsi(values, n=14):
    if len(values) < n + 1:
        return None
    gains, losses = [], []
    for i in range(-n, 0):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / n
    avg_loss = sum(losses) / n
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def quote(ticker):
    try:
        meta, ts, closes = _fetch_chart(ticker, rng="5d", iv="1d")
        price = meta.get("regularMarketPrice") or (closes[-1] if closes else None)
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        chg_pct = round((price - prev) / prev * 100, 2) if price and prev else None
        return {
            "ticker": ticker,
            "price": price,
            "previous_close": prev,
            "change_pct": chg_pct,
            "currency": meta.get("currency"),
            "exchange": meta.get("exchangeName"),
        }
    except Exception as e:
        return {"ticker": ticker, "error": f"quote 실패: {e}"}


def technicals(ticker):
    try:
        meta, ts, closes = _fetch_chart(ticker, rng="1y", iv="1d")
        if not closes:
            return {"ticker": ticker, "error": "가격 데이터 없음"}
        last = closes[-1]
        sma20, sma50, sma200 = _sma(closes, 20), _sma(closes, 50), _sma(closes, 200)
        hi_52w = round(max(closes), 2)
        lo_52w = round(min(closes), 2)
        ret_1m = round((last / closes[-21] - 1) * 100, 1) if len(closes) >= 21 else None
        ret_3m = round((last / closes[-63] - 1) * 100, 1) if len(closes) >= 63 else None
        return {
            "ticker": ticker,
            "last_close": round(last, 2),
            "sma20": sma20, "sma50": sma50, "sma200": sma200,
            "rsi14": _rsi(closes, 14),
            "above_sma200": (last > sma200) if sma200 else None,
            "high_52w": hi_52w, "low_52w": lo_52w,
            "pct_from_52w_high": round((last / hi_52w - 1) * 100, 1) if hi_52w else None,
            "return_1m_pct": ret_1m, "return_3m_pct": ret_3m,
        }
    except Exception as e:
        return {"ticker": ticker, "error": f"technicals 실패: {e}"}


def fundamentals(ticker):
    try:
        import yfinance as yf  # 선택 의존성
    except Exception:
        return {"ticker": ticker,
                "note": "yfinance 미설치 — 펀더멘털은 뉴스/웹검색 에이전트가 웹에서 보완하세요."}
    try:
        info = yf.Ticker(ticker).info
        keys = ["longName", "sector", "industry", "marketCap", "trailingPE", "forwardPE",
                "priceToBook", "pegRatio", "profitMargins", "revenueGrowth", "earningsGrowth",
                "debtToEquity", "freeCashflow", "recommendationKey", "targetMeanPrice",
                "numberOfAnalystOpinions", "dividendYield"]
        out = {"ticker": ticker}
        for k in keys:
            if k in info and info[k] is not None:
                out[k] = info[k]
        # 다음 실적발표일
        try:
            cal = yf.Ticker(ticker).calendar
            if cal is not None and "Earnings Date" in getattr(cal, "index", []):
                out["next_earnings"] = str(cal.loc["Earnings Date"].values[0])
        except Exception:
            pass
        return out
    except Exception as e:
        return {"ticker": ticker, "error": f"fundamentals 실패: {e}",
                "note": "웹검색으로 보완 필요"}


def news(ticker):
    try:
        import yfinance as yf
    except Exception:
        return {"ticker": ticker, "note": "yfinance 미설치 — 뉴스는 WebSearch 로 수집하세요."}
    try:
        items = yf.Ticker(ticker).news or []
        heads = []
        for it in items[:8]:
            content = it.get("content", it)
            title = content.get("title") or it.get("title")
            if title:
                heads.append(title)
        return {"ticker": ticker, "headlines": heads}
    except Exception as e:
        return {"ticker": ticker, "error": f"news 실패: {e}", "note": "WebSearch 로 보완"}


def all_data(ticker):
    return {
        "quote": quote(ticker),
        "technicals": technicals(ticker),
        "fundamentals": fundamentals(ticker),
        "news": news(ticker),
    }


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: market.py [all|quote|technicals|fundamentals|news] TICKER"}))
        return
    cmd, ticker = sys.argv[1], sys.argv[2].upper()
    fn = {"all": all_data, "quote": quote, "technicals": technicals,
          "fundamentals": fundamentals, "news": news}.get(cmd)
    if not fn:
        print(json.dumps({"error": f"unknown command {cmd}"}))
        return
    print(json.dumps(fn(ticker), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
