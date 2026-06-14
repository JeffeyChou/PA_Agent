const state = {
  settings: null,
  frame: null,
  decision: null,
  rawRecord: null,
  analysisJob: null,
  latestRecordId: null,
  zoom: 1,
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json();
}

function setStatus(text) {
  $("statusLine").textContent = text;
  $("connectionStatus").textContent = text;
}

function writeJson(id, value) {
  $(id).textContent = JSON.stringify(value ?? {}, null, 2);
}

function appendLog(text) {
  const log = $("streamLog");
  log.textContent += text;
  log.scrollTop = log.scrollHeight;
}

async function boot() {
  bindUi();
  await Promise.all([loadSettings(), loadSources()]);
  await refreshSnapshot();
  startMarketStream();
}

function bindUi() {
  $("subscribeBtn").addEventListener("click", subscribe);
  $("fitBtn").addEventListener("click", () => {
    state.zoom = 1;
    drawChart();
  });
  $("resumeBtn").addEventListener("click", refreshSnapshot);
  $("analyzeBtn").addEventListener("click", () => startAnalysis(false));
  $("incrementalBtn").addEventListener("click", () => startAnalysis(true));
  $("cancelBtn").addEventListener("click", cancelAnalysis);
  $("settingsBtn").addEventListener("click", openSettings);
  $("saveSettingsBtn").addEventListener("click", saveSettings);
  $("followupBtn").addEventListener("click", sendFollowup);
  for (const btn of document.querySelectorAll(".tabs button")) {
    btn.addEventListener("click", () => activateTab(btn.dataset.tab));
  }
  window.addEventListener("resize", () => {
    drawChart();
    drawFlow();
  });
}

function activateTab(name) {
  for (const btn of document.querySelectorAll(".tabs button")) {
    btn.classList.toggle("active", btn.dataset.tab === name);
  }
  for (const panel of document.querySelectorAll(".tab-panel")) {
    panel.classList.toggle("active", panel.id === `tab-${name}`);
  }
  if (name === "flow") drawFlow();
}

async function loadSettings() {
  state.settings = await api("/api/settings");
  const g = state.settings.general || {};
  const p = state.settings.provider || {};
  $("symbol").value = g.last_symbol || "XAUUSDm";
  $("timeframe").value = g.last_timeframe || "15m";
  $("barCount").value = g.analysis_bar_count || 100;
  $("setModel").value = p.model || "";
  $("setBaseUrl").value = p.base_url || "";
  $("setReasoning").value = p.reasoning_effort || "max";
  $("setContext").value = p.context_window || 2000000;
  $("setThinking").checked = Boolean(p.thinking);
  $("setConfidence").value = g.decision_confidence_threshold ?? 60;
  $("setNextBar").checked = Boolean(g.enable_next_bar_prediction);
  const v = state.settings.validation || {};
  $("setRetryEnabled").checked = Boolean(v.retry_enabled);
  $("setRetryMax").value = v.retry_max ?? 3;
  $("setCritic").value = String(Boolean(v.trade_critic_enabled));
}

async function loadSources() {
  const sources = await api("/api/sources");
  const select = $("dataSource");
  select.innerHTML = "";
  for (const source of sources.choices || []) {
    const option = document.createElement("option");
    option.value = source.id;
    option.textContent = source.label;
    select.append(option);
  }
  select.value = sources.current || "mt5";
}

async function saveSettings(event) {
  event.preventDefault();
  const payload = {
    provider: {
      model: $("setModel").value,
      base_url: $("setBaseUrl").value,
      api_key: $("setApiKey").value,
      thinking: $("setThinking").checked,
      reasoning_effort: $("setReasoning").value,
      context_window: Number($("setContext").value || 0),
    },
    general: {
      decision_confidence_threshold: Number($("setConfidence").value || 0),
      enable_next_bar_prediction: $("setNextBar").checked,
    },
    validation: {
      retry_enabled: $("setRetryEnabled").checked,
      retry_max: Number($("setRetryMax").value || 0),
      trade_critic_enabled: $("setCritic").value === "true",
    },
  };
  if (!payload.provider.api_key) delete payload.provider.api_key;
  state.settings = await api("/api/settings", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  $("settingsDialog").close();
  setStatus("Settings saved");
}

function openSettings() {
  $("settingsDialog").showModal();
}

async function subscribe() {
  const payload = currentMarketPayload();
  const result = await api("/api/source/subscribe", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  setStatus(result.ok ? "Subscribed" : `Subscribe failed: ${result.error}`);
  await refreshSnapshot();
}

function currentMarketPayload() {
  return {
    data_source: $("dataSource").value,
    symbol: $("symbol").value.trim(),
    timeframe: $("timeframe").value,
    bar_count: Number($("barCount").value || 100),
  };
}

async function refreshSnapshot() {
  const payload = currentMarketPayload();
  const qs = new URLSearchParams({
    symbol: payload.symbol,
    timeframe: payload.timeframe,
    bar_count: String(payload.bar_count),
  });
  const result = await api(`/api/market/snapshot?${qs.toString()}`);
  if (result.frame) {
    state.frame = result.frame;
    drawChart();
  }
  setStatus(result.ok ? "Snapshot loaded" : `Snapshot unavailable: ${result.error}`);
}

function startMarketStream() {
  const events = new EventSource("/api/market/events");
  events.addEventListener("snapshot", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.data?.frame) {
      state.frame = payload.data.frame;
      drawChart();
      $("connectionStatus").textContent = "Live";
    }
  });
  events.onerror = () => {
    $("connectionStatus").textContent = "Live disconnected";
  };
}

