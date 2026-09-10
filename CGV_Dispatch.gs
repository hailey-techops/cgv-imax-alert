/**
 * CGV watch 워크플로 디스패처 (Google Apps Script)
 *
 * GitHub Actions의 schedule 트리거는 실제로 2~5시간씩 밀리므로,
 * GAS 시간 트리거(10분마다)에서 workflow_dispatch API를 호출해 워크플로를 직접 깨운다.
 * workflow_dispatch는 schedule과 달리 즉시 큐에 들어간다.
 *
 * 설정 (스크립트 속성 — 프로젝트 설정 > 스크립트 속성):
 *   GITHUB_TOKEN   Fine-grained PAT. 대상 리포: hailey-techops/cgv-imax-alert,
 *                  권한: Actions → Read and write (Metadata는 자동 포함)
 *   ALERT_WEBHOOK  (선택) 디스패치 실패가 연속될 때 알림 보낼 Slack Webhook URL
 *
 * 최초 1회: setupTrigger() 실행 → 10분 트리거 생성
 * 수동 테스트: dispatchWatch() 실행 후 Actions 탭에서 workflow_dispatch 실행 확인
 */

const GH_OWNER = 'hailey-techops';
const GH_REPO = 'cgv-imax-alert';
const GH_WORKFLOW = 'watch.yml';
const GH_REF = 'main';
const FAIL_ALERT_THRESHOLD = 3; // 연속 실패 n회째에 Slack 알림

function dispatchWatch() {
  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('스크립트 속성 GITHUB_TOKEN이 없습니다.');

  const url = `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/actions/workflows/${GH_WORKFLOW}/dispatches`;
  const res = UrlFetchApp.fetch(url, {
    method: 'post',
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    contentType: 'application/json',
    payload: JSON.stringify({ ref: GH_REF }),
    muteHttpExceptions: true,
  });

  const code = res.getResponseCode();
  if (code === 204) {
    props.setProperty('FAIL_COUNT', '0');
    props.setProperty('LAST_OK', new Date().toISOString());
    console.log('dispatched OK');
    return;
  }

  const fails = Number(props.getProperty('FAIL_COUNT') || 0) + 1;
  props.setProperty('FAIL_COUNT', String(fails));
  const msg = `workflow_dispatch 실패 HTTP ${code}: ${res.getContentText().slice(0, 300)}`;
  console.error(msg);

  if (fails === FAIL_ALERT_THRESHOLD) {
    const hook = props.getProperty('ALERT_WEBHOOK');
    if (hook) {
      UrlFetchApp.fetch(hook, {
        method: 'post',
        contentType: 'application/json',
        payload: JSON.stringify({
          text: `⚠️ CGV watch 디스패처 ${fails}회 연속 실패\n${msg}\n토큰 만료 여부 확인 필요`,
        }),
        muteHttpExceptions: true,
      });
    }
  }
  throw new Error(msg);
}

/** 10분 간격 트리거 생성 (중복 방지: 기존 dispatchWatch 트리거는 제거) */
function setupTrigger() {
  removeTrigger();
  ScriptApp.newTrigger('dispatchWatch').timeBased().everyMinutes(10).create();
  console.log('트리거 생성 완료: dispatchWatch 10분마다');
}

function removeTrigger() {
  ScriptApp.getProjectTriggers()
    .filter((t) => t.getHandlerFunction() === 'dispatchWatch')
    .forEach((t) => ScriptApp.deleteTrigger(t));
}

/** 상태 확인용 */
function status() {
  const p = PropertiesService.getScriptProperties();
  console.log({
    lastOk: p.getProperty('LAST_OK'),
    failCount: p.getProperty('FAIL_COUNT'),
    triggers: ScriptApp.getProjectTriggers().map((t) => t.getHandlerFunction()),
  });
}
