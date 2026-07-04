"""서류행정 부문 tool. 순수 함수다. MCP나 Claude를 모른다.
입력은 키워드 인자, 출력은 {summary, detail, numbers, card} dict.

원칙 (asset 부문과 동일 규약):
- 스캔/OCR을 쓰지 않는다. 회원 프로필 정본(shared/personas.py)에서 채울 수 있는 칸만 채운다.
- 값은 get_profile(신원/연락/금융/소속) + derive_profile_fields(생년월일/재학/연소득/지급국/신청일)로만.
- 페르소나에 없는 값(상대방 정보 등)은 공란으로 둔다. 지어내지 않는다.
- form_autofill 1종. persona_id로 분기하지 않고 페르소나 필드로만 값을 만든다.
"""

import os

import fitz  # pymupdf

from shared.personas import get_persona, get_profile, derive_profile_fields
from mcp_servers.docs import data

# 템플릿/출력 폴더 경로.
# 출력은 제출 폴더 밖 고정 위치(~/.liferoad/output)에 둔다. 시연을 아무리 돌려도
# 제출 폴더에는 산출물이 안 생기고, 사용자 홈 기준이라 팀원 컴퓨터에서도 그대로 동작한다.
_DOCS_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(_DOCS_DIR, "templates")
OUTPUT_DIR = os.path.expanduser("~/.liferoad/output")

# 한글 폰트 경로 후보. 앞에서부터 실제 존재하는 첫 파일을 쓴다.
# 맥 우선(시연 환경), 없으면 리눅스/윈도우 순으로 폴백한다. 전부 없으면 fontfile 미지정.
_FONT_CANDIDATES = [
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",          # macOS
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",  # macOS 보조
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",     # Linux(배포)
    "C:/Windows/Fonts/malgun.ttf",                         # Windows
]


def _korean_font_path() -> str | None:
    """존재하는 첫 한글 폰트 경로를 반환한다. 없으면 None."""
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


