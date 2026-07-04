# mcp_servers (도메인 부문)

각 금융 도메인을 독립 부문으로 담습니다. **폴더만 규약대로 넣으면 자동 연결**됩니다.

| 폴더 | 부문 | 상태 | 도구 |
|---|---|---|---|
| `asset/` | 자산 | 완료(표준 예시) | deadline_radar, pension_estimator, collateral_calc, remit_optimizer, credit_builder |
| `docs/` | 서류행정 | 완료 | perception_parse(OCR), compliance_reason(가드레일), form_autofill(자동작성) |
| (`fraud/`) | 사기탐지 | 미합류 | 폴더를 넣으면 자동 연결 예정 |

## 새 부문 추가 규칙

1. 상위 `CONTRACT.md`를 먼저 읽습니다(입출력 4키 규약).
2. `asset/` 폴더를 영문명으로 복제합니다(한글명은 import 깨짐).
3. `tools.py`와 `schemas.py`를 자기 부문에 맞게 바꿉니다.
4. `python -m pytest`로 검증합니다. 가드레일이 자동 검사합니다.

각 부문 폴더 구성: `tools.py`(도구 함수), `schemas.py`(도구 스키마), `data.py`(데이터), `server.py`, `tests/`.
