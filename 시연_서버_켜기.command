#!/bin/bash
# 시연 서버 켜기. Finder에서 더블클릭하면 터미널이 열리며 서버 2개가 같이 뜬다.
# 백엔드(FastAPI, 8001) + 프론트(정적 web, 8000).
# 끄려면 이 터미널 창에서 Ctrl+C 한 번 누르거나 창을 닫는다.

cd "$(dirname "$0")"

echo "=== LifeRoad 시연 서버 켜는 중 ==="
echo ""

# 가상환경이 없으면 원인 불명 오류 대신 안내를 준다.
if [ ! -x ".venv/bin/uvicorn" ]; then
  echo "[오류] .venv 가상환경이 없습니다."
  echo "  처음이면 '시연_시작_맥.command'를 더블클릭하세요. 설치까지 자동으로 해 줍니다."
  read -n 1 -s
  exit 1
fi

# 백엔드 띄우기(백그라운드). 시연은 이 컴퓨터에서만 접속하므로 127.0.0.1에 묶는다.
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8001 --reload &
BACK_PID=$!

# 프론트 띄우기(백그라운드)
.venv/bin/python -m http.server 8000 -d web &
FRONT_PID=$!

# 기업 관점 이상탐지 관제 콘솔(정적, 8002)
.venv/bin/python -m http.server 8002 -d fraud_console &
FRAUD_PID=$!

# 창 닫으면 서버 3개 같이 정리
trap "kill $BACK_PID $FRONT_PID $FRAUD_PID 2>/dev/null" EXIT

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
