# web (정적 프론트)

브라우저가 직접 띄우는 채팅 UI입니다. 빌드 과정 없이 그대로 서빙합니다.

| 파일 | 역할 |
|---|---|
| `index.html` | 정적 페이지 로더, 폰트 임베드. |
| `app.js` | 채팅 메시지, 페르소나 선택, SSE 수신, 마커 분리 표시. |
| `config.js` | API 주소 자동 전환(로컬 8001 vs 배포 URL). |
| `styles.css` | 반응형 UI, 다국어 텍스트 지원. |

실행: `python -m http.server 8000 -d web` 후 브라우저에서 `http://localhost:8000/`.
배포 시 `config.js`의 `PROD_API`를 백엔드 배포 주소로 맞춥니다.
