// mod_fraud.js
(function () {
  window.LIFEROAD_MODULES = window.LIFEROAD_MODULES || {};

  window.LIFEROAD_MODULES["fraud"] = {
    id: "fraud",
    name: "사기탐지 에이전트",
    nameEn: "Fraud Guard Agent",
    icon: "🛡️",
    tagline: "외국인 특화 사기 패턴을 능동 감지해 계좌와 자산을 선제 보호",

    tools: [
      {
        name: "register_baseline",
        desc: "(segment × nationality) 그룹별 정상 거래 분포 학습. 외국인 본국 송금을 사기로 오탐하는 문제 해결.",
      },
      {
        name: "score_transaction",
        desc: "룰(corridor, 금액, 시간) + Isolation Forest 잔차 + LLM 맥락 판단을 결합해 거래별 위험 점수 산출.",
      },
      {
        name: "detect_account_takeover",
        desc: "residency_end_date 기준 D-day 가중치 + 일괄인출 + 신규 디바이스 가중. 출국 직전 계좌양도(대포통장) 자동 홀딩.",
      },
      {
        name: "request_verification",
        desc: "Claude로 모국어(베트남어, 네팔어) 본인확인 메시지 생성. 피싱 의심 거래 시 사용자에게 모국어로 직접 확인.",
      },
    ],

    steps: {
      minh: [
        // ─── arrival (t 끝자리 2 or 5 or 8) ───
        {
          phase: "arrival",
          t: 12,
          actor: "fraud",
          to: "fraud",
          kind: "trigger",
          title: "베트남 송금 baseline 등록",
          detail:
            "E-9 베트남 근로자 세그먼트의 정상 송금 패턴을 register_baseline으로 학습했습니다. 월 1~2회, 건당 20만~80만 원, 한국→베트남 corridor가 정상 분포에 포함됩니다. 이 baseline이 없으면 귀국 전 대규모 본국 송금을 사기로 오탐하게 됩니다. 5.15% 수준의 재래식 송금 경로도 정상 패턴으로 학습했습니다.",
          tool: "register_baseline",
        },
        {
          phase: "arrival",
          t: 18,
          actor: "fraud",
          to: "asset",
          kind: "message",
          title: "송금 corridor 화이트리스트 자산 에이전트에 공유",
          detail:
            "register_baseline 완료 후 베트남 정상 송금 corridor 정보를 asset 에이전트에게 전달했습니다. asset 에이전트가 최저비용 송금 경로를 비교할 때 한국→베트남 구간을 사기 의심 없이 처리할 수 있도록 합니다. 외국인 근로자 연간 국내 송금 규모는 약 3조 원 이상으로 정상 패턴 학습이 필수입니다.",
        },

        // ─── settle ───
        {
          phase: "settle",
          t: 32,
          actor: "fraud",
          to: "fraud",
          kind: "trigger",
          title: "베트남어 보이스피싱 시나리오 탐지",
          detail:
            "정착 3개월 차, 베트남어로 작성된 피싱 SMS가 수신됐습니다. '한국 법무부 미납벌금 즉시납부' 패턴을 score_transaction이 감지했습니다. 외국인 대상 모국어 피싱은 국내 일반 패턴 탐지에 잡히지 않아 외국인 오탐률이 높습니다. 대포폰의 70%가 외국인 명의로 개통되며 명의도용 사례는 5년간 30만 건에 달합니다.",
          tool: "score_transaction",
        },
        {
          phase: "settle",
          t: 35,
          actor: "fraud",
          to: "fraud",
          kind: "tool",
          title: "베트남어 본인확인 메시지 발송",
          detail:
            "request_verification을 통해 Claude가 베트남어로 본인확인 메시지를 생성했습니다. '위 문자는 사기입니다. 법무부는 SMS로 벌금을 요청하지 않습니다. 계속 진행하려면 앱 내 본인확인을 완료해 주세요.'라는 메시지를 모국어로 전달했습니다. 한국어 경고만으로는 생활회화 수준인 외국인에게 위험이 전달되지 않습니다.",
          tool: "request_verification",
          card: {
            icon: "🚨",
            head: "베트남어 피싱 문자 차단",
            body: "법무부 사칭 문자를 탐지했습니다. 베트남어로 경고를 전송했으며 해당 링크는 차단됐습니다.",
            metric: "위험도 92점 → 즉시 차단",
          },
        },

        // ─── expand ───
        {
          phase: "expand",
          t: 58,
          actor: "fraud",
          to: "fraud",
          kind: "trigger",
          title: "인출책 패턴 자동 홀딩",
          detail:
            "신규 입금 후 30분 내 즉시 출금 패턴이 3회 반복됐습니다. score_transaction이 Isolation Forest 잔차로 이상 거래를 포착했습니다. 이는 전형적인 인출책 가담 패턴으로 환치기 중간 단계에서 자주 나타납니다. 한국-베트남 간 환치기 규모는 연간 3,010억 원으로 추산됩니다. 해당 계좌로의 이체를 자동 홀딩했습니다.",
          tool: "score_transaction",
          card: {
            icon: "⛔",
            head: "인출책 의심 거래 홀딩",
            body: "신규 입금→즉시 출금 패턴 3회가 감지됐습니다. 거래를 일시 보류하고 본인확인을 요청합니다.",
            metric: "이상 패턴 3회 연속 감지",
          },
        },

        // ─── exit ───
        {
          phase: "exit",
          t: 82,
          actor: "fraud",
          to: "asset",
          kind: "message",
          title: "출국 D-30 도달: 계좌양도 가중치 요청",
          detail:
            "asset 에이전트로부터 민 씨의 출국 예정일(residency_end_date) 정보를 수신했습니다. D-30 구간에 진입함에 따라 detect_account_takeover의 가중치를 표준 수준에서 고위험 수준으로 상향합니다. 대포통장 사건에서 외국인 명의자 626명이 동원됐고 해당 계좌를 통한 입출금 규모는 12.8조 원에 달합니다. 출국 임박 시점이 계좌 양도 유인이 가장 높은 구간입니다.",
        },
        {
          phase: "exit",
          t: 85,
          actor: "fraud",
          to: "fraud",
          kind: "tool",
          title: "계좌양도 감지: 일괄인출 + 신규 디바이스",
          detail:
            "detect_account_takeover가 신규 디바이스 로그인과 동시에 전액에 가까운 일괄인출 시도를 탐지했습니다. D-30 가중치가 적용된 상태에서 세 가지 신호(출국 임박, 신규 기기, 비정상 인출 금액)가 동시에 발생했습니다. 해당 거래를 즉시 홀딩했습니다. 2019년 이후 외국인 명의도용 대포통장 사건 명의자는 누적 5년간 30만 건을 넘습니다.",
          tool: "detect_account_takeover",
          card: {
            icon: "🔒",
            head: "계좌양도 자동 홀딩 완료",
            body: "출국 D-30 구간에서 신규 기기 로그인과 전액 인출 시도가 동시에 감지됐습니다. 계좌를 즉시 보호 상태로 전환했습니다.",
            metric: "대포통장 626명 명의 도용 방어",
          },
        },
        {
          phase: "exit",
          t: 88,
          actor: "fraud",
          to: "fraud",
          kind: "tool",
          title: "베트남어 긴급 본인확인 발송",
          detail:
            "계좌 홀딩 직후 request_verification을 통해 베트남어 긴급 본인확인 메시지를 생성했습니다. 'Tài khoản của bạn đã bị tạm dừng vì lý do bảo mật. Vui lòng xác nhận danh tính trong ứng dụng.' — 이 메시지는 Claude가 생성한 자연스러운 베트남어로 전달됩니다. 한국어 알림만으로는 생활회화 수준 사용자가 내용을 놓칠 위험이 있습니다.",
          tool: "request_verification",
          card: {
            icon: "📲",
            head: "베트남어 본인확인 전송 완료",
            body: "계좌 보호 조치를 베트남어로 직접 안내했습니다. 앱 내 인증을 완료하면 정상 출금이 가능합니다.",
            metric: "모국어 즉시 전달",
          },
        },
      ],

      suman: [
        // ─── arrival ───
        {
          phase: "arrival",
          t: 15,
          actor: "fraud",
          to: "fraud",
          kind: "trigger",
          title: "학교 공식계좌 화이트리스트 검증",
          detail:
            "수만 씨가 등록금과 기숙사비를 납부할 학교 공식 계좌를 register_baseline으로 화이트리스트에 등록했습니다. 유학생을 대상으로 학교 행정처나 기숙사 관리처를 사칭해 다른 계좌로 납부를 유도하는 피싱이 빈번합니다. 2,000만 원 규모의 잔고증명 예치금이 묶여 있어 피해 발생 시 손실 규모가 큽니다.",
          tool: "register_baseline",
        },

        // ─── settle ───
        {
          phase: "settle",
          t: 38,
          actor: "fraud",
          to: "fraud",
          kind: "trigger",
          title: "검찰과 경찰과 금감원 사칭 패턴 차단",
          detail:
            "수만 씨에게 '금융감독원 조사 협조 요청'이라는 제목의 이메일이 수신됐습니다. score_transaction의 LLM 맥락 판단이 검찰과 경찰과 금감원 사칭 유형 시나리오로 분류했습니다. 유학생은 한국 법집행 기관에 대한 배경지식이 부족해 피해에 취약합니다. 해당 이메일의 링크 접근을 차단했습니다.",
          tool: "score_transaction",
          card: {
            icon: "🚫",
            head: "기관 사칭 피싱 차단",
            body: "금감원 사칭 이메일을 탐지해 링크를 차단했습니다. 실제 금감원은 이메일로 개인정보를 요청하지 않습니다.",
            metric: "LLM 맥락 점수 89점 → 차단",
          },
        },
        {
          phase: "settle",
          t: 42,
          actor: "fraud",
          to: "fraud",
          kind: "tool",
          title: "네팔어 경고 메시지 발송",
          detail:
            "request_verification을 통해 Claude가 네팔어로 경고를 생성했습니다. 'यो इमेल ठगी हो। नेपाली विद्यार्थीहरूलाई लक्षित गरिएको छ।' — 사칭 기관명과 실제 공식 연락처를 함께 안내해 유학생이 직접 공식 채널로 확인할 수 있도록 했습니다.",
          tool: "request_verification",
        },

        // ─── expand ───
        {
          phase: "expand",
          t: 62,
          actor: "fraud",
          to: "fraud",
          kind: "trigger",
          title: "통장 대여 패턴 홀딩 및 위조 알선 URL 차단",
          detail:
            "비정상 입금(출처 불명 계좌) 후 10분 내 즉시 출금 시도가 감지됐습니다. 외국인 유학생을 대상으로 '알바비 수령' 명목으로 통장을 빌리는 방식의 범죄 가담 유도 사례가 증가하고 있습니다. 동시에 운전면허증 위조 알선 사이트 접근도 score_transaction이 탐지해 URL을 차단했습니다.",
          tool: "score_transaction",
          card: {
            icon: "⛔",
            head: "통장 대여 의심 거래 홀딩",
            body: "출처 불명 입금 후 즉시 출금 시도를 차단했습니다. 통장 대여는 전자금융거래법 위반으로 강제 출국 사유가 됩니다.",
            metric: "즉시출금 시도 홀딩 완료",
          },
        },

        // ─── exit ───
        {
          phase: "exit",
          t: 85,
          actor: "fraud",
          to: "asset",
          kind: "message",
          title: "졸업 임박 통지 수신: 계좌양도 가중치 상향",
          detail:
            "asset 에이전트로부터 수만 씨의 졸업 예정일과 비자 만료 일정을 수신했습니다. residency_end_date 기준 D-60 구간에 진입함에 따라 detect_account_takeover의 가중치를 상향했습니다. 졸업 후 귀국을 앞둔 유학생 계좌는 환치기 중간 통장으로 악용될 위험이 높습니다. 한국-네팔 간 비공식 환치기 규모는 추산하기 어려우나 동남아시아 및 남아시아 경로 전체로는 연간 수천억 원 수준입니다.",
        },
        {
          phase: "exit",
          t: 92,
          actor: "fraud",
          to: "fraud",
          kind: "tool",
          title: "비등록 환치기 송금 시도 차단",
          detail:
            "졸업 직전, 미등록 환전 브로커를 통한 네팔 대규모 송금 시도가 감지됐습니다. detect_account_takeover가 신규 수취인과 비정상 금액을 포착했습니다. 외국환거래법상 미신고 해외 송금은 형사 처벌 대상입니다. 거래를 홀딩하고 합법 송금 경로(은행 전신환)를 안내했습니다.",
          tool: "detect_account_takeover",
          card: {
            icon: "🔒",
            head: "환치기 시도 차단 완료",
            body: "미등록 브로커 경로 송금을 탐지해 차단했습니다. 은행 공식 전신환 경로로 안전하게 송금할 수 있도록 연결했습니다.",
            metric: "한-베 환치기 연간 3,010억 차단 근거 적용",
          },
        },
      ],
    },
  };
})();
