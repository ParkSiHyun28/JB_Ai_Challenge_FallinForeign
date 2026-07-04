"""AI 서식 채움. Claude(Sonnet)가 템플릿 PDF를 읽고 채울 위치를 스스로 정한다.

동작 3단계:
1. extract_layout: 템플릿 PDF에서 단어와 좌표를 추출한다 (Claude가 서식을 읽는 재료).
2. plan_fill: Sonnet에게 서식 레이아웃과 회원 값(한국어 라벨 병기)을 주고
   "어디에 무엇을 쓸지" 계획(JSON)을 받는다. 이 단계가 AI의 서류 작성 판단이다.
3. validate_plan: 계획을 코드로 검증한다. 좌표가 페이지 안인지, 삽입 텍스트가
   회원 값에서 온 것인지(환각 차단), 삽입점이 인쇄된 글자 위가 아닌지(라벨 겹침
   차단) 확인해 안전한 항목만 남긴다.

검증을 통과한 계획이 부족하면 호출부(tools.form_autofill)가 실측 좌표
(FORM_FILL_COORDS)로 채우는 차선책으로 넘어간다. 시연이 끊기지 않게 하는 안전망이다.

모델은 CLAUDE_MODEL_DOCS(기본 claude-sonnet-4-6)를 쓴다. 서류는 정확성이 우선이다.
환경변수 DOCS_AI_FILL=off면 이 모듈을 건너뛴다(테스트가 결정적으로 돌게).
"""

import os
import json

import fitz  # pymupdf

from shared.personas import PROFILE_FIELD_LABELS

_DOCS_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(_DOCS_DIR, "templates")

# 계획 항목 수 허용 범위. 너무 적으면 실패로 보고 차선책으로 넘어간다.
_MIN_ITEMS = 3
_MAX_ITEMS = 80

# 채움 값 키 → 한국어 라벨. AI가 서식 라벨과 값을 정확히 대응시키게 하는 안내판이다.
# 프로필 규약 키는 정본(PROFILE_FIELD_LABELS)을 쓰고 유도 키만 여기에 추가한다.
_EXTRA_LABELS = {
    "surname": "영문 성(Surname)",
    "given_names": "영문 이름(Given names)",
    "reg_no_front": "외국인등록번호 앞 6자리",
    "reg_no_back": "외국인등록번호 뒤 7자리",
    "birth_date": "생년월일",
    "birth_year": "생년월일 연도",
    "birth_month": "생년월일 월",
    "birth_day": "생년월일 일",
    "phone_country": "전화 국가코드(+82)",
    "phone_seg1": "휴대전화 첫 마디",
    "phone_seg2": "휴대전화 가운데 마디",
    "phone_seg3": "휴대전화 끝 마디",
    "departure_date": "출국 예정일",
    "apply_date": "신청일",
    "apply_year": "신청일 연도",
    "apply_month": "신청일 월",
    "apply_day": "신청일 일",
    "claim_year": "청구일 연도",
    "claim_month": "청구일 월",
    "claim_day": "청구일 일",
    "email_local": "이메일 @ 앞부분",
    "email_domain": "이메일 @ 뒷부분",
    "enrolled": "재학 여부",
    "annual_income": "연 소득금액",
    "annual_income_manwon": "연 소득금액(만원 단위)",
    "pay_country": "지급 상대국",
}


def _key_label(key: str) -> str:
    """값 키의 한국어 라벨. 정본 프로필 라벨을 먼저 보고 유도 키 라벨로 보충한다."""
    return PROFILE_FIELD_LABELS.get(key) or _EXTRA_LABELS.get(key) or key


