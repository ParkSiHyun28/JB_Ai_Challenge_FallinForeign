// mod_asset.js
(function () {
  window.LIFEROAD_MODULES = window.LIFEROAD_MODULES || {};

  window.LIFEROAD_MODULES["asset"] = {
    id: "asset",
    name: "자산관리 에이전트",
    nameEn: "Asset Agent",
    icon: "💰",
    tagline: "마감 전에 먼저 감지하고 내 숫자로 계산해 행동까지 잇는다",
    tools: [
      { name: "deadline_radar", desc: "반환일시금과 보험금과 연금 청구 마감 D-Day 자동 추적" },
      { name: "remit_optimizer", desc: "송금 수수료와 환율과 경로 비교로 최저비용 경로 안내" },
      { name: "pension_estimator", desc: "E-9 국민연금 반환일시금 예상액 개인 산출" },
      { name: "credit_builder", desc: "월세와 통신비와 공과금 대안신용 데이터 축적 시작" },
      { name: "collateral_calc", desc: "잔고증명 예금 기준 담보대출 한도 95% 산출" },
    ],
    steps: {
      minh: [
        {
          phase: "arrival",
          t: 11,
          actor: "asset",
          to: "asset",
          kind: "trigger",
          title: "한도제한계좌 송금 손실 감지",
          detail:
            "입국 직후 개설한 외국인 한도제한계좌에서 월 베트남 송금 시 평균 수수료율 5.15% 적용 중임을 감지했습니다. " +
            "remit_optimizer가 하나은행 GLN과 WireBarley 경로를 비교한 결과 수수료 1.8% 이하 경로가 존재합니다. " +
            "월 송금액 100만 원 기준 연간 절감 예상액은 약 33만 원입니다.",
          tool: "remit_optimizer",
        },
        {
          phase: "arrival",
          t: 14,
          actor: "asset",
          to: "minh",
          kind: "result",
          title: "송금 최저경로 안내 카드",
          detail:
            "remit_optimizer가 산출한 최저비용 경로를 사용자 화면에 카드로 푸시합니다. " +
            "현재 경로(5.15%) 대비 WireBarley 경로(1.6%) 선택 시 이번 달 절감액 3,550원을 즉시 확인할 수 있습니다.",
          card: {
            icon: "💸",
            head: "송금 비용 절반으로 줄일 수 있습니다",
            body: "현재 은행 경로(5.15%) 대신 WireBarley(1.6%)를 쓰면 이번 달 3,550원 아낍니다. 연간 약 33만 원 절감.",
            metric: "경로 3개 비교 완료",
          },
        },
        {
          phase: "settle",
          t: 31,
          actor: "asset",
          to: "asset",
          kind: "trigger",
          title: "출국만기보험 적립 가시화",
          detail:
            "E-9 사업장은 출국만기보험 의무 가입 대상입니다. 월 통상임금 8.3%가 자동 적립 중이나 민 씨는 이 사실을 모르고 있었습니다. " +
            "입국 2022년 3월 기준 현재까지 약 50개월 적립이 진행됐습니다. " +
            "월 통상임금 270만 원의 8.3%인 월 22만 4천 원 기준으로 총 적립 예상액은 약 1,120만 원입니다. " +
            "소멸시효는 출국일로부터 3년이지만 청구를 모르면 소멸 위험이 있습니다.",
          tool: "deadline_radar",
        },
        {
          phase: "settle",
          t: 34,
          actor: "asset",
          to: "minh",
          kind: "result",
          title: "출국만기보험 적립 현황 카드",
          detail:
            "출국만기보험 적립 현황과 출국 예정일(2027년 1월) 기준 청구 마감 D-Day를 카드로 안내합니다. " +
            "현재 D-240 기준으로 청구 준비를 시작해야 소멸시효 3년을 여유롭게 관리할 수 있습니다.",
          card: {
            icon: "🏦",
            head: "출국만기보험 약 1,120만 원 적립 중",
            body: "50개월치 적립금이 쌓여 있습니다. 출국 후 3년 내 청구 필수. 지금 수령 절차를 미리 확인하세요.",
            metric: "청구 마감 D-1,095",
          },
        },
        {
          phase: "expand",
          t: 57,
          actor: "asset",
          to: "asset",
          kind: "trigger",
          title: "국민연금 반환일시금 수령 자격 정정",
          detail:
            "E-9 비자 근로자는 베트남과의 사회보장협정 미체결로 귀국 시 국민연금 반환일시금 수령 대상입니다. " +
            "민 씨가 '외국인은 연금 못 받는다'는 잘못된 정보를 갖고 있음을 대화 맥락에서 감지했습니다. " +
            "pension_estimator로 2022년 3월부터 현재까지 납부 기록을 기반으로 예상 반환일시금을 산출합니다. " +
            "2023년 기준 외국인 반환일시금 총 지급액은 3,294억 원이며 평균 수령액 기준으로 민 씨는 약 480만 원 수령 예상입니다.",
          tool: "pension_estimator",
        },
        {
          phase: "expand",
          t: 61,
          actor: "asset",
          to: "asset",
          kind: "tool",
          title: "환율 적기 송금 알림 설정",
          detail:
            "2022년 환율 1,290원에서 2024년 1,370원으로 약 6.2% 상승했습니다. " +
            "remit_optimizer가 베트남 동(VND) 환율 임계점 1,380원 도달 시 자동 알림을 설정합니다. " +
            "목표 환율 도달 시점에 송금하면 동일 원화로 더 많은 동을 베트남에 보낼 수 있습니다.",
          tool: "remit_optimizer",
        },
        {
          phase: "exit",
          t: 81,
          actor: "asset",
          to: "asset",
          kind: "trigger",
          title: "반환일시금 청구 마감 D-90 선제 감지",
          detail:
            "deadline_radar가 출국 예정일(2027년 1월) 기준 D-90 시점에 도달했음을 감지했습니다. " +
            "국민연금 반환일시금 청구는 출국일로부터 2년 내 가능하며 준비 서류는 여권 사본과 외국인등록증과 지급신청서 원본입니다. " +
            "pension_estimator 최종 산출 결과: 납부 월수 58개월 기준 예상 반환일시금은 약 496만 원입니다. " +
            "또한 미청구 휴면보험금이 307.6억 원 규모로 적립되어 있으며 반환율은 30%에 그칩니다. " +
            "민 씨 명의 보험금도 별도 조회가 필요합니다.",
          tool: "deadline_radar",
        },
        {
          phase: "exit",
          t: 84,
          actor: "asset",
          to: "docs",
          kind: "handoff",
          title: "반환일시금 지급신청서 작성 docs에 인계",
          detail:
            "asset이 반환일시금 청구 마감을 trigger로 감지한 뒤 국민연금공단 양식(NPS-F-001) 자동작성을 docs에 handoff합니다. " +
            "전달 데이터: 민 씨 납부 기록(58개월)과 예상 수령액(약 496만 원)과 출국 예정일(2027.1) 그리고 필요 서류 목록을 함께 넘깁니다. " +
            "docs가 form_autofill로 PDF를 채우면 asset은 수령 계좌(베트남 Vietcombank)와 연결하는 remit_optimizer 설정을 이어서 처리합니다.",
        },
        {
          phase: "exit",
          t: 87,
          actor: "asset",
          to: "minh",
          kind: "result",
          title: "귀국 자산 수령 종합 안내 카드",
          detail:
            "국민연금 반환일시금과 출국만기보험금과 미청구 보험금 3종의 예상 수령액을 통합 안내합니다. " +
            "총 수령 예상액은 약 1,616만 원이며 수령 후 베트남 송금 최저경로도 함께 준비되어 있습니다.",
          card: {
            icon: "🎯",
            head: "귀국 전 받을 돈 총 약 1,616만 원",
            body: "반환일시금 496만 원 + 출국만기보험 1,120만 원. 신청서 초안이 준비됐습니다. 서명만 하세요.",
            metric: "3종 동시 청구 준비 완료",
          },
        },
      ],
      suman: [
        {
          phase: "arrival",
          t: 14,
          actor: "asset",
          to: "asset",
          kind: "trigger",
          title: "잔고증명 예치금 인출 가능 범위 계산",
          detail:
            "D-2 유학생은 비자 유지 요건으로 잔고증명 예치금 2,000만 원을 유지해야 합니다. " +
            "collateral_calc가 현재 잔고 2,000만 원에서 인출 가능 범위를 실시간 계산합니다. " +
            "잔고 요건 2,000만 원을 유지하면서도 예금담보대출 95% 한도(1,900만 원)를 활용해 생활비를 마련하는 방법이 있습니다. " +
            "직접 인출 시 잔고 요건 위반 위험이 있으므로 담보대출 경로를 먼저 안내합니다.",
          tool: "collateral_calc",
        },
        {
          phase: "arrival",
          t: 17,
          actor: "asset",
          to: "suman",
          kind: "result",
          title: "잔고 안전 활용 안내 카드",
          detail:
            "잔고 2,000만 원을 유지하면서 예금담보대출(95% 한도 1,900만 원)로 생활비를 마련하는 방법을 카드로 안내합니다. " +
            "직접 인출보다 이자 부담은 있지만 비자 요건 위반 리스크가 없습니다.",
          card: {
            icon: "🔐",
            head: "잔고 2,000만 원 유지하며 1,900만 원 활용 가능",
            body: "예금담보대출(한도 95%)로 생활비 마련 가능. 잔고 요건 위반 없이 안전하게 쓸 수 있습니다.",
            metric: "담보대출 한도 1,900만 원",
          },
        },
        {
          phase: "settle",
          t: 41,
          actor: "asset",
          to: "asset",
          kind: "tool",
          title: "월세와 통신비 신용데이터 축적 시작",
          detail:
            "D-2 유학생은 소득이 없어 신용이력이 거의 없는 Thin Filer입니다. " +
            "credit_builder가 월 납부 중인 월세와 통신비와 공과금을 대안신용 데이터로 축적하기 시작합니다. " +
            "KCB 마이데이터 연동으로 비금융 납부 이력을 신용점수에 반영하는 경로를 개통합니다. " +
            "6개월 이상 꾸준한 납부 이력이 쌓이면 JB 외국인 전용 신용평가 심사에 활용할 수 있습니다.",
          tool: "credit_builder",
        },
        {
          phase: "settle",
          t: 44,
          actor: "asset",
          to: "suman",
          kind: "result",
          title: "신용 쌓기 시작 안내 카드",
          detail:
            "월세와 통신비 납부 이력을 신용데이터로 연동한 결과를 카드로 안내합니다. " +
            "6개월 후 대안신용 등급이 형성되면 JB 외국인 대출 심사에서 플러스 요인이 됩니다.",
          card: {
            icon: "📈",
            head: "오늘부터 신용 쌓기 시작",
            body: "월세와 통신비 납부 이력을 신용데이터로 연동했습니다. 6개월 후 JB 대출 심사에서 활용됩니다.",
            metric: "신용데이터 연동 완료",
          },
        },
        {
          phase: "expand",
          t: 57,
          actor: "asset",
          to: "asset",
          kind: "trigger",
          title: "네팔 상호주의 미체결 연금 손익 정직 안내",
          detail:
            "D-2 유학생 수만 씨가 '나도 연금 돌려받냐'고 문의했습니다. " +
            "한국은 네팔과 사회보장협정을 맺지 않아 귀국 시 반환일시금 지급 대상이 아닙니다. " +
            "이 사실을 숨기지 않고 정직하게 안내합니다. 단 취업비자(E-7)로 전환 후 한국에 남을 경우 납부 이력이 수령으로 이어질 수 있습니다. " +
            "유학생 취업전환율은 22.4%로 전환 가능성이 있으므로 연금 유지 vs 귀국 포기 손익 구조를 함께 제시합니다.",
          tool: "pension_estimator",
        },
        {
          phase: "expand",
          t: 61,
          actor: "asset",
          to: "suman",
          kind: "result",
          title: "연금 손익 정직 안내 카드",
          detail:
            "네팔 상호주의 미체결로 귀국 시 연금 반환 불가 사실과 취업전환 시 연금 유지 경로를 카드로 안내합니다. " +
            "선택의 손익을 숨기지 않고 보여 줍니다.",
          card: {
            icon: "⚖️",
            head: "귀국하면 연금 돌려받기 어렵습니다",
            body: "네팔-한국 협정 미체결. 단 E-7 취업전환(전환율 22.4%) 시 납부 이력이 수령으로 이어집니다. 취업비자 전환 도움 필요하시면 알려주세요.",
            metric: "취업전환 가능성 22.4%",
          },
        },
        {
          phase: "exit",
          t: 84,
          actor: "asset",
          to: "suman",
          kind: "result",
          title: "신용 프로필 완성 JB 대출와 카드 심사 연결",
          detail:
            "credit_builder가 18개월간 축적한 월세와 통신비 납부 이력으로 대안신용 프로필이 완성됐습니다. " +
            "JB 외국인 전용 신용평가 모델에 해당 데이터를 제출하면 학생 신분에서도 소액 대출과 체크카드 발급이 가능합니다. " +
            "취업 전환 시 급여 이력이 추가되면 일반 신용대출 심사 기준도 충족할 수 있습니다.",
          card: {
            icon: "🎓",
            head: "18개월 납부 이력으로 신용 프로필 완성",
            body: "JB 외국인 전용 대출과 카드 심사에 바로 활용 가능합니다. 취업 후 신용대출도 준비됩니다.",
            metric: "대안신용 데이터 18개월치",
          },
        },
      ],
    },
  };
})();
