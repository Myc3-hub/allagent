/* 客户需求分析智能体 - 前端逻辑(vanilla JS,无构建) */
"use strict";

const $ = (sel) => document.querySelector(sel);

const state = {
  session: null,      // 当前会话(GET /api/sessions/{sid} 的数据)
  streaming: false,
  abort: null,
};

const PHASE_LABEL = { clarify: "需求澄清", research: "数据调研", confirm: "待确认", choose: "选择导出文件", task: "任务执行中", done: "已完成" };
const FILE_TYPES = [
  { key: "word", label: "Word 报告" },
  { key: "ppt", label: "PPT 演示" },
  { key: "excel", label: "Excel 表格" },
  { key: "pdf", label: "PDF 文档" },
];
// 能力卡片(右侧欢迎区:两大能力入口 + 小字说明)
const CAPABILITIES = [
  {
    label: "需求分析",
    desc: "帮您梳理并分析业务需求,解决各类业务问题",
    sample: "我想做一个员工考勤系统,大约 50 人使用,预算 15 万以内,希望三个月内上线",
  },
  {
    label: "文件生成",
    desc: "帮您撰写发言稿、制作PPT、报告方案、通知等,解决各类文件问题",
    sample: "帮我写一篇年会发言稿,主题是团队成长与感恩,面向全体员工,5 分钟左右",
  },
];

/* ---------------------------------------------------------------- API Key */

const KEY_STORE = "deepseek_api_key";

function getKey() { return localStorage.getItem(KEY_STORE) || ""; }

function saveKey(key) {
  if (key) localStorage.setItem(KEY_STORE, key.trim());
  else localStorage.removeItem(KEY_STORE);
}

function showKeyModal() {
  $("#key-modal").hidden = false;
  $("#key-input").value = "";
  $("#key-cancel").hidden = !getKey();  // 已存 Key 时允许取消
  $("#key-input").focus();
}

function hideKeyModal() { $("#key-modal").hidden = true; }

/* ---------------------------------------------------------------- 基础工具 */

function authHeaders(extra = {}) {
  const key = getKey();
  return {
    "Content-Type": "application/json",
    ...(key ? { "X-API-Key": key } : {}),
    ...extra,
  };
}

async function api(path, opts = {}) {
  const resp = await fetch(path, {
    ...opts,
    headers: authHeaders(opts.headers || {}),
  });
  if (!resp.ok) {
    let detail = "请求失败";
    try { detail = (await resp.json()).detail || detail; } catch (e) { /* ignore */ }
    throw new Error(detail);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

let toastTimer = null;
function toast(message) {
  const box = $("#toast");
  box.textContent = message;
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, 4000);
}

function scrollBottom() {
  const box = $("#messages");
  box.scrollTop = box.scrollHeight;
}

function fmtSize(bytes) {
  if (bytes > 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + " MB";
  if (bytes > 1024) return (bytes / 1024).toFixed(0) + " KB";
  return bytes + " B";
}

/* ---------------------------------------------------------------- 会话管理 */

async function refreshList() {
  const list = await api("/api/sessions");
  const ul = $("#session-list");
  ul.innerHTML = "";
  for (const s of list) {
    const li = el("li", "session-item" + (state.session && s.session_id === state.session.session_id ? " active" : ""));
    li.appendChild(el("span", "s-title", s.title));
    li.appendChild(el("span", "phase-badge", PHASE_LABEL[s.phase] || s.phase));
    const del = el("button", "s-del", "×");
    del.title = "删除会话";
    del.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm("删除该会话及已生成的文件?")) return;
      await api("/api/sessions/" + s.session_id, { method: "DELETE" });
      if (state.session && state.session.session_id === s.session_id) resetToNew();
      await refreshList();
    });
    li.appendChild(del);
    li.addEventListener("click", () => loadSession(s.session_id));
    ul.appendChild(li);
  }
}

async function newSession() {
  const s = await api("/api/sessions", { method: "POST" });
  await loadSession(s.session_id);
  await refreshList();
}

async function loadSession(sid) {
  state.session = await api("/api/sessions/" + sid);
  renderAll();
  await refreshList();
}

function resetToNew() {
  state.session = null;
  renderAll();
}

function renderAll() {
  renderHeader();
  renderMessages();
  renderFileBar();
}

