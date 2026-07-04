"""contracts/visa_input.py — 서류팀(doc-automator) → 이상치팀 경계 계약.

서류팀이 OCR 로 추출한 비자 정보 중, 이상치 탐지가 의존하는 **최소 필드만**
Pydantic 으로 정의한다. 이 모델을 통과한 dict 만 core 로 들어온다.
서류팀 연동 전에는 `data/mock_visa/` 의 가짜 데이터로 대체한다.

주의: 설치 환경은 pydantic v1(1.10.x) 이므로 v1 API(`validator`, `class Config`)로 작성.
      (v1 `validator` 는 v2 에서도 deprecation 경고와 함께 동작하여 상위호환.)
"""
from datetime import date
from enum import Enum

from pydantic import BaseModel, validator


class VisaType(str, Enum):
    """체류자격. 초기 대상(우선): 외국인 근로자 E-9, 유학생 D-2.

    나머지는 실재하는 체류자격으로, 미지정 값은 검증에서 명확히 실패시킨다.
    """

    # --- 우선 대상 ---
    E_9 = "E-9"   # 비전문취업(외국인 근로자)
    D_2 = "D-2"   # 유학(학위과정)
    # --- 확장 대상 ---
    D_4 = "D-4"   # 일반연수(어학연수 등)
    E_7 = "E-7"   # 특정활동
    F_2 = "F-2"   # 거주
    F_4 = "F-4"   # 재외동포
    F_5 = "F-5"   # 영주
    F_6 = "F-6"   # 결혼이민
    H_2 = "H-2"   # 방문취업


class VisaInput(BaseModel):
    """서류팀에서 받을 비자 입력. dict→VisaInput 검증 통과/실패가 명확해야 한다."""

    customer_id: str
    visa_type: VisaType        # enum 외 값은 검증 실패
    residency_end_date: date   # ISO 문자열/ date 객체 모두 파싱
    nationality: str

    class Config:
        # core 는 enum 을 모른다 → 통과 후 .visa_type 은 "E-9" 같은 문자열로 노출.
        use_enum_values = True

    @validator("customer_id", "nationality")
    def _not_blank(cls, v: str) -> str:
        if v is None or not str(v).strip():
            raise ValueError("must not be blank")
        return str(v).strip()

    @validator("nationality")
    def _nationality_upper(cls, v: str) -> str:
        # 국가코드는 대문자 정규화("vn" → "VN") — segment_key 일관성.
        return v.upper()


if __name__ == "__main__":
    # 통과/실패 데모 (완료 기준: 검증 통과/실패가 명확)
    ok = VisaInput(
        customer_id="VN-0001",
        visa_type="E-9",
        residency_end_date="2026-12-31",
        nationality="vn",
    )
    print("[PASS]", ok.dict())

    for bad in (
        {"customer_id": "X", "visa_type": "Z-9", "residency_end_date": "2026-01-01", "nationality": "KR"},
        {"customer_id": " ", "visa_type": "D-2", "residency_end_date": "2026-01-01", "nationality": "NP"},
        {"customer_id": "Y", "visa_type": "D-2", "residency_end_date": "not-a-date", "nationality": "NP"},
    ):
        try:
            VisaInput(**bad)
            print("[UNEXPECTED PASS]", bad)
        except Exception as e:  # pydantic.ValidationError
            print("[FAIL as expected]", bad.get("visa_type"), "/", type(e).__name__)
