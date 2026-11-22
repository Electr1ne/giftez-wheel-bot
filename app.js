const GIFTEZ_CONFIG = {
  BOT_API_URL: "https://bot-1795292735-3673-electr1ne.bothost.tech",
  CHANNEL_USERNAME: "gift_e_z",
  CACHE_KEY: "giftezup_winter_cache_v2",
  IMAGES: {
    bear: "./bear.png",
    rose: "./rose.png",
    heart: "./heart.png",
    giftbox: "./giftbox.png",
    rocket: "./rocket.png",
    ring: "./ring.png",
    nothing: "./nothing.png"
  }
};

const PRIZE_META = {
  nothing: { name: "Ничего",  stars: 0,   exchangeStars: 0,  imgKey: "nothing" },
  bear:    { name: "Мишка",   stars: 15,  exchangeStars: 13, imgKey: "bear" },
  rose:    { name: "Роза",    stars: 25,  exchangeStars: 21, imgKey: "rose" },
  heart:   { name: "Сердце",  stars: 15,  exchangeStars: 13, imgKey: "heart" },
  giftbox: { name: "Коробка", stars: 25,  exchangeStars: 21, imgKey: "giftbox" },
  rocket:  { name: "Ракета",  stars: 50,  exchangeStars: 42, imgKey: "rocket" },
  ring:    { name: "Кольцо",  stars: 100, exchangeStars: 85, imgKey: "ring" }
};

