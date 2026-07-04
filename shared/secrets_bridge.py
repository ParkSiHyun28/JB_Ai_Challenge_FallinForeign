"""secrets 브리지. 로컬(.env)과 Streamlit Cloud(st.secrets) 양쪽에서 같은 코드가 키를 읽게 한다.

Streamlit Community Cloud는 .env 파일을 쓰지 않는다. 대신 앱 설정의 Secrets 탭에 적은 값을
st.secrets로 노출한다. 반면 기존 llm_provider.py는 os.environ.get으로만 키를 읽는다.
이 브리지가 st.secrets의 값을 os.environ으로 옮겨, 키 읽는 코드를 한 줄도 안 고치고
로컬과 클라우드 둘 다에서 동작하게 만든다.

사용법: app.py 최상단에서 llm_provider를 import 하기 전에 bridge_secrets()를 호출한다.
import 시점에 모듈 수준 os.environ.get이 실행되므로 순서가 중요하다.
"""

import os

# 브리지가 옮길 키 목록. 공급자 선택과 각 공급자 키, 모델 오버라이드를 포함한다.
_BRIDGED_KEYS = (
    "LLM_PROVIDER",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_BASE_URL",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "GROQ_BASE_URL",
    "ANTHROPIC_API_KEY",
    "CLAUDE_MODEL",
    "OLLAMA_MODEL",
    "OLLAMA_BASE_URL",
)


def bridge_secrets() -> dict:
    """st.secrets에 있는 키를 os.environ으로 복사한다. 이미 환경에 있는 값은 덮어쓰지 않는다.

    로컬: st.secrets가 없거나 비어 있으면 아무것도 안 한다. .env(load_dotenv)가 채운 값을 쓴다.
    클라우드: st.secrets에서 키를 읽어 os.environ에 넣는다.

    반환: 실제로 브리지한 키 이름과 출처('secrets')를 담은 dict. 디버그 표시용.
    """
    moved = {}
    try:
        import streamlit as st
    except ModuleNotFoundError:
        return moved  # streamlit 없는 환경(테스트 등). 브리지 불필요.

    # st.secrets 접근은 secrets.toml이 없으면 예외를 던질 수 있다. 통째로 감싼다.
    try:
        secrets = st.secrets
    except Exception:
        return moved

    for key in _BRIDGED_KEYS:
        # 이미 환경에 있으면(로컬 .env 등) 존중한다. 클라우드에선 환경이 비어 있어 secrets가 채운다.
        if os.environ.get(key):
            continue
        try:
            val = secrets.get(key) if hasattr(secrets, "get") else secrets[key]
        except Exception:
            val = None
        if val is not None and str(val) != "":
            os.environ[key] = str(val)
            moved[key] = "secrets"
    return moved