# ── PDF 좌표 매핑 ───────────────────────────────────────────
# 각 form_id별로 (삽입할 x, y 좌표 / 값 key / 폰트 크기) 목록.
# y 좌표는 PyMuPDF 기준 (페이지 상단=0, 아래로 증가). 실측값이며 주석에 근거를 남긴다.
FORM_FILL_COORDS = {
    "alien_registration_renewal": {
        # ── 일반 텍스트 삽입 필드 ──────────────────────────────
        "simple": [
            {"key": "surname",         "x": 130, "y": 315, "size": 9},
            {"key": "given_names",     "x": 270, "y": 315, "size": 9},
            {"key": "nationality",     "x": 490, "y": 342, "size": 8},
            {"key": "passport_no",     "x": 145, "y": 381, "size": 9},
            {"key": "passport_issue",  "x": 325, "y": 381, "size": 9},
            {"key": "passport_expiry", "x": 490, "y": 381, "size": 9},
            {"key": "address_kr",      "x": 155, "y": 403, "size": 9},
            {"key": "birth_year",      "x": 148, "y": 340, "size": 7},
            {"key": "birth_month",     "x": 230, "y": 340, "size": 8},
            {"key": "birth_day",       "x": 265, "y": 340, "size": 8},
            {"key": "apply_date",      "x": 212, "y": 587, "size": 9},
            {"key": "phone",           "x": 425, "y": 420, "size": 8},
            {"key": "address_home",    "x": 180, "y": 434, "size": 7},
            {"key": "school_name",     "x": 365, "y": 452, "size": 7},
            {"key": "workplace_name",  "x": 218, "y": 497, "size": 6},
            {"key": "annual_income_manwon", "x": 212, "y": 539, "size": 7},
            {"key": "occupation",      "x": 482, "y": 539, "size": 8},
            {"key": "email",           "x": 368, "y": 552, "size": 7},
        ],
        # 성별 체크박스: 브래킷 내부 x=367. M baseline y=330.6, F baseline y=341.4
        "checkboxes": [
            {
                "key":    "gender",
                "values": {"M": {"x": 367, "y": 330}, "F": {"x": 367, "y": 341}},
                "mark": "X",
                "size": 5,
            },
        ],
        # 외국인등록번호: 박스별 한 자리씩 삽입. 실측 세로선 좌표.
        "digits": {
            "key": "reg_no",
            "y": 362,
            "size": 8,
            "front_boxes": [186.5, 206.5, 227.3, 247.3, 267.3, 287.4, 307.4],
            "back_boxes":  [307.4, 325.0, 342.7, 360.3, 377.9, 395.5, 413.2, 431.0, 448.8],
        },
    },
    "pension_return_claim": {
        # 글자 크기: 제출 서류 가독성 위해 주요 칸 10pt. 좁은 칸만 축소.
        "simple": [
            {"key": "claim_year",   "x": 340, "y": 357, "size": 10},
            {"key": "claim_month",  "x": 389, "y": 357, "size": 10},
            {"key": "claim_day",    "x": 428, "y": 357, "size": 10},
            {"key": "korean_name",  "x": 395, "y": 371, "size": 10},
        ],
        # 수급권자 블록(page 0)은 칸 기반 정렬. 셀 사각형은 표 선 실측값이다.
        # 값칸 우측열 x 222.1~538.8. 세로는 항상 칸 중앙, 가로는 align으로 정한다.
        "cells": [
            # 성명: 넓은 칸이라 왼쪽 정렬(이름은 좌측 기재가 자연스럽다).
            {"key": "korean_name",  "cell": [222.1, 190.5, 538.8, 210.8], "align": "left",   "size": 10, "gap": 14},
            # 외국인등록번호: 인쇄된 '-'(x 377.3~383.6, 중심 380.5) 기준 좌우 대칭.
            # 앞자리는 오른끝을, 뒷자리는 왼끝을 '-'에 같은 간격으로 붙인다.
            {"key": "reg_no_front", "cell": [222.1, 210.8, 377.3, 232.2], "align": "right",  "size": 10, "gap": 6},
            {"key": "reg_no_back",  "cell": [383.6, 210.8, 538.8, 232.2], "align": "left",   "size": 10, "gap": 6},
            # 전화: 괄호쌍마다 가운데정렬. 세로 기준선은 인쇄된 괄호 높이(y 232.2~248)에 맞춘다.
            # 첫 괄호=국가코드(+82), 2~4번째=번호 분절. 안내문 "국가/지역코드 포함 기재" 준수.
            {"key": "phone_country", "cell": [257.1, 232.2, 292.0, 248.0], "align": "center", "size": 9},
            {"key": "phone_seg1",   "cell": [315.8, 232.2, 361.3, 248.0], "align": "center", "size": 9},
            {"key": "phone_seg2",   "cell": [385.1, 232.2, 434.7, 248.0], "align": "center", "size": 9},
            {"key": "phone_seg3",   "cell": [458.4, 232.2, 534.0, 248.0], "align": "center", "size": 9},
            # 주소: 넓은 칸 왼쪽 정렬.
            {"key": "address_kr",   "cell": [222.1, 252.8, 538.8, 273.5], "align": "left",   "size": 8, "gap": 8},
            # 이메일: 전체(아이디@도메인)를 한 덩어리로 주소와 같은 왼쪽 시작점(gap 8)에 정렬한다.
            # 서식에 인쇄된 '@'(x 386.7~394.7)는 흰색으로 덮어 이메일 값 안의 '@'만 보이게 한다.
            {"key": "email", "cell": [222.1, 273.5, 538.8, 294.5], "align": "left", "size": 9, "gap": 8,
             "cover": [[385.0, 277.5, 396.5, 289.5]]},
            # ── 2페이지 국내계좌(KOREA BANK ACCOUNT) 행. 행 y 95.9~127.5, 값칸 가운데정렬.
            {"key": "bank_name",    "cell": [124.0, 95.9, 200.7, 127.5], "align": "center", "size": 9, "page": 1},
            {"key": "bank_account", "cell": [293.3, 95.9, 367.3, 127.5], "align": "center", "size": 9, "page": 1},
            # 예금주성명 칸은 폭 38pt로 매우 좁다. 6pt로 줄여 칸 안에 담는다.
            {"key": "korean_name",  "cell": [501.3, 95.9, 539.3, 127.5], "align": "center", "size": 6, "page": 1},
            # 2페이지 해외송금계좌 지급상대국(값칸 [200.7~539.3]).
            {"key": "pay_country",  "cell": [200.7, 213.9, 539.3, 244.8], "align": "center", "size": 9, "page": 1},
        ],
        "checkboxes": [],
        "digits": None,
    },
    "departure_postpone": {
        "simple": [
            {"key": "korean_name",    "x": 270, "y": 113, "size": 10},
            {"key": "birth_date",     "x": 250, "y": 172, "size": 9},
            {"key": "nationality",    "x": 445, "y": 172, "size": 9},
            {"key": "address_home",   "x": 150, "y": 208, "size": 7},
            {"key": "address_kr",     "x": 285, "y": 236, "size": 8},
            {"key": "phone",          "x": 425, "y": 252, "size": 8},
            {"key": "departure_date", "x": 345, "y": 270, "size": 9},
            {"key": "apply_year",     "x": 405, "y": 590, "size": 9},
            {"key": "apply_month",    "x": 446, "y": 590, "size": 9},
            {"key": "apply_day",      "x": 486, "y": 590, "size": 9},
        ],
        "checkboxes": [
            {"key": "gender",
             "values": {"M": {"x": 469, "y": 140}, "F": {"x": 469, "y": 157}},
             "mark": "X", "size": 6},
        ],
        "digits": None,
    },
    "residence_confirmation": {
        "simple": [
            {"key": "nationality", "x": 182, "y": 134, "size": 9},
            {"key": "reg_no",      "x": 388, "y": 135, "size": 9},
            {"key": "korean_name", "x": 182, "y": 172, "size": 9},
            {"key": "phone",       "x": 430, "y": 174, "size": 8},
            {"key": "address_kr",  "x": 182, "y": 200, "size": 8},
        ],
        "checkboxes": [],
        "digits": None,
    },
    "parttime_work_confirmation": {
        "simple": [
            {"key": "korean_name", "x": 180, "y": 158, "size": 9},
            {"key": "reg_no",      "x": 390, "y": 152, "size": 9},
            {"key": "phone",       "x": 175, "y": 215, "size": 9},
        ],
        "checkboxes": [],
        "digits": None,
    },
}


