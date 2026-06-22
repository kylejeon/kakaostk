#!/usr/bin/env python3
"""
긴급 신호 감시기. launchd 가 미국장 시간대에 10분마다 호출한다.

정규 분석(analyze.py, 하루 3회)과 별개로, 보유 종목 시세를 가볍게(=claude 호출 없이)
감시하다가 급락/급등/큰손실 구간에 닿으면 즉시 텔레그램으로 알린다.

알림 조건(설정 telegram_config.json 의 alert_thresholds 로 조정 가능):
  intraday_drop_pct  : 당일 변동률이 이 값 이하면 급락 알림 (기본 -7)
  intraday_spike_pct : 당일 변동률이 이 값 이상이면 급등 알림 (기본 +10)
  total_loss_pct     : 평단 대비 손익률이 이 값 이하면 손절점검 알림 (기본 -15)

스팸 방지: 같은 종목·같은 조건은 하루 1번만 (monitor_state.json 에 상태 저장).
"""
import json
import os
from datetime import datetime, timedelta, timezone

import bridge
import market
import portfolio

KST = timezone(timedelta(hours=9))
STATE_PATH = os.path.join(bridge.BASE_DIR, "monitor_state.json")

DEFAULT_THRESHOLDS = {
    "intraday_drop_pct": -7.0,
    "intraday_spike_pct": 10.0,
    "total_loss_pct": -15.0,
}


def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


def in_us_market_window():
    """대략 미국 프리마켓~애프터(한국시간 17시~다음날 6시)만 감시. 그 외엔 시세 변동 없음."""
    h = datetime.now(KST).hour
    return h >= 17 or h <= 6


def main():
    if not in_us_market_window():
        return
    positions = portfolio.load().get("positions", [])
    if not positions:
        return

    cfg = bridge.load_config()
    th = {**DEFAULT_THRESHOLDS, **cfg.get("alert_thresholds", {})}
    today = datetime.now(KST).strftime("%Y-%m-%d")
    state = load_state()

    for p in positions:
        ticker = p["ticker"]
        q = market.quote(ticker)
        price = q.get("price")
        if price is None:
            continue
        chg = q.get("change_pct")  # 당일 변동률(전일 종가 대비)
        avg = p.get("avg_price")
        total_pct = round((price - avg) / avg * 100, 1) if avg else None

        # 오늘 이미 보낸 조건들
        st = state.get(ticker, {})
        if st.get("date") != today:
            st = {"date": today, "fired": []}
        fired = set(st.get("fired", []))

        alerts = []
        if chg is not None and chg <= th["intraday_drop_pct"] and "drop" not in fired:
            alerts.append(f"📉 당일 {chg:+.1f}% 급락")
            fired.add("drop")
        if chg is not None and chg >= th["intraday_spike_pct"] and "spike" not in fired:
            alerts.append(f"📈 당일 {chg:+.1f}% 급등 (익절 기회 점검)")
            fired.add("spike")
        if total_pct is not None and total_pct <= th["total_loss_pct"] and "loss" not in fired:
            alerts.append(f"🔴 평단 대비 {total_pct:+.1f}% (손절 구간 점검)")
            fired.add("loss")

        if alerts:
            msg = (f"🚨 긴급 [{ticker}] ${price}\n"
                   + "\n".join("• " + a for a in alerts)
                   + "\n→ 상세 분석은 /analyze")
            bridge.tg_send(cfg, msg)
            bridge.log(f"긴급 알림 전송: {ticker} {alerts}")

        st["fired"] = sorted(fired)
        state[ticker] = st

    # 더 이상 보유하지 않는 종목 상태 정리
    held = {p["ticker"] for p in positions}
    for t in list(state.keys()):
        if t not in held:
            del state[t]
    save_state(state)


if __name__ == "__main__":
    main()
