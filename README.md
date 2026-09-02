# cgv-imax-alert

CGV 특정 극장·영화·상영관(IMAX 등)의 예매 오픈을 감지해 Slack으로 알림을 보내는 감시 스크립트.

표준 라이브러리만 사용 — `pip install` 불필요.

## 동작 원리

CGV 신사이트(cgv.co.kr, Next.js)의 내부 JSON API를 폴링한다:

| API | 용도 |
|---|---|
| `GET /api/v1/booking/searchSiteScnscYmdListBySite?coCd=A420&siteNo={극장}` | 예매 오픈된 날짜 목록 |
| `GET /api/v1/booking/searchMovScnInfo?coCd=A420&siteNo={극장}&scnYmd={날짜}&rtctlScopCd=08` | 해당 날짜 전체 회차 (제목·상영관·시작시간·잔여석 포함) |

- 요청 헤더에 **전체 Chrome User-Agent**가 필요하다 (축약형은 403).
- 이미 알린 회차는 `notified.json`에 기록해 중복 알림을 막는다.
- 구 사이트의 `iframeTheater.aspx` 방식은 2026년 현재 폐기됨.

## 설정

### 1. config.json

```json
{
  "targets": [
    {
      "site_no": "0013",
      "site_name": "용산아이파크몰",
      "movie_keyword": "오디세이",
      "screen_keyword": "IMAX",
      "dates": []
    }
  ]
}
```

- `movie_keyword` / `screen_keyword`: 부분일치. 빈 문자열 = 조건 없음.
- `dates`: `["20260915"]` 형식. 빈 배열 = 오픈된 모든 날짜 감시.
- 타깃 여러 개 등록 가능 (극장별·영화별 배열에 추가).

주요 극장 코드: 용산아이파크몰 `0013`, 씨네드쉐프 용산 `P013`, 강남 `0056`.
다른 극장은 `https://cgv.co.kr/api/v1/content/site/searchAllRegionAndSite?coCd=A420` 응답의 `siteInfo`에서 확인.

용산아이파크몰 상영관명 예시: `IMAX관`, `4DX관`, `SCREENX관 (뻥클라이너) with PRIVATE BOX`, `14관[SCREENX] (Laser)`, `골드클래스[CGV아트하우스]`.

### 2. Slack Incoming Webhook

Slack 앱 관리 → Incoming Webhooks → 채널 지정 후 URL 발급.
URL은 코드에 넣지 말고 환경변수 `SLACK_WEBHOOK`으로만 주입한다.

## 실행

### 로컬 1회 실행 (테스트)

```powershell
$env:SLACK_WEBHOOK = "https://hooks.slack.com/services/..."
python watcher.py
```

### GitHub Actions (권장, 10분 간격)

1. 이 디렉토리를 GitHub 리포로 푸시
2. 리포 Settings → Secrets and variables → Actions → `SLACK_WEBHOOK` 등록
3. `.github/workflows/watch.yml`이 10분마다 실행되고, `notified.json`을 커밋해 상태를 유지

수동 실행: Actions 탭 → CGV watch → Run workflow.

### Windows 작업 스케줄러 (로컬 상시 PC가 있는 경우)

```powershell
schtasks /Create /TN "CGV Watch" /SC MINUTE /MO 10 /TR "python \"G:\내 드라이브\[MZC]\Claude 작업\cgv-imax-alert\watcher.py\""
```

(작업 스케줄러 사용 시 `SLACK_WEBHOOK`을 시스템 환경변수로 등록해야 함.)

## 주의

- 비공식 API라 CGV가 예고 없이 바꿀 수 있다. 깨지면 브라우저 개발자도구 Network 탭에서 `searchMovScnInfo` 호출을 다시 확인.
- 폴링 간격은 10분 유지 권장 (과도한 요청은 차단 위험).
- 개인 용도로만 사용.
