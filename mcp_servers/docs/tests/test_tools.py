"""서류행정 부문 테스트. form_autofill(페르소나 정보로 정부 신청서 채우기) 전용.
스캔/OCR과 준법심사는 제거됐으므로 관련 테스트도 없다."""

import os

from mcp_servers.docs import tools
from mcp_servers.docs import data


CARD_KEYS = {"icon", "head", "body", "metric"}


# --- 기본 동작: 페르소나 정보로 채우기 ---

def test_form_autofill_minh_alien_registration_renewal():
    result = tools.form_autofill(persona_id="minh", form_id="alien_registration_renewal")
    form = data.GOVERNMENT_FORMS["alien_registration_renewal"]
    assert result["numbers"]["autofill_fields"] == form["autofill_fields"]
    assert result["numbers"]["total_fields"] == form["total_fields"]
    assert result["numbers"]["autofill_ratio"] == round(
        form["autofill_fields"] / form["total_fields"], 2
    )
    # 페르소나 이름이 실제로 채워졌는지
    assert result["numbers"]["filled_data"]["성명"] == "응웬 반 민"
    assert result["card"] is not None
    assert set(result["card"].keys()) == CARD_KEYS
    assert result["card"]["icon"] == ""   # 이모지 금지


def test_form_autofill_suman_pension_return_claim():
    result = tools.form_autofill(persona_id="suman", form_id="pension_return_claim")
    form = data.GOVERNMENT_FORMS["pension_return_claim"]
    assert result["numbers"]["autofill_fields"] == form["autofill_fields"]
    assert result["numbers"]["filled_data"]["성명"] == "수만 라이"
    assert result["card"] is not None


# --- 실제 PDF 생성 (템플릿 보유 5종) ---

def test_form_autofill_generates_pdf_for_template_forms():
    result = tools.form_autofill(persona_id="minh", form_id="alien_registration_renewal")
    path = result["numbers"]["output_pdf_path"]
    assert path is not None
    assert os.path.exists(path)
    assert path.endswith("minh_alien_registration_renewal_filled.pdf")


def test_form_autofill_unique_filename_per_persona():
    r1 = tools.form_autofill(persona_id="minh", form_id="pension_return_claim")
    r2 = tools.form_autofill(persona_id="suman", form_id="pension_return_claim")
    # 페르소나별 고유 파일명이라 서로 덮어쓰지 않는다
    assert r1["numbers"]["output_pdf_path"] != r2["numbers"]["output_pdf_path"]


# --- 템플릿 없는 양식: 값만 채우고 PDF는 미생성 ---

def test_form_autofill_no_template_no_pdf():
    result = tools.form_autofill(persona_id="minh", form_id="departure_insurance_claim")
    assert result["numbers"]["output_pdf_path"] is None
    assert result["card"] is not None   # 값 채움 자체는 성공


# --- 방어 케이스 ---

def test_form_autofill_invalid_form_returns_none_card():
    result = tools.form_autofill(persona_id="minh", form_id="nonexistent_form")
    assert result["numbers"]["total_fields"] == 0
    assert result["card"] is None


def test_form_autofill_default_form_id_works():
    result = tools.form_autofill(persona_id="minh")
    assert result["numbers"]["form_id"] == "alien_registration_renewal"
    assert result["card"] is not None


# --- 규약 검증 ---

def test_registry_only_form_autofill():
    from mcp_servers.docs.tools import TOOL_REGISTRY, ACTIVE_TOOLS
    assert set(TOOL_REGISTRY) == {"form_autofill"}
    assert ACTIVE_TOOLS == ["form_autofill"]


def test_every_tool_has_schema():
    from mcp_servers.docs import schemas
    from mcp_servers.docs.tools import TOOL_REGISTRY
    for name in TOOL_REGISTRY:
        assert name in schemas.TOOL_SCHEMAS, f"{name} 스키마 누락"
        s = schemas.TOOL_SCHEMAS[name]
        assert s["name"] == name
        assert "description" in s
        assert s["input_schema"]["type"] == "object"


def test_four_key_contract():
    result = tools.form_autofill(persona_id="suman", form_id="residence_confirmation")
    assert set(result.keys()) == {"summary", "detail", "numbers", "card"}


def test_fill_method_recorded_as_coords_when_ai_off():
    # conftest가 DOCS_AI_FILL=off로 두므로 실측 좌표 경로가 기록돼야 한다
    result = tools.form_autofill(persona_id="minh", form_id="alien_registration_renewal")
    assert result["numbers"]["fill_method"] == "measured_coords"


# --- AI 채움 계획 검증 (validate_plan은 순수 함수라 결정적으로 테스트) ---

def test_validate_plan_accepts_member_values_and_marks():
    from mcp_servers.docs import ai_fill
    layout = [{"page": 0, "width": 600, "height": 800, "words": [], "boxes": []}]
    values = {"korean_name": "응웬 반 민", "reg_no": "920305-5680512", "gender": "M"}
    plan = [
        {"text": "응웬 반 민", "page": 0, "cell": [200, 190, 350, 215]},   # 회원 값 그대로
        {"text": "920305", "page": 0, "cell": [200, 220, 300, 240]},      # 값의 일부(분할 기재)
        {"text": "X", "page": 0, "cell": [364, 324, 372, 336]},           # 표기 기호
    ]
    out = ai_fill.validate_plan(plan, values, layout)
    assert len(out) == 3
    assert out[0]["cell"] == [200, 190, 350, 215]


