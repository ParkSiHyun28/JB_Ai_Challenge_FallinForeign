"""사기탐지 부문 데모 상수와 라벨. 진짜 엔진(engine/) 입력을 구성한다.

원칙:
- 판정과 점수는 전부 engine/(core L1~L4)이 계산한다. 이 파일은 결과 숫자를 하드코딩하지 않는다.
- 이 파일이 두는 것은 세 가지뿐이다.
  (1) 데모 거래(엔진 Transaction 입력 형식). 시연 고정 시나리오.
  (2) 엔진 원시 코드값을 한국어로 옮기는 라벨.
  (3) 페르소나(flag/visa 등)를 엔진 프로필 필드로 옮기는 매핑 규칙.
- shared 나 mcp 를 import 하지 않는다. 순수 상수와 순수 보조 함수만 둔다.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

# 시연 기준일(shared.personas.DEMO_TODAY_STR 과 같은 날). 민 출국 D-90 무렵.
DEMO_TODAY_STR = "2026-10-03"
_KST = timezone(timedelta(hours=9))


def epoch_at(date_str: str, hour: int) -> float:
    """'YYYY-MM-DD' 날짜의 KST 로컬 hour 를 epoch 초로. 엔진 Transaction.timestamp 용."""
    y, m, d = (int(v) for v in date_str.split("-"))
    return datetime(y, m, d, hour, 0, tzinfo=_KST).timestamp()


def won(n: float) -> str:
    """원화 정수를 사람이 읽는 한국어 금액 문자열로. 예 9400000 -> '940만 원'."""
    man = round(n / 10000)
    if man >= 10000:
        eok, rest = divmod(man, 10000)
        return f"{eok}억 {rest:,}만 원" if rest else f"{eok}억 원"
    return f"{man:,}만 원"


# ===========================================================================
# 엔진 룰/액션 코드값 -> 한국어 라벨 (콘솔과 tool 이 함께 쓴다)
# ===========================================================================
RULE_LABELS_KO = {
    "corridor_mismatch": "본국이 아닌 제3국 송금",
    "exit_drawdown": "출국 임박 시점 잔액 인출",
    "new_device_high_amount": "미등록 새 기기에서 고액 거래",
    "rapid_passthrough": "입금 직후 전액 이체(통과계좌 의심)",
    "night_remittance": "심야 시간대 해외 송금",
    "residency_overstayed": "체류 만료 후 금융 활동",
    "exit_takeover_boost": "출국기 계좌양도 가중",
}

ACTION_LABELS_KO = {
    "allow": "정상",
    "review": "추가 검토",
    "soft_block": "즉시 보류",
}

# AI 조사관(Investigator) 코드값 -> 한국어 (콘솔 소견 표시용)
SUSPECTED_LABELS_KO = {
    "exit_period_account_takeover": "출국기 계좌양도 의심",
    "phishing_or_remote_control": "보이스피싱 / 원격제어 의심",
    "baseline_anomaly": "정상분포 이탈 이상거래",
    "unusual_transaction": "이례 거래",
}

RECOMMEND_LABELS_KO = {
    "hold_and_native_language_verify": "보류 유지 + 모국어 본인확인",
    "hold_and_manual_review": "보류 유지 + 수동 심사",
    "manual_review": "수동 심사",
    "monitor": "정상 처리 후 관찰",
}

CONFIDENCE_LABELS_KO = {"high": "높음", "medium": "중간", "low": "낮음"}

# 엔진 피처 코드값 -> 한국어 (Local-DIFFI 설명 표시용)
FEATURE_LABELS_KO = {
    "amount_log": "거래 금액",
    "balance_drawdown_ratio": "잔액 인출 비율",
    "hour": "거래 시각",
    "is_new_device": "신규 기기 여부",
    "corridor_match": "송금 경로 일치",
    "tx_velocity_24h": "24시간 거래 빈도",
    "days_to_residency_end": "체류 만료 남은 일수",
}

# ===========================================================================
# 페르소나(flag) -> 엔진 프로필 매핑 규칙
# 엔진 세그먼트 키는 f"{nationality}:{visa_type}" 이며 학습모델(VN:E-9, NP:D-2)과 맞는다.
# ===========================================================================
FLAG_TO_LANG = {"VN": "vi", "NP": "ne", "KR": "ko"}


def persona_to_profile(p: dict) -> dict:
    """shared.personas 의 페르소나 dict -> 엔진 profile dict.

    엔진 CustomerProfile 이 요구하는 필드를 페르소나 값에서 결정론적으로 유도한다.
    - nationality/home_country: flag(VN/NP)
    - visa_type: visa(E-9/D-2)
    - residency_end_date: exit_plan('YYYY-MM') 의 1일로 확정
    - language: flag 로 유도(vi/ne), 없으면 영어
    """
    flag = p.get("flag", "")
    exit_plan = p.get("exit_plan", "2027-01")
    return {
        "customer_id": p["id"],
        "nationality": flag,
        "visa_type": p.get("visa", ""),
        "residency_end_date": f"{exit_plan}-01",
        "language": FLAG_TO_LANG.get(flag, "en"),
        "home_country": flag,
    }


# ===========================================================================
# 시연 고정 거래 (엔진 Transaction 입력 형식)
# 주인공 minh(베트남 E-9)의 실시간 거래 피드. 940만 원 계좌양도 건이 핵심이다.
# timestamp 는 epoch_at 으로 시연 기준일에서 만든다. 엔진이 이 거래를 실제로 채점한다.
# label 은 화면 표시용이며 엔진 입력이 아니다.
# ===========================================================================
def _tx(tx_id, label, customer_id, amount, channel, cp_country, new_device,
        drawdown, hour, velocity, date_str=DEMO_TODAY_STR):
    """데모 거래 한 건을 엔진 Transaction dict 로. balance_before 는 인출비율에서 역산."""
    balance_before = round(amount / drawdown) if drawdown > 0 else amount * 5
    return {
        "label": label,
        "tx": {
            "tx_id": tx_id,
            "customer_id": customer_id,
            "timestamp": epoch_at(date_str, hour),
            "amount": amount,
            "channel": channel,
            "counterparty_country": cp_country,
            "device_id": ("NEWDEV-" + tx_id[-4:]) if new_device else ("DEV-" + customer_id),
            "ip_country": cp_country,
            "balance_before": balance_before,
            "balance_drawdown_ratio": drawdown,
            "is_new_device": new_device,
            "tx_velocity_24h": velocity,
            "tz_offset_minutes": 540,
        },
    }


DEMO_TRANSACTIONS = {
    "minh": [
        # 핵심: 출국 임박 + 새 기기 + 잔액 전액 도메스틱 이체 = 계좌양도 의심
        _tx("TX-MINH-9401", "계좌양도 의심 이체", "minh", 9_400_000, "domestic", "KR",
            new_device=True, drawdown=0.99, hour=14, velocity=1),
        # 정상: 일상 생활비 이체(모델 정상분포 안쪽)
        _tx("TX-MINH-2701", "생활비 이체", "minh", 450_000, "domestic", "KR",
            new_device=False, drawdown=0.12, hour=9, velocity=1),
        # 주의: 심야 제3국 해외 송금
        _tx("TX-MINH-1001", "심야 해외 송금", "minh", 1_000_000, "remittance", "PH",
            new_device=False, drawdown=0.2, hour=2, velocity=2),
    ],
    "suman": [
        # 수만(네팔 D-2 유학생) 균형용: 심야 제3국 송금 주의 건
        _tx("TX-SUMAN-0801", "심야 해외 송금", "suman", 800_000, "remittance", "PH",
            new_device=True, drawdown=0.6, hour=1, velocity=2),
    ],
}


def demo_feed(persona_id: str) -> list:
    """페르소나의 데모 거래 피드(라벨+엔진 tx). 없으면 빈 리스트."""
    return DEMO_TRANSACTIONS.get(persona_id, [])


def hero_tx(persona_id: str):
    """페르소나의 대표 의심 거래(피드 첫 건). 없으면 None."""
    feed = DEMO_TRANSACTIONS.get(persona_id)
    return feed[0] if feed else None


# ===========================================================================
# 관제 화면 전용 가상 보류 대상자
# 페르소나 2명(minh, suman)은 폰 채팅 tool 의 고정 주인공이고, 은행 관제 화면에는
# 다른 고객 케이스도 함께 보여야 실제 FDS 답다. 아래 가상 고객은 관제 대기열에만
# 나오며 tool 이나 폰 채팅에서는 접근할 수 없다(가드레일과 무관).
# 거래는 전부 엔진이 실제로 채점한다. 결과 숫자 하드코딩 없음.
# 세그먼트는 학습 모델이 있는 VN:E-9 와 NP:D-2 안에서만 만든다.
# ===========================================================================
EXTRA_SUSPECTS = {
    "huong": {
        "name": "쩐 티 흐엉",
        "country": "베트남",
        "visa": "E-9",
        "flag": "VN",
        "residency_end": "2027-04-01",
        "seed_decision": None,   # 초기 상태: 본인확인 응답 대기
        "item": _tx("TX-HUONG-4801", "입금 직후 전액 이체", "huong", 4_800_000, "domestic", "KR",
                    new_device=False, drawdown=0.95, hour=15, velocity=6),
    },
    "ramesh": {
        "name": "라메쉬 구룽",
        "country": "네팔",
        "visa": "D-2",
        "flag": "NP",
        "residency_end": "2027-08-01",
        "seed_decision": None,
        "item": _tx("TX-RAMESH-5501", "새 기기 고액 이체", "ramesh", 5_500_000, "domestic", "KR",
                    new_device=True, drawdown=0.7, hour=13, velocity=1),
    },
    "cuong": {
        "name": "레 반 끄엉",
        "country": "베트남",
        "visa": "E-9",
        "flag": "VN",
        "residency_end": "2027-06-01",
        "seed_decision": None,   # 전부 미결(보류) 상태로 시작. 분석가가 큐에서 골라 결정한다.
        "item": _tx("TX-CUONG-0601", "심야 제3국 송금", "cuong", 600_000, "remittance", "PH",
                    new_device=False, drawdown=0.3, hour=3, velocity=2),
    },
}


def extra_suspect(sid: str):
    """가상 보류 대상자 1명. 없으면 None."""
    return EXTRA_SUSPECTS.get(sid)


def suspect_profile(sid: str) -> dict:
    """가상 대상자 -> 엔진 profile dict. 페르소나와 같은 매핑 규칙."""
    s = EXTRA_SUSPECTS[sid]
    return {
        "customer_id": sid,
        "nationality": s["flag"],
        "visa_type": s["visa"],
        "residency_end_date": s["residency_end"],
        "language": FLAG_TO_LANG.get(s["flag"], "en"),
        "home_country": s["flag"],
    }