# ---------------------------------------------------------------------------
# 등록번호 → 생년월일 유도 (순수 함수)
# ---------------------------------------------------------------------------

def _parse_birth_year(reg_no: str) -> str:
    d = reg_no.replace("-", "")
    if len(d) < 2:
        return ""
    yy = int(d[:2])
    return str(1900 + yy) if yy >= 24 else str(2000 + yy)


def _parse_birth_month(reg_no: str) -> str:
    d = reg_no.replace("-", "")
    return d[2:4] if len(d) >= 4 else ""


def _parse_birth_day(reg_no: str) -> str:
    d = reg_no.replace("-", "")
    return d[4:6] if len(d) >= 6 else ""


def _birth_date(reg_no: str) -> str:
    """등록번호에서 'YYYY.MM.DD' 생년월일 문자열을 만든다. 없으면 빈 문자열."""
    y = _parse_birth_year(reg_no)
    if not y:
        return ""
    return f"{y}.{_parse_birth_month(reg_no)}.{_parse_birth_day(reg_no)}"


def _build_form_values(p: dict) -> dict:
    """PDF 좌표 매핑용 값 dict를 만든다. 순수 함수.

    회원 프로필 정본(get_profile) + 자동 유도값(derive_profile_fields)만 쓴다.
    페르소나에 없는 값은 공란으로 둔다(지어내지 않는다)."""
    doc = get_profile(p)              # 정본 프로필 (PROFILE_CONTRACT 규약 키)
    d = derive_profile_fields(p)      # 자동 유도값 (생년월일/재학/연소득/지급국/신청일)

    def pick(*vals):
        """앞에서부터 비어있지 않은 첫 값을 고른다."""
        for v in vals:
            if v:
                return str(v)
        return ""

    # 신청일: 정본 데모 기준일(YYYY-MM-DD). 시연 재현성 위해 date.today() 대신 사용.
    ay, am, ad = (d["apply_date"].split("-") + ["", "", ""])[:3]

    # 영문 이름 분리 (성/이름)
    name_en = pick(doc.get("name_en"), p.get("name_en"))
    name_parts = name_en.split()
    surname = name_parts[0] if name_parts else p["name"]
    given = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

    reg_no = pick(doc.get("reg_no"))
    if "-" in reg_no:
        parts = reg_no.split("-")
        reg_no_front = parts[0]
        reg_no_back = parts[1] if len(parts) > 1 else ""
    else:
        reg_no_front = reg_no[:6] if len(reg_no) >= 6 else reg_no
        reg_no_back = reg_no[6:] if len(reg_no) > 6 else ""

    # 전화번호/이메일 분절 (반환일시금 1페이지: 전화 괄호칸, 이메일 @ 분리용)
    phone_val = pick(doc.get("phone"))
    phone_parts = phone_val.split("-")
    email_val = pick(doc.get("email"))
    email_parts = email_val.split("@")

    return {
        "korean_name":     pick(doc.get("korean_name"), p.get("name")),
        "surname":         surname,
        "given_names":     given,
        "nationality":     pick(doc.get("nationality"), p.get("country")),
        "reg_no":          reg_no,
        "reg_no_front":    reg_no_front,
        "reg_no_back":     reg_no_back,
        "visa_type":       pick(doc.get("visa_type"), p.get("visa")),
        "gender":          pick(doc.get("gender")),
        "passport_no":     pick(doc.get("passport_no")),
        "passport_issue":  pick(doc.get("passport_issue")),
        "passport_expiry": pick(doc.get("passport_expiry")),
        "birth_year":      _parse_birth_year(reg_no),
        "birth_month":     _parse_birth_month(reg_no),
        "birth_day":       _parse_birth_day(reg_no),
        "birth_date":      _birth_date(reg_no),
        "address_kr":      pick(doc.get("address_kr")),
        "phone":           phone_val,
        # 국가코드: 한국 체류 중 신청이므로 전화가 있으면 +82 고정 기재
        "phone_country":   "+82" if phone_val else "",
        "phone_seg1":      phone_parts[0] if len(phone_parts) > 0 else "",
        "phone_seg2":      phone_parts[1] if len(phone_parts) > 1 else "",
        "phone_seg3":      phone_parts[2] if len(phone_parts) > 2 else "",
        "departure_date":  (p.get("exit_plan") or "").replace("-", "."),
        "apply_date":      d["apply_date"].replace("-", "."),
        "apply_year":      ay,
        "apply_month":     am,
        "apply_day":       ad,
        "claim_year":      ay,
        "claim_month":     am,
        "claim_day":       ad,
        # ── 회원 프로필 확장 컬럼 (PROFILE_CONTRACT.md) ──
        "email":           email_val,
        "email_local":     email_parts[0] if len(email_parts) > 0 else "",
        "email_domain":    email_parts[1] if len(email_parts) > 1 else "",
        "address_home":    pick(doc.get("address_home")),
        "bank_name":       pick(doc.get("bank_name")),
        "bank_account":    pick(doc.get("bank_account")),
        "occupation":      pick(doc.get("occupation")),
        "workplace_name":  pick(doc.get("workplace_name")),
        "school_name":     pick(doc.get("school_name")),
        "school_type":     pick(doc.get("school_type")),
        # ── 자동 유도 (정본 derive_profile_fields) ──
        "enrolled":        d["enrolled"],
        "annual_income":   f"{d['annual_income']:,}원" if d["annual_income"] else "",
        "annual_income_manwon": f"{d['annual_income'] // 10000:,}" if d["annual_income"] else "",
        "pay_country":     pick(d.get("pay_country"), p.get("country")),
    }


