# tests (회귀 테스트)

전체 통합 테스트입니다. 데모 전에 반드시 통과시킵니다.

| 파일 | 역할 |
|---|---|
| `test_contract.py` | **공용 규약 가드레일**. 페르소나 2명 동결, 도구 4키 형식 검증. **수정 금지.** |
| `test_dynamic_personas.py` | 시뮬레이션용 동적 페르소나 생성 검증. |
| `test_active_demo.py` | 능동 모드 데모 흐름 검증. |
| `test_deploy_and_numbers.py` | 배포 환경 점검과 금액 포맷 검증. |
| `smoke_real_llm.py` | 실제 LLM 연동 통합 흐름 테스트. |

실행: `python -m pytest -v`

> `test_contract.py`는 새 부문이 추가돼도 자동으로 검사합니다. 통과하면 규약 준수입니다.
