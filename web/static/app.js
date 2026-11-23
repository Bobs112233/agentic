// AdForge workspace. All user and model text goes through esc(); only server-rendered SVG is inserted as markup.
const $ = (id) => document.getElementById(id);
const token = localStorage.getItem("adforge_token");
if (!token) location.href = "/";

const state = { campaigns: [], current: null, snap: null, busy: false };
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const rs = (value) => value == null ? "n/a" : "Rs " + Number(value).toLocaleString("en-PK", { maximumFractionDigits: 2 });
const num = (value) => Number(value || 0).toLocaleString("en-PK");

const NODE_NAMES = {
  guard: "Guard", trim: "Trim", router: "Router", strategist: "Strategist", copywriter: "Copywriter",
  copy_tools: "save_ad_variants", creative: "Creative Director", creative_tools: "render_creative",
  launcher: "Launcher", analyst: "Analyst", analyst_tools: "tools", memory_writer: "Memory", refuse: "Refused",
};

async function api(path, options = {}) {
  const response = await fetch("/api" + path, {
    method: options.method || "GET",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (response.status === 401) { localStorage.removeItem("adforge_token"); location.href = "/"; }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join(". ") : data.detail;
    throw new Error(detail || "Something went wrong. Please try again.");
  }
  return data;
}

function working(title, text, steps) {
  $("working-title").textContent = title;
  $("working-text").textContent = text;
  $("working-steps").innerHTML = steps.map((s, i) => `<span class="chip on" style="animation:pulse 1.6s ${i * 0.25}s infinite">${esc(s)}</span>`).join("");
  $("working").classList.remove("hidden");
}

async function agentCall(title, text, steps, call) {
  if (state.busy) return;
  state.busy = true;
  working(title, text, steps);
  try {
    const snap = await call();
    state.snap = snap;
    state.current = snap.campaign.id;
    await loadCampaigns();
    render();
  } catch (error) {
    alertBar(error.message);
  } finally {
    state.busy = false;
    $("working").classList.add("hidden");
  }
}

function alertBar(message) {
  const el = document.createElement("div");
  el.className = "panel pad";
  el.style.cssText = "position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:60;border-color:rgba(251,113,133,.6);max-width:90vw";
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 6000);
}

// ---------- sidebar
async function loadCampaigns() {
  state.campaigns = (await api("/campaigns")).campaigns;
  $("campaigns").innerHTML = state.campaigns.length
    ? state.campaigns.map((c) => `<button type="button" data-id="${esc(c.id)}" class="${c.id === state.current ? "active" : ""}">
        ${esc(c.name)}<small>${esc(c.status)} · ${rs(c.daily_budget)}/day · ${c.days}d</small></button>`).join("")
    : `<p class="muted" style="font-size:13px">No campaigns yet.</p>`;
  $("campaigns").querySelectorAll("button").forEach((b) => (b.onclick = () => openCampaign(b.dataset.id)));
}

function renderMemory(memory) {
  const text = (m) => m.kind === "brand"
    ? Object.entries(m.value).map(([k, v]) => `<b>${esc(k)}:</b> ${esc(v)}`).join("<br>")
    : m.kind === "preferences" ? esc(m.value.text)
    : `Winning angle: <b>${esc(m.value.winner_angle)}</b>`;
  $("memory").innerHTML = memory.length
    ? memory.map((m) => `<div class="mem"><span class="label">${esc(m.kind)}</span>
        <button type="button" title="Forget this" data-kind="${esc(m.kind)}" data-key="${esc(m.key)}">×</button>
        <div style="margin-top:4px;padding-right:14px">${text(m)}</div></div>`).join("")
    : `<p class="muted" style="font-size:13px">Nothing saved yet. It fills in after your first campaign.</p>`;
  $("memory").querySelectorAll("button").forEach((b) => (b.onclick = async () => {
    renderMemory((await api(`/memory/${b.dataset.kind}/${b.dataset.key}`, { method: "DELETE" })).memory);
  }));
}