def _insert_text(page, x, y, text, size, font_path, color=(0.0, 0.0, 0.0)):
    """페이지에 텍스트를 삽입하는 공통 헬퍼. 글자색은 검정(인쇄 제출용).
    fontname을 반드시 지정해야 한글 글리프가 올바르게 렌더링된다."""
    kwargs = {"fontsize": size, "color": color}
    if font_path and os.path.exists(font_path):
        kwargs["fontfile"] = font_path
        kwargs["fontname"] = "kfont"   # 폰트 이름 명시: 한글 렌더링 필수
    page.insert_text(fitz.Point(x, y), text, **kwargs)


def _text_width(text: str, size: float, font_path: str | None) -> float:
    """글자폭을 잰다. 폰트 파일이 있으면 실측, 없으면 한글 1.0 / 그 외 0.55 근사."""
    if font_path:
        try:
            return fitz.Font(fontfile=font_path).text_length(text, fontsize=size)
        except Exception:
            pass
    w = 0.0
    for ch in text:
        w += size * (1.0 if ord(ch) > 0x2E80 else 0.55)
    return w


def fit_into_cell(text: str, cell: tuple, font_path: str | None,
                  pad: float = 2.0, max_size: float = 14.0, min_size: float = 5.0) -> tuple:
    """칸(x0,y0,x1,y1)에 '조금 꽉 차게' 들어가는 글씨 크기와 중앙 정렬 삽입점을 계산한다.

    크기: 칸 높이의 70%에서 시작하고, 그 크기로 폭이 넘치면 폭에 맞게 줄인다.
    위치: 가로세로 중앙 정렬(baseline은 세로 중앙 + 글자 높이 보정).
    반환: (x, y_baseline, size). 순수 함수라 결정적이다."""
    x0, y0, x1, y1 = cell
    w = max(1.0, (x1 - x0) - pad * 2)
    h = max(1.0, (y1 - y0))
    size = min(max_size, h * 0.70)
    tw = _text_width(text, size, font_path)
    if tw > w:
        size = max(min_size, size * (w / tw))
        tw = _text_width(text, size, font_path)
    # 중앙 정렬. 최소 크기에서도 폭이 넘치는 극단 케이스는 왼쪽 여백에 붙인다.
    x = max(x0 + pad, x0 + ((x1 - x0) - tw) / 2)
    y = (y0 + y1) / 2 + size * 0.35
    return (x, y, size)