def ai_fill_enabled() -> bool:
    """AI 서식 채움 사용 여부. 키가 없거나 DOCS_AI_FILL=off면 False."""
    if os.environ.get("DOCS_AI_FILL", "on").lower() == "off":
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def extract_layout(form_id: str) -> list[dict] | None:
    """템플릿 PDF에서 페이지별 단어 배치를 추출한다.

    반환: [{page, width, height,
            words: [[텍스트, x, y(baseline)], ...],   # AI 프롬프트용(압축)
            boxes: [[x0, y0, x1, y1], ...]}, ...]     # 겹침 검증용(전체 상자)
    템플릿이 없으면 None."""
    path = os.path.join(TEMPLATES_DIR, f"{form_id}.pdf")
    if not os.path.exists(path):
        return None
    doc = fitz.open(path)
    pages = []
    for i, page in enumerate(doc):
        words = []
        boxes = []
        for w in page.get_text("words"):
            x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], w[4]
            text = text.strip()
            if not text:
                continue
            words.append([text, round(x0), round(y1)])  # y1을 baseline 근사로 쓴다
            boxes.append([x0, y0, x1, y1])
        # 표의 선(셀 경계) 추출. AI가 라벨 셀과 입력 셀을 구분하는 핵심 재료다.
        # 세로선: [x, y시작, y끝], 가로선: [y, x시작, x끝]. 5pt 미만 토막선은 노이즈로 버린다.
        vlines = []
        hlines = []
        for dr in page.get_drawings():
            for item in dr["items"]:
                if item[0] != "l":
                    continue
                a, b = item[1], item[2]
                if abs(a.x - b.x) < 0.5 and abs(a.y - b.y) >= 5:
                    ys, ye = sorted([a.y, b.y])
                    vlines.append([round(a.x), round(ys), round(ye)])
                elif abs(a.y - b.y) < 0.5 and abs(a.x - b.x) >= 5:
                    xs, xe = sorted([a.x, b.x])
                    hlines.append([round(a.y), round(xs), round(xe)])
        pages.append({
            "page": i,
            "width": round(page.rect.width),
            "height": round(page.rect.height),
            "words": words,
            "boxes": boxes,
            "vlines": vlines[:200],
            "hlines": hlines[:200],
        })
    doc.close()
    return pages


def _norm(s: str) -> str:
    """비교용 정규화. 공백과 쉼표와 점과 하이픈을 제거한다."""
    return str(s).replace(" ", "").replace(",", "").replace(".", "").replace("-", "")


def _trim_cell(cell: tuple, boxes: list) -> tuple:
    """칸과 겹치는 인쇄 글자를 피해 칸을 좌우로 재단한다.

    AI가 라벨까지 포함한 넓은 칸을 주는 경우가 있다(예: '계좌번호 라벨+빈칸' 전체).
    겹치는 글자 상자의 중심이 칸 중심보다 왼쪽이면 칸의 왼쪽 경계를 그 글자 오른쪽으로,
    오른쪽이면 칸의 오른쪽 경계를 그 글자 왼쪽으로 당긴다. 결과는 빈 영역만 남는다."""
    x0, y0, x1, y1 = cell
    cx = (x0 + x1) / 2
    for bx0, by0, bx1, by1 in boxes:
        # 세로로 겹치고 가로로도 겹치는 인쇄 글자만 본다
        if by1 <= y0 or by0 >= y1 or bx1 <= x0 or bx0 >= x1:
            continue
        if (bx0 + bx1) / 2 <= cx:
            x0 = max(x0, bx1 + 2)   # 왼쪽 라벨 회피
        else:
            x1 = min(x1, bx0 - 2)   # 오른쪽 라벨 회피
    return (x0, y0, x1, y1)


def _label_coverage(cell: tuple, boxes: list) -> float:
    """칸 면적 중 인쇄된 글자 상자가 덮는 비율(0~1). 라벨 칸 오인 검출용."""
    cx0, cy0, cx1, cy1 = cell
    area = max(1.0, (cx1 - cx0) * (cy1 - cy0))
    covered = 0.0
    for x0, y0, x1, y1 in boxes:
        ix0, iy0 = max(cx0, x0), max(cy0, y0)
        ix1, iy1 = min(cx1, x1), min(cy1, y1)
        if ix1 > ix0 and iy1 > iy0:
            covered += (ix1 - ix0) * (iy1 - iy0)
    return covered / area