// ---------- center
function briefForm() {
  state.current = null; state.snap = null;
  loadCampaigns();
  $("center").innerHTML = `
    <div class="panel glow pad">
      <span class="label">New campaign</span>
      <h2 style="font-size:28px;margin:8px 0 18px">Brief your <span class="grad">ad team</span></h2>
      <form id="brief">
        <label class="field"><span class="label">Product or service</span>
          <input id="b-product" maxlength="80" required placeholder="Cold brew coffee bottles"></label>
        <label class="field"><span class="label">Details, price, offer</span>
          <textarea id="b-details" maxlength="500" placeholder="Rs 450 a bottle, brewed 18 hours, same-day delivery in Islamabad"></textarea></label>
        <label class="field"><span class="label">Who should see it</span>
          <input id="b-audience" maxlength="200" placeholder="Students and office workers in Islamabad"></label>
        <div class="row">
          <label class="field"><span class="label">Goal</span>
            <select id="b-goal"><option>Sales</option><option>Leads</option><option>Store visits</option><option>Awareness</option></select></label>
          <label class="field"><span class="label">Platform</span>
            <select id="b-platform"><option>Instagram</option><option>Facebook</option><option>TikTok</option></select></label>
        </div>
        <div class="row">
          <label class="field"><span class="label">Daily budget (Rs)</span>
            <input id="b-budget" type="number" min="500" max="500000" step="100" value="2000" required></label>
          <label class="field"><span class="label">Days</span>
            <input id="b-days" type="number" min="1" max="30" value="5" required></label>
        </div>
        <button class="btn primary">Forge my ads</button>
      </form>
    </div>`;
  $("brief").onsubmit = (event) => {
    event.preventDefault();
    const body = {
      product: $("b-product").value.trim(), details: $("b-details").value.trim(), audience: $("b-audience").value.trim(),
      goal: $("b-goal").value, platform: $("b-platform").value,
      daily_budget: Number($("b-budget").value), days: Number($("b-days").value),
    };
    agentCall("Forging your campaign", "Three agents are working. This takes about 20 seconds.",
      ["Guard", "Strategist", "Copywriter", "Creative Director", "Memory"],
      () => api("/campaigns", { method: "POST", body }));
  };
  renderChat();
}

async function openCampaign(id) {
  try {
    state.snap = await api("/campaigns/" + id);
    state.current = id;
    await loadCampaigns();
    render();
  } catch (error) { alertBar(error.message); }
}