function renderHeader() {
  $("#chat-title").textContent = state.session ? state.session.title : "新会话";
  const badge = $("#chat-phase");
  if (state.session) {
    badge.hidden = false;
    badge.textContent = PHASE_LABEL[state.session.phase] || state.session.phase;
  } else {
    badge.hidden = true;
  }
  $("#btn-send").disabled = !state.session || state.streaming;
}

/* ---------------------------------------------------------------- 消息渲染 */

function renderMessages() {
  const box = $("#messages");
  box.innerHTML = "";
  if (!state.session) {
    box.appendChild(welcomePanel());
    return;
  }
  for (const m of state.session.messages) appendMessage(m);
  scrollBottom();
}

function welcomePanel() {
  const panel = el("div", "welcome-panel");
  panel.appendChild(el("div", "welcome-title", "您好,我是综合性 AI 运营智能体"));
  panel.appendChild(el("div", "welcome-sub", "我能帮您解决各种问题:"));
  const grid = el("div", "cap-grid");
  for (const cap of CAPABILITIES) {
    const card = el("div", "cap-card");
    card.appendChild(el("div", "cap-title", cap.label));
    card.appendChild(el("div", "cap-desc", cap.desc));
    card.addEventListener("click", () => startWithSample(cap.sample));
    grid.appendChild(card);
  }
  panel.appendChild(grid);
  panel.appendChild(el("div", "welcome-sub", "也可以直接在下方输入框描述您的需求或任务。"));
  return panel;
}

async function startWithSample(sample) {
  if (!state.session) await newSession();
  const input = $("#input");
  input.value = sample;
  input.focus();
}

function appendMessage(m) {
  const box = $("#messages");
  if (m.kind === "questions" && m.payload && m.payload.questions) {
    box.appendChild(questionsCard(m.payload.questions));
  } else if (m.kind === "requirement_card" && m.payload) {
    box.appendChild(requirementCard(m.payload));
  } else if (m.kind === "task_file" && m.payload && m.payload.file) {
    box.appendChild(taskFileItem(m.payload));
  } else if (m.role === "user") {
    box.appendChild(el("div", "bubble user", m.content));
  } else if (m.kind === "system") {
    box.appendChild(el("div", "bubble system", m.content));
  } else {
    box.appendChild(el("div", "bubble assistant", m.content));
  }
  scrollBottom();
}

function taskFileItem(payload) {
  const item = el("div", "card task-file-card");
  item.appendChild(el("div", "card-title", "📄 已生成交付文件"));
  const row = el("div", "file-item");
  const a = el("a", null, payload.file.filename);
  a.href = `/api/sessions/${state.session.session_id}/task-files/${payload.index}/download`;
  row.appendChild(a);
  row.appendChild(el("span", "fi-meta", fmtSize(payload.file.size_bytes)));
  item.appendChild(row);
  return item;
}

function questionsCard(questions) {
  const card = el("div", "card");
  card.appendChild(el("div", "card-title", "请确认以下问题"));
  const ol = el("ol");
  for (const q of questions) ol.appendChild(el("li", null, q.text));
  card.appendChild(ol);
  card.appendChild(el("div", "gap-note", "可以一次回复多个问题,例如:「1. 预算 15 万左右;2. 三个月内上线」"));
  return card;
}

