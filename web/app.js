/* LifeRoad 프론트 로직.
   백엔드(FastAPI) /personas /intro /chat(SSE)를 호출한다.
   streamlit rerun이 없으므로 모든 변화는 부분 DOM 조작이다 → 스크롤 점프 0.
*/

const API = window.API_BASE;

// 상태
let curPersona = "minh";
let curLang = "auto";
let history = [];                 // [{role:"user"|"assistant", content}]
let completedTools = [];
let busy = false;

// DOM 핸들
const scrollEl = () => document.getElementById("chat-scroll");
const inputEl = () => document.getElementById("chat-input");
const sendBtn = () => document.getElementById("send-btn");

/* ---------- 유틸 ---------- */
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

// 가벼운 마크다운: ## 헤딩, **bold**, - 불릿. 본문은 white-space:pre-wrap이라 줄바꿈은 CSS가 처리.
function mdInline(s) {
  const lines = esc(s).split("\n");
  const out = lines.map(line => {
    // 헤딩(### / ## / #) → 굵은 소제목
    const h = line.match(/^\s*#{1,6}\s+(.*)$/);
    if (h) return `<span class="md-h">${h[1]}</span>`;
    return line;
  });
  let html = out.join("\n");
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
  const exitVal = p.exit ? esc(p.exit) : "—";
  const expiryVal = p.visaExpiry ? esc(p.visaExpiry) : "—";
  const renewalVal = p.visaRenewal ? esc(p.visaRenewal) : "—";
  const statusLabel = visaStatusLabel(p.visaStatus || "", p.visaMonthsLeft || 0);
  const statusBadge = p.visaStatus
    ? `<br><span style="margin-top:3px;display:inline-block">${visaBadge(p.visaStatus, statusLabel)}</span>`
    : "";
  document.getElementById("persona-card").innerHTML = `
    <div class="persona-top">
      <div class="id-meta">
        <div class="id-name">${esc(p.name)}${p.en ? `<span class="en">${esc(p.en)}</span>` : ""}</div>
        ${p.code ? `<span class="id-code">${esc(p.code)}</span>` : ""}
      </div>
      <div class="fields">
        <div class="field"><div class="flabel">국적</div><div class="fval">${esc(p.nationality) || "—"}</div></div>
        <div class="field"><div class="flabel">비자</div><div class="fval">${esc(p.visa) || "—"}</div></div>
        <div class="field"><div class="flabel">입국</div><div class="fval">${esc(p.entry) || "—"}</div></div>
        <div class="field"><div class="flabel">출국 예정</div><div class="fval">${exitVal}</div></div>
        <div class="field"><div class="flabel">비자 만료</div><div class="fval">${expiryVal}${statusBadge}</div></div>
        <div class="field"><div class="flabel">갱신 신청</div><div class="fval">${renewalVal}</div></div>
      </div>
    </div>
    ${p.note ? `<div class="persona-note"><span class="nlabel">시나리오</span><span class="ntext">${esc(p.note)}</span></div>` : ""}`;
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
  // 카톡식: 왼쪽에 에이전트 아바타(이모지) + 이름 + 말풍선.
  wrap.innerHTML = `
    <div class="ai-head"><span class="ai-ava">🤖</span><span class="ai-name">LifeRoad AI</span></div>
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
  el.innerHTML =
    `<div class="chead">${esc(card.head || "")}</div>` +
    (card.body ? `<div class="cbody">${esc(card.body)}</div>` : "") +
    (card.metric ? `<div class="cmetric">${esc(card.metric)}</div>` : "");
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
    end.textContent = "대화 종료하기";
    end.onclick = resetChat;
    wrap.appendChild(end);
  }
  scrollEl().appendChild(wrap);
}

/* ---------- SSE 대화 ---------- */
async function sendTurn(intent, isAction, displayText) {
  if (busy) return;
  busy = true;
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
  // 버튼 클릭은 직전 답변 언어를 따른다. 현재 lang 설정을 그대로 보내되 auto면 ko.
  return curLang === "auto" ? "ko" : curLang;
}

function onActionClick(label) {
  sendTurn(label, true, `[선택] ${label}`);
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
  const aiWrap = addAiBubble();
  const bubble = aiWrap.querySelector(".bubble");
  try {
    const r = await fetch(`${API}/intro?persona=${curPersona}&lang=${curLang}`);
    const data = await r.json();
    setBubbleText(bubble, data.body, false);
    history.push({ role: "assistant", content: data.body });
    markSynced();
    addActions(data.labels, data.header, false, null);
  } catch (e) {
    setBubbleText(bubble, "인트로를 불러오지 못했습니다.", false);
  }
}

function resetChat() {
  scrollEl().innerHTML = "";
  history = [];
  completedTools = [];
  loadIntro();
}

/* ---------- 컨트롤 전환 ---------- */
function applyControls() {
  curPersona = document.getElementById("persona-select").value;
  curLang = document.getElementById("lang-select").value;
  if (personaData[curPersona]) renderPersona(personaData[curPersona]);
  // 동기화 핀 초기화
  const pill = document.getElementById("sync-pill");
  pill.classList.remove("live");
  document.getElementById("sync-text").textContent = "앱 준비 중";
  resetChat();
}

/* ---------- 초기화 ---------- */
async function init() {
  document.getElementById("persona-select").addEventListener("change", applyControls);
  document.getElementById("lang-select").addEventListener("change", applyControls);
  sendBtn().addEventListener("click", submitInput);
  inputEl().addEventListener("keydown", e => { if (e.key === "Enter") submitInput(); });

  await loadPersonas();
  await loadIntro();
}

document.addEventListener("DOMContentLoaded", init);