def validate_plan(plan: list, form_values: dict, layout: list[dict]) -> list[dict]:
    """AI가 낸 채움 계획을 검증해 안전한 항목만 돌려준다.

    각 항목 {text, page, cell:[x0,y0,x1,y1]}에 대해:
    - text가 비어있지 않고, 표시 기호(X, O)거나 회원 값의 일부여야 한다(환각 차단).
    - page가 실제 페이지 범위 안, 칸이 그 페이지 안의 정상 사각형이어야 한다.
    - 칸 면적의 35% 이상이 인쇄 글자로 덮여 있으면 라벨 칸으로 보고 버린다.
      단 X/O 표시는 괄호 등 인쇄 문자와 가까워 정상이어도 걸릴 수 있어 검사를 건너뛴다.
    크기와 위치는 여기서 정하지 않는다. tools.fit_into_cell이 칸 크기를 재서
    결정적으로 계산한다(AI는 '어느 칸에 어떤 값'만 답한다).
    """
    if not isinstance(plan, list):
        return []
    # 회원 값 정규화 집합. 부분 기재(등록번호 분할, 이메일 분절 등)를 허용하기 위해
    # "text가 어떤 값의 부분문자열"이면 통과시킨다.
    norm_values = [_norm(v) for v in form_values.values() if str(v).strip()]
    page_info = {p["page"]: p for p in layout}

    out = []
    for item in plan[:_MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text or len(text) > 80:
            continue
        is_mark = text in ("X", "O")
        if not is_mark:
            nt = _norm(text)
            if not nt or not any(nt in nv for nv in norm_values):
                continue  # 회원 값에 없는 텍스트. 환각으로 보고 버린다.
        cell = item.get("cell")
        if not (isinstance(cell, (list, tuple)) and len(cell) == 4):
            continue
        try:
            page = int(item.get("page", 0))
            x0, y0, x1, y1 = (float(v) for v in cell)
        except (TypeError, ValueError):
            continue
        if page not in page_info:
            continue
        info = page_info[page]
        # 정상 사각형 + 페이지 안 + 최소 크기(글자 하나는 들어갈 폭/높이)
        if not (0 <= x0 < x1 <= info["width"] and 0 <= y0 < y1 <= info["height"]):
            continue
        if (x1 - x0) < 8 or (y1 - y0) < 7:
            continue
        boxes = info.get("boxes", [])
        # 칸 재단: AI가 라벨까지 포함한 넓은 칸을 줬으면 인쇄 글자를 피해 줄인다.
        if not is_mark:
            x0, y0, x1, y1 = _trim_cell((x0, y0, x1, y1), boxes)
            if (x1 - x0) < 8 or (y1 - y0) < 7:
                continue  # 재단 후 남는 빈 영역이 없음. 잘못 잡은 칸이다.
            # 라벨 칸 오인 차단: 재단 후에도 인쇄 글자로 상당 부분 덮여 있으면 버린다.
            if _label_coverage((x0, y0, x1, y1), boxes) > 0.35:
                continue
        key = str(item.get("key", "")).strip()   # 실측 보충 대조용. 검증엔 안 쓴다.
        out.append({"key": key, "text": text, "page": page, "cell": [x0, y0, x1, y1]})
    return out


def plan_fill(form_id: str, form_name_ko: str, form_values: dict) -> list[dict] | None:
    """Sonnet에게 서식 레이아웃과 회원 값을 주고 채움 계획을 받는다.

    반환: 검증 통과한 계획 리스트. 실패(응답 파싱 불가, 항목 부족)면 None.
    호출부는 None이면 실측 좌표 차선책으로 넘어간다."""
    layout = extract_layout(form_id)
    if not layout:
        return None

    # 빈 값은 제외하고, 각 값에 한국어 라벨을 병기해 서식 라벨과 대응시킨다.
    values = {
        f"{k} ({_key_label(k)})": str(v)
        for k, v in form_values.items() if str(v).strip()
    }
    if not values:
        return None

    # 프롬프트에는 겹침 검증용 boxes를 빼고 보낸다(토큰 절약).
    # 셀 경계선(vlines/hlines)은 포함한다. AI가 입력 칸을 정확히 찾는 핵심 재료다.
    prompt_layout = [
        {"page": p["page"], "width": p["width"], "height": p["height"],
         "words": p["words"], "vlines": p.get("vlines", []), "hlines": p.get("hlines", [])}
        for p in layout
    ]

    from anthropic import Anthropic
    model = os.environ.get("CLAUDE_MODEL_DOCS", "claude-sonnet-4-6")
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    system = (
        "정부 신청서 PDF 서식에 회원 정보를 써 넣는 전문가다. "
        "서식의 단어 배치(단어, x, baseline y)와 표의 선을 읽고, 각 회원 값이 들어갈 "
        "'입력 칸'(빈 사각형 영역)을 정한다.\n"
        "출력은 좌표점이 아니라 칸이다(가장 중요):\n"
        "- 각 값에 대해 그 값이 들어갈 빈 입력 칸의 사각형 [x0, y0, x1, y1]을 답한다. "
        "글씨 크기와 정렬은 시스템이 칸 크기를 재서 자동으로 처리하므로 신경 쓰지 마라.\n"
        "- vlines는 세로선 [x, y시작, y끝], hlines는 가로선 [y, x시작, x끝]이다. "
        "이 선들이 표의 칸을 만든다. 칸의 경계는 가능한 한 이 선들에서 골라라.\n"
        "- 라벨 단어가 들어 있는 칸은 라벨 칸이다. 값은 반드시 그 옆(오른쪽)이나 아래의 "
        "빈 입력 칸을 골라라. 라벨 칸 사각형을 답하면 안 된다.\n"
        "- 선이 없는 빈 줄(밑줄식 입력란, 괄호 안 등)은 인쇄 글자를 피해서 빈 영역 사각형을 직접 잡아라.\n"
        "- 전화번호 괄호 칸이 여러 개면 첫 괄호에 국가코드(+82)를 넣고 두 번째 괄호부터 번호 마디를 넣는다. "
        "각 마디의 칸은 여는 괄호와 닫는 괄호 사이 영역이다.\n"
        "값 대응 규칙:\n"
        "- 값의 라벨과 서식 칸의 라벨이 의미까지 정확히 일치할 때만 그 칸에 쓴다. "
        "비슷해 보여도 의미가 다르면(예: 주소를 학과 칸에, 학교명을 근무처 칸에) 절대 넣지 않는다. "
        "맞는 칸이 없는 값은 뺀다.\n"
        "- 성별 표기 칸([ ]남 [ ]여 같은 것)에는 text를 'X'로 하고 괄호 안 작은 사각형을 칸으로 준다.\n"
        "- 등록번호를 한 자씩 쓰는 박스가 보이면 숫자를 나눠 각 박스 사각형에 한 자씩 넣어도 된다.\n"
        "- 좌표계는 페이지 왼쪽 위가 (0,0), 아래로 y 증가다.\n"
        "- 각 항목에 값의 키 이름(key)을 함께 적는다(회원 값 목록의 키 그대로).\n"
        "- 반드시 JSON만 출력한다. 형식: "
        "{\"fills\": [{\"key\": \"korean_name\", \"text\": \"값\", \"page\": 0, \"cell\": [x0, y0, x1, y1]}]}"
    )
    user = (
        f"서식 이름: {form_name_ko} ({form_id})\n\n"
        f"서식 단어 배치(페이지별 [단어, x, baseline y]):\n{json.dumps(prompt_layout, ensure_ascii=False)}\n\n"
        f"써 넣을 회원 값(키 (라벨): 값):\n{json.dumps(values, ensure_ascii=False, indent=1)}\n\n"
        "각 값이 들어갈 입력 칸 사각형(cell)을 정해 JSON으로만 답하라."
    )

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=4000,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = "".join(b.text for b in resp.content if b.type == "text").strip()
        # 앞뒤 코드 블록 표시 제거
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw[raw.index("{"):]
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end < 0:
            return None
        data = json.loads(raw[start:end + 1])
        plan = validate_plan(data.get("fills", []), form_values, layout)
        if len(plan) < _MIN_ITEMS:
            return None
        return plan
    except Exception:
        # 어떤 실패든 조용히 차선책으로 넘긴다. 시연이 끊기지 않는 것이 우선이다.
        return None