async function startAnalysis(forceIncremental) {
  $("streamLog").textContent = "";
  $("cancelBtn").disabled = false;
  const payload = {
    ...currentMarketPayload(),
    force_incremental: forceIncremental,
    wait_for_close: $("waitClose").checked,
    keep_analysis: $("keepAnalysis").checked,
  };
  const job = await api("/api/analysis", { method: "POST", body: JSON.stringify(payload) });
  state.analysisJob = job.job_id;
  setStatus("Analysis queued");
  streamJob(job.events_url, handleAnalysisEvent);
}

async function cancelAnalysis() {
  if (!state.analysisJob) return;
  await api(`/api/analysis/${state.analysisJob}/cancel`, { method: "POST", body: "{}" });
  $("cancelBtn").disabled = true;
}

function streamJob(url, handler) {
  const events = new EventSource(url);
  events.onmessage = (event) => handler(JSON.parse(event.data), events);
  const names = ["created", "status", "market_frame", "orchestrator_event", "token", "prompt", "stage2_files", "record", "turn", "error", "cancelled", "terminal"];
  for (const name of names) {
    events.addEventListener(name, (event) => handler(JSON.parse(event.data), events));
  }
  events.onerror = () => {
    events.close();
  };
}

function handleAnalysisEvent(payload, events) {
  const data = payload.data || {};
  if (payload.event === "token") appendLog(data.text || "");
  if (payload.event === "orchestrator_event") {
    setStatus(data.name || payload.status);
    if ((data.name || "").includes("Retry")) $("retryStatus").textContent = data.name;
  }
  if (payload.event === "prompt") {
    $("promptView").textContent += `\n\n[${data.stage} system]\n${data.system}\n\n[${data.stage} user]\n${data.user}`;
  }
  if (payload.event === "record") {
    const record = data.record || {};
    state.rawRecord = record;
    state.decision = data.effective_decision || record.effective_decision || record.stage2_decision;
    state.latestRecordId = recordIdFromMeta(record.meta);
    $("recordStatus").textContent = state.latestRecordId || "record saved";
    renderDecision(record);
    drawChart();
  }
  if (payload.event === "error") setStatus(`Error: ${data.message}`);
  if (payload.event === "terminal") {
    $("cancelBtn").disabled = true;
    events.close();
  }
}