def test_validate_plan_rejects_hallucination_and_bad_cells():
    from mcp_servers.docs import ai_fill
    layout = [{"page": 0, "width": 600, "height": 800, "words": [], "boxes": []}]
    values = {"korean_name": "응웬 반 민"}
    plan = [
        {"text": "홍길동", "page": 0, "cell": [200, 190, 350, 215]},      # 환각(회원 값에 없음)
        {"text": "응웬 반 민", "page": 0, "cell": [500, 190, 700, 215]},  # 페이지 밖 x1
        {"text": "응웬 반 민", "page": 3, "cell": [200, 190, 350, 215]},  # 없는 페이지
        {"text": "응웬 반 민", "page": 0, "cell": [350, 190, 200, 215]},  # 뒤집힌 사각형
        {"text": "응웬 반 민", "page": 0, "cell": [200, 190, 204, 194]},  # 너무 작은 칸
        {"text": "응웬 반 민", "page": 0, "x": 200, "y": 200, "size": 9}, # 옛 점 형식(cell 없음)
    ]
    out = ai_fill.validate_plan(plan, values, layout)
    assert out == []


def test_validate_plan_trims_label_out_of_wide_cell():
    from mcp_servers.docs import ai_fill
    # 라벨 '계좌번호'(100~160)와 빈 영역(160~300)을 합쳐 넓게 잡은 칸 →
    # 재단 후 라벨 오른쪽 빈 영역만 남아야 한다
    layout = [{"page": 0, "width": 600, "height": 800, "words": [],
               "boxes": [[100, 100, 160, 112]]}]
    values = {"bank_account": "1013-45-678901"}
    plan = [{"text": "1013-45-678901", "page": 0, "cell": [95, 98, 300, 118]}]
    out = ai_fill.validate_plan(plan, values, layout)
    assert len(out) == 1
    x0 = out[0]["cell"][0]
    assert x0 >= 162          # 라벨 오른쪽으로 재단됨
    # 오른쪽 라벨 회피: 값 칸이 라벨 왼쪽인 경우('___년/Y' 형태)
    plan2 = [{"text": "1013-45-678901", "page": 0, "cell": [40, 98, 158, 118]}]
    layout2 = [{"page": 0, "width": 600, "height": 800, "words": [],
                "boxes": [[130, 100, 158, 112]]}]
    out2 = ai_fill.validate_plan(plan2, values, layout2)
    assert len(out2) == 1
    assert out2[0]["cell"][2] <= 128   # 라벨 왼쪽으로 재단됨


def test_validate_plan_rejects_label_cell():
    from mcp_servers.docs import ai_fill
    # (100,100)-(160,115) 영역에 인쇄된 라벨이 있다고 가정
    layout = [{"page": 0, "width": 600, "height": 800, "words": [],
               "boxes": [[100, 100, 160, 115]]}]
    values = {"korean_name": "응웬 반 민", "gender": "M"}
    plan = [
        # 라벨을 포함한 칸(덮임 비율 높음) → 라벨 칸으로 보고 거부
        {"text": "응웬 반 민", "page": 0, "cell": [98, 98, 162, 117]},
        # 라벨 오른쪽 빈 칸 → 통과
        {"text": "응웬 반 민", "page": 0, "cell": [165, 98, 300, 117]},
        # 표기 기호는 예외 → 통과
        {"text": "X", "page": 0, "cell": [100, 100, 112, 114]},
    ]
    out = ai_fill.validate_plan(plan, values, layout)
    assert len(out) == 2


# --- 칸 자동 맞춤 (fit_into_cell은 순수 함수라 결정적으로 테스트) ---

def test_fit_into_cell_centers_and_caps_size():
    # 넓은 칸(높이 25pt): 높이 70%는 17.5지만 상한 14가 적용된다. 가로세로 중앙 정렬.
    x, y, size = tools.fit_into_cell("응웬 반 민", (200, 190, 400, 215), None)
    assert size == 14
    tw = tools._text_width("응웬 반 민", size, None)
    assert abs(x - (200 + (200 - tw) / 2)) < 0.01   # 가로 중앙
    assert abs(y - (202.5 + size * 0.35)) < 0.01    # 세로 중앙 + baseline 보정


def test_fit_into_cell_shrinks_for_narrow_cell():
    # 좁은 칸(폭 40pt)에 긴 텍스트 → 크기가 축소된다(최소 5pt 바닥).
    # 최소 크기에서도 넘치는 극단 케이스는 왼쪽 여백(x0+pad)에 붙는다.
    text = "전북특별자치도 전주시 덕진구"
    cell = (100, 100, 140, 120)
    x, y, size = tools.fit_into_cell(text, cell, None)
    assert size == 5          # 최소 크기 바닥
    assert x == 102           # x0 + pad(2)


def test_fit_into_cell_short_digits_fit_snugly():
    # 등록번호 한 자리 박스(폭 20, 높이 14): 높이 70%인 9.8pt로 들어가고 중앙 정렬
    x, y, size = tools.fit_into_cell("9", (186.5, 355, 206.5, 369), None)
    assert abs(size - 14 * 0.70) < 0.01
    assert 186.5 < x < 206.5


def test_extract_layout_reads_template_words():
    from mcp_servers.docs import ai_fill
    layout = ai_fill.extract_layout("alien_registration_renewal")
    assert layout is not None
    assert layout[0]["width"] > 0
    assert len(layout[0]["words"]) > 50   # 신청서라 단어가 많다
    assert ai_fill.extract_layout("nonexistent_form") is None
