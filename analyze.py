#!/usr/bin/env python3
"""
보유 종목 정기/요청 분석 실행기 (오케스트레이터).

흐름:
  1) portfolio.json 의 보유 종목을 읽는다
  2) claude CLI 헤드리스로, 종목마다 4개 서브에이전트
     (technical / fundamental / news-sentiment / risk-strategist)를 돌려 종합하게 한다
  3) 결과 리포트를 텔레그램으로 전송한다

사용:
  python3 analyze.py            # 현재 시각 기준 세션 라벨 자동
  python3 analyze.py ondemand   # 사용자가 /analyze 로 요청한 경우

스케줄러(launchd)가 하루 3번 호출한다. bridge.py 의 설정/전송 함수를 재사용한다.
"""
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import bridge
import portfolio

KST = timezone(timedelta(hours=9))
CLAUDE_TIMEOUT = 1800  # 종목 많고 웹검색 포함이라 넉넉히


def session_label(ondemand=False):
    if ondemand:
        return "🔍 요청 분석"
    h = datetime.now(KST).hour
    if 6 <= h < 12:
        return "🌅 한국 오전 — 전일 미국장 마감 요약 & 오늘 전략"
    if 18 <= h < 21:
        return "📊 프리마켓 동향 점검"
    if 21 <= h <= 23:
        return "🔔 미국 개장 직전 브리핑"
    return "🗓️ 정기 점검"


def build_prompt(positions, label):
    lines = [f"[{label}] 아래 보유 미국주식을 분석해줘.\n", "보유 종목:"]
    for p in positions:
        lines.append(f"- {p['ticker']}: {p['shares']:g}주, 평단가 ${p['avg_price']:g}")
    lines.append("""
각 종목마다 다음 서브에이전트를 사용해 분석을 모아라(가능하면 병렬로):
1) technical-analyst  — 기술적/추세
2) fundamental-analyst — 재무/밸류
3) news-sentiment-analyst — 최신 뉴스/전문가 의견 (WebSearch 적극 사용)
그 결과와 평단가를 risk-strategist 에게 넘겨 최종 매매판단을 받아라.

투자 성향은 '공격적'(추세추종, 변동성 감수, 단 추세 깨지면 빠른 손절)이다.

최종적으로 사용자에게 보낼 한국어 텔레그램 리포트를 작성하라.

[형식 규칙 — 중요]
- 텔레그램 일반 텍스트로 작성. 마크다운 별표(**)나 #제목 문법을 절대 쓰지 마라.
  텔레그램에서 그대로 별표/샵으로 보인다. 강조는 줄바꿈·이모지·[티커]·대문자로만.
- 맨 위에 '🚨 오늘 우선순위'로 가장 시급한 1~2개 액션을 한 줄 요약하라.

형식:

📈 {라벨} ({날짜})

🚨 오늘 우선순위: (가장 시급한 액션 1~2개 한 줄)

[티커] 현재가 $.. (평단 대비 +/-..%)
결정: 🟢추가매수 / ⚪홀드 / 🟡일부매도 / 🔴손절 (확신도: 상/중/하)
• 기술: ..
• 펀더: ..
• 뉴스: ..
손절가: $..  | 목표/대응: ..
한줄: ..

(종목별로 반복)

📊 한눈 요약: 🔴손절 .. / 🟡일부매도 .. / ⚪홀드 .. / 🟢추가매수 ..

⚠️ 참고용 분석이며 최종 결정·책임은 사용자에게 있음.

장황하지 말고 핵심만. 데이터를 못 구한 항목은 솔직히 '확인 불가'로 표기하라.
레버리지/인버스 ETF 등 일반 개별주가 아닌 종목은 그 사실과 데케이 위험을 반드시 명시하라.""")
    return "\n".join(lines)


def run_analysis(cfg, prompt):
    claude_bin = cfg.get("claude_bin", "claude")
    project_dir = cfg.get("project_dir", bridge.BASE_DIR)
    perm = cfg.get("analyze_permission_mode", "bypassPermissions")
    cmd = [claude_bin, "-p", prompt, "--permission-mode", perm, "--output-format", "text"]
    try:
        proc = subprocess.run(cmd, cwd=project_dir, capture_output=True,
                              text=True, timeout=CLAUDE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return f"⏱️ 분석이 {CLAUDE_TIMEOUT}초를 초과했어요. 종목 수를 줄이거나 다시 시도해주세요."
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return f"❌ 분석 오류(코드 {proc.returncode}):\n{err[:1500]}"
    return (proc.stdout or "").strip() or "(빈 응답)"


def main():
    ondemand = len(sys.argv) > 1 and sys.argv[1] == "ondemand"
    cfg = bridge.load_config()
    label = session_label(ondemand)

    data = portfolio.load()
    positions = data.get("positions", [])
    if not positions:
        bridge.tg_send(cfg, "📭 보유 종목이 없어 분석을 건너뜁니다.\n/add 티커 수량 평단 으로 등록하세요. (예: /add AAPL 10 180)")
        return

    bridge.log(f"분석 시작: {label}, 종목 {len(positions)}개")
    prompt = build_prompt(positions, label)
    report = run_analysis(cfg, prompt)
    bridge.tg_send(cfg, report)
    bridge.log("분석 리포트 전송 완료")


if __name__ == "__main__":
    main()
