"""개인정보 보안 공용 계층 (privacy / security).

기능명세서 '개인정보, 보안 관리' 항목을 구현한다.
순수 파이썬. streamlit, anthropic, MCP를 import 하지 않는다. 어느 부문에서도 쓸 수 있다.

제공 기능
    1. PII 마스킹        mask_value / mask_fields  - 로그와 화면 노출 시 민감정보 가림
    2. append-only 감사로그  append_audit / read_audit / verify_audit
                          - sha256 해시 체인으로 위변조 방지(무결성)
    3. sha256 무결성      sha256_bytes / sha256_file - 생성 산출물(PDF) 해시 기록
    4. Human-in-the-loop  build_approval / grant_approval - 큰 결정 전 사람 승인 게이트

설계 원칙
    - 감사로그와 산출물에는 원본 PII를 그대로 남기지 않는다. 마스킹 후 기록한다.
    - 감사로그는 append-only. 각 레코드는 직전 레코드 해시를 물어 체인을 이룬다.
    - 시간은 datetime.now(UTC). 테스트 재현을 위해 ts 주입을 허용한다.
    (스캔/OCR을 제거하면서 이미지 즉시 파기 secure_delete는 함께 뺐다.)
"""

from __future__ import annotations

import os
import re
import json
import hashlib
from datetime import datetime, timezone

# ── 경로 ─────────────────────────────────────────────────────
# 감사로그는 제출 폴더 밖 고정 위치(~/.liferoad/audit)에 둔다. 개인정보 포함
# 산출물이 제출 폴더에 생기지 않게 하고, 사용자 홈 기준이라 어느 컴퓨터든 동작한다.
AUDIT_DIR = os.path.expanduser("~/.liferoad/audit")
AUDIT_LOG = os.path.join(AUDIT_DIR, "audit_log.jsonl")

# 해시 체인의 시작점 (genesis)
_GENESIS_HASH = "0" * 64


# ============================================================
# 0. 공통 헬퍼
# ============================================================

def _now_iso() -> str:
    """현재 UTC 시각 ISO 문자열."""
    return datetime.now(timezone.utc).isoformat()


def _canonical(obj) -> str:
    """해시 계산용 표준 직렬화. 키 정렬 + 공백 제거로 재현성 보장."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    """바이트열의 sha256 hex."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """문자열의 sha256 hex (UTF-8)."""
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    """파일 내용의 sha256 hex. 생성 PDF 등 산출물 무결성 검증용."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


# ============================================================
# 1. PII 마스킹
# ============================================================

_REG_NO = re.compile(r"\b(\d{6})-?(\d{7})\b")          # 외국인등록번호와 주민번호
_PASSPORT = re.compile(r"\b([A-Z]{1,2}\d{6,8})\b")     # 여권번호

# OCR 필드명이나 프로필 키 → 마스킹 종류 매핑
_FIELD_KIND = {
    "등록번호": "reg_no",
    "주민번호": "reg_no",
    "reg_no": "reg_no",
    "여권번호": "passport",
    "passport_no": "passport",
    "성명": "name",
    "영문성명": "name",
    "korean_name": "name",
}


def mask_value(value, kind: str = "auto") -> str:
    """민감정보 한 값을 마스킹한다.

    kind: reg_no / passport / name / auto
        reg_no   961012-1234567 → 961012-1******   (앞 7자리만, 뒷 6자리 가림)
        passport M12345678       → M1******
        name     수만 라이         → 수* 라*          (각 토큰 첫 글자만)
        auto     문자열 안의 등록번호와 여권번호 패턴을 자동 탐지해 가림
    """
    if value is None:
        return ""
    s = str(value)

    if kind == "reg_no":
        m = _REG_NO.search(s)
        if m:
            return f"{m.group(1)}-{m.group(2)[0]}{'*' * 6}"
        return s

    if kind == "passport":
        m = _PASSPORT.search(s)
        if m:
            token = m.group(1)
            return token[:2] + "*" * (len(token) - 2)
        return s

    if kind == "name":
        return " ".join(
            (tok[0] + "*" * (len(tok) - 1)) if len(tok) > 1 else tok
            for tok in s.split()
        )

    # auto: 문자열 전체에서 알려진 패턴을 치환
    s = _REG_NO.sub(lambda m: f"{m.group(1)}-{m.group(2)[0]}{'*' * 6}", s)
    s = _PASSPORT.sub(lambda m: m.group(1)[:2] + "*" * (len(m.group(1)) - 2), s)
    return s


def mask_fields(fields: dict) -> dict:
    """필드 dict를 필드명 기준으로 마스킹한다.
    감사로그와 화면 미리보기에 쓴다. (사용자 본인에게 전체를 보여줄 때는 원본을 쓴다.)"""
    out = {}
    for k, v in (fields or {}).items():
        kind = _FIELD_KIND.get(k, "auto")
        out[k] = mask_value(v, kind)
    return out


# ============================================================
# 2. append-only 감사 로그 (sha256 해시 체인)
# ============================================================

def _last_hash(log_path: str) -> str:
    """로그 마지막 레코드의 hash를 반환. 없으면 genesis."""
    if not os.path.exists(log_path):
        return _GENESIS_HASH
    last = _GENESIS_HASH
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    last = json.loads(line)["hash"]
                except (json.JSONDecodeError, KeyError):
                    continue
    return last


