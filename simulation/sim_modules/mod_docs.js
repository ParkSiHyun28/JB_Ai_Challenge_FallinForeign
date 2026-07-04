// mod_docs.js
(function () {
  window.LIFEROAD_MODULES = window.LIFEROAD_MODULES || {};

  window.LIFEROAD_MODULES["docs"] = {
    id: "docs",
    name: "서류 행정 에이전트",
    nameEn: "Docs Agent",
    icon: "📄",
    tagline: "비정형 서류를 정형 데이터로. 마감 전에 먼저 움직입니다.",
    tools: [
      { name: "form_checker",       desc: "실명표기/날인 불일치 검출" },
      { name: "cross_border_parser", desc: "해외 은행 거래내역 파싱" },
      { name: "risk_scanner",       desc: "임대차 전세사기 위험도 분석" },
      { name: "rule_validator",     desc: "시간제취업/비자 가드레일 검증" },
      { name: "form_autofill",      desc: "정부 PDF 자동 타이핑" },
      { name: "closed_loop",        desc: "출국 전 대출상환 가상계좌 매핑" },
    ],
    steps: {
      minh: [
        // ── arrival 구간 (t 끝자리 0, 3) ──────────────────────────────
        {
          phase: "arrival",
          t: 10,
          actor: "docs",
          to: "docs",
          kind: "trigger",
          title: "실명 표기 불일치 능동 감지",
          detail:
            "외국인등록증과 근로계약서의 영문 성명 띄어쓰기 불일치를 자동 감지했습니다. " +
            "form_checker가 'NGUYEN VAN MINH'(등록증)와 'NGUYENVANMINH'(계약서)를 " +
            "대조해 불일치를 확인했습니다. 한도제한계좌 해제 요건에 실명 일치가 필수이므로 " +
            "즉시 교정 절차를 시작합니다.",
          tool: "form_checker",
        },
        {
          phase: "arrival",
          t: 13,
          actor: "docs",
          to: "asset",
          kind: "handoff",
          title: "한도제한 해제 서류 패키지 전달",
          detail:
            "실명 교정이 완료된 서류 패키지(외국인등록증 사본 + 수정 근로계약서 + 재직증명서)를 " +
            "자산 에이전트에 전달합니다. 전북은행 비대면 한도제한 해제 프로세스를 " +
            "asset이 이어받아 처리합니다.",
          card: {
            icon: "✅",
            head: "실명 불일치 교정 완료",
            body: "서류 3종 패키지를 준비했습니다. 전북은행 한도제한 해제로 이어집니다.",
            metric: "처리 1.2초",
          },
        },

        // ── settle 구간 (t 끝자리 0, 3) ──────────────────────────────
        {
          phase: "settle",
          t: 30,
          actor: "docs",
          to: "docs",
          kind: "tool",
          title: "베트남 은행 거래내역 파싱",
          detail:
            "Vietcombank 6개월 거래내역(PDF)을 cross_border_parser로 파싱했습니다. " +
            "베트남어 항목명을 한국어 카테고리로 자동 변환하고 " +
            "월 평균 송금액과 잔고 흐름을 추출했습니다. " +
            "이 데이터를 근거로 전북은행 외국인 특화 대출 금리 13.5%를 6.5%로 인하 신청하는 " +
            "금리 인하 요청서를 form_autofill로 자동 작성합니다.",
          tool: "cross_border_parser",
        },
        {
          phase: "settle",
          t: 33,
          actor: "docs",
          to: "docs",
          kind: "result",
          title: "금리 인하 요청서 자동 완성",
          detail:
            "금리 인하 요청서(전북은행 양식)에 베트남 거래내역 파싱 결과와 재직증명서 수치를 " +
            "자동 입력했습니다. 신청 금리 목표는 13.5%에서 6.5%입니다. " +
            "서명란만 남겨두고 나머지는 모두 채워진 상태입니다.",
          tool: "form_autofill",
          card: {
            icon: "📉",
            head: "금리 인하 요청서 완성",
            body: "베트남 거래내역 파싱 근거로 13.5% → 6.5% 신청서를 작성했습니다. 서명 후 제출하면 됩니다.",
            metric: "예상 금리 인하 6.5%p",
          },
        },

        // ── expand 구간 (t 끝자리 6, 9) ──────────────────────────────
        {
          phase: "expand",
          t: 56,
          actor: "docs",
          to: "docs",
          kind: "trigger",
          title: "비자 만료 D-90 선제 탐지",
          detail:
            "E-9 비자 만료일이 90일 이내로 진입했습니다. rule_validator가 비자연장 신청 가능 기간(D-90)과 " +
            "현재일을 대조해 자동 감지했습니다. " +
            "비자연장에 필요한 숙소제공확인서 발급이 지체되면 체류 자격이 단절되므로 " +
            "즉시 서류 수집을 시작합니다.",
          tool: "rule_validator",
        },
        {
          phase: "expand",
          t: 59,
          actor: "docs",
          to: "docs",
          kind: "result",
          title: "숙소제공확인서 자동 작성 완료",
          detail:
            "고용주 정보와 기존 계약서 내용을 기반으로 숙소제공확인서를 form_autofill로 " +
            "자동 작성했습니다. 법무부 양식 최신 버전을 적용했으며 " +
            "사업자등록번호와 주소 항목도 자동 검증했습니다. " +
            "고용주 날인만 받으면 비자연장 신청 가능합니다.",
          tool: "form_autofill",
          card: {
            icon: "🗂️",
            head: "비자연장 서류 준비 완료",
            body: "숙소제공확인서를 자동 작성했습니다. 고용주 날인 후 D-90 내 출입국사무소에 제출하세요.",
            metric: "만료 D-87",
          },
        },

        // ── exit 구간 (t 끝자리 0, 3, 6) ─────────────────────────────
        {
          phase: "exit",
          t: 80,
          actor: "docs",
          to: "docs",
          kind: "trigger",
          title: "asset 반환일시금 감지 수신 — 지급신청서 Auto-fill 착수",
          detail:
            "자산 에이전트가 국민연금 반환일시금 수령 대상(재직 중 납부 기간 확인)을 감지해 " +
            "서류 에이전트에 handoff를 전송했습니다. " +
            "2023년 기준 전체 반환일시금 규모는 3,294억 원이며 청구 마감은 출국일로부터 5년입니다. " +
            "form_autofill로 국민연금공단 반환일시금 지급청구서를 즉시 자동 작성합니다.",
          tool: "form_autofill",
        },
        {
          phase: "exit",
          t: 83,
          actor: "docs",
          to: "docs",
          kind: "tool",
          title: "대출 Closed-Loop — 가상계좌 매핑 및 자동상환",
          detail:
            "반환일시금 입금 예정 계좌와 전북은행 대출 잔액을 closed_loop로 연결했습니다. " +
            "반환일시금이 지정 계좌에 입금되는 즉시 대출 잔액(원금 + 이자)을 " +
            "자동으로 상환하는 가상계좌 매핑을 완료했습니다. " +
            "잔여 금액은 베트남 송금 대기 계좌로 이체됩니다.",
          tool: "closed_loop",
        },
        {
          phase: "exit",
          t: 86,
          actor: "docs",
          to: "asset",
          kind: "result",
          title: "귀국 전 서류 처리 완료 — asset에 최종 잔액 전달",
          detail:
            "반환일시금 지급청구서 제출과 대출 자동상환 설정이 모두 완료됐습니다. " +
            "대출 상환 후 예상 잔액을 자산 에이전트에 전달해 귀국 환전 및 최종 송금 경로 최적화를 " +
            "이어받도록 합니다.",
          card: {
            icon: "🏁",
            head: "귀국 전 서류 전 단계 완료",
            body: "반환일시금 청구서 제출 및 대출 자동상환 설정이 끝났습니다. 잔액은 자산 에이전트가 귀국 송금 경로로 안내합니다.",
            metric: "처리 총 3.1초",
          },
        },
      ],

      suman: [
        // ── arrival 구간 (t 끝자리 0, 3) ──────────────────────────────
        {
          phase: "arrival",
          t: 20,
          actor: "docs",
          to: "docs",
          kind: "trigger",
          title: "임대차계약서 전세사기 위험 능동 스캔",
          detail:
            "수만 라이가 업로드한 원룸 임대차계약서를 risk_scanner로 분석했습니다. " +
            "등기부등본상 근저당 설정액이 임대보증금의 85%를 초과해 " +
            "전세사기 위험도 85%로 판정됐습니다. " +
            "경고 메시지는 네팔어로 생성해 전달합니다.",
          tool: "risk_scanner",
        },
        {
          phase: "arrival",
          t: 23,
          actor: "docs",
          to: "docs",
          kind: "result",
          title: "전세사기 위험 경고 — 네팔어 알림 전송",
          detail:
            "전세사기 위험도 85% 판정 결과를 네팔어 경고 카드로 생성해 푸시했습니다. " +
            "근저당 설정 현황과 안전 기준(보증금 대비 근저당 70% 이하)을 함께 안내합니다. " +
            "안전한 대안 매물 탐색을 위해 자산 에이전트와 연계를 권장합니다.",
          card: {
            icon: "⚠️",
            head: "전세사기 위험도 85%",
            body: "근저당 설정액이 보증금의 85%입니다. 계약 전 반드시 확인하세요. (네팔어 원문 첨부)",
            metric: "위험도 85%",
          },
        },

        // ── settle 구간 (t 끝자리 6, 9) ──────────────────────────────
        {
          phase: "settle",
          t: 36,
          actor: "docs",
          to: "docs",
          kind: "tool",
          title: "시간제취업 확인서 대리 작성",
          detail:
            "D-2 비자 시간제취업 허가 요건(주 20시간 이하)을 rule_validator로 검증했습니다. " +
            "수만 라이의 현재 알바 시간이 주 20시간 한도 내에 있음을 확인하고 " +
            "시간제취업 확인서를 form_autofill로 자동 작성했습니다. " +
            "지도교수 서명란만 남겨두고 나머지 항목은 모두 채웠습니다.",
          tool: "rule_validator",
        },
        {
          phase: "settle",
          t: 39,
          actor: "docs",
          to: "asset",
          kind: "handoff",
          title: "시간제취업 확인서 완성 → asset에 소득 데이터 전달",
          detail:
            "시간제취업 확인서 작성이 완료됐습니다. " +
            "확인된 월 소득 데이터를 자산 에이전트에 전달해 " +
            "Thin Filer 신용이력 축적 재료로 활용하도록 합니다.",
          card: {
            icon: "📋",
            head: "시간제취업 확인서 완성",
            body: "주 20시간 요건 충족을 확인했습니다. 지도교수 서명 후 제출하면 됩니다.",
            metric: "D-2 비자 유지",
          },
        },

        // ── expand 구간 (t 끝자리 6) ──────────────────────────────────
        {
          phase: "expand",
          t: 66,
          actor: "docs",
          to: "docs",
          kind: "result",
          title: "잔고증명서 신뢰도 97% 뱃지 발급",
          detail:
            "자산 에이전트로부터 전달받은 잔고증명 데이터와 은행 원본 서류를 교차 검증했습니다. " +
            "2,000만 원 예치금의 입출금 이력과 계좌 진위를 검증해 " +
            "신뢰도 97% 뱃지를 잔고증명서에 부착했습니다. " +
            "입학처 및 비자 연장 심사에 바로 제출 가능한 형태입니다.",
          card: {
            icon: "🏅",
            head: "잔고증명 신뢰도 97% 인증",
            body: "2,000만 원 잔고증명이 검증됐습니다. 신뢰도 97% 뱃지가 첨부된 서류를 입학처에 제출하세요.",
            metric: "신뢰도 97%",
          },
        },

        // ── exit 구간 (t 끝자리 9) ────────────────────────────────────
        {
          phase: "exit",
          t: 89,
          actor: "docs",
          to: "docs",
          kind: "tool",
          title: "E-7 고용사유서 직무연관성 교정 리포트",
          detail:
            "졸업 후 E-7(특정활동) 비자 전환을 위한 고용사유서를 분석했습니다. " +
            "form_checker가 전공(컴퓨터공학)과 직무(데이터 분석)의 연관성 서술이 " +
            "출입국 심사 기준에 미흡함을 탐지했습니다. " +
            "E-7 내국인고용 20% 임계점 요건을 명시하는 보완 문구를 포함한 교정 리포트를 생성했습니다.",
          tool: "form_checker",
        },
        {
          phase: "exit",
          t: 96,
          actor: "docs",
          to: "asset",
          kind: "result",
          title: "E-7 전환 서류 패키지 완성 — asset에 신용프로필 연계 요청",
          detail:
            "고용사유서 교정 완료분과 재직예정증명서를 포함한 E-7 전환 서류 패키지를 완성했습니다. " +
            "자산 에이전트에 수만 라이의 신용프로필 결실 데이터(월세 납부 이력 및 통신비 이력)를 " +
            "서류 패키지에 첨부 가능하도록 연계를 요청합니다.",
          card: {
            icon: "🎓",
            head: "E-7 전환 서류 패키지 완성",
            body: "직무연관성 교정 및 내국인고용 20% 임계점 명시 완료. 자산 에이전트의 신용이력 데이터와 함께 제출 준비됩니다.",
            metric: "E-7 전환 준비 완료",
          },
        },
      ],
    },
  };
})();