def _place_in_cell(text: str, cell: tuple, font_path: str | None,
                   align: str = "center", size_max: float = 14.0,
                   min_size: float = 5.0, pad: float = 2.0, gap: float = 2.0) -> tuple:
    """칸(x0,y0,x1,y1)에 정렬 방식대로 넣는 글씨 크기와 삽입점을 계산한다.

    fit_into_cell은 항상 가로 중앙이지만, 이 함수는 정렬을 고른다:
    - center: 가로 중앙 (일반 값).
    - right : 오른끝을 칸 오른쪽 경계에서 gap만큼 안으로. 인쇄된 구분자('-','@')
              왼쪽 값이 구분자에 붙게 한다(대칭 기재).
    - left  : 왼끝을 칸 왼쪽 경계에서 gap만큼 안으로. 구분자 오른쪽 값용.
    세로는 항상 칸 중앙(baseline = 세로중앙 + 글자높이 보정). 순수 함수라 결정적이다."""
    x0, y0, x1, y1 = cell
    w = max(1.0, (x1 - x0) - pad * 2)
    h = max(1.0, (y1 - y0))
    size = min(size_max, h * 0.70)
    tw = _text_width(text, size, font_path)
    if tw > w:
        size = max(min_size, size * (w / tw))
        tw = _text_width(text, size, font_path)
    if align == "right":
        x = max(x0 + pad, x1 - gap - tw)
    elif align == "left":
        x = x0 + gap
    else:  # center
        x = max(x0 + pad, x0 + ((x1 - x0) - tw) / 2)
    y = (y0 + y1) / 2 + size * 0.35
    return (x, y, size)


def _norm_text(s: str) -> str:
    """이중 기재 검사용 정규화. 공백과 쉼표와 점과 하이픈을 제거한다."""
    return str(s).replace(" ", "").replace(",", "").replace(".", "").replace("-", "")


