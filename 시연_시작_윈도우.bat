@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
REM ============================================================
REM   My LifeRoad 시연 시작 (Windows)
REM   더블클릭하면: 파이썬 확인 -> 가상환경 + 패키지 설치 -> 서버 2개 -> 브라우저 자동 열기
REM   끄려면: 이 창을 닫기
REM ============================================================

cd /d "%~dp0"

echo =============================================
echo    My LifeRoad 시연 서버 (Windows)
echo =============================================
echo.

REM 1) 파이썬 찾기
set PYBIN=
where python >nul 2>&1 && set PYBIN=python
if "%PYBIN%"=="" (
  where py >nul 2>&1 && set PYBIN=py
)

REM 파이썬이 없으면: winget 있으면 자동설치 시도, 없으면 안내
if "%PYBIN%"=="" (
  echo [알림] 파이썬이 설치돼 있지 않습니다.
  echo.
  where winget >nul 2>&1
  if errorlevel 1 (
    echo   자동 설치 도구가 없어 직접 설치가 필요합니다.
    echo   설치 페이지를 엽니다. 설치 후 이 파일을 다시 실행하세요.
    echo   설치 화면에서 "Add Python to PATH" 체크를 꼭 켜세요.
    start "" "https://www.python.org/downloads/release/python-3127/"
    pause
    exit /b 1
  ) else (
    echo   winget으로 파이썬 3.12를 자동 설치할 수 있습니다.
    set /p ANS="  지금 설치할까요? (y/n) "
    if /i "!ANS!"=="y" (
      echo   설치 중... 몇 분 걸릴 수 있습니다
      winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
      echo.
      echo   [중요] 설치가 끝났습니다. PATH 적용을 위해
      echo   이 창을 닫고 이 파일을 다시 더블클릭하세요.
      pause
      exit /b 0
    )
  )
)

REM 자동설치를 건너뛰었거나 실패해 여전히 없으면 재탐지 후 종료
REM (블록 안에서는 지연 확장 !PYBIN!을 써야 방금 set한 값이 보인다)
if "%PYBIN%"=="" (
  where python >nul 2>&1 && set PYBIN=python
  if "!PYBIN!"=="" where py >nul 2>&1 && set PYBIN=py
)
if "%PYBIN%"=="" (
  echo.
  echo   파이썬을 설치한 뒤 이 파일을 다시 실행하세요:
  echo   https://www.python.org/downloads/
  pause
  exit /b 1
)

echo [1/4] 파이썬 확인 완료
%PYBIN% --version

REM 2) 가상환경 (없으면 생성)
if not exist ".venv" (
  echo [2/4] 가상환경 만드는 중... 처음 한 번만, 잠시 걸립니다
  %PYBIN% -m venv .venv
  if errorlevel 1 (
    echo [오류] 가상환경 생성 실패. 파이썬 버전을 확인하세요.
    echo   Microsoft Store 연결용 가짜 python이 잡혔을 수 있습니다.
    echo   python.org 설치판을 설치하고 "Add Python to PATH"를 켜세요.
    pause
    exit /b 1
  )
) else (
  echo [2/4] 가상환경 확인 완료
)

REM 3) 패키지 설치
echo [3/4] 필요한 패키지 확인/설치 중... 처음엔 1~3분 걸릴 수 있습니다
.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
if errorlevel 1 (
  echo [오류] 패키지 설치 실패. 인터넷 연결을 확인하세요.
  pause
  exit /b 1
)

REM 4) 서버 2개 띄우기 (각각 새 창)
echo [4/4] 서버 켜는 중...
echo.

start "LifeRoad 백엔드" .venv\Scripts\uvicorn.exe backend.main:app --host 127.0.0.1 --port 8001
start "LifeRoad 프론트" .venv\Scripts\python.exe -m http.server 8000 -d web
start "LifeRoad 관제콘솔" .venv\Scripts\python.exe -m http.server 8002 -d fraud_console

REM 백엔드 기동 대기 후 브라우저 자동 열기
timeout /t 3 /nobreak >nul
start "" "http://localhost:8000/"

echo.
echo =============================================
echo   준비 완료. 브라우저가 자동으로 열립니다.
echo   안 열리면 직접 여세요:  http://localhost:8000/
echo.
echo   끄기: 새로 뜬 서버 창 2개를 닫으세요.
echo =============================================
echo.
pause
