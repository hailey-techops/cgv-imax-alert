#!/usr/bin/env python3
"""CGV 상영 스케줄 감시 → Slack 알림.

CGV 신사이트(cgv.co.kr) 내부 JSON API를 폴링해서 config.json에 정의한
조건(극장 + 영화 키워드 + 상영관 키워드 + 날짜)에 맞는 회차가 새로 열리면
Slack Incoming Webhook으로 알림을 보낸다.

사용 API (2026-09 기준, 브라우저 Network 탭에서 확인):
  GET https://cgv.co.kr/api/v1/booking/searchSiteScnscYmdListBySite
      ?coCd=A420&siteNo={극장코드}                → 예매 오픈된 날짜 목록
  GET https://cgv.co.kr/api/v1/booking/searchMovScnInfo
      ?coCd=A420&siteNo={극장코드}&scnYmd={YYYYMMDD}&rtctlScopCd=08
                                                  → 해당 날짜 전체 회차

환경변수:
  SLACK_WEBHOOK  Slack Incoming Webhook URL (필수)
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://cgv.co.kr/api/v1"
CO_CD = "A420"  # CGV 법인 코드 (고정)
HEADERS = {
    # 축약형 UA는 403이 떨어짐 — 전체 Chrome UA 필요
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://cgv.co.kr/cnm/movieBook/cinema",
    "Accept": "application/json",
}
BOOKING_URL = "https://cgv.co.kr/cnm/movieBook/movie"

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "notified.json"


def api_get(path: str, params: dict) -> dict:
    url = f"{BASE}/{path}?{urlencode(params)}"
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=30) as r:
        body = json.loads(r.read().decode("utf-8"))
    if body.get("statusCode") != 0:
        raise RuntimeError(f"API error {body.get('statusCode')}: {body.get('statusMessage')} ({url})")
    return body["data"]


def open_dates(site_no: str) -> list[str]:
    """극장의 예매 오픈된 날짜(YYYYMMDD) 목록."""
    data = api_get("booking/searchSiteScnscYmdListBySite", {"coCd": CO_CD, "siteNo": site_no})
    return [d["scnYmd"] for d in data]


def showtimes(site_no: str, ymd: str) -> list[dict]:
    """해당 극장·날짜의 전체 회차."""
    return api_get(
        "booking/searchMovScnInfo",
        {"coCd": CO_CD, "siteNo": site_no, "scnYmd": ymd, "rtctlScopCd": "08"},
    )


def fmt_time(hhmm: str) -> str:
    return f"{hhmm[:2]}:{hhmm[2:]}" if hhmm and len(hhmm) >= 4 else hhmm


def fmt_date(ymd: str) -> str:
    dt = datetime.strptime(ymd, "%Y%m%d")
    return dt.strftime("%m/%d") + "(" + "월화수목금토일"[dt.weekday()] + ")"


def match(show: dict, target: dict) -> bool:
    movie_kw = target.get("movie_keyword", "")
    screen_kw = target.get("screen_keyword", "")
    dates = target.get("dates", [])
    title = show.get("expoProdNm") or show.get("prodNm") or ""
    screen = show.get("expoScnsNm") or show.get("scnsNm") or ""
    if movie_kw and movie_kw not in title:
        return False
    if screen_kw and screen_kw not in screen:
        return False
    if dates and show.get("scnYmd") not in dates:
        return False
    return True


def show_key(show: dict) -> str:
    return "|".join(
        str(show.get(k, "")) for k in ("siteNo", "scnYmd", "scnsNo", "prodNo", "scnsrtTm")
    )


def build_messages(new_hits: list[tuple[dict, dict]]) -> list[str]:
    """(영화, 극장, 상영관)별로 별도 메시지 생성. 시간마다 잔여/전체 좌석 표기.

    highlight_dates에 해당하는 회차가 포함되면 @channel 멘션 + 🚨 강조 헤더.
    """
    groups: dict[tuple, dict[str, list[str]]] = {}
    hot_dates: dict[tuple, set] = {}
    for target, s in new_hits:
        title = s.get("expoProdNm", "")
        fmt = s.get("movkndDsplNm", "")
        if fmt and fmt not in title:
            title = f"{title} ({fmt})"
        key = (title, s.get("siteNm", ""), s.get("expoScnsNm", ""))
        entry = f"{fmt_time(s.get('scnsrtTm', ''))}({s.get('frSeatCnt', '?')}/{s.get('stcnt', '?')})"
        groups.setdefault(key, {}).setdefault(s["scnYmd"], []).append(entry)
        if s["scnYmd"] in target.get("highlight_dates", []):
            hot_dates.setdefault(key, set()).add(s["scnYmd"])

    messages = []
    for (title, site, screen), by_date in groups.items():
        hot = hot_dates.get((title, site, screen), set())
        if hot:
            hot_str = ", ".join(fmt_date(d) for d in sorted(hot))
            lines = [f"🚨🚨 <!channel> *{hot_str} 예매 열렸다!!* 🚨🚨", ""]
        else:
            lines = ["🎬 *CGV 예매 오픈 감지!*", ""]
        lines.append(f"*{title}*  |  {site} · {screen}")
        for ymd in sorted(by_date):
            times = " · ".join(sorted(by_date[ymd]))
            mark = "🔥 " if ymd in hot else ""
            lines.append(f">{mark}*{fmt_date(ymd)}*  {times}")
        lines.append("")
        lines.append(f"<{BOOKING_URL}|바로 예매하러 가기 →>")
        messages.append("\n".join(lines))
    return messages


def send_slack(webhook: str, text: str) -> None:
    payload = json.dumps({"text": text}).encode("utf-8")
    req = Request(webhook, data=payload, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=30) as r:
        r.read()


def main() -> int:
    webhook = os.environ.get("SLACK_WEBHOOK")
    if not webhook:
        print("ERROR: SLACK_WEBHOOK 환경변수가 없습니다.", file=sys.stderr)
        return 1

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    state: dict = {}
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    notified: set[str] = set(state.get("notified", []))

    new_hits: list[tuple[dict, dict]] = []  # (target, show)

    for target in config["targets"]:
        site_no = target["site_no"]
        try:
            dates = open_dates(site_no)
        except Exception as e:
            print(f"WARN: 날짜 목록 조회 실패 site={site_no}: {e}", file=sys.stderr)
            continue

        wanted = target.get("dates", [])
        check_dates = [d for d in dates if not wanted or d in wanted]

        for ymd in check_dates:
            try:
                shows = showtimes(site_no, ymd)
            except Exception as e:
                print(f"WARN: 회차 조회 실패 site={site_no} date={ymd}: {e}", file=sys.stderr)
                continue
            for show in shows:
                if not match(show, target):
                    continue
                key = show_key(show)
                if key in notified:
                    continue
                notified.add(key)
                new_hits.append((target, show))
            time.sleep(0.5)  # 예의상 요청 간격

    if new_hits:
        msgs = build_messages(new_hits)
        for msg in msgs:
            send_slack(webhook, msg)
        print(f"알림 전송: {len(new_hits)}건 ({len(msgs)}개 메시지)")
    else:
        print("새 회차 없음")

    STATE_PATH.write_text(
        json.dumps({"notified": sorted(notified)}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
