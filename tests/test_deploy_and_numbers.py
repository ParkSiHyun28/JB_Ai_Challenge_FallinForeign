"""배포 안전망과 수치 무결성 회귀 테스트.

1. secrets 브리지: st.secrets와 os.environ 폴백이 올바로 동작하는지.
2. 수치 표시값: 리팩터(상수화) 후에도 심사 대상 통계가 동일하게 나오는지.
"""

import os

from mcp_servers.asset import data
from mcp_servers.asset import tools


# ---------------------------------------------------------------------------
# 1. secrets 브리지
# ---------------------------------------------------------------------------

def test_bridge_secrets_importable_without_streamlit_context():
    """streamlit 런타임 컨텍스트 밖에서도 bridge_secrets()가 예외 없이 돈다.
    테스트나 MCP stdio 서버처럼 streamlit 없는 환경에서 import만으로 깨지면 안 된다."""
    from shared.secrets_bridge import bridge_secrets

    moved = bridge_secrets()
    assert isinstance(moved, dict)  # 비어 있어도 dict를 반환한다.


def test_bridge_does_not_overwrite_existing_env(monkeypatch):
    """이미 환경에 있는 키(로컬 .env 등)는 브리지가 덮어쓰지 않는다."""
    from shared.secrets_bridge import bridge_secrets

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    bridge_secrets()
    assert os.environ["LLM_PROVIDER"] == "ollama"


# ---------------------------------------------------------------------------
# 2. 수치 무결성: 상수화 후에도 표시값 동결
# ---------------------------------------------------------------------------

def test_claim_deadline_constant_exists():
    """소멸시효 3년이 data.py 상수로 존재해야 한다. 하드코딩 금지."""
    assert data.CLAIM_DEADLINE_YEARS == 3


def test_pension_refund_value_stable():
    """민 반환일시금 = 납부월수 * 85,517원. 납부월수는 페르소나 데이터에서 읽어
    데이터 변경(입국일/납부월수 조정)에도 계산식이 안정적인지 검증한다."""
    from shared.personas import get_persona
    months = get_persona("minh")["pension_months"]
    out = tools.pension_estimator("minh")
    assert out["numbers"]["estimated_refund_krw"] == 85_517 * months


def test_pension_convert_rate_renders_22_4_percent():
    """취업전환율 표시가 22.4%로 정확히 나와야 한다(상수에서 도출)."""
    out = tools.pension_estimator("suman")
    assert "22.4%" in out["detail"]
    assert "22.4%" in out["card"]["metric"]


def test_deadline_radar_uses_claim_deadline_constant():
    """deadline_radar 출력의 소멸시효 연수가 상수와 일치해야 한다."""
    out = tools.deadline_radar("minh", as_of="2026-10-03")
    assert out["numbers"]["claim_deadline_years"] == data.CLAIM_DEADLINE_YEARS
    assert f"{data.CLAIM_DEADLINE_YEARS}년" in out["detail"]


def test_pension_total_payout_derived_from_constant():
    """반환일시금 총 지급액 통계가 상수에서 도출돼 3,294억 원으로 표시돼야 한다."""
    out = tools.pension_estimator("minh")
    assert "3,294억" in out["detail"]


def test_fx_constants_removed():
    """미사용 FX 환율 상수는 제거됐어야 한다(죽은 코드 정리)."""
    assert not hasattr(data, "FX_BASE_KRW")
    assert not hasattr(data, "FX_NOW_KRW")
    assert not hasattr(data, "FX_ALERT_THRESHOLD_KRW")