function render() {
  const snap = state.snap;
  if (!snap) return briefForm();
  const { campaign, variants, results, recommendations } = snap;
  const live = campaign.status === "live";
  const winner = recommendations[0]?.winner;
  const best = Math.max(1, ...results.map((r) => r.conversions));
  const statusChip = live ? `<span class="chip live"><span class="dot"></span>live</span>`
    : `<span class="chip ${campaign.status === "ready" ? "on" : ""}">${esc(campaign.status)}</span>`;

  $("center").innerHTML = `
    <div class="panel pad">
      <div class="head">
        <div><span class="label">Campaign</span><h2 style="font-size:26px;margin-top:4px">${esc(campaign.name)} ${statusChip}</h2></div>
        <div class="actions">
          <button class="btn primary" id="act-launch" type="button" ${live || !variants.length ? "disabled" : ""}>Launch</button>
          <button class="btn" id="act-analyze" type="button" ${live ? "" : "disabled"}>Analyse results</button>
          <button class="btn" id="act-revise" type="button" ${variants.length ? "" : "disabled"}>New challenger ad</button>
        </div>
      </div>
      ${campaign.strategy ? `<div class="kv" style="margin-top:18px">
        <div><span class="label">Audience</span><span>${esc(campaign.strategy.audience)}</span></div>
        <div><span class="label">Tone</span><span>${esc(campaign.strategy.tone)}</span></div>
        <div><span class="label">Budget</span><span>${rs(campaign.daily_budget)} a day for ${campaign.days} days</span></div>
      </div>` : ""}
    </div>

    <div class="ads">${variants.map((v, i) => `
      <div class="panel ad ${v.label === winner ? "win" : ""}" style="animation-delay:${i * 0.08}s">
        <div class="art">${v.svg || ""}</div>
        <div class="meta">
          <div class="tag"><span class="badge-l">${esc(v.label)}</span>
            ${v.label === winner ? `<span class="chip live">winner</span>` : `<span class="chip">${esc(v.angle)}</span>`}</div>
          <b>${esc(v.headline)}</b><span class="muted" style="font-size:13.5px">${esc(v.body)}</span>
          <span class="chip on" style="align-self:flex-start">${esc(v.cta)}</span>
        </div>
      </div>`).join("")}</div>

    ${results.length ? `<div class="panel pad">
      <div class="head"><span class="label">Results</span><span class="chip">sandbox ad network</span></div>
      <table style="margin-top:8px"><thead><tr><th>Ad</th><th>Impressions</th><th>Clicks</th><th>CTR</th><th>CPC</th><th>Conversions</th><th>CPA</th></tr></thead>
      <tbody>${results.map((r) => `<tr>
        <td><b>${esc(r.label)}</b> <span class="muted">${esc(r.headline)}</span></td>
        <td>${num(r.impressions)}</td><td>${num(r.clicks)}</td><td>${r.ctr}%</td><td>${rs(r.cpc)}</td>
        <td>${num(r.conversions)}<div class="bar"><i style="width:${Math.round((r.conversions / best) * 100)}%"></i></div></td>
        <td>${rs(r.cpa)}</td></tr>`).join("")}</tbody></table>
    </div>` : ""}

    ${recommendations.length ? `<div class="panel pad rec">
      <span class="label">Analyst recommendation</span>
      <p style="margin:8px 0">${esc(recommendations[0].summary)}</p>
      <ul style="margin:0;padding-left:18px">${recommendations[0].fixes.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>
    </div>` : ""}`;

  $("act-launch").onclick = () => act("launch", "Preparing launch", "Checking the campaign before asking for your approval.", ["Guard", "Router", "Launcher"]);
  $("act-analyze").onclick = () => act("analyze", "Reading the results", "The analyst is pulling numbers and doing the maths.", ["Analyst", "get_campaign_results", "calculator", "Memory"]);
  $("act-revise").onclick = () => act("revise", "Writing a challenger", "A new ad built on what the last test taught us.", ["Copywriter", "Creative Director"]);

  renderChat();
  renderMemory(snap.memory);
  renderApproval();
}

function act(action, title, text, steps) {
  agentCall(title, text, steps, () => api(`/campaigns/${state.current}/action`, { method: "POST", body: { action } }));
}

// ---------- chat and approval
function renderChat() {
  const snap = state.snap;
  const enabled = !!snap && !snap.pending;
  $("chat-text").disabled = !enabled;
  $("chat-send").disabled = !enabled;
  $("messages").innerHTML = snap && snap.messages.length
    ? snap.messages.map((m) => `<div class="msg ${m.role === "user" ? "user" : "agent"}">${esc(m.text)}</div>`).join("")
    : `<div class="empty">Create or open a campaign, then ask for changes, launch it, or ask how it is doing.</div>`;
  $("messages").scrollTop = $("messages").scrollHeight;
  $("trace").innerHTML = snap && snap.trace.length
    ? `<span class="label">Last run</span>` + snap.trace.map((n) => `<span class="chip ${n === "refuse" ? "warn" : "on"}">${esc(NODE_NAMES[n] || n)}</span>`).join("")
    : `<span class="label">Agent path appears here</span>`;
}

function renderApproval() {
  const pending = state.snap?.pending;
  $("approval").classList.toggle("hidden", !pending);
  if (!pending) return;
  $("approval-total").textContent = rs(pending.total_spend);
  $("approval-text").textContent = `${pending.variants.length} ads (${pending.variants.join(", ")}) for "${pending.campaign}": ` +
    `${rs(pending.daily_budget)} a day for ${pending.days} days.`;
}

function decide(approve) {
  $("approval").classList.add("hidden");
  agentCall(approve ? "Launching" : "Cancelling", approve ? "Sending your ads to the network." : "Nothing will be spent.",
    ["Launcher", "Memory"], () => api(`/campaigns/${state.current}/approval`, { method: "POST", body: { approve } }));
}

$("approve").onclick = () => decide(true);
$("reject").onclick = () => decide(false);
$("new-campaign").onclick = briefForm;
$("logout").onclick = () => { localStorage.removeItem("adforge_token"); location.href = "/"; };
$("chat-form").onsubmit = (event) => {
  event.preventDefault();
  const message = $("chat-text").value.trim();
  if (!message || !state.current) return;
  $("chat-text").value = "";
  agentCall("Agents at work", "Routing your message to the right agent.", ["Guard", "Router", "Agent", "Memory"],
    () => api(`/campaigns/${state.current}/chat`, { method: "POST", body: { message } }));
};

(async () => {
  try {
    const me = await api("/me");
    $("business").textContent = me.user.business;
    renderMemory(me.memory);
    await loadCampaigns();
    if (state.campaigns.length) openCampaign(state.campaigns[0].id); else briefForm();
  } catch (error) { alertBar(error.message); }
})();
