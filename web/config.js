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
