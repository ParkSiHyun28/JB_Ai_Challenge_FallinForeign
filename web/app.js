/* LifeRoad 프론트 로직.
   백엔드(FastAPI) /personas /intro /chat(SSE)를 호출한다.
   streamlit rerun이 없으므로 모든 변화는 부분 DOM 조작이다 → 스크롤 점프 0.
*/

const API = window.API_BASE;

// 상태
let curPersona = "minh";
let curLang = "auto";
let lastReplyLang = "ko";         // 직전 답변 언어 (final 이벤트가 갱신)
let history = [];                 // [{role:"user"|"assistant", content}]
let completedTools = [];
let busy = false;
let chatGen = 0;                  // 대화 세대. resetChat마다 증가.
                                  // 언어/페르소나 전환 후 도착하는 이전 요청의 늦은 콜백이
                                  // 새 대화에 이전 언어 버블과 버튼을 끼워 넣는 것을 막는다.

// UI 문구 현지화. 답변 언어와 화면 부속 문구를 맞춰 한국어 혼용을 막는다.
const UI_TEXT = {
  ko: { select: "[선택]", placeholder: "질문을 입력하세요", end: "대화 종료하기" },
  en: { select: "[Selected]", placeholder: "Type your question", end: "End conversation" },
  vi: { select: "[Đã chọn]", placeholder: "Nhập câu hỏi của bạn", end: "Kết thúc hội thoại" },
  ne: { select: "[छानिएको]", placeholder: "आफ्नो प्रश्न लेख्नुहोस्", end: "कुराकानी अन्त्य गर्नुहोस्" },
};
function uiLang() {
  return curLang === "auto" ? lastReplyLang : curLang;
}
function uiText(key) {
  return (UI_TEXT[uiLang()] || UI_TEXT.ko)[key];
}

// DOM 핸들
const scrollEl = () => document.getElementById("chat-scroll");
const inputEl = () => document.getElementById("chat-input");
const sendBtn = () => document.getElementById("send-btn");

/* ---------- 유틸 ---------- */
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

// 마크다운 표는 좁은 채팅 폭에서 파이프(|)가 그대로 깨져 보인다.
// 2열(항목|값) 표는 '- 항목: 값' 불릿으로, 그 이상 열은 '- 셀 | 셀' 로 바꾼다.
// 구분선(|---|)과 헤더행(다음 줄이 구분선인 행)은 지운다.
function tableToBullets(src) {
  const lines = String(src == null ? "" : src).split("\n");
  const isRow = l => /^\s*\|.*\|\s*$/.test(l);
  const cellsOf = l => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(c => c.trim());
  const isSep = l => isRow(l) && cellsOf(l).every(c => /^:?-{2,}:?$/.test(c));
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (!isRow(l)) { out.push(l); continue; }
    if (isSep(l)) continue;                                   // 구분선 제거
    if (i + 1 < lines.length && isSep(lines[i + 1])) continue; // 헤더행 제거
    const cells = cellsOf(l);
    out.push(cells.length === 2 ? `- ${cells[0]}: ${cells[1]}` : `- ${cells.join(" | ")}`);
  }
  return out.join("\n");
}

