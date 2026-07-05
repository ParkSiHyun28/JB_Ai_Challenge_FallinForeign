#!/bin/bash
# ============================================================
#  My LifeRoad 시연 시작 (macOS)
#  더블클릭하면: 파이썬 확인 → 가상환경 + 패키지 설치 → 서버 2개 → 브라우저 자동 열기
#  끄려면: 이 터미널 창에서 Ctrl+C 또는 창 닫기
# ============================================================

cd "$(dirname "$0")"

echo "============================================="
echo "   My LifeRoad 시연 서버 (macOS)"
echo "============================================="
echo ""

# 1) 파이썬 찾기 (python3 우선)
find_python() {
  if command -v python3 >/dev/null 2>&1; then PYBIN="python3"
  elif command -v python >/dev/null 2>&1; then PYBIN="python"
  else PYBIN=""; fi
}

PYBIN=""
find_python

# 파이썬이 없으면: Homebrew 있으면 자동설치 시도, 없으면 안내
if [ -z "$PYBIN" ]; then
  echo "[알림] 파이썬이 설치돼 있지 않습니다."
  echo ""
  if command -v brew >/dev/null 2>&1; then
    echo "  Homebrew가 있습니다. 파이썬 3.12를 자동으로 설치할 수 있습니다."
    printf "  지금 설치할까요? (y/n) "
    read -r ANS
    if [ "$ANS" = "y" ] || [ "$ANS" = "Y" ]; then
      echo "  설치 중... (몇 분 걸릴 수 있습니다)"
      brew install python@3.12
      # brew 파이썬 경로를 PATH 앞에 추가
      BREW_PY="$(brew --prefix)/opt/python@3.12/libexec/bin"
      [ -d "$BREW_PY" ] && export PATH="$BREW_PY:$PATH"
      find_python
    fi
  else
    echo "  자동 설치 도구(Homebrew)가 없습니다."
    printf "  Homebrew를 먼저 설치하고 파이썬까지 자동으로 깔까요? (y/n) "
    read -r ANS2
    if [ "$ANS2" = "y" ] || [ "$ANS2" = "Y" ]; then
      echo ""
      echo "  Homebrew 설치 중... 중간에 [관리자 비밀번호]를 물으면 입력하세요."
      echo "  (비밀번호는 화면에 안 보입니다. 입력 후 Enter)"
      echo ""
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
      # 설치 직후 같은 세션에서 brew를 PATH에 올린다 (Apple Silicon / Intel 경로 모두 시도)
      if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"
      elif [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"; fi
      if command -v brew >/dev/null 2>&1; then
        echo "  파이썬 3.12 설치 중..."
        brew install python@3.12
        BREW_PY="$(brew --prefix)/opt/python@3.12/libexec/bin"
        [ -d "$BREW_PY" ] && export PATH="$BREW_PY:$PATH"
        find_python
      else
        echo "  [오류] Homebrew 설치가 끝나지 않았습니다. 파이썬을 직접 설치해 주세요."
        open "https://www.python.org/downloads/release/python-3127/"
      fi
    else
      echo "  파이썬 설치 페이지를 엽니다. 설치 후 이 파일을 다시 더블클릭하세요."
      open "https://www.python.org/downloads/release/python-3127/"
    fi
  fi
fi

# 자동설치 시도 후에도 없으면 종료
if [ -z "$PYBIN" ]; then
  echo ""
  echo "  파이썬을 설치한 뒤 이 파일을 다시 실행하세요:"
  echo "  https://www.python.org/downloads/"
  echo ""
  echo "  (창을 닫으려면 아무 키나 누르세요)"
  read -n 1 -s
  exit 1
fi

echo "[1/4] 파이썬 확인: $($PYBIN --version)"

# 2) 가상환경 (없으면 생성)
if [ ! -d ".venv" ]; then
  echo "[2/4] 가상환경 만드는 중... (처음 한 번만, 잠시 걸립니다)"
  "$PYBIN" -m venv .venv
  if [ $? -ne 0 ]; then
    echo "[오류] 가상환경 생성 실패. 위 파이썬 버전을 확인하세요."
    read -n 1 -s
    exit 1
  fi
else
  echo "[2/4] 가상환경 확인 완료"
fi

# 3) 패키지 설치 (이미 설치돼 있으면 빠르게 넘어감)
echo "[3/4] 필요한 패키지 확인/설치 중... (처음엔 1~3분 걸릴 수 있습니다)"
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
if [ $? -ne 0 ]; then
  echo "[오류] 패키지 설치 실패. 인터넷 연결을 확인하세요."
  read -n 1 -s
  exit 1
fi

# 4) 서버 2개 띄우기
echo "[4/4] 서버 켜는 중..."
echo ""

# 시연은 이 컴퓨터에서만 접속하므로 127.0.0.1에 묶는다(공용 와이파이 노출 방지).
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8001 &
BACK_PID=$!

.venv/bin/python -m http.server 8000 -d web &
FRONT_PID=$!

# 기업 관점 이상탐지 관제 콘솔(정적). 메인 화면 iframe이 이 주소를 띄운다.
.venv/bin/python -m http.server 8002 -d fraud_console &
FRAUD_PID=$!

# 창 닫으면 서버 3개 같이 정리
trap "kill $BACK_PID $FRONT_PID $FRAUD_PID 2>/dev/null" EXIT

# 백엔드 기동 대기 후 브라우저 자동 열기
sleep 3
open "http://localhost:8000/"

echo ""
echo "============================================="
echo "  준비 완료. 브라우저가 자동으로 열립니다."
echo "  안 열리면 직접 여세요:  http://localhost:8000/"
echo ""
echo "  끄기: 이 창에서 Ctrl+C 또는 창 닫기"
echo "============================================="
echo ""

wait