const FALLBACK_SVG = {
  bear: `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 64 64" fill="none"><circle cx="18" cy="18" r="8" fill="#0284c7"/><circle cx="46" cy="18" r="8" fill="#0284c7"/><circle cx="32" cy="34" r="18" fill="#38bdf8"/><ellipse cx="32" cy="38" rx="8" ry="6" fill="#e0f2fe"/><circle cx="26" cy="30" r="2.2" fill="#0f172a"/><circle cx="38" cy="30" r="2.2" fill="#0f172a"/><circle cx="32" cy="36" r="2.5" fill="#0f172a"/></svg>`)}`,
  rose: `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 64 64" fill="none"><path d="M32 34V56" stroke="#10b981" stroke-width="3.5" stroke-linecap="round"/><path d="M32 45C25 45 21 40 21 36C26 36 30 39 32 45Z" fill="#10b981"/><path d="M20 22C20 14 26 10 32 10C38 10 44 14 44 22C44 30 38 35 32 35C26 35 20 30 20 22Z" fill="#f43f5e"/><circle cx="32" cy="21" r="4" fill="#ffe4e6"/></svg>`)}`,
  heart: `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 64 64" fill="none"><path d="M32 52C32 52 12 38 12 23C12 16 17 11 23 11C27 11 30 13 32 16C34 13 37 11 41 11C47 11 52 16 52 23C52 38 32 52 32 52Z" fill="#ec4899"/></svg>`)}`,
  giftbox: `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 64 64" fill="none"><rect x="12" y="26" width="40" height="28" rx="6" fill="#6366f1"/><rect x="10" y="18" width="44" height="10" rx="4" fill="#818cf8"/><rect x="29" y="18" width="6" height="36" fill="#fbbf24"/></svg>`)}`,
  rocket: `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 64 64" fill="none"><path d="M32 10C40 18 44 30 42 42H22C20 30 24 18 32 10Z" fill="#38bdf8"/><circle cx="32" cy="28" r="5" fill="#e0f2fe"/><path d="M26 42L32 54L38 42H26Z" fill="#fbbf24"/></svg>`)}`,
  ring: `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 64 64" fill="none"><circle cx="32" cy="36" r="15" stroke="#fbbf24" stroke-width="5"/><polygon points="32,10 24,19 32,24 40,19" fill="#7dd3fc"/></svg>`)}`,
  nothing: `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/></svg>`)}`
};

const DEFAULT_CASES_LIST = [
  {
    id: "daily",
    page: "case-daily.html",
    name: "Ежедневный",
    price: 0,
    is_daily: true,
    badge: "24Ч",
    tierStyle: "",
    icon: "bear.png",
    fallbackKey: "bear",
    items: [
      { label: "Ничего", type: "nothing", prize: "nothing" },
      { label: "1–5 ★", type: "stars", prize: "stars" },
      { label: "6–12 ★", type: "stars", prize: "stars" },
      { label: "13–20 ★", type: "stars", prize: "stars" },
      { label: "Мишка", type: "gift", prize: "bear" },
      { label: "Роза", type: "gift", prize: "rose" }
    ]
  },
  {
    id: "starter",
    page: "case-starter.html",
    name: "Стартовый",
    price: 5,
    is_daily: false,
    badge: "ЗИМА",
    tierStyle: "",
    icon: "bear.png",
    fallbackKey: "bear",
    items: [
      { label: "1–4 ★", type: "stars", prize: "stars" },
      { label: "5–10 ★", type: "stars", prize: "stars" },
      { label: "Мишка", type: "gift", prize: "bear" },
      { label: "Роза", type: "gift", prize: "rose" }
    ]
  },
  {
    id: "romance",
    page: "case-romance.html",
    name: "Морозный",
    price: 12,
    is_daily: false,
    badge: "ТОП",
    tierStyle: "tier-pine",
    icon: "rose.png",
    fallbackKey: "rose",
    items: [
      { label: "3–10 ★", type: "stars", prize: "stars" },
      { label: "Сердце", type: "gift", prize: "heart" },
      { label: "Роза", type: "gift", prize: "rose" },
      { label: "Коробка", type: "gift", prize: "giftbox" }
    ]
  },
  {
    id: "cosmos",
    page: "case-cosmos.html",
    name: "Северный",
    price: 25,
    is_daily: false,
    badge: "NEW",
    tierStyle: "",
    icon: "rocket.png",
    fallbackKey: "rocket",
    items: [
      { label: "8–22 ★", type: "stars", prize: "stars" },
      { label: "Роза", type: "gift", prize: "rose" },
      { label: "Ракета", type: "gift", prize: "rocket" },
      { label: "Кольцо", type: "gift", prize: "ring" }
    ]
  },
  {
    id: "luxury",
    page: "case-luxury.html",
    name: "Новогодний",
    price: 50,
    is_daily: false,
    badge: "VIP",
    tierStyle: "tier-gold",
    icon: "ring.png",
    fallbackKey: "ring",
    items: [
      { label: "15–45 ★", type: "stars", prize: "stars" },
      { label: "Коробка", type: "gift", prize: "giftbox" },
      { label: "Ракета", type: "gift", prize: "rocket" },
      { label: "Кольцо", type: "gift", prize: "ring" }
    ]
  }
];

const tg = window.Telegram?.WebApp;
if (tg) {
  try {
    tg.ready();
    tg.expand();
  } catch (_) {}
}

function apiUrl(path) {
  const base = (GIFTEZ_CONFIG.BOT_API_URL || "").replace(/\/+$/, "");
  return `${base}${path}`;
}

function getImageSrc(key) {
  return GIFTEZ_CONFIG.IMAGES[key] || FALLBACK_SVG[key] || FALLBACK_SVG.bear;
}

function getFallbackSrc(key) {
  return FALLBACK_SVG[key] || FALLBACK_SVG.bear;
}

function goPage(href) {
  window.location.href = href;
}

let volumePct = Number(localStorage.getItem("giftez_vol_pct") ?? 62);
let lastNonZeroVolume = volumePct > 0 ? volumePct : 62;
let audioCtx = null;

function getAudioCtx() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (audioCtx.state === "suspended") audioCtx.resume();
  return audioCtx;
}

function playTick() {
  if (volumePct <= 0) return;
  try {
    const c = getAudioCtx();
    const osc = c.createOscillator();
    const gain = c.createGain();
    const peak = (volumePct / 100) * 0.22;
    osc.type = "triangle";
    osc.frequency.setValueAtTime(520, c.currentTime);
    osc.frequency.exponentialRampToValueAtTime(170, c.currentTime + 0.032);
    gain.gain.setValueAtTime(Math.max(0.0005, peak), c.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, c.currentTime + 0.032);
    osc.connect(gain);
    gain.connect(c.destination);
    osc.start();
    osc.stop(c.currentTime + 0.034);
  } catch (_) {}
}

function playWin() {
  if (volumePct <= 0) return;
  try {
    const c = getAudioCtx();
    const peak = (volumePct / 100) * 0.34;
    [523.25, 659.25, 783.99, 1046.5].forEach((f, i) => {
      const osc = c.createOscillator();
      const gain = c.createGain();
      osc.type = "sine";
      const t = c.currentTime + i * 0.09;
      osc.frequency.setValueAtTime(f, t);
      gain.gain.setValueAtTime(Math.max(0.0005, peak), t);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.28);
      osc.connect(gain);
      gain.connect(c.destination);
      osc.start(t);
      osc.stop(t + 0.29);
    });
  } catch (_) {}
}

function toggleGlobalMute() {
  if (volumePct > 0) {
    lastNonZeroVolume = volumePct;
    volumePct = 0;
  } else {
    volumePct = lastNonZeroVolume || 62;
  }
  localStorage.setItem("giftez_vol_pct", String(volumePct));
  syncMuteButtonUI();
  if (volumePct > 0) playTick();
}

function syncMuteButtonUI() {
  const btn = document.getElementById("globalMuteBtn");
  if (!btn) return;
  const muted = volumePct <= 0;
  btn.classList.toggle("muted", muted);
  btn.innerHTML = muted
    ? `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>`
    : `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>`;
}

function startSnowfall() {
  if (document.getElementById("snowCanvas")) return;
  const c = document.createElement("canvas");
  c.id = "snowCanvas";
  c.className = "snow-canvas";
  document.body.prepend(c);

  const g = c.getContext("2d");
  let w = (c.width = window.innerWidth);
  let h = (c.height = window.innerHeight);

  window.addEventListener("resize", () => {
    w = c.width = window.innerWidth;
    h = c.height = window.innerHeight;
  });

  const flakes = Array.from({ length: 26 }, () => ({
    x: Math.random() * w,
    y: Math.random() * h,
    r: 1 + Math.random() * 2,
    vy: 0.35 + Math.random() * 0.65,
    vx: -0.25 + Math.random() * 0.5,
    a: 0.25 + Math.random() * 0.45
  }));

  function loop() {
    g.clearRect(0, 0, w, h);
    for (const f of flakes) {
      f.y += f.vy;
      f.x += f.vx;
      if (f.y > h) {
        f.y = -4;
        f.x = Math.random() * w;
      }
      if (f.x > w) f.x = 0;
      if (f.x < 0) f.x = w;

      g.beginPath();
      g.arc(f.x, f.y, f.r, 0, Math.PI * 2);
      g.fillStyle = `rgba(224, 242, 254, ${f.a})`;
      g.fill();
    }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
}

let toastTimer = null;
function toast(msg) {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add("show");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
}

function escapeHtml(v) {
  return String(v ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function cleanUsername(v) {
  return String(v || "").trim().replace(/^@+/, "").replace(/[^a-zA-Z0-9_]/g, "");
}

function validUsername(v) {
  return /^[a-zA-Z][a-zA-Z0-9_]{4,31}$/.test(cleanUsername(v));
}

function saveCache(state) {
  try {
    localStorage.setItem(GIFTEZ_CONFIG.CACHE_KEY, JSON.stringify(state));
  } catch (_) {}
}

function loadCache() {
  try {
    const raw = localStorage.getItem(GIFTEZ_CONFIG.CACHE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_) {
    return null;
  }
}

function renderSystemLockScreen(mode) {
  const isUpd = mode === "update";
  document.body.className = "locked-body";
  document.body.innerHTML = `
    <div class="lock-screen fade-in">
      <div class="lock-clock">
        <svg width="42" height="42" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1">
          <circle cx="12" cy="12" r="9"></circle>
          <polyline points="12 7 12 12 15.5 14"></polyline>
        </svg>
      </div>
      <h1 style="font-size:21px;font-weight:900;">${isUpd ? "Идёт обновление" : "Идут технические работы"}</h1>
      <p style="font-size:13.5px;color:var(--muted);line-height:1.45;">
        ${isUpd ? "Обновляем GiftezUp и готовим зимние новинки. Скоро вернёмся!" : "Исправляем и улучшаем работу сервиса. Скоро вернёмся!"}
      </p>
    </div>
  `;
}

function mountHeader(state, onRefresh) {
  const host = document.getElementById("headerMount");
  if (!host) return;

  const u = tg?.initDataUnsafe?.user;
  const subLabel = u?.username ? `@${u.username}` : "Зимний сезон";

  host.innerHTML = `
    <div class="top-bar fade-in">
      <a class="brand-box" href="index.html">
        <div class="brand-mark">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
            <path d="M12 2v20M2 12h20M4.93 4.93l14.14 14.14M19.07 4.93L4.93 19.07"/>
          </svg>
        </div>
        <div class="brand-text">
          <div class="title">GiftezUp</div>
          <div class="sub">${escapeHtml(subLabel)}</div>
        </div>
      </a>

      <div class="top-right">
        <div class="stars-pill">
          <span>★</span>
          <span id="hdrStarsCount">${Number(state.stars_balance || 0)}</span>
        </div>
        <button type="button" class="btn-topup-sm" id="btnOpenTopup">+ Пополнить</button>
        <button type="button" class="volume-mute-btn" id="globalMuteBtn" title="Звук"></button>
      </div>
    </div>
  `;

  syncMuteButtonUI();
  document.getElementById("globalMuteBtn").onclick = toggleGlobalMute;

  let modal = document.getElementById("topupBackdrop");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "topupBackdrop";
    modal.className = "backdrop";
    modal.innerHTML = `
      <div class="modal-box" onclick="event.stopPropagation()">
        <h3>Пополнение баланса</h3>
        <p>Пополнение через Telegram Stars от 1 ★</p>
        <div class="grid-2" style="width:100%;">
          <button type="button" class="btn-soft" data-star-preset="1">1 ★</button>
          <button type="button" class="btn-soft" data-star-preset="5">5 ★</button>
          <button type="button" class="btn-soft" data-star-preset="15">15 ★</button>
          <button type="button" class="btn-soft" data-star-preset="50">50 ★</button>
        </div>
        <input type="number" class="field-input" id="topupStarsInput" min="1" max="10000" value="5" placeholder="Сумма от 1 ★" />
        <button type="button" class="btn-main" id="confirmTopupBtn">Пополнить звёздами</button>
        <button type="button" class="btn-ghost" id="closeTopupBtn">Закрыть</button>
      </div>
    `;
    modal.onclick = () => modal.classList.remove("open");
    document.body.appendChild(modal);
  }

  document.getElementById("btnOpenTopup").onclick = () => modal.classList.add("open");
  document.getElementById("closeTopupBtn").onclick = () => modal.classList.remove("open");
  modal.querySelectorAll("[data-star-preset]").forEach((b) => {
    b.onclick = () => {
      document.getElementById("topupStarsInput").value = b.getAttribute("data-star-preset");
    };
  });

  document.getElementById("confirmTopupBtn").onclick = async () => {
    const stars = Math.floor(Number(document.getElementById("topupStarsInput").value || 0));
    if (stars < 1) {
      toast("Минимум 1 ★");
      return;
    }
    if (!tg?.initData || !tg?.openInvoice) {
      toast("Оплата Stars доступна внутри Telegram");
      return;
    }
    const payBtn = document.getElementById("confirmTopupBtn");
    payBtn.disabled = true;
    try {
      const r = await fetch(apiUrl("/api/create_topup_invoice"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: tg.initData, stars })
      });
      const d = await r.json();
      payBtn.disabled = false;
      if (!d.ok || !d.invoice_link) {
        toast(d.message || "Не удалось создать счёт");
        return;
      }
      tg.openInvoice(d.invoice_link, async (status) => {
        if (status === "paid") {
          modal.classList.remove("open");
          toast(`Баланс пополнен на ${stars} ★!`);
          if (onRefresh) await onRefresh();
        } else {
          toast("Оплата отменена");
        }
      });
    } catch (_) {
      payBtn.disabled = false;
      toast("Ошибка сети");
    }
  };
}

function mountBottomNav(activeKey, state) {
  let wrap = document.getElementById("bottomNavWrap");
  if (!wrap) {
    wrap = document.createElement("div");
    wrap.id = "bottomNavWrap";
    wrap.className = "bottom-nav-wrap";
    document.body.appendChild(wrap);
  }

  const tabs = [
    { key: "home", href: "index.html", label: "Главная" },
    { key: "inventory", href: "inventory.html", label: "Инвентарь", badge: (state.inventory_items || []).length },
    { key: "requests", href: "requests.html", label: "Заявки", badge: (state.my_requests || []).filter((x) => x.status !== "done").length },
    { key: "profile", href: "profile.html", label: "Профиль" }
  ];
  if (state.is_admin) {
    tabs.push({ key: "admin", href: "admin.html", label: "Админ" });
  }

  const activeIdx = Math.max(0, tabs.findIndex((t) => t.key === activeKey));

  wrap.innerHTML = `
    <div class="bottom-nav" style="--tabs-count:${tabs.length};--active-idx:${activeIdx};">
      <div class="nav-indicator"></div>
      ${tabs
        .map(
          (t) => `
            <button
              type="button"
              class="nav-tab ${t.key === activeKey ? "active" : ""}"
              data-nav-href="${t.href}"
            >
              <span>${escapeHtml(t.label)}</span>
              ${typeof t.badge === "number" ? `<span class="nav-tab-badge">${t.badge}</span>` : ""}
            </button>
          `
        )
        .join("")}
    </div>
  `;

  wrap.querySelectorAll("[data-nav-href]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const targetHref = btn.getAttribute("data-nav-href");
      if (targetHref) {
        window.location.href = targetHref;
      }
    });
  });
}

function updateStarsDisplay(val) {
  const el = document.getElementById("hdrStarsCount");
  if (el) el.textContent = String(Number(val || 0));
}

function initGiftezPage(activeKey, { requireAdmin = false, onStateReady = null } = {}) {
  startSnowfall();

  const cached = loadCache();
  const state = cached || {
    ok: true,
    is_subscribed: false,
    is_admin: false,
    system_modes: { maintenance: false, update: false },
    stars_balance: 0,
    total_spins: 0,
    next_spin_at: 0,
    inventory_items: [],
    my_requests: [],
    cases: DEFAULT_CASES_LIST,
    upgrade_targets: []
  };

  if (!Array.isArray(state.cases) || !state.cases.length) {
    state.cases = DEFAULT_CASES_LIST;
  }

  const modes = state.system_modes || { maintenance: false, update: false };
  if (!state.is_admin && (modes.update || modes.maintenance)) {
    renderSystemLockScreen(modes.update ? "update" : "maintenance");
    return null;
  }

  const syncFromServer = async () => {
    if (!tg?.initData) return state;
    try {
      const r = await fetch(apiUrl("/api/state"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: tg.initData })
      });
      const d = await r.json();
      if (d && d.ok) {
        Object.assign(state, d);
        saveCache(state);

        const m = state.system_modes || { maintenance: false, update: false };
        if (!state.is_admin && (m.update || m.maintenance)) {
          renderSystemLockScreen(m.update ? "update" : "maintenance");
          return state;
        }
        if (requireAdmin && !state.is_admin) {
          window.location.replace("index.html");
          return state;
        }

        updateStarsDisplay(state.stars_balance);
        mountBottomNav(activeKey, state);
        if (onStateReady) onStateReady(state);
      }
    } catch (_) {}
    return state;
  };

  mountHeader(state, syncFromServer);
  mountBottomNav(activeKey, state);
  syncFromServer();

  return {
    state,
    syncFromServer,
    isTelegram: Boolean(tg && tg.initData)
  };
}