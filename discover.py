#!/usr/bin/env python3
"""
신규 종목 발굴기 (요청 시 /discover 로 실행).

흐름:
  1) 보유 종목(portfolio.json)을 읽어 '제외 목록'으로 삼는다(중복 추천 방지)
  2) claude 헤드리스로:
     - stock-screener 에이전트가 WebSearch 로 저평가·성장 기회 후보 발굴
     - 상위 후보를 fundamental/technical/news 에이전트로 검증
     - risk-strategist 관점으로 진입가·손절가·목표가 제시
  3) 순위 매긴 발굴 리포트를 텔레그램으로 전송

bridge.py 의 설정/전송 함수를 재사용한다.
"""
import subprocess
from datetime import datetime, timedelta, timezone

import bridge
import portfolio

KST = timezone(timedelta(hours=9))
CLAUDE_TIMEOUT = 1800


def build_prompt(held_tickers):
    exclude = ", ".join(held_tickers) if held_tickers else "(없음)"
    return f"""[신규 종목 발굴] 저평가되어 있고 투자 가치가 있는 '신규' 미국주식을 찾아줘.

이미 보유 중이라 추천에서 제외할 종목: {exclude}

발굴 기준:
- 스타일: 가치 + 성장 혼합, 저평가되었고 상승 여력 있는 '기회 위주'
- 범위: 미국 상장, 중소형주 포함(고위험·고수익 텐배거 후보 환영)
- 투자 성향: 공격적 (단, 실체 없는 테마주·극단적 유동성 부족은 위험으로 명시)

절차:
1) stock-screener 에이전트로 WebSearch 를 적극 활용해 후보 8~12개 발굴(제외 목록 빼고).
2) 그중 가장 매력적인 상위 5개를 골라, 각각
   fundamental-analyst / technical-analyst / news-sentiment-analyst 로 검증.
3) risk-strategist 관점으로 매수 매력도·진입 구간·손절가·목표가를 제시.
4) 최종 순위를 매겨 아래 형식의 한국어 텔레그램 리포트를 작성.

[형식 규칙]
- 텔레그램 일반 텍스트. 마크다운 별표(**)·#제목 쓰지 마라(그대로 보임). 강조는 이모지·줄바꿈.

형식:

🔎 신규 종목 발굴 ({datetime.now(KST).strftime('%Y-%m-%d')})

🚨 톱픽: (가장 매력적인 1~2개 한 줄)

[티커] 회사명 — 현재가 $.. (대형/중형/소형)
밸류: 저평가 근거 (PER/PEG 등)
성장/촉매: ..
리스크: (중소형이면 변동성·유동성 반드시 명시)
진입 제안: 매수구간 $.. / 손절 $.. / 목표 $..
추천 이유 한줄: ..

(상위 5개 반복)

📊 발굴 요약 (종목별 1줄)
[티커] 추천도 상/중/하 — 핵심 이유

⚠️ 신규 발굴은 불확실성이 큽니다. 참고용이며 최종 결정·책임은 사용자에게 있음.

장황하지 말고 핵심만. 데이터 확인 안 된 항목은 '확인 불가'로 표기하라. 제외 목록 종목은 절대 추천하지 마라.
[중요] 절대 어떤 파일도 생성/수정하지 마라(git 충돌 방지). 데이터 조회·발굴·분석만 하고 리포트 텍스트만 출력하라."""


def main():
    cfg = bridge.load_config()
    held = [p["ticker"] for p in portfolio.load().get("positions", [])]

    bridge.log(f"신규 종목 발굴 시작 (제외 {len(held)}종목)")
    prompt = build_prompt(held)

    claude_bin = cfg.get("claude_bin", "claude")
    project_dir = cfg.get("project_dir", bridge.BASE_DIR)
    perm = cfg.get("analyze_permission_mode", "bypassPermissions")
    cmd = [claude_bin, "-p", prompt, "--permission-mode", perm, "--output-format", "text"]
    try:
        proc = subprocess.run(cmd, cwd=project_dir, capture_output=True,
                              text=True, timeout=CLAUDE_TIMEOUT)
    except subprocess.TimeoutExpired:
        bridge.tg_send(cfg, f"⏱️ 발굴이 {CLAUDE_TIMEOUT}초를 초과했어요. 다시 시도해주세요.")
        return
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        bridge.tg_send(cfg, f"❌ 발굴 오류(코드 {proc.returncode}):\n{err[:1500]}")
        return

    report = (proc.stdout or "").strip() or "(빈 응답)"
    bridge.tg_send(cfg, report)
    bridge.log("발굴 리포트 전송 완료")


if __name__ == "__main__":
    main()