def _fill_pdf_by_plan(form_id: str, plan: list[dict], out_name: str, form_values: dict) -> str:
    """실측 좌표를 먼저 채우고, AI(Sonnet) 계획은 실측이 안 다룬 값만 보태서 저장한다.

    우선순위: 실측 좌표(FORM_FILL_COORDS) > AI 칸 계획.
    - 실측은 검증된 위치라 항상 정확하다. 5종 기본 서식의 품질을 보장한다.
    - AI 계획은 실측에 좌표가 없는 값(또는 실측 자체가 없는 새 서식)을 채운다.
      AI가 고른 칸에는 fit_into_cell이 크기와 중앙 정렬을 결정적으로 계산한다.
    - 이중 기재 차단: 이미 넣은 값 텍스트(정규화)와 겹치는 AI 항목은 건너뛴다.
      (AI의 key 표기는 신뢰하지 않는다. 텍스트 대조가 확실하다.)"""
    template_path = os.path.join(TEMPLATES_DIR, f"{form_id}.pdf")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, out_name)

    font_path = _korean_font_path()
    doc = fitz.open(template_path)
    coord_map = FORM_FILL_COORDS.get(form_id, {})
    inserted: list[str] = []   # 넣은 값 텍스트(정규화). AI 이중 기재 차단용.
    marks_done = False         # 실측 체크박스 표기 여부. AI의 X/O 중복 차단용.

    def _page(cfg):
        i = cfg.get("page", 0)
        return doc[i] if 0 <= i < doc.page_count else doc[0]

    # ── 1. 실측 좌표 먼저 (검증된 위치, 항상 정확) ─────────────
    for field in coord_map.get("simple", []):
        value = str(form_values.get(field["key"], "")).strip()
        if not value:
            continue
        _insert_text(_page(field), field["x"], field["y"], value, field["size"], font_path)
        inserted.append(_norm_text(value))

    # 칸 기반 정렬 필드(중앙정렬/구분자 대칭). 세로도 칸 중앙으로 맞춘다.
    for field in coord_map.get("cells", []):
        value = str(form_values.get(field["key"], "")).strip()
        if not value:
            continue
        # cover: 값을 쓰기 전에 인쇄된 기호(예: '@')를 흰색으로 덮는다.
        for r in field.get("cover", []):
            _page(field).draw_rect(fitz.Rect(*r), color=(1, 1, 1), fill=(1, 1, 1), width=0)
        x, y, size = _place_in_cell(
            value, tuple(field["cell"]), font_path,
            align=field.get("align", "center"),
            size_max=field.get("size", 10),
            gap=field.get("gap", 2.0),
        )
        _insert_text(_page(field), x, y, value, size, font_path)
        inserted.append(_norm_text(value))

    for cb in coord_map.get("checkboxes", []):
        val = str(form_values.get(cb["key"], "")).strip().upper()
        if val in cb.get("values", {}):
            pos = cb["values"][val]
            _insert_text(_page(cb), pos["x"], pos["y"], cb["mark"], cb["size"], font_path)
            marks_done = True

    digits_cfg = coord_map.get("digits")
    if digits_cfg:
        page = _page(digits_cfg)
        reg_no = str(form_values.get(digits_cfg["key"], ""))
        if "-" in reg_no:
            front_str, back_str = reg_no.split("-", 1)
        else:
            front_str, back_str = reg_no[:6], reg_no[6:]
        y, sz = digits_cfg["y"], digits_cfg["size"]
        for i, ch in enumerate(front_str[:len(digits_cfg["front_boxes"]) - 1]):
            e = digits_cfg["front_boxes"]
            _insert_text(page, (e[i] + e[i + 1]) / 2 - sz * 0.15, y, ch, sz, font_path)
        for i, ch in enumerate(back_str[:len(digits_cfg["back_boxes"]) - 1]):
            e = digits_cfg["back_boxes"]
            _insert_text(page, (e[i] + e[i + 1]) / 2 - sz * 0.15, y, ch, sz, font_path)
        if reg_no:
            inserted.append(_norm_text(reg_no))
            inserted.append(_norm_text(front_str))
            inserted.append(_norm_text(back_str))

    # ── 2. AI 계획 보충 (실측이 안 다룬 값만, 칸 자동 맞춤) ────
    for item in plan:
        text = item["text"]
        if text in ("X", "O"):
            if marks_done:
                continue  # 실측 체크박스가 이미 표기함
        else:
            nt = _norm_text(text)
            # 이미 넣은 값과 어느 방향으로든 포함 관계면 같은 정보의 재기재로 본다
            if any(nt in done or done in nt for done in inserted if done):
                continue
        idx = item["page"]
        page = doc[idx] if 0 <= idx < doc.page_count else doc[0]
        x, y, size = fit_into_cell(text, tuple(item["cell"]), font_path)
        _insert_text(page, x, y, text, size, font_path)
        if text not in ("X", "O"):
            inserted.append(_norm_text(text))

    doc.save(output_path)
    doc.close()
    return output_path