function requirementCard(payload) {
  const card = el("div", "card");
  card.appendChild(el("div", "card-title", `需求分析已生成(第 ${payload.version} 版)`));
  card.appendChild(el("div", "summary-text", payload.summary_text || ""));

  const refs = payload.references || [];
  if (refs.length) {
    const det = el("details");
    det.appendChild(el("summary", null, `数据来源(${refs.length} 条已公布数据)`));
    const list = el("div", "ref-list");
    for (const r of refs) {
      const row = el("div");
      row.appendChild(el("span", null, `[${r.id}] ${r.claim} — `));
      const a = el("a", null, r.source_name);
      a.href = r.source_url;
      a.target = "_blank";
      a.rel = "noopener";
      row.appendChild(a);
      row.appendChild(el("span", null, `(检索于 ${r.retrieved_at})`));
      list.appendChild(row);
    }
    det.appendChild(list);
    card.appendChild(det);
  }
  if (payload.gaps && payload.gaps.length) {
    card.appendChild(el("div", "gap-note", "未能获取到的公开数据:" + payload.gaps.join(";")));
  }
  const detJson = el("details");
  detJson.appendChild(el("summary", null, "查看完整需求文档(JSON)"));
  detJson.appendChild(el("pre", null, JSON.stringify(payload.requirement, null, 2)));
  card.appendChild(detJson);

  const actions = el("div", "actions");
  const btnOk = el("button", "btn btn-primary", "确认无误,生成文件");
  btnOk.addEventListener("click", () => confirmSession(card));
  const btnEdit = el("button", "btn", "提出修改");
  btnEdit.addEventListener("click", () => {
    btnOk.disabled = true;
    btnEdit.disabled = true;
    const ta = el("textarea");
    ta.rows = 3;
    ta.placeholder = "请描述需要修改的内容,例如:预算改为 20 万以内,增加移动端打卡功能";
    const btnSubmit = el("button", "btn btn-primary", "提交修改");
    btnSubmit.addEventListener("click", () => {
      const text = ta.value.trim();
      if (!text) return toast("请填写修改意见");
      card.remove();
      send(text, "revise");
    });
    actions.appendChild(ta);
    actions.appendChild(btnSubmit);
  });
  actions.appendChild(btnOk);
  actions.appendChild(btnEdit);
  card.appendChild(actions);
  return card;
}

async function confirmSession() {
  try {
    await api(`/api/sessions/${state.session.session_id}/confirm`, { method: "POST" });
    await loadSession(state.session.session_id);
  } catch (e) {
    toast(e.message);
  }
}

/* ---------------------------------------------------------------- 文件生成 */

function renderFileBar() {
  const bar = $("#file-bar");
  bar.innerHTML = "";
  if (!state.session) {
    bar.hidden = true;
    return;
  }

  // choose 阶段:快捷选择导出文件类型
  if (state.session.phase === "choose") {
    bar.hidden = false;
    bar.appendChild(el("span", "fb-label", "快速选择:"));
    for (const ft of FILE_TYPES) {
      const chip = el("button", "btn", ft.label);
      chip.disabled = state.streaming;
      chip.addEventListener("click", () => send(ft.label, "message"));
      bar.appendChild(chip);
    }
    const all = el("button", "btn", "全部");
    all.disabled = state.streaming;
    all.addEventListener("click", () => send("全部", "message"));
    bar.appendChild(all);
    return;
  }

  if (state.session.phase !== "done") {
    bar.hidden = true;
    return;
  }
  bar.hidden = false;

  // done 阶段:需求分析类文件按钮(仅做过需求分析的会话显示)
  if (state.session.requirement) {
    const requested = state.session.requested_files || [];
    const types = requested.length
      ? FILE_TYPES.filter((f) => requested.includes(f.key))
      : FILE_TYPES;
    bar.appendChild(el("span", "fb-label", "生成交付文件:"));
    for (const ft of types) {
      const btn = el("button", "btn", ft.label);
      btn.disabled = state.streaming;
      btn.addEventListener("click", () => generateFile(ft, btn));
      bar.appendChild(btn);
    }
  }
  for (const [key, record] of Object.entries(state.session.files || {})) {
    const item = el("div", "file-item");
    const a = el("a", null, record.filename);
    a.href = `/api/sessions/${state.session.session_id}/files/${key}/download`;
    item.appendChild(a);
    item.appendChild(el("span", "fi-meta", `${fmtSize(record.size_bytes)} · v${record.version} · ${record.created_at.slice(0, 16).replace("T", " ")}`));
    const re = el("button", "btn", "重新生成");
    re.addEventListener("click", async () => {
      re.disabled = true;
      try {
        await api(`/api/sessions/${state.session.session_id}/files/${key}`, { method: "POST" });
        await loadSession(state.session.session_id);
      } catch (e) { toast(e.message); re.disabled = false; }
    });
    item.appendChild(re);
    bar.appendChild(item);
  }
}

async function generateFile(ft, btn) {
  btn.disabled = true;
  btn.textContent = "生成中…";
  try {
    await api(`/api/sessions/${state.session.session_id}/files/${ft.key}`, { method: "POST" });
    await loadSession(state.session.session_id);
    toast(`${ft.label}已生成`);
  } catch (e) {
    toast(e.message);
    btn.disabled = false;
    btn.textContent = ft.label;
  }
}

