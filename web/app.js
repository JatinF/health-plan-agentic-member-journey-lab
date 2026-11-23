const journeys = [
  ["Benefits", "Is physical therapy covered, and how many visits?"],
  ["Claims", "Why do I owe $85 for my urgent care visit?"],
  ["Partial claim", "Why was my claim partially paid?"],
  ["Care", "Find in-network cardiology options."],
  ["Billing review", "Open a billing review request."],
  ["Voice claim", "Can you explain my latest claim?"],
];

const actorSelect = document.querySelector("#actor");
const thread = document.querySelector("#thread");
const question = document.querySelector("#question");
const speechState = document.querySelector("#speech-state");
const cases = document.querySelector("#cases");

function dollars(cents) {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  const whole = Math.floor(abs / 100);
  const rem = abs % 100;
  return rem === 0 ? `${sign}$${whole}` : `${sign}$${whole}.${String(rem).padStart(2, "0")}`;
}

function token() {
  return actorSelect.value;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token()}`,
      ...(options.headers || {}),
    },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || response.statusText);
  }
  return body;
}

function addBubble(title, text, extra) {
  const block = document.createElement("article");
  block.className = "bubble";
  const who = document.createElement("p");
  who.className = "who";
  who.textContent = title;
  const answer = document.createElement("div");
  answer.className = "answer";
  answer.textContent = text;
  block.append(who, answer);
  if (extra) block.append(extra);
  thread.prepend(block);
}

function computedNode(computed) {
  if (!computed || computed.member_owes_cents == null) return null;
  const sum = computed.copay_cents + computed.deductible_cents + computed.coinsurance_cents;
  const row = document.createElement("div");
  row.className = "math";
  const chip = document.createElement("span");
  chip.className = "chip";
  chip.textContent = sum === computed.member_owes_cents
    ? `${dollars(computed.copay_cents)} copay + ${dollars(computed.deductible_cents)} deductible + ${dollars(computed.coinsurance_cents)} coinsurance = ${dollars(computed.member_owes_cents)}`
    : "The returned amounts do not add up. The page will not show a total.";
  row.append(chip);
  return row;
}

function renderResult(title, body) {
  const extra = document.createElement("div");
  const math = computedNode(body.computed);
  if (math) extra.append(math);
  if (body.pending_action) {
    const pending = document.createElement("p");
    pending.className = "pending";
    pending.textContent = `Approval required before case ${body.pending_action.case_id} opens.`;
    extra.append(pending);
  }
  const note = document.createElement("p");
  note.className = "disclaimer";
  note.textContent = `${body.disclaimer} Narration: ${body.narration}. Server speech recognizer: ${body.server_speech_recognizer}.`;
  extra.append(note);
  addBubble(title, body.answer, extra);
}

async function send(path, payload, title) {
  addBubble("Member", payload.question || payload.transcript, null);
  try {
    const body = await api(path, { method: "POST", body: JSON.stringify(payload) });
    renderResult(title, body);
    await loadCases();
  } catch (error) {
    addBubble("MemberCare Assistant", error.message, null);
  }
}

async function loadCases() {
  cases.replaceChildren();
  try {
    const body = await api("/api/cases");
    if (!body.cases.length) {
      cases.textContent = "No billing reviews for this actor.";
      return;
    }
    for (const item of body.cases) {
      const card = document.createElement("article");
      card.className = "bubble";
      const title = document.createElement("strong");
      title.textContent = `${item.id} · ${item.status}`;
      const detail = document.createElement("p");
      detail.textContent = `EOB ${item.eob_id}`;
      card.append(title, detail);
      if (actorSelect.selectedOptions[0]?.dataset.role === "reviewer" && item.status === "pending_approval") {
        const row = document.createElement("div");
        row.className = "row";
        const approve = document.createElement("button");
        approve.className = "primary";
        approve.type = "button";
        approve.textContent = "Approve and open";
        approve.addEventListener("click", () => decide(item.id, "approve"));
        const reject = document.createElement("button");
        reject.className = "warn";
        reject.type = "button";
        reject.textContent = "Reject";
        reject.addEventListener("click", () => decide(item.id, "reject"));
        row.append(approve, reject);
        card.append(row);
      }
      cases.append(card);
    }
  } catch (error) {
    cases.textContent = error.message;
  }
}

async function decide(caseId, decision) {
  try {
    const body = await api(`/api/cases/${caseId}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision }),
    });
    renderResult("Reviewer", body);
    await loadCases();
  } catch (error) {
    addBubble("Reviewer", error.message, null);
  }
}

document.querySelector("#journeys").append(...journeys.map(([label, prompt]) => {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "journey";
  const name = document.createElement("strong");
  name.textContent = label;
  const text = document.createElement("span");
  text.textContent = prompt;
  button.append(name, text);
  button.addEventListener("click", () => {
    question.value = prompt;
    const path = label === "Voice claim" ? "/api/voice" : "/api/chat";
    const payload = label === "Voice claim" ? { transcript: prompt } : { question: prompt };
    send(path, payload, "MemberCare Assistant");
  });
  return button;
}));

document.querySelector("#composer").addEventListener("submit", (event) => {
  event.preventDefault();
  send("/api/chat", { question: question.value.trim() }, "MemberCare Assistant");
});

document.querySelector("#use-voice").addEventListener("click", () => {
  const transcript = question.value.trim();
  if (!transcript) return;
  send("/api/voice", { transcript }, "MemberCare Assistant");
});

const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
document.querySelector("#speak").addEventListener("click", () => {
  if (!Speech) {
    speechState.textContent = "This browser has no speech recognizer. Type the words you would say, then send the transcript.";
    question.focus();
    return;
  }
  const recognizer = new Speech();
  recognizer.lang = "en-US";
  recognizer.onresult = (event) => {
    question.value = event.results[0][0].transcript;
    speechState.textContent = "Transcript captured in the browser. Send it when you are ready. The server will treat it as text.";
  };
  recognizer.onerror = () => {
    speechState.textContent = "The browser recognizer did not return a transcript. You can type one instead.";
  };
  speechState.textContent = "Listening in the browser.";
  recognizer.start();
});

actorSelect.addEventListener("change", loadCases);

async function boot() {
  const body = await fetch("/api/demo/actors").then((response) => response.json());
  document.querySelector("#actor-warning").textContent = body.warning;
  for (const actor of body.actors) {
    const option = document.createElement("option");
    option.value = actor.token;
    option.dataset.role = actor.role;
    option.textContent = `${actor.display_name} · ${actor.role} · ${actor.tenant_id}`;
    actorSelect.append(option);
  }
  await loadCases();
}

boot();