def append_audit(
    action: str,
    actor: str = "system",
    doc_type: str | None = None,
    detail: dict | None = None,
    log_path: str = AUDIT_LOG,
    ts: str | None = None,
) -> dict:
    """감사 이벤트를 append-only로 기록한다. 기록된 레코드(dict)를 반환한다.

    action:   'form_autofill' / 'approval_grant' 등
    actor:    누가 (persona_id 또는 'system' 또는 담당자 ID)
    detail:   부가 정보. 호출 전에 mask_fields로 마스킹해서 넘길 것.
    각 레코드는 prev_hash + 본문의 sha256을 hash로 물어 체인을 이룬다.
    """
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    prev = _last_hash(log_path)

    body = {
        "ts": ts or _now_iso(),
        "actor": actor,
        "action": action,
        "doc_type": doc_type,
        "detail": detail or {},
        "prev_hash": prev,
    }
    record = dict(body)
    record["hash"] = sha256_text(prev + _canonical(body))

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(_canonical(record) + "\n")
    return record


def read_audit(log_path: str = AUDIT_LOG) -> list[dict]:
    """감사 로그 전체를 레코드 리스트로 읽는다."""
    if not os.path.exists(log_path):
        return []
    records = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def verify_audit(log_path: str = AUDIT_LOG) -> tuple[bool, int | None]:
    """감사 로그 해시 체인 무결성을 검증한다.
    반환: (정상여부, 처음 깨진 레코드 index 또는 None)."""
    prev = _GENESIS_HASH
    for i, rec in enumerate(read_audit(log_path)):
        body = {k: rec[k] for k in ("ts", "actor", "action", "doc_type", "detail", "prev_hash")}
        expected = sha256_text(prev + _canonical(body))
        if rec.get("prev_hash") != prev or rec.get("hash") != expected:
            return (False, i)
        prev = rec["hash"]
    return (True, None)


# ============================================================
# 3. Human-in-the-loop 승인 게이트
# ============================================================

def build_approval(action: str, summary: str, payload: dict | None = None) -> dict:
    """큰 결정(신청서 제출이나 PDF 확정 등) 전 사람 승인을 요구하는 요청 객체를 만든다.
    AI는 제안만 하고, status가 'approved'가 되기 전에는 확정하거나 제출하지 않는다."""
    return {
        "status": "pending",
        "action": action,
        "summary": summary,
        "payload": payload or {},
        "requested_at": _now_iso(),
        "approved_by": None,
        "approved_at": None,
    }


def grant_approval(request: dict, approver: str, log_path: str = AUDIT_LOG) -> dict:
    """승인 요청을 사람이 승인 처리한다. 승인 사실을 감사로그에 남긴다."""
    granted = dict(request)
    granted["status"] = "approved"
    granted["approved_by"] = approver
    granted["approved_at"] = _now_iso()
    append_audit(
        action="approval_grant",
        actor=approver,
        detail={"for": request.get("action"), "summary": request.get("summary")},
        log_path=log_path,
    )
    return granted


def is_approved(request: dict | None) -> bool:
    """확정과 제출 전 호출부에서 승인 여부를 확인하는 게이트."""
    return bool(request) and request.get("status") == "approved"


# ============================================================
# 자체 점검 (python -m shared.security)
# ============================================================

if __name__ == "__main__":
    import tempfile

    print("=== 1. 마스킹 ===")
    assert mask_value("961012-1234567", "reg_no") == "961012-1******"
    assert mask_value("M12345678", "passport") == "M1*******"
    assert mask_value("수만 라이", "name") == "수* 라*"
    auto = mask_value("등록번호 961012-1234567 여권 M12345678", "auto")
    assert "961012-1******" in auto and "M1*******" in auto, auto
    masked = mask_fields({"등록번호": "961012-1234567", "성명": "수만 라이", "국적": "NEPAL"})
    assert masked["등록번호"] == "961012-1******"
    assert masked["국적"] == "NEPAL"  # 민감정보 아님 → 그대로
    print("  OK", masked)

    with tempfile.TemporaryDirectory() as d:
        log = os.path.join(d, "audit.jsonl")

        print("=== 2. 감사로그 해시 체인 ===")
        append_audit("form_autofill", actor="suman", doc_type="alien_registration_renewal",
                     detail=mask_fields({"등록번호": "961012-1234567"}), log_path=log)
        append_audit("form_autofill", actor="suman", doc_type="pension_return_claim",
                     detail={"form": "pension_return_claim"}, log_path=log)
        ok, bad = verify_audit(log)
        assert ok and bad is None, (ok, bad)
        recs = read_audit(log)
        assert recs[1]["prev_hash"] == recs[0]["hash"]   # 체인 연결 확인
        print(f"  {len(recs)}건 기록, 무결성 OK")

        print("=== 2b. 위변조 탐지 ===")
        lines = open(log, encoding="utf-8").read().splitlines()
        tampered = json.loads(lines[0]); tampered["actor"] = "attacker"
        lines[0] = _canonical(tampered)
        open(log, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        ok2, bad2 = verify_audit(log)
        assert ok2 is False and bad2 == 0, (ok2, bad2)
        print(f"  위변조 감지 OK (깨진 index={bad2})")

        print("=== 3. sha256 무결성 ===")
        p = os.path.join(d, "sample.pdf")
        open(p, "wb").write(b"%PDF-1.7 dummy")
        assert sha256_file(p) == sha256_bytes(b"%PDF-1.7 dummy")
        print("  OK", sha256_file(p)[:16], "...")

        print("=== 4. 승인 게이트 ===")
        log2 = os.path.join(d, "audit2.jsonl")
        req = build_approval("form_submit", "외국인등록증 갱신 신청서 제출")
        assert not is_approved(req)
        req = grant_approval(req, approver="suman", log_path=log2)
        assert is_approved(req)
        print("  pending → approved OK")

    print("\n[모든 자체 점검 통과]")