def _fill_pdf_template(form_id: str, form_values: dict, out_name: str) -> str:
    """PDF 템플릿에 값을 좌표 기반으로 삽입하고 output 폴더에 저장한다.
    out_name은 요청별 고유 파일명(덮어쓰기 경합 방지). 반환: 저장된 파일 경로."""
    template_path = os.path.join(TEMPLATES_DIR, f"{form_id}.pdf")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, out_name)

    if not os.path.exists(template_path):
        raise FileNotFoundError(f"템플릿 파일 없음: {template_path}")

    font_path = _korean_font_path()
    coord_map = FORM_FILL_COORDS.get(form_id, {})

    doc = fitz.open(template_path)

    def _page(cfg):
        """필드에 지정된 page 인덱스의 페이지를 반환한다 (기본 0페이지).
        범위를 벗어나면 0페이지로 안전 폴백."""
        idx = cfg.get("page", 0)
        return doc[idx] if 0 <= idx < doc.page_count else doc[0]

    # ── 1. 일반 텍스트 필드 삽입 ──────────────────────────────
    for field in coord_map.get("simple", []):
        value = str(form_values.get(field["key"], "")).strip()
        if not value:
            continue
        _insert_text(_page(field), field["x"], field["y"], value, field["size"], font_path)

    # ── 1b. 칸 기반 정렬 필드 (중앙정렬/구분자 대칭 + 세로 중앙) ──
    for field in coord_map.get("cells", []):
        value = str(form_values.get(field["key"], "")).strip()
        if not value:
            continue
        # cover: 값을 쓰기 전에 인쇄된 기호(예: '@')를 흰색으로 덮는다.
        for r in field.get("cover", []):
            _page(field).draw_rect(fitz.Rect(*r), color=(1, 1, 1), fill=(1, 1, 1), width=0)
        x, y, size = _place_in_cell(
            value, tuple(field["cell"]), font_path,
            align=field.get("align", "center"),
            size_max=field.get("size", 10),
            gap=field.get("gap", 2.0),
        )
        _insert_text(_page(field), x, y, value, size, font_path)

    # ── 2. 체크박스 (성별 등) ─────────────────────────────────
    for cb in coord_map.get("checkboxes", []):
        val = str(form_values.get(cb["key"], "")).strip().upper()
        if val in cb.get("values", {}):
            pos = cb["values"][val]
            _insert_text(_page(cb), pos["x"], pos["y"], cb["mark"], cb["size"], font_path)

    # ── 3. 외국인등록번호: 박스별 한 자리씩 삽입 ──────────────
    digits_cfg = coord_map.get("digits")
    if digits_cfg:
        page = _page(digits_cfg)
        reg_no = str(form_values.get(digits_cfg["key"], ""))
        if "-" in reg_no:
            front_str, back_str = reg_no.split("-", 1)
        else:
            front_str = reg_no[:6]
            back_str = reg_no[6:]

        y = digits_cfg["y"]
        sz = digits_cfg["size"]
        front_edges = digits_cfg["front_boxes"]
        for i, ch in enumerate(front_str[:len(front_edges) - 1]):
            x_center = (front_edges[i] + front_edges[i + 1]) / 2 - sz * 0.15
            _insert_text(page, x_center, y, ch, sz, font_path)

        back_edges = digits_cfg["back_boxes"]
        for i, ch in enumerate(back_str[:len(back_edges) - 1]):
            x_center = (back_edges[i] + back_edges[i + 1]) / 2 - sz * 0.15
            _insert_text(page, x_center, y, ch, sz, font_path)

    doc.save(output_path)
    doc.close()
    return output_path