// 가벼운 마크다운: ## 헤딩, **bold**, -/숫자 불릿. 표는 위에서 불릿으로 변환. 본문은 white-space:pre-wrap이라 줄바꿈은 CSS가 처리.
function mdInline(s) {
  s = tableToBullets(String(s == null ? "" : s));
  // 모델이 개행 없이 문장 끝에 '## 소제목'을 붙이는 경우가 있어 개행을 강제 삽입한다.
  s = s.replace(/([^\n\s#])[ \t]*(#{1,6}\s+)/g, "$1\n$2");
  // 3개 이상 연속 빈 줄은 1개로 접어 버블 안 여백 폭주를 막는다.
  const lines = esc(s).replace(/\n{3,}/g, "\n\n").split("\n");
  const out = lines.map(line => {
    // 헤딩(### / ## / #) → 굵은 소제목
    const h = line.match(/^\s*#{1,6}\s+(.*)$/);
    if (h) return `<span class="md-h">${h[1]}</span>`;
    // 불릿(- • *) → 점 스타일 행
    const li = line.match(/^\s*[-•*]\s+(.*)$/);
    if (li) return `<span class="md-li">${li[1]}</span>`;
    // 숫자 목록(1. 2)) → 번호 스타일 행
    const ol = line.match(/^\s*(\d{1,2})[.)]\s+(.*)$/);
    if (ol) return `<span class="md-li md-ol" data-n="${ol[1]}.">${ol[2]}</span>`;
    return line;
  });
  let html = out.join("\n");
  // 불릿/헤딩은 display:block이라 스스로 줄을 만든다. 주변 개행(빈 줄 포함)을
  // 제거해 pre-wrap 이중 여백을 막고, 간격은 CSS 마진이 담당한다.
  html = html.replace(/\n{1,2}(<span class="md-(?:h|li))/g, "$1");
  html = html.replace(/(<\/span>)\n{1,2}/g, "$1");
  // 문단 사이 빈 줄은 고정 높이 간격으로 치환해 읽는 리듬을 일정하게 만든다.
  html = html.replace(/\n\n/g, '<span class="pgap"></span>');
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  return html;
}

function scrollToEl(el) {
  if (el) el.scrollIntoView({ block: "start", behavior: "smooth" });
}

/* ---------- 페르소나 카드 ---------- */
function visaBadge(status, label) {
  if (!label) return "";
  const cls = { ok: "ok", renewal_window: "renewal", expired: "expired", no_renewal: "no_renewal" }[status] || "no_renewal";
  return `<span class="visa-badge ${cls}">${esc(label)}</span>`;
}
function visaStatusLabel(status, monthsLeft) {
  if (status === "expired") return "만료됨";
  if (status === "renewal_window") return `갱신 신청 가능 (${monthsLeft}개월 남음)`;
  if (status === "no_renewal") return "갱신 불필요";
  if (status === "ok") return `${monthsLeft}개월 남음`;
  return "";
}
function renderPersona(p) {
  // 듀얼 스테이지: 페르소나는 민 1명 고정, 상단 스트립에 압축 표기한다.
  const statusLabel = visaStatusLabel(p.visaStatus || "", p.visaMonthsLeft || 0);
  document.getElementById("persona-strip").innerHTML = `
    <span class="ps-name">${esc(p.name)}${p.en ? `<span class="en">${esc(p.en)}</span>` : ""}</span>
    ${p.visa ? `<span class="ps-chip">${esc(p.visa)}</span>` : ""}
    <span class="ps-sep"></span>
    <span class="ps-item"><small>국적</small>${esc(p.nationality) || "-"}</span>
    <span class="ps-item"><small>입국</small>${esc(p.entry) || "-"}</span>
    <span class="ps-item"><small>출국 예정</small>${p.exit ? esc(p.exit) : "-"}</span>
    <span class="ps-item"><small>비자 만료</small>${p.visaExpiry ? esc(p.visaExpiry) : "-"}</span>
    ${p.visaStatus ? visaBadge(p.visaStatus, statusLabel) : ""}`;
}

let personaData = {};   // id -> card
async function loadPersonas() {
  try {
    const r = await fetch(`${API}/personas`);
    const list = await r.json();
    list.forEach(p => { personaData[p.id] = p; });
    if (personaData[curPersona]) renderPersona(personaData[curPersona]);
  } catch (e) {
    console.error("personas 로드 실패", e);
  }
}

function markSynced() {
  const pill = document.getElementById("sync-pill");
  pill.classList.add("live");
  document.getElementById("sync-text").textContent = "실시간 동기화 중";
}

/* ---------- 메시지 빌더 ---------- */
function addUserBubble(text) {
  const wrap = document.createElement("div");
  wrap.className = "msg msg-user";
  wrap.innerHTML = `<div class="bubble">${esc(text)}</div>`;
  scrollEl().appendChild(wrap);
  return wrap;
}

function addAiBubble() {
  const wrap = document.createElement("div");
  wrap.className = "msg msg-ai";
  // 카톡식: 왼쪽에 서비스 프로필(LR 모노그램) + 이름 + 말풍선. 이모지 아바타는 쓰지 않는다.
  wrap.innerHTML = `
    <div class="ai-head"><span class="ai-ava">LR</span><span class="ai-name">My LifeRoad</span></div>
    <div class="bubble"><span class="cursor"></span></div>`;
  scrollEl().appendChild(wrap);
  return wrap;
}

function setBubbleText(bubble, text, streaming) {
  bubble.innerHTML = mdInline(text) + (streaming ? `<span class="cursor"></span>` : "");
}

function collectCard(step, bucket) {
  // 처리 과정 패널은 표시하지 않는다. tool 카드는 모아뒀다가 답변이 끝난 뒤 그린다.
  // tool 실행 시점에 카드를 먼저 그리면 답변보다 카드가 앞서 떠 "설계된 듯"한 인상을 준다.
  if (step.card) bucket.push(step.card);
}

function addCard(aiWrap, card) {
  const el = document.createElement("div");
  el.className = "lr-card";
  // download_url 은 백엔드가 PDF를 만들어 카드에 실어 보낸다. 정적 서버(8000)가 아니라
  // 백엔드(API_BASE, 8001)의 /download 로 연결해야 파일이 열린다.
  const dl = card.download_url
    ? `<a class="cdl" href="${esc(API + card.download_url)}" target="_blank" rel="noopener" download>신청서 PDF 내려받기</a>`
    : "";
  el.innerHTML =
    `<div class="chead">${esc(card.head || "")}</div>` +
    (card.body ? `<div class="cbody">${esc(card.body)}</div>` : "") +
    (card.metric ? `<div class="cmetric">${esc(card.metric)}</div>` : "") +
    dl;
  aiWrap.appendChild(el);
}

function addActions(labels, header, isDone, doneCaption) {
  const wrap = document.createElement("div");
  wrap.className = "actions";
  if (labels && labels.length) {
    if (header) {
      const h = document.createElement("div");
      h.className = "ahead";
      h.textContent = header;
      wrap.appendChild(h);
    }
    labels.forEach(label => {
      const b = document.createElement("button");
      b.className = "act-btn";
      b.textContent = label;
      b.onclick = () => onActionClick(label);
      wrap.appendChild(b);
    });
  }
  if (isDone) {
    if (doneCaption && (!labels || !labels.length)) {
      const c = document.createElement("div");
      c.className = "done-caption";
      c.textContent = doneCaption;
      wrap.appendChild(c);
    }
    const end = document.createElement("button");
    end.className = "act-btn end";
    end.textContent = uiText("end");
    end.onclick = resetChat;
    wrap.appendChild(end);
  }
  scrollEl().appendChild(wrap);
}

/* ---------- SSE 대화 ---------- */
async function sendTurn(intent, isAction, displayText) {
  if (busy) return;
  busy = true;
  const gen = chatGen;
  setSendEnabled(false);

  // 1. 사용자 버블 추가 + 그 위치로 1회 스크롤(점프 왕복 없음)
  const userWrap = addUserBubble(displayText != null ? displayText : intent);
  scrollToEl(userWrap);
  history.push({ role: "user", content: intent });

  // 2. 빈 AI 버블
  const aiWrap = addAiBubble();
  const bubble = aiWrap.querySelector(".bubble");

  let acc = "";
  let finalBody = null;
  const cards = [];   // tool 카드를 모아 답변이 끝난 뒤 그린다.

  try {
    const resp = await fetch(`${API}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        persona: curPersona,
        lang: isAction ? resolveActionLang() : curLang,
        intent,
        is_action: isAction,
        history: history.slice(0, -1).slice(-6),  // 직전 발화 제외, 최근 6개
        completed_tools: completedTools,
      }),
    });

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      if (gen !== chatGen) { reader.cancel(); busy = false; setSendEnabled(true); return; }
      buf += decoder.decode(value, { stream: true });
      // SSE 이벤트 경계는 빈 줄. CRLF(\r\n\r\n)와 LF(\n\n) 둘 다 처리한다.
      let m;
      while ((m = buf.match(/\r?\n\r?\n/))) {
        const sep = m.index;
        const raw = buf.slice(0, sep);
        buf = buf.slice(sep + m[0].length);
        handleSSE(raw, { aiWrap, bubble, cards, onToken: t => { acc += t; }, onFinal: f => { finalBody = f; } });
        if (acc) setBubbleText(bubble, stripMarkers(acc), true);
      }
    }
  } catch (e) {
    console.error("chat 실패", e);
    setBubbleText(bubble, "일시적인 오류가 발생했습니다. 다시 시도해 주세요.", false);
    busy = false;
    setSendEnabled(true);
    return;
  }

  // 3. final 본문 확정
  if (gen !== chatGen) { busy = false; setSendEnabled(true); return; }
  const body = finalBody ? finalBody.body : stripMarkers(acc);
  setBubbleText(bubble, body, false);
  history.push({ role: "assistant", content: body });

  // 답변이 끝난 뒤에야 근거 카드를 그린다(판단→근거 순서).
  // tool 카드 텍스트는 한국어 원본이다. 답변 언어가 한국어가 아니면 본문이
  // 이미 그 언어로 같은 내용을 설명하므로, 한국어 카드를 숨겨 언어 혼용을 막는다.
  const replyLang = finalBody && finalBody.lang ? finalBody.lang : (curLang === "auto" ? "ko" : curLang);
  if (replyLang === "ko") {
    cards.forEach(c => addCard(aiWrap, c));
  }

  if (finalBody) {
    if (finalBody.lang) {
      lastReplyLang = finalBody.lang;
      inputEl().placeholder = uiText("placeholder");
    }
    if (finalBody.completed_tools) completedTools = finalBody.completed_tools;
    addActions(
      finalBody.next_labels,
      finalBody.next_labels && finalBody.next_labels.length ? finalBody.header : null,
      finalBody.is_done,
      finalBody.done_caption
    );
  }

  busy = false;
  setSendEnabled(true);
}

function handleSSE(raw, ctx) {
  let event = "message";
  let dataStr = "";
  raw.split("\n").forEach(line => {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataStr += line.slice(5).trim();
  });
  if (!dataStr) return;
  let data;
  try { data = JSON.parse(dataStr); } catch (e) { return; }

  if (event === "token") {
    ctx.onToken(data.t || "");
  } else if (event === "step") {
    markSynced();
    collectCard(data, ctx.cards);
  } else if (event === "final") {
    ctx.onFinal(data);
  } else if (event === "error") {
    setBubbleText(ctx.bubble, data.message || "오류가 발생했습니다.", false);
  }
}

// 스트리밍 중 마커/부분마커 숨김(백엔드 final이 권위)
function stripMarkers(text) {
  if (!text) return text;
  const ni = text.indexOf("<<NEXT>>");
  if (ni >= 0) text = text.slice(0, ni).trimEnd();
  text = text.replace(/<<DONE>>/g, "");
  const partials = ["<<NEXT>", "<<NEXT", "<<NEX", "<<NE", "<<N", "<<DONE", "<<DON", "<<DO", "<<D", "<<"];
  for (const p of partials) {
    if (text.endsWith(p)) return text.slice(0, -p.length).trimEnd();
  }
  return text;
}

function resolveActionLang() {
  // 버튼 클릭은 직전 답변 언어를 따른다. auto면 final 이벤트가 알려준 직전 답변 언어를 쓴다.
  // (예전엔 auto -> ko 고정이라 영어 대화 중 버튼을 누르면 한국어로 돌아오는 버그가 있었다.)
  return curLang === "auto" ? lastReplyLang : curLang;
}

function onActionClick(label) {
  sendTurn(label, true, `${uiText("select")} ${label}`);
}

/* ---------- 입력창 ---------- */
function setSendEnabled(on) {
  sendBtn().disabled = !on;
  inputEl().disabled = !on;
}
function submitInput() {
  const v = inputEl().value.trim();
  if (!v || busy) return;
  inputEl().value = "";
  sendTurn(v, false, null);
}

/* ---------- 인트로 ---------- */
async function loadIntro() {
  const gen = chatGen;
  const aiWrap = addAiBubble();
  const bubble = aiWrap.querySelector(".bubble");
  try {
    const r = await fetch(`${API}/intro?persona=${curPersona}&lang=${curLang}`);
    const data = await r.json();
    if (gen !== chatGen) return;  // 그 사이 대화가 리셋됨 - 낡은 응답 폐기
    setBubbleText(bubble, data.body, false);
    history.push({ role: "assistant", content: data.body });
    markSynced();
    addActions(data.labels, data.header, false, null);
  } catch (e) {
    if (gen !== chatGen) return;
    setBubbleText(bubble, "인트로를 불러오지 못했습니다.", false);
  }
}

function resetChat() {
  chatGen += 1;  // 진행 중인 이전 요청 콜백 무효화
  scrollEl().innerHTML = "";
  history = [];
  completedTools = [];
  busy = false;
  setSendEnabled(true);
  loadIntro();
}

/* ---------- 컨트롤 전환 ---------- */
function applyControls() {
  curPersona = document.getElementById("persona-select").value;
  curLang = document.getElementById("lang-select").value;
  lastReplyLang = curLang === "auto" ? "ko" : curLang;
  inputEl().placeholder = uiText("placeholder");
  if (personaData[curPersona]) renderPersona(personaData[curPersona]);
  // 동기화 핀 초기화
  const pill = document.getElementById("sync-pill");
  pill.classList.remove("live");
  document.getElementById("sync-text").textContent = "앱 준비 중";
  resetChat();
}

/* ---------- 관점 모드 (고객=폰 / 기업=관제) ----------
   자산관리+서류행정 에이전트는 고객이 만나는 앱 화면, 이상탐지 에이전트는
   은행 내부 관제 화면이다. 발표에서 이 관점 이동이 명확히 보이도록
   전환 시 오버레이 문구 + 배경 전환으로 연출한다. */

const duoEl = () => document.getElementById("duo");
let curMode = "customer";
let modeSwitching = false;

const MODE_COPY = {
  customer: {
    title: "고객 관점 - My LifeRoad 앱",
    sub: "외국인 고객이 직접 만나는 화면입니다 (자산관리, 서류행정 에이전트)",
  },
  bank: {
    title: "기업 관점 - 은행 이상거래 관제",
    sub: "같은 고객을 은행 내부에서 지키는 화면입니다 (이상탐지 에이전트)",
  },
};

function applyMode(mode) {
  curMode = mode;
  duoEl().classList.toggle("mode-customer", mode === "customer");
  duoEl().classList.toggle("mode-bank", mode === "bank");
  document.querySelectorAll("#mode-seg button").forEach(b =>
    b.classList.toggle("on", b.dataset.mode === mode));
  // 관제 콘솔(iframe)은 기업 관점에 처음 진입할 때 지연 로드한다.
  if (mode === "bank") {
    const fr = document.getElementById("fraud-frame");
    if (!fr.src && window.FRAUD_CONSOLE_URL) fr.src = window.FRAUD_CONSOLE_URL;
  }
}

function setMode(mode, done) {
  // 오버레이가 정점일 때 화면을 갈아끼워 전환 순간을 또렷하게 만든다.
  if (modeSwitching || mode === curMode) { if (done) done(); return; }
  modeSwitching = true;
  const ov = document.getElementById("mode-overlay");
  document.getElementById("mo-title").textContent = MODE_COPY[mode].title;
  document.getElementById("mo-sub").textContent = MODE_COPY[mode].sub;
  ov.classList.add("show");
  setTimeout(() => applyMode(mode), 550);
  setTimeout(() => {
    ov.classList.remove("show");
    modeSwitching = false;
    if (done) done();
  }, 1500);
}

function initMode() {
  document.querySelectorAll("#mode-seg button").forEach(b =>
    b.addEventListener("click", () => setMode(b.dataset.mode)));
  // 발표자 단축키: 1=고객 관점, 2=기업 관점, F=계좌양도 탐지 시나리오
  document.addEventListener("keydown", e => {
    const t = e.target.tagName;
    if (t === "INPUT" || t === "TEXTAREA" || t === "SELECT") return;
    if (e.key === "1") setMode("customer");
    if (e.key === "2") setMode("bank");
    if (e.key === "f" || e.key === "F") runFraudScenario();
  });
}

/* ---------- 크로스오버 (기업 관점 → 고객 관점 본인확인 푸시) ----------
   기업 관점 화면은 fraud_guard/의 실제 FDS 콘솔(iframe)이 담당한다.
   F 키는 관점을 잇는 연출만 맡는다: 콘솔에서 탐지와 보류를 보여준 발표자가
   F를 누르면 고객 관점으로 전환되며 모국어 본인확인 푸시가 도착한다. */

let fraudBusy = false;   // 크로스오버 진행 중 중복 실행 가드

// 크로스오버 푸시 문구 (답변 언어를 따라간다)
const FRAUD_TEXT = {
  ko: {
    push: "[보안 알림] 방금 새 기기에서 940만 원 이체 시도가 감지되어 거래를 잠시 보류했습니다. 등록되지 않은 기기이고, 출국을 앞둔 시점의 전액 이체 패턴이라 직접 확인이 필요합니다.\n\n본인이 진행하신 거래인가요?",
    self: "네, 본인이 한 거래입니다",
    block: "아니요, 차단해 주세요",
    blockMsg: "이체를 차단하고 계좌를 안전 모드로 전환했습니다.\n\n- 새 기기의 접근 권한을 즉시 해지했습니다\n- 보류된 940만 원은 계좌에 안전하게 보관 중입니다\n- 금융감독원 신고 자료를 자동으로 준비해 두겠습니다\n\n출국 전 귀국 자금은 제가 계속 지켜보고 있으니 안심하세요.",
    selfMsg: "확인 감사합니다. 보류를 해제하고 이체를 정상 처리했습니다. 새 기기는 인증 기기로 등록해 두었습니다.",
    coercion: "누가 시켜서 한 거래예요",
    remote: "원격 앱을 설치하라고 했어요",
    coercionMsg: "고객님 안전이 최우선입니다. 이 거래는 보호 조치로 차단했습니다.\n\n- 지금 이 대화는 상대방에게 보이지 않습니다\n- 계좌를 안전 모드로 전환했습니다\n- 은행 보호팀과 경찰 연계 절차를 준비했습니다\n\n잠시 후 보호팀이 모국어로 연락드립니다. 어떤 불이익도 없으니 안심하세요.",
    remoteMsg: "원격제어 앱 피해가 의심됩니다. 지금 그 앱을 삭제하고 휴대폰을 잠시 비행기 모드로 두세요.\n\n- 이 거래는 보호 조치로 차단했습니다\n- 새 기기의 접근 권한을 모두 해지했습니다\n- 계좌를 안전 모드로 전환했습니다\n\n보호팀이 곧 모국어로 연락드립니다.",
    replySelf: "네 제가 한 거래 맞습니다. 본인 거래입니다.",
    replyBlock: "제가 한 거래 아닙니다. 모르는 거래입니다.",
    replyCoercion: "누가 시켰습니다. 말하지 말라고 했습니다.",
    replyRemote: "원격 앱을 설치하라고 해서 설치했습니다.",
  },
  en: {
    push: "[Security Alert] A transfer of KRW 9,400,000 from a new device was just detected and placed on hold. The device is unregistered, and a full-balance transfer right before your departure matches a takeover pattern.\n\nDid you make this transfer yourself?",
    self: "Yes, this was me",
    block: "No, block it",
    blockMsg: "The transfer has been blocked and your account is now in safe mode.\n\n- Access from the new device was revoked immediately\n- The held KRW 9,400,000 remains safely in your account\n- I will prepare the financial fraud report for you\n\nI will keep watching your funds until your departure.",
    selfMsg: "Thank you for confirming. The hold has been released and the transfer was processed. The new device is now registered as trusted.",
    coercion: "Someone told me to do it",
    remote: "I was told to install an app",
    coercionMsg: "Your safety comes first. This transfer has been blocked as a protective measure.\n\n- This conversation is not visible to anyone else\n- Your account is now in safe mode\n- Our protection team and police liaison are ready\n\nThe protection team will contact you in your language shortly. You will face no penalty.",
    remoteMsg: "A remote-control app scam is suspected. Please delete that app now and switch your phone to airplane mode for a moment.\n\n- This transfer has been blocked as a protective measure\n- All access from the new device was revoked\n- Your account is now in safe mode\n\nThe protection team will contact you shortly.",
    replySelf: "Yes, I did this transfer myself.",
    replyBlock: "That transfer was not me. I don't know this transaction.",
    replyCoercion: "Someone told me to send it and said don't tell the bank.",
    replyRemote: "They made me install a remote control app.",
  },
  vi: {
    push: "[Cảnh báo bảo mật] Vừa phát hiện lệnh chuyển KRW 9,400,000 từ thiết bị mới và giao dịch đã được tạm giữ. Thiết bị chưa đăng ký, và việc chuyển toàn bộ số dư ngay trước khi xuất cảnh trùng với mẫu chiếm đoạt tài khoản.\n\nCó phải chính bạn thực hiện giao dịch này không?",
    self: "Đúng, là tôi thực hiện",
    block: "Không phải tôi, hãy chặn lại",
    blockMsg: "Giao dịch đã bị chặn và tài khoản chuyển sang chế độ an toàn.\n\n- Quyền truy cập của thiết bị mới đã bị thu hồi ngay\n- KRW 9,400,000 vẫn được giữ an toàn trong tài khoản\n- Tôi sẽ chuẩn bị hồ sơ trình báo gian lận cho bạn\n\nTôi sẽ tiếp tục bảo vệ số tiền của bạn cho đến ngày xuất cảnh.",
    selfMsg: "Cảm ơn bạn đã xác nhận. Lệnh tạm giữ đã được gỡ và giao dịch được xử lý. Thiết bị mới đã được đăng ký là thiết bị tin cậy.",
    coercion: "Có người bảo tôi làm",
    remote: "Họ bảo tôi cài ứng dụng",
    coercionMsg: "An toàn của bạn là trên hết. Giao dịch này đã bị chặn để bảo vệ bạn.\n\n- Cuộc trò chuyện này không ai khác nhìn thấy\n- Tài khoản đã chuyển sang chế độ an toàn\n- Đội bảo vệ khách hàng và cảnh sát đã sẵn sàng hỗ trợ\n\nĐội bảo vệ sẽ liên hệ bằng tiếng Việt ngay. Bạn sẽ không gặp bất lợi nào.",
    remoteMsg: "Nghi ngờ lừa đảo bằng ứng dụng điều khiển từ xa. Hãy xóa ứng dụng đó ngay và bật chế độ máy bay trong giây lát.\n\n- Giao dịch này đã bị chặn để bảo vệ bạn\n- Mọi quyền truy cập của thiết bị mới đã bị thu hồi\n- Tài khoản đã chuyển sang chế độ an toàn\n\nĐội bảo vệ sẽ liên hệ với bạn ngay.",
    replySelf: "Đúng, tôi đã thực hiện giao dịch này.",
    replyBlock: "Tôi không biết giao dịch này.",
    replyCoercion: "Có người bảo tôi làm và không được báo ngân hàng.",
    replyRemote: "Họ bảo tôi cài ứng dụng điều khiển từ xa.",
  },
  ne: {
    push: "[सुरक्षा सूचना] नयाँ डिभाइसबाट KRW 9,400,000 रकम पठाउने प्रयास भेटियो र कारोबार रोकिएको छ। डिभाइस दर्ता नगरिएको हो, र प्रस्थानअघि पूरै रकम सार्ने ढाँचा खाता कब्जासँग मिल्छ।\n\nके यो कारोबार तपाईं आफैले गर्नुभएको हो?",
    self: "हो, यो मैले गरेको हुँ",
    block: "होइन, रोक्नुहोस्",
    blockMsg: "कारोबार रोकियो र तपाईंको खाता सुरक्षित मोडमा राखियो।\n\n- नयाँ डिभाइसको पहुँच तुरुन्तै हटाइयो\n- रोकिएको KRW 9,400,000 खातामै सुरक्षित छ\n- ठगी उजुरीको कागजात म तयार गर्नेछु\n\nप्रस्थानसम्म तपाईंको रकम म निगरानी गरिरहनेछु।",
    selfMsg: "पुष्टि गर्नुभएकोमा धन्यवाद। रोक हटाइयो र कारोबार सम्पन्न भयो। नयाँ डिभाइस विश्वसनीय रूपमा दर्ता गरियो।",
    coercion: "कसैले भनेर गरेको हुँ",
    remote: "एप इन्स्टल गर्न लगाइयो",
    coercionMsg: "तपाईंको सुरक्षा सबैभन्दा पहिलो हो। यो कारोबार सुरक्षाका लागि रोकियो।\n\n- यो कुराकानी अरू कसैले देख्दैन\n- खाता सुरक्षित मोडमा राखियो\n- बैंक सुरक्षा टोली र प्रहरी सहयोग तयार छ\n\nसुरक्षा टोलीले चाँडै नेपालीमा सम्पर्क गर्नेछ। तपाईंलाई कुनै हानि हुनेछैन।",
    remoteMsg: "रिमोट कन्ट्रोल एप ठगीको शंका छ। अहिले नै त्यो एप मेटाउनुहोस् र फोन केही बेर एयरप्लेन मोडमा राख्नुहोस्।\n\n- यो कारोबार सुरक्षाका लागि रोकियो\n- नयाँ डिभाइसको सबै पहुँच हटाइयो\n- खाता सुरक्षित मोडमा राखियो\n\nसुरक्षा टोलीले चाँडै सम्पर्क गर्नेछ।",
    replySelf: "हो, यो मैले गरेको हुँ।",
    replyBlock: "यो कारोबार थाहा छैन।",
    replyCoercion: "कसैले धम्की दियो। नभन्न भन्यो।",
    replyRemote: "एप इन्स्टल गर्न लगाइयो।",
  },
};
function fraudText(key) {
  return (FRAUD_TEXT[uiLang()] || FRAUD_TEXT.ko)[key];
}

function runFraudScenario() {
  if (fraudBusy || busy) return;
  fraudBusy = true;
  // 은행이 탐지하고 보류하고(기업 관점, 콘솔에서 발표자가 설명) 고객에게 확인을
  // 구하는(고객 관점) 흐름. 어느 관점에 있든 고객 관점으로 전환하며 푸시가 온다.
  // 진짜 엔진의 대표 케이스 점수를 미리 받아 카드에 반영한다(실패해도 흐름 유지).
  window._fraudHeroScore = null;
  fetch(`${window.API_BASE}/fraud/feed?persona_id=minh`)
    .then(r => r.json())
    .then(d => { if (d && d.hero) window._fraudHeroScore = d.hero.score; })
    .catch(() => {});
  setMode("customer", () => showPushBanner());
}

// 고객 답변을 백엔드 의도분류(엔진)로 보고한다. 관제 콘솔이 폴링으로 반영한다.
// 실패해도 폰 데모 흐름은 그대로 간다(라이브 안전망).
function reportFraudReply(kind) {
  const key = "reply" + kind.charAt(0).toUpperCase() + kind.slice(1);
  const reply = fraudText(key) || fraudText(kind);
  fetch(`${window.API_BASE}/fraud/reply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ persona_id: "minh", reply }),
  }).catch(() => {});
}

// iOS식 알림 배너: 폰 화면 상단에 슬라이드인 → 잠시 머문 뒤 → 채팅으로 이어진다
function showPushBanner() {
  const gen = chatGen;
  const screen = document.querySelector(".pane-phone .screen");
  const firstLine = fraudText("push").split("\n")[0];

  const banner = document.createElement("div");
  banner.className = "push-banner";
  banner.innerHTML = `
    <span class="pb-ava">LR</span>
    <span class="pb-txt">
      <span class="pb-title">My LifeRoad<small>${uiLang() === "ko" ? "지금" : "now"}</small></span>
      <span class="pb-body">${esc(firstLine)}</span>
    </span>`;
  screen.appendChild(banner);
  requestAnimationFrame(() => requestAnimationFrame(() => banner.classList.add("show")));

  // 2.6초 노출 후 올라가며 사라지고, 채팅 버블로 이어진다
  setTimeout(() => banner.classList.remove("show"), 2600);
  setTimeout(() => {
    banner.remove();
    if (gen === chatGen) injectSecurityPush();
  }, 3150);
}

function injectSecurityPush() {
  const gen = chatGen;
  const pushMsg = fraudText("push");

  const aiWrap = addAiBubble();
  setBubbleText(aiWrap.querySelector(".bubble"), pushMsg, false);
  history.push({ role: "assistant", content: pushMsg });

  const wrap = document.createElement("div");
  wrap.className = "actions";
  // 답변 4종: 본인 확인 / 거래 부인 / 강요 정황 / 원격제어 정황.
  // 뒤 2개는 엔진의 안전신호 결정론 탐지(보호 조치 상신)를 시연한다.
  ["self", "block", "coercion", "remote"].forEach((key) => {
    const b = document.createElement("button");
    b.className = "act-btn";
    b.textContent = fraudText(key);
    b.onclick = () => { if (gen === chatGen) { wrap.remove(); onFraudAnswer(key); } };
    wrap.appendChild(b);
  });
  scrollEl().appendChild(wrap);
  scrollEl().scrollTop = scrollEl().scrollHeight;
}

function onFraudAnswer(kind) {
  const label = fraudText(kind);
  addUserBubble(label);
  history.push({ role: "user", content: label });

  // 엔진 의도분류로 보고(관제 콘솔이 고객 응답 카드로 표시). 실패해도 진행.
  reportFraudReply(kind);

  const aiWrap = addAiBubble();
  const msg = fraudText(kind + "Msg");
  setBubbleText(aiWrap.querySelector(".bubble"), msg, false);
  history.push({ role: "assistant", content: msg });

  if (uiLang() === "ko") {
    const score = window._fraudHeroScore;
    const metricScore = score != null ? score : 100;
    if (kind === "block") {
      addCard(aiWrap, {
        head: "이체 차단 완료 - 940만 원 보호",
        body: "신규 기기 접근 해지, 계좌 안전 모드 전환, 신고 자료 자동 준비",
        metric: `위험 점수 ${metricScore} → 차단 확정`,
      });
    } else if (kind === "coercion" || kind === "remote") {
      addCard(aiWrap, {
        head: "고객 보호 조치 발동",
        body: "거래 차단, 새 기기 접근 해지, 보호팀과 경찰 연계 준비",
        metric: kind === "remote" ? "원격제어 정황 감지" : "강요 정황 감지",
      });
    }
  }
  scrollEl().scrollTop = scrollEl().scrollHeight;
  fraudBusy = false;
}

/* ---------- 초기화 ---------- */
async function init() {
  document.getElementById("persona-select").addEventListener("change", applyControls);
  document.getElementById("lang-select").addEventListener("change", applyControls);
  sendBtn().addEventListener("click", submitInput);
  inputEl().addEventListener("keydown", e => { if (e.key === "Enter") submitInput(); });

  initMode();

  await loadPersonas();
  await loadIntro();
}

document.addEventListener("DOMContentLoaded", init);
