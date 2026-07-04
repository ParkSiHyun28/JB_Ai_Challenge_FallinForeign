/* API_BASE 자동전환.
   - localhost / 127.0.0.1 / file:// 로 열면 로컬 백엔드(http://localhost:8001)
   - 그 외(Cloudflare Pages 배포)면 배포 백엔드(Render)
   배포 백엔드 URL은 배포 단계에서 확정해 PROD_API에 박는다.
*/
const LOCAL_API = "http://localhost:8001";
const PROD_API  = "https://liferoad-api.onrender.com"; // 배포 확정 후 갱신

const _host = location.hostname;
const _isLocal =
  _host === "localhost" || _host === "127.0.0.1" || _host === "" || location.protocol === "file:";

window.API_BASE = _isLocal ? LOCAL_API : PROD_API;

/* 기업 관점(이상거래 관제 콘솔) URL.
   현재 이 프로젝트에는 fraud_guard 콘솔이 아직 없다. 그래서 값을 비워 둔다.
   비어 있으면 기업 관점 화면은 빈 iframe 대신 안내 템플릿만 보여준다.

   사기탐지 부문 연동 완료(2026-07-05):
   - mcp_servers/fraud_guard/ : 팀원 tool 라이브(폰 채팅이 호출).
   - fraud_console/ : 기업 관점 관제 콘솔(정적, 8002로 서빙).
   배포(Cloudflare Pages) 시엔 콘솔 호스팅 주소가 정해지면 아래 PROD 값을 채운다. */
window.FRAUD_CONSOLE_URL = _isLocal ? "http://localhost:8002/" : "";
