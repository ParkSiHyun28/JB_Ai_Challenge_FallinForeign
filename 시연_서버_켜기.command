#!/bin/bash
# 시연 서버 켜기. Finder에서 더블클릭하면 터미널이 열리며 서버 2개가 같이 뜬다.
# 백엔드(FastAPI, 8001) + 프론트(정적 web, 8000).
# 끄려면 이 터미널 창에서 Ctrl+C 한 번 누르거나 창을 닫는다.

cd "$(dirname "$0")"

echo "=== LifeRoad 시연 서버 켜는 중 ==="
echo ""

# 백엔드 띄우기(백그라운드)
.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload &
BACK_PID=$!

# 프론트 띄우기(백그라운드)
.venv/bin/python -m http.server 8000 -d web &
FRONT_PID=$!

# 창 닫으면 두 서버 같이 정리
trap "kill $BACK_PID $FRONT_PID 2>/dev/null" EXIT

# 백엔드 기동 대기
sleep 2

echo ""
echo "==========================================="
echo "  준비 완료. 아래 주소를 브라우저에서 열어라:"
echo ""
echo "      http://localhost:8000/"
echo ""
echo "  녹화: Cmd+Shift+5"
echo "  서버 끄기: 이 창에서 Ctrl+C 또는 창 닫기"
echo "==========================================="
echo ""

# 포그라운드 유지(창이 안 닫히게)
wait