function recordIdFromMeta(meta) {
  if (!meta?.timestamp_local_ms) return "";
  const d = new Date(meta.timestamp_local_ms);
  const pad = (n) => String(n).padStart(2, "0");
  const stamp = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}_${pad(d.getHours())}-${pad(d.getMinutes())}-${pad(d.getSeconds())}`;
  return `${stamp}_${meta.symbol}_${meta.timeframe}`;
}

function renderDecision(record) {
  writeJson("decisionView", state.decision?.decision || state.decision);
  writeJson("treeView", {
    gate_trace: record.stage1_diagnosis?.gate_trace,
    decision_trace: state.decision?.decision_trace,
    terminal: state.decision?.terminal,
    pre_delivery_gate: record.pre_delivery_gate,
  });
  writeJson("futureView", {
    next_cycle_prediction: state.decision?.next_cycle_prediction,
    next_bar_prediction: state.decision?.next_bar_prediction,
  });
  writeJson("rawView", record);
  const gate = record.pre_delivery_gate;
  const banner = $("gateBanner");
  if (gate && gate.status !== "allow") {
    banner.hidden = false;
    banner.textContent = `Gate ${gate.status}: ${(gate.blockers || []).join("; ")}`;
  } else {
    banner.hidden = true;
  }
  drawFlow();
}

async function sendFollowup() {
  const message = $("followupText").value.trim();
  if (!message) return;
  const job = await api("/api/followup", {
    method: "POST",
    body: JSON.stringify({ record_id: state.latestRecordId, message }),
  });
  appendLog(`\n\n> ${message}\n`);
  $("followupText").value = "";
  streamJob(job.events_url, (payload, events) => {
    if (payload.event === "token") appendLog(payload.data?.text || "");
    if (payload.event === "error") appendLog(`\n${payload.data?.message || "Error"}`);
    if (payload.event === "terminal") events.close();
  });
}

function drawChart() {
  const canvas = $("chartCanvas");
  const rect = canvas.parentElement.getBoundingClientRect();
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * scale));
  canvas.height = Math.max(1, Math.floor(rect.height * scale));
  const ctx = canvas.getContext("2d");
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  ctx.fillStyle = "#0b0d0f";
  ctx.fillRect(0, 0, rect.width, rect.height);
  const bars = (state.frame?.bars || []).slice().reverse();
  if (!bars.length) {
    ctx.fillStyle = "#68727d";
    ctx.fillText("No market data", 20, 30);
    return;
  }
  const ema = (state.frame?.indicators?.ema20 || []).slice().reverse();
  const padding = { left: 48, right: 74, top: 22, bottom: 28 };
  const prices = bars.flatMap((b) => [b.high, b.low]);
  const activeDecision = state.decision?.decision || {};
  const isOrder = ["限价单", "突破单", "市价单"].includes(activeDecision.order_type);
  if (isOrder) {
    for (const key of ["entry_price", "stop_loss_price", "take_profit_price"]) {
      const value = Number(activeDecision[key]);
      if (Number.isFinite(value)) prices.push(value);
    }
  }
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const range = max - min || 1;
  const w = rect.width - padding.left - padding.right;
  const h = rect.height - padding.top - padding.bottom;
  const y = (price) => padding.top + (max - price) / range * h;
  const xStep = w / Math.max(1, bars.length - 1);
  ctx.strokeStyle = "#1f252b";
  ctx.lineWidth = 1;
  for (let i = 0; i < 6; i++) {
    const yy = padding.top + (h / 5) * i;
    ctx.beginPath();
    ctx.moveTo(padding.left, yy);
    ctx.lineTo(rect.width - padding.right, yy);
    ctx.stroke();
  }
  bars.forEach((bar, i) => {
    const x = padding.left + i * xStep;
    const bull = Number(bar.close) >= Number(bar.open);
    ctx.strokeStyle = bull ? "#35b779" : "#e5534b";
    ctx.fillStyle = ctx.strokeStyle;
    ctx.beginPath();
    ctx.moveTo(x, y(bar.high));
    ctx.lineTo(x, y(bar.low));
    ctx.stroke();
    const bodyTop = y(Math.max(bar.open, bar.close));
    const bodyBottom = y(Math.min(bar.open, bar.close));
    const bodyHeight = Math.max(2, bodyBottom - bodyTop);
    ctx.fillRect(x - Math.max(2, xStep * 0.28), bodyTop, Math.max(4, xStep * 0.56), bodyHeight);
  });
  ctx.strokeStyle = "#e0a73a";
  ctx.beginPath();
  ema.forEach((value, i) => {
    if (!Number.isFinite(Number(value))) return;
    const x = padding.left + i * xStep;
    const yy = y(Number(value));
    if (i === 0) ctx.moveTo(x, yy);
    else ctx.lineTo(x, yy);
  });
  ctx.stroke();
  drawOrderLine(ctx, rect, y, activeDecision, isOrder);
  ctx.fillStyle = "#98a2ad";
  ctx.fillText(`${state.frame.symbol || ""} ${state.frame.timeframe || ""}`, padding.left, 16);
}

function drawOrderLine(ctx, rect, y, decision, isOrder) {
  if (!isOrder) return;
  const lines = [
    ["entry_price", "#3d8bfd", "Entry"],
    ["take_profit_price", "#35b779", "TP"],
    ["stop_loss_price", "#e5534b", "SL"],
  ];
  for (const [key, color, label] of lines) {
    const price = Number(decision[key]);
    if (!Number.isFinite(price)) continue;
    const yy = y(price);
    ctx.strokeStyle = color;
    ctx.setLineDash([6, 5]);
    ctx.beginPath();
    ctx.moveTo(48, yy);
    ctx.lineTo(rect.width - 18, yy);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = color;
    ctx.fillText(`${label} ${price}`, rect.width - 70, yy - 4);
  }
}

function drawFlow() {
  const canvas = $("flowCanvas");
  const rect = canvas.parentElement.getBoundingClientRect();
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * scale));
  canvas.height = Math.max(1, Math.floor(rect.height * scale));
  const ctx = canvas.getContext("2d");
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  const trace = state.decision?.decision_trace || [];
  const nodes = trace.slice(0, 12);
  if (!nodes.length) return;
  const y = rect.height / 2;
  const step = rect.width / Math.max(1, nodes.length);
  nodes.forEach((node, i) => {
    const x = step * i + step / 2;
    ctx.fillStyle = node.answer === "是" ? "#35b779" : "#e0a73a";
    ctx.beginPath();
    ctx.arc(x, y, 18, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#07130d";
    ctx.textAlign = "center";
    ctx.fillText(node.node_id || String(i + 1), x, y + 4);
    if (i < nodes.length - 1) {
      ctx.strokeStyle = "#66717d";
      ctx.beginPath();
      ctx.moveTo(x + 20, y);
      ctx.lineTo(x + step - 20, y);
      ctx.stroke();
    }
  });
}

boot().catch((error) => {
  setStatus(`Startup failed: ${error.message}`);
});
