"""수치 무결성 회귀 테스트.

심사 대상 통계가 리팩터(상수화) 후에도 동일하게 표시되는지 고정한다.
(streamlit 폐기와 함께 secrets 브리지 테스트는 제거됐다.)
"""

from mcp_servers.asset import data
from mcp_servers.asset import tools


# ---------------------------------------------------------------------------
# 수치 무결성: 상수화 후에도 표시값 동결
# ---------------------------------------------------------------------------

def test_claim_deadline_constants_split_by_law():
    """시효 상수가 제도별로 분리돼 있어야 한다.
    출국만기보험 3년(외국인고용법 전용보험).
    반환일시금은 사유별: 출국 사유 5년 / 60세 도달 사유 10년(국민연금법 제115조).
    2026-07-04 공단 1차 출처 재검증으로 옛 '일률 10년' 표기를 정정했다.
    출처: https://www.nps.or.kr/pnsinfo/ntpsklg/getOHAF0084M0.do"""
    assert data.CLAIM_DEADLINE_YEARS == 3
    assert data.PENSION_REFUND_DEADLINE_YEARS == 5
    assert data.PENSION_REFUND_DEADLINE_YEARS_AGE60 == 10


def test_pension_detail_mentions_5_year_deadline():
    """반환일시금 안내에 출국 사유 시효 5년이 상수에서 도출돼 표시된다(옛 10년 표기 회귀 방지)."""
    out = tools.pension_estimator("minh")
    assert "5년" in out["detail"]
    assert "10년" not in out["detail"]


def test_pension_refund_follows_nps_formula():
    """반환일시금 = 납부보험료(연도별 요율) + 이자. 옛 통계 단가(85,517원/월) 회귀 방지.
    2026-07-04 고도화: 공단 공식(국민연금법 제77조)으로 교체됐다."""
    out = tools.pension_estimator("minh")
    n = out["numbers"]
    assert n["principal_krw"] > 0
    assert n["interest_krw"] > 0
    assert n["estimated_refund_krw"] == n["principal_krw"] + n["interest_krw"]
    # 통계 단가 방식이면 나오던 값(85,517 × 납부월수)과 달라야 한다
    assert n["estimated_refund_krw"] != 85_517 * n["pension_months"]


def test_pension_suman_not_enrolled_honest():
    """수만(네팔)은 가입 제외국. 반환일시금 해당 없음을 정직하게 안내해야 한다.
    옛 '취업전환 시 수령 가능' 오류 안내(사실 아님) 회귀 방지."""
    out = tools.pension_estimator("suman")
    assert out["numbers"]["eligible"] is False
    assert out["numbers"]["reason"] == "not_enrolled"
    assert "가입 대상이 아닙" in out["detail"]


def test_deadline_radar_uses_claim_deadline_constant():
    """deadline_radar 출력의 소멸시효 연수가 상수와 일치해야 한다."""
    out = tools.deadline_radar("minh", as_of="2026-10-03")
    assert out["numbers"]["claim_deadline_years"] == data.CLAIM_DEADLINE_YEARS
    assert f"{data.CLAIM_DEADLINE_YEARS}년" in out["detail"]


def test_pension_total_payout_derived_from_constant():
    """반환일시금 총 지급액 통계가 상수에서 도출돼 3,294억 원으로 표시돼야 한다."""
    out = tools.pension_estimator("minh")
    assert "3,294억" in out["detail"]