/* ---------------------------------------------------------------- SSE 发送 */

async function send(text, kind = "message") {
  if (!state.session || state.streaming) return;
  state.streaming = true;
  $("#btn-send").disabled = true;
  renderFileBar();

  const box = $("#messages");
  box.appendChild(el("div", "bubble user", text));
  const streamEl = el("div", "bubble assistant streaming", "");
  box.appendChild(streamEl);
  let researchCard = null;
  scrollBottom();

  const ctrl = new AbortController();
  state.abort = ctrl;
  try {
    const resp = await fetch(`/api/sessions/${state.session.session_id}/stream`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ kind, text }),
      signal: ctrl.signal,
    });
    if (!resp.ok) throw new Error("服务响应异常");
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const ev = parseEvent(block);
        if (!ev) continue;
        const { event, payload } = ev;
        if (event === "meta") {
          $("#chat-phase").textContent = PHASE_LABEL[payload.phase] || payload.phase;
        } else if (event === "text") {
          streamEl.textContent += payload.delta || "";
        } else if (event === "questions") {
          streamEl.classList.remove("streaming");
          box.appendChild(questionsCard(payload.questions));
        } else if (event === "research") {
          researchCard = updateResearchCard(researchCard, payload);
        } else if (event === "requirement") {
          streamEl.classList.remove("streaming");
          if (researchCard) researchCard.remove();
          box.appendChild(requirementCard(payload));
        } else if (event === "task_file") {
          streamEl.classList.remove("streaming");
          if (researchCard) researchCard.remove();
          box.appendChild(taskFileItem(payload));
        } else if (event === "error") {
          streamEl.classList.remove("streaming");
          toast(payload.message || "服务暂时不可用");
        }
        scrollBottom();
      }
    }
  } catch (e) {
    if (e.name !== "AbortError") toast("连接中断:" + e.message);
  } finally {
    state.streaming = false;
    state.abort = null;
    try {
      await loadSession(state.session.session_id);
    } catch (e) { /* 会话可能已被删除 */ }
    $("#input").focus();
  }
}

function parseEvent(block) {
  let event = "message";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7).trim();
    else if (line.startsWith("data: ")) data += line.slice(6);
  }
  if (!data) return null;
  try { return { event, payload: JSON.parse(data) }; } catch (e) { return null; }
}

function updateResearchCard(card, payload) {
  const box = $("#messages");
  if (!card) {
    card = el("div", "research-card");
    box.appendChild(card);
  }
  card.innerHTML = "";
  if (payload.status === "started") {
    card.appendChild(el("div", "rc-line", "🔍 正在检索已公布的同类数据(行业报告 / 市场数据 / 政策标准)…"));
  } else if (payload.status === "progress") {
    if (payload.stage === "searching") {
      card.appendChild(el("div", "rc-line", "🔍 检索中:" + (payload.queries || []).join(" / ")));
    } else if (payload.stage === "fetching") {
      card.appendChild(el("div", "rc-line", "📄 正在读取公开来源:" + (payload.url || "")));
    }
  } else if (payload.status === "done") {
    card.appendChild(el("div", "rc-line", `✅ 数据调研完成,共获取 ${payload.sources_found || 0} 条可引用数据,正在生成分析…`));
  }
  scrollBottom();
  return card;
}

/* ---------------------------------------------------------------- 初始化 */

$("#btn-new").addEventListener("click", newSession);
$("#btn-key").addEventListener("click", showKeyModal);
$("#key-save").addEventListener("click", () => {
  const key = $("#key-input").value.trim();
  if (!key) { toast("请输入 API Key"); return; }
  saveKey(key);
  hideKeyModal();
  toast("Key 已保存,开始使用吧");
});
$("#key-cancel").addEventListener("click", hideKeyModal);
$("#btn-send").addEventListener("click", () => {
  const input = $("#input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  input.style.height = "auto";
  send(text, "message");
});
$("#input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("#btn-send").click();
  }
});
$("#input").addEventListener("input", () => {
  const t = $("#input");
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 120) + "px";
});

refreshList();
renderAll();  // 初始渲染:打开页面立即显示右侧欢迎卡片

// 首次使用:弹出 API Key 输入框(使用者的 Key,各用自己的额度)
if (!getKey()) showKeyModal();
