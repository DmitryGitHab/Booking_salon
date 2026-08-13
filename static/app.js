"use strict";

/* ---------- Состояние ---------- */

const state = {
  token: localStorage.getItem("booking_token") || null,
  user: JSON.parse(localStorage.getItem("booking_user") || "null"),
  masters: [],           // [{id, user_id, full_name, bio, services:[...]}]
  slotsByMaster: {},     // master_id -> [{id, start_time, end_time, status}]
  serviceById: {},       // service_id -> {name, price, duration_minutes, master_id}
  slotById: {},          // slot_id -> {start_time, end_time, master_id}
  masterNameById: {},    // master_id -> full_name
  activeView: "browse",
};

/* ---------- API-обёртка ---------- */

async function api(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && state.token) headers["Authorization"] = `Bearer ${state.token}`;

  const res = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  let data = null;
  try {
    data = await res.json();
  } catch (_) {
    /* тело могло быть пустым */
  }

  if (!res.ok) {
    const message = (data && data.detail) || `Ошибка ${res.status}`;
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }
  return data;
}

/* ---------- Тосты ---------- */

let toastTimer = null;
function showToast(message, kind = "") {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.className = `toast ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 4000);
}

/* ---------- Форматирование ---------- */

function formatDateTime(iso) {
  const d = new Date(iso);
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatMoney(value) {
  return `${Number(value).toLocaleString("ru-RU")} ₽`;
}

const STATUS_LABELS = {
  pending_payment: "Ожидает оплаты",
  confirmed: "Подтверждена",
  cancelled: "Отменена",
  expired: "Просрочена",
  refunded: "Возврат оформлен",
};

const SLOT_STATUS_LABELS = {
  free: "свободен",
  pending_payment: "ожидает оплаты",
  booked: "забронирован",
  cancelled: "отменён",
};

/* ---------- Авторизация ---------- */

function persistSession(token, user) {
  state.token = token;
  state.user = user;
  localStorage.setItem("booking_token", token);
  localStorage.setItem("booking_user", JSON.stringify(user));
}

function clearSession() {
  state.token = null;
  state.user = null;
  localStorage.removeItem("booking_token");
  localStorage.removeItem("booking_user");
}

async function handleLogin(e) {
  e.preventDefault();
  const form = new FormData(e.target);
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      auth: false,
      body: { email: form.get("email"), password: form.get("password") },
    });
    persistSession(data.access_token, data.user);
    showToast(`С возвращением, ${data.user.full_name}`, "success");
    enterApp();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function handleRegister(e) {
  e.preventDefault();
  const form = new FormData(e.target);
  try {
    const data = await api("/api/auth/register", {
      method: "POST",
      auth: false,
      body: {
        email: form.get("email"),
        password: form.get("password"),
        full_name: form.get("full_name"),
        phone: form.get("phone") || null,
      },
    });
    persistSession(data.access_token, data.user);
    showToast("Аккаунт создан", "success");
    enterApp();
  } catch (err) {
    showToast(err.message, "error");
  }
}

function handleLogout() {
  clearSession();
  render();
}

/* ---------- Загрузка каталога ---------- */

async function loadCatalog() {
  const masters = await api("/api/masters", { auth: false });
  state.masters = masters;
  state.serviceById = {};
  state.masterNameById = {};

  for (const master of masters) {
    state.masterNameById[master.id] = master.full_name;
    for (const service of master.services) {
      state.serviceById[service.id] = { ...service, master_id: master.id };
    }
  }

  // Слоты грузим отдельно на мастера (свободные — для брони, все — чтобы красиво
  // показать "мои брони" даже для уже занятых слотов).
  await Promise.all(
    masters.map(async (master) => {
      const slots = await api(`/api/masters/${master.id}/slots?only_free=false`, { auth: false });
      state.slotsByMaster[master.id] = slots;
      for (const slot of slots) {
        state.slotById[slot.id] = slot;
      }
    })
  );
}

async function loadMyBookings() {
  return api("/api/bookings/me");
}

/* ---------- Рендер: мастера и слоты ---------- */

function renderBrowseView() {
  const container = document.getElementById("masters-list");
  container.innerHTML = "";

  if (state.masters.length === 0) {
    container.innerHTML = `<p class="ledger-empty">Пока нет ни одного мастера. Загляните позже.</p>`;
    return;
  }

  const canBook = state.user && state.user.role === "client";

  for (const master of state.masters) {
    const allSlots = (state.slotsByMaster[master.id] || [])
      .slice()
      .sort((a, b) => a.start_time.localeCompare(b.start_time));
    const freeSlots = allSlots.filter((s) => s.status === "free");

    const entry = document.createElement("div");
    entry.className = "master-entry";

    const servicesHtml = master.services.length
      ? master.services
          .map(
            (s) => `
        <div class="service-row">
          <span class="service-name">${escapeHtml(s.name)}</span>
          <span class="service-meta">${s.duration_minutes} мин · ${formatMoney(s.price)}</span>
        </div>`
          )
          .join("")
      : `<p class="no-slots">Мастер пока не добавил услуги.</p>`;

    const serviceOptions = master.services
      .map((s) => `<option value="${s.id}">${escapeHtml(s.name)} — ${formatMoney(s.price)}</option>`)
      .join("");

    const slotsHtml = allSlots.length
      ? allSlots
          .map((s) =>
            s.status === "free"
              ? `<button class="slot-chip" data-slot="${s.id}" type="button">${formatDateTime(s.start_time)}</button>`
              : `<span class="slot-chip slot-chip-taken status-${s.status}">${formatDateTime(s.start_time)} · ${SLOT_STATUS_LABELS[s.status] || s.status}</span>`
          )
          .join("")
      : `<span class="no-slots">Слотов пока нет</span>`;

    entry.innerHTML = `
      <div class="master-entry-head">
        <div class="master-avatar">${initialsOf(master.full_name)}</div>
        <div class="master-name-block">
          <span class="master-name">${escapeHtml(master.full_name)}</span>
          ${master.bio ? `<span class="master-bio">${escapeHtml(master.bio)}</span>` : ""}
        </div>
      </div>
      ${servicesHtml}
      <div class="slots-wrap" data-master="${master.id}">
        ${slotsHtml}
      </div>
      ${
        canBook && freeSlots.length
          ? master.services.length
            ? `
      <div class="book-row hidden" data-book-row="${master.id}">
        <select data-service-select="${master.id}">${serviceOptions}</select>
        <button class="btn-primary" type="button" data-confirm-book="${master.id}">Забронировать</button>
      </div>`
            : `<p class="no-slots">У мастера пока нет ни одной услуги — бронирование недоступно, пока мастер их не добавит.</p>`
          : ""
      }
    `;

    container.appendChild(entry);
  }

  if (!canBook && state.user) {
    const note = document.createElement("p");
    note.className = "ledger-empty";
    note.textContent = "Бронирование доступно только клиентским аккаунтам.";
    container.prepend(note);
  }

  attachBrowseHandlers();
}

function attachBrowseHandlers() {
  document.querySelectorAll(".slot-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const wrap = chip.closest(".slots-wrap");
      wrap.querySelectorAll(".slot-chip").forEach((c) => c.classList.remove("selected"));
      chip.classList.add("selected");
      const masterId = wrap.dataset.master;

      if (!state.user || state.user.role !== "client") {
        showToast("Бронирование доступно только клиентским аккаунтам.", "error");
        return;
      }

      const bookRow = document.querySelector(`[data-book-row="${masterId}"]`);
      if (!bookRow) {
        showToast("У этого мастера нет услуг — попросите его добавить услугу в панели мастера.", "error");
        return;
      }
      bookRow.classList.remove("hidden");
      bookRow.dataset.selectedSlot = chip.dataset.slot;
    });
  });

  document.querySelectorAll("[data-confirm-book]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const masterId = btn.dataset.confirmBook;
      const bookRow = document.querySelector(`[data-book-row="${masterId}"]`);
      const select = document.querySelector(`[data-service-select="${masterId}"]`);
      const slotId = bookRow?.dataset.selectedSlot;

      if (!slotId) {
        showToast("Сначала выберите время", "error");
        return;
      }

      btn.disabled = true;
      try {
        await api("/api/bookings", {
          method: "POST",
          body: { slot_id: slotId, service_id: select.value },
        });
        showToast("Бронь создана — загляните во вкладку «Мои брони»", "success");
        await loadCatalog();
        renderBrowseView();
      } catch (err) {
        showToast(err.message, "error");
      } finally {
        btn.disabled = false;
      }
    });
  });
}

/* ---------- Рендер: мои брони ---------- */

async function renderBookingsView() {
  const container = document.getElementById("bookings-list");
  container.innerHTML = `<p class="ledger-empty">Загрузка…</p>`;

  let bookings;
  try {
    bookings = await loadMyBookings();
  } catch (err) {
    container.innerHTML = `<p class="ledger-empty">${escapeHtml(err.message)}</p>`;
    return;
  }

  if (bookings.length === 0) {
    container.innerHTML = `<p class="ledger-empty">Броней пока нет — оформите на вкладке «Мастера и слоты».</p>`;
    return;
  }

  container.innerHTML = bookings
    .map((b) => {
      const service = state.serviceById[b.service_id];
      const slot = state.slotById[b.slot_id];
      const title = service ? service.name : "Услуга";
      const masterName = service ? state.masterNameById[service.master_id] : "";
      const when = slot ? formatDateTime(slot.start_time) : "";

      const actions = [];
      if (b.status === "pending_payment") {
        actions.push(`<button class="btn-primary" data-pay="${b.id}" type="button">Оплатить</button>`);
      }
      if (b.status === "pending_payment" || b.status === "confirmed") {
        actions.push(`<button class="btn-danger" data-cancel="${b.id}" type="button">Отменить</button>`);
      }

      return `
        <div class="booking-entry">
          <div class="booking-main">
            <span class="master-name">${escapeHtml(title)}${masterName ? ` · ${escapeHtml(masterName)}` : ""}</span>
            <span class="service-meta">${when}</span>
            <span class="booking-price">${formatMoney(b.price_at_booking)}</span>
            <span class="status-dot status-${b.status}">${STATUS_LABELS[b.status] || b.status}</span>
          </div>
          <div class="booking-actions">${actions.join("")}</div>
        </div>`;
    })
    .join("");

  attachBookingsHandlers();
}

function attachBookingsHandlers() {
  document.querySelectorAll("[data-pay]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const result = await api(`/api/bookings/${btn.dataset.pay}/pay`, { method: "POST" });
        showToast(
          `Платёжное намерение создано (${result.payment_intent_id}). ` +
            `Для реальной оплаты нужны настоящие Stripe-ключи и Stripe.js — см. README. ` +
            `Для теста: stripe trigger payment_intent.succeeded.`,
          "success"
        );
      } catch (err) {
        showToast(err.message, "error");
      } finally {
        btn.disabled = false;
      }
    });
  });

  document.querySelectorAll("[data-cancel]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Точно отменить бронь?")) return;
      btn.disabled = true;
      try {
        await api(`/api/bookings/${btn.dataset.cancel}/cancel`, { method: "POST" });
        showToast("Бронь отменена", "success");
        await loadCatalog();
        renderBookingsView();
      } catch (err) {
        showToast(err.message, "error");
      } finally {
        btn.disabled = false;
      }
    });
  });
}

/* ---------- Панель мастера: свои услуги и слоты ---------- */

async function renderMasterPanel() {
  const container = document.getElementById("master-panel-content");
  container.innerHTML = `<p class="ledger-empty">Загрузка…</p>`;

  let profile;
  let myBookings = [];
  try {
    profile = await api("/api/masters/me");
  } catch (err) {
    container.innerHTML = `<p class="ledger-empty">${escapeHtml(err.message)}</p>`;
    return;
  }
  try {
    myBookings = await api("/api/masters/me/bookings");
  } catch (err) {
    showToast(err.message, "error");
  }

  const slots = (state.slotsByMaster[profile.id] || []).slice().sort((a, b) => a.start_time.localeCompare(b.start_time));

  const servicesHtml = profile.services.length
    ? profile.services
        .map(
          (s) => `
        <div class="service-row">
          <span class="service-name">${escapeHtml(s.name)}</span>
          <span class="service-meta">${s.duration_minutes} мин · ${formatMoney(s.price)}</span>
        </div>`
        )
        .join("")
    : `<p class="no-slots">Пока нет услуг — добавьте первую ниже.</p>`;

  const slotsHtml = slots.length
    ? `<div class="slots-wrap">${slots
        .map(
          (s) =>
            `<span class="slot-chip slot-chip-info status-${s.status}">${formatDateTime(s.start_time)} · ${SLOT_STATUS_LABELS[s.status] || s.status}</span>`
        )
        .join("")}</div>`
    : `<p class="no-slots">Пока нет слотов — добавьте первый ниже.</p>`;

  const bookingsHtml = myBookings.length
    ? myBookings
        .map(
          (b) => `
        <div class="booking-entry">
          <div class="booking-main">
            <span class="master-name">${escapeHtml(b.client_full_name)}</span>
            <span class="service-meta">${escapeHtml(b.service_name)} · ${formatDateTime(b.slot_start)}${b.client_phone ? ` · ${escapeHtml(b.client_phone)}` : ""}</span>
            <span class="booking-price">${formatMoney(b.price_at_booking)}</span>
          </div>
          <span class="status-dot status-${b.status}">${STATUS_LABELS[b.status] || b.status}</span>
        </div>`
        )
        .join("")
    : `<p class="no-slots">Пока никто не записался.</p>`;

  container.innerHTML = `
    <div class="master-entry">
      <div class="master-entry-head">
        <div class="master-avatar">${initialsOf(profile.full_name)}</div>
        <div class="master-name-block">
          <span class="master-name">${escapeHtml(profile.full_name)}</span>
          ${profile.bio ? `<span class="master-bio">${escapeHtml(profile.bio)}</span>` : ""}
        </div>
      </div>

      <p class="panel-subhead">Записи ко мне</p>
      ${bookingsHtml}

      <p class="panel-subhead">Мои услуги</p>
      ${servicesHtml}
      <form id="add-service-form" class="stack panel-form">
        <label>Название услуги
          <input type="text" name="name" required />
        </label>
        <label>Длительность (мин)
          <input type="number" name="duration_minutes" min="1" required />
        </label>
        <label>Цена (₽)
          <input type="number" name="price" min="0" step="0.01" required />
        </label>
        <button type="submit" class="btn-primary">Добавить услугу</button>
      </form>

      <p class="panel-subhead">Мои слоты</p>
      ${slotsHtml}
      <form id="add-slot-form" class="stack panel-form">
        <label>Начало
          <input type="datetime-local" name="start_time" required />
        </label>
        <label>Окончание
          <input type="datetime-local" name="end_time" required />
        </label>
        <button type="submit" class="btn-primary">Добавить слот</button>
      </form>
    </div>
  `;

  document.getElementById("add-service-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    try {
      await api(`/api/masters/${profile.id}/services`, {
        method: "POST",
        body: {
          name: form.get("name"),
          duration_minutes: Number(form.get("duration_minutes")),
          price: form.get("price"),
        },
      });
      showToast("Услуга добавлена", "success");
      await loadCatalog();
      renderMasterPanel();
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  document.getElementById("add-slot-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    try {
      await api(`/api/masters/${profile.id}/slots`, {
        method: "POST",
        body: {
          start_time: form.get("start_time"),
          end_time: form.get("end_time"),
        },
      });
      showToast("Слот добавлен", "success");
      await loadCatalog();
      renderMasterPanel();
    } catch (err) {
      showToast(err.message, "error");
    }
  });
}

/* ---------- Панель админа: создание мастеров ---------- */

async function renderAdminPanel() {
  const container = document.getElementById("admin-panel-content");

  const mastersHtml = state.masters.length
    ? state.masters
        .map(
          (m) => `
      <div class="master-entry">
        <div class="master-entry-head">
          <div class="master-avatar">${initialsOf(m.full_name)}</div>
          <div class="master-name-block">
            <span class="master-name">${escapeHtml(m.full_name)}</span>
            <span class="master-bio">${m.services.length} услуг(и)</span>
          </div>
        </div>
      </div>`
        )
        .join("")
    : `<p class="ledger-empty">Мастеров пока нет — создайте первого ниже.</p>`;

  container.innerHTML = `
    <p class="panel-subhead">Существующие мастера</p>
    ${mastersHtml}

    <div class="master-entry">
      <p class="panel-subhead" style="margin-top: 0">Создать мастера</p>
      <form id="add-master-form" class="stack panel-form">
        <label>Email
          <input type="email" name="email" required />
        </label>
        <label>Имя
          <input type="text" name="full_name" required />
        </label>
        <label>О себе <span class="hint">необязательно</span>
          <input type="text" name="bio" />
        </label>
        <label>Временный пароль <span class="hint">минимум 8 символов</span>
          <input type="password" name="temporary_password" required minlength="8" />
        </label>
        <button type="submit" class="btn-primary">Создать мастера</button>
      </form>
    </div>
  `;

  document.getElementById("add-master-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    try {
      await api("/api/admin/masters", {
        method: "POST",
        body: {
          email: form.get("email"),
          full_name: form.get("full_name"),
          bio: form.get("bio") || null,
          temporary_password: form.get("temporary_password"),
        },
      });
      showToast("Мастер создан", "success");
      await loadCatalog();
      renderAdminPanel();
    } catch (err) {
      showToast(err.message, "error");
    }
  });
}

/* ---------- Навигация между вкладками ---------- */

async function showView(view) {
  state.activeView = view;
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  document.getElementById("view-browse").classList.toggle("hidden", view !== "browse");
  document.getElementById("view-bookings").classList.toggle("hidden", view !== "bookings");
  document.getElementById("view-master-panel").classList.toggle("hidden", view !== "master-panel");
  document.getElementById("view-admin-panel").classList.toggle("hidden", view !== "admin-panel");

  // Каталог (мастера/услуги/слоты) обновляем при каждом переключении вкладки —
  // иначе, например, мастер не увидит новую запись клиента без перезахода.
  if (view === "browse" || view === "master-panel" || view === "admin-panel") {
    try {
      await loadCatalog();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  if (view === "browse") renderBrowseView();
  if (view === "bookings") renderBookingsView();
  if (view === "master-panel") renderMasterPanel();
  if (view === "admin-panel") renderAdminPanel();
}

/* ---------- Вход в приложение / общий рендер ---------- */

async function enterApp() {
  document.getElementById("view-auth").classList.add("hidden");
  document.getElementById("tabs").classList.remove("hidden");

  const sessionBox = document.getElementById("session-box");
  sessionBox.classList.remove("hidden");
  document.getElementById("session-name").textContent = state.user.full_name;
  document.getElementById("session-role").textContent = state.user.role;

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    const roles = btn.dataset.roles;
    const visible = !roles || roles.split(",").includes(state.user.role);
    btn.classList.toggle("hidden", !visible);
  });

  const defaultViewByRole = { client: "browse", master: "master-panel", admin: "admin-panel" };
  await showView(defaultViewByRole[state.user.role] || "browse");
}

function render() {
  if (state.token && state.user) {
    enterApp();
  } else {
    document.getElementById("view-auth").classList.remove("hidden");
    document.getElementById("tabs").classList.add("hidden");
    document.getElementById("session-box").classList.add("hidden");
    document.getElementById("view-browse").classList.add("hidden");
    document.getElementById("view-bookings").classList.add("hidden");
  }
}

/* ---------- Утилиты ---------- */

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function initialsOf(fullName) {
  return (fullName || "?")
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() || "")
    .join("");
}

/* ---------- Инициализация ---------- */

document.addEventListener("DOMContentLoaded", () => {
  window.addEventListener("error", (e) => {
    console.error("Необработанная ошибка:", e.error || e.message);
    showToast(`Ошибка интерфейса: ${e.message}`, "error");
  });
  window.addEventListener("unhandledrejection", (e) => {
    console.error("Необработанный отказ промиса:", e.reason);
    showToast(`Ошибка интерфейса: ${e.reason?.message || e.reason}`, "error");
  });

  document.getElementById("login-form").addEventListener("submit", handleLogin);
  document.getElementById("register-form").addEventListener("submit", handleRegister);
  document.getElementById("logout-btn").addEventListener("click", handleLogout);

  document.getElementById("show-login").addEventListener("click", () => {
    document.getElementById("show-login").classList.add("active");
    document.getElementById("show-register").classList.remove("active");
    document.getElementById("login-form").classList.remove("hidden");
    document.getElementById("register-form").classList.add("hidden");
  });
  document.getElementById("show-register").addEventListener("click", () => {
    document.getElementById("show-register").classList.add("active");
    document.getElementById("show-login").classList.remove("active");
    document.getElementById("register-form").classList.remove("hidden");
    document.getElementById("login-form").classList.add("hidden");
  });

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => showView(btn.dataset.view));
  });

  render();
});