def form_autofill(persona_id: str, form_id: str = "alien_registration_renewal") -> dict:
    """정부 PDF 신청서를 회원 프로필 정본으로 자동작성한다.
    스캔 없이 페르소나 정보에서 채울 수 있는 칸만 채우고 나머지는 직접 입력으로 남긴다.
    커버: 작성 가능 신청서 5종(템플릿 PDF 보유). 템플릿 없는 양식은 값만 채우고 PDF는 미생성."""
    p = get_persona(persona_id)
    form = data.GOVERNMENT_FORMS.get(form_id)
    mapping = data.FORM_FIELD_MAPPING.get(form_id)

    if form is None or mapping is None:
        return {
            "summary": f"지원하지 않는 신청서 양식입니다: {form_id}",
            "detail": f"지원 양식: {list(data.GOVERNMENT_FORMS.keys())}",
            "numbers": {
                "form_id": form_id,
                "total_fields": 0,
                "autofill_fields": 0,
                "manual_fields": 0,
                "autofill_ratio": 0.0,
                "filled_data": {},
                "manual_fields_list": [],
                "output_pdf_path": None,
            },
            "card": None,
        }

    # ── 필드 채우기 (페르소나 정본에서만) ─────────────────────
    filled = {}
    for field, value in mapping["autofill"].items():
        filled[field] = value(p) if callable(value) else value

    total = form["total_fields"]
    auto = len(filled)
    manual = mapping["manual"]
    ratio = auto / total

    # ── PDF 파일 생성 (템플릿이 있는 경우) ──────────────────
    # 1차: AI 서식 채움. Claude(Sonnet)가 템플릿 PDF의 단어 배치를 읽고
    #      어디에 무엇을 쓸지 스스로 정한다(ai_fill.plan_fill). 검증 통과 계획만 쓴다.
    # 2차: AI 계획이 없거나 검증 미달이면 실측 좌표(FORM_FILL_COORDS)로 채운다.
    #      시연이 끊기지 않게 하는 차선책이다.
    output_pdf_path = None
    fill_method = None
    template_path = os.path.join(TEMPLATES_DIR, f"{form_id}.pdf")
    if os.path.exists(template_path):
        form_values = _build_form_values(p)
        out_name = f"{persona_id}_{form_id}_filled.pdf"   # 요청별 고유명(경합 방지)
        from mcp_servers.docs import ai_fill
        if ai_fill.ai_fill_enabled():
            plan = ai_fill.plan_fill(form_id, form["name_ko"], form_values)
            if plan:
                output_pdf_path = _fill_pdf_by_plan(form_id, plan, out_name, form_values)
                fill_method = "ai_sonnet"
        if output_pdf_path is None:
            output_pdf_path = _fill_pdf_template(form_id, form_values, out_name)
            fill_method = "measured_coords"

    numbers = {
        "form_id": form_id,
        "form_name_ko": form["name_ko"],
        "total_fields": total,
        "autofill_fields": auto,
        "manual_fields": len(manual),
        "autofill_ratio": round(ratio, 2),
        "filled_data": filled,
        "manual_fields_list": manual,
        "output_pdf_path": output_pdf_path,
        "fill_method": fill_method,   # ai_sonnet(AI가 서식을 읽고 작성) | measured_coords(실측 좌표)
    }

    pdf_msg = " PDF 저장 완료." if output_pdf_path else ""

    return {
        "summary": (
            f"{p['name']}님의 {form['name_ko']}를 {auto}/{total}개 항목 자동작성 완료. "
            f"{len(manual)}개 항목만 직접 입력하면 됩니다.{pdf_msg}"
        ),
        "detail": (
            f"{form['name_ko']} 총 {total}개 항목 중 {auto}개({ratio * 100:.0f}%)를 회원 정보로 자동 완성했습니다. "
            f"직접 입력 항목: {', '.join(manual)}. "
            + ("작성된 PDF를 내려받을 수 있습니다." if output_pdf_path else "템플릿 파일이 없어 PDF는 생성하지 못했습니다.")
        ),
        "numbers": numbers,
        "card": {
            "icon": "",
            "head": f"{form['name_ko']} {auto}/{total}개 자동완성",
            "body": (
                f"나머지 {len(manual)}개 항목({', '.join(manual)})만 직접 입력하면 제출 준비 완료."
                + (" PDF 저장 완료." if output_pdf_path else "")
            ),
            "metric": f"자동완성 {ratio * 100:.0f}%",
        },
    }


# tool 레지스트리. server.py와 backend가 이 목록으로 tool을 등록한다.
TOOL_REGISTRY = {
    "form_autofill": form_autofill,
}

# 능동 모드에서 먼저 호출하는 트리거 tool
ACTIVE_TOOLS = ["form_autofill"]
