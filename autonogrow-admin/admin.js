const API_BASE_URL = AutonoGrowAuth.API_BASE_URL;
const browserFetch = window.fetch.bind(window);
const fetch = async (input, options = {}) => {
  const securedOptions = await AutonoGrowAuth.secureRequestOptions(options);
  const response = await browserFetch(input, securedOptions);
  const url = String(input);
  if (response.status === 401 && (url.includes("/api/admin/") || url.includes("/api/bookings/"))) {
    queueMicrotask(() => showAdminLogin());
  }
  if (response.status === 403 && (url.includes("/api/admin/") || url.includes("/api/bookings/"))) {
    queueMicrotask(() => showAdminLogin("Tu cuenta no tiene acceso a este negocio.", true));
  }
  return response;
};

let currentBusiness = null;
let adminAuthUser = null;
let allBookings = [];
let reviewRequestsByBooking = new Map();
let messageOutbox = [];
let adminServices = [];
let availabilitySettings = null;
let availabilityExceptions = [];
let exceptionDraftWindows = [];
let currentBookingView = "pending";
let previousGrowthTaskStates = null;
let previousGrowthAllComplete = null;
let adminGallery = [];
const TEMPLATE_DESCRIPTIONS = {
  classic: "Estructura equilibrada para cualquier negocio.", elegant: "Diseño más premium y visual.",
  beauty: "Pensada para estética, manicura y peluquería.", clinic: "Limpia y profesional para centros de salud o consulta.",
  urban: "Más impacto para barberías y negocios modernos.", minimal: "Directa y sencilla para servicios prácticos."
};
const BRAND_PALETTES = {
  slate_gold: ["#334155", "#0f172a", "#f59e0b", "#f8fafc"], rose_beauty: ["#be123c", "#831843", "#f9a8d4", "#fff1f2"],
  emerald_clean: ["#047857", "#064e3b", "#6ee7b7", "#ecfdf5"], blue_clinic: ["#2563eb", "#1e3a8a", "#93c5fd", "#eff6ff"],
  amber_barber: ["#92400e", "#451a03", "#fbbf24", "#fffbeb"], violet_modern: ["#7c3aed", "#4c1d95", "#c4b5fd", "#f5f3ff"]
};
const BRAND_COLOR_NAMES = ["primary", "secondary", "accent", "background"];
const growthDataReady = {
  bookings: false,
  messages: false,
  reviews: false
};
let rescheduleState = {
  booking: null,
  date: "",
  dayLabel: "",
  slot: null
};

function getBusinessSlug() {
  const params = new URLSearchParams(window.location.search);
  return params.get("b") || "demo-manicura";
}

function resolveMediaUrl(url, cacheBust = false) {
  if (!url) return "";
  const resolved = /^https?:\/\//i.test(url) ? url : (url.startsWith("/") ? `${API_BASE_URL}${url}` : url);
  if (!cacheBust) return resolved;
  return `${resolved}${resolved.includes("?") ? "&" : "?"}v=${Date.now()}`;
}

function showAdminSection(sectionName, updateHash = true) {
  const availableSections = Array.from(document.querySelectorAll("[data-admin-section]"));
  const sectionExists = availableSections.some((section) => section.dataset.adminSection === sectionName);
  const targetSection = sectionExists ? sectionName : "summary";

  availableSections.forEach((section) => {
    section.classList.toggle("admin-section-active", section.dataset.adminSection === targetSection);
  });

  document.querySelectorAll(".admin-tab[data-section]").forEach((tab) => {
    const isActive = tab.dataset.section === targetSection;
    tab.classList.toggle("admin-tab-active", isActive);
    tab.setAttribute("aria-selected", String(isActive));
  });

  if (updateHash) {
    window.history.replaceState(null, "", `#${targetSection}`);
  }
}

function setupAdminNavigation() {
  document.querySelectorAll(".admin-tab[data-section]").forEach((tab) => {
    tab.addEventListener("click", () => showAdminSection(tab.dataset.section));
  });

  showAdminSection(window.location.hash.slice(1) || "summary", false);
}

function setupBookingViews() {
  document.querySelectorAll("[data-booking-view]").forEach((tab) => {
    tab.addEventListener("click", () => {
      currentBookingView = tab.dataset.bookingView;
      document.querySelectorAll("[data-booking-view]").forEach((item) => {
        item.classList.toggle("booking-view-tab-active", item === tab);
      });
      renderBookings();
    });
  });
}

function getMadridDateKey(value = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Madrid",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).formatToParts(value);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function addDaysToDateKey(dateKey, days) {
  const value = new Date(`${dateKey}T12:00:00Z`);
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}

function getBookingDateKey(booking) {
  return booking.start_datetime?.slice(0, 10) || booking.preferred_date || "";
}

function getTimestampDateKey(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : getMadridDateKey(date);
}

function calculateGrowthTasks() {
  const today = getMadridDateKey();
  const pendingBookings = allBookings.filter((booking) => ["requested", "pending"].includes(booking.status));
  const pendingConfirmations = messageOutbox.filter(
    (message) => message.message_type === "booking_confirmed" && message.status === "pending"
  );
  const importantPendingMessages = messageOutbox.filter(
    (message) => [
      "booking_confirmed",
      "booking_rejected",
      "booking_rescheduled",
      "booking_completed_review"
    ].includes(message.message_type) && message.status === "pending"
  );
  const todayApplicableBookings = allBookings.filter((booking) =>
    getBookingDateKey(booking) === today && !["rejected", "cancelled"].includes(booking.status)
  );
  const completedToday = todayApplicableBookings.filter((booking) => booking.status === "completed");
  const reviewMessageSentToday = messageOutbox.some((message) =>
    message.message_type === "booking_completed_review" &&
    ["opened", "sent"].includes(message.status) &&
    getTimestampDateKey(message.sent_at || message.opened_at || message.created_at) === today
  );
  const reviewHandledToday = Array.from(reviewRequestsByBooking.values()).some((reviewRequest) =>
    ["copied", "sent"].includes(reviewRequest.status) &&
    getTimestampDateKey(reviewRequest.sent_at || reviewRequest.copied_at || reviewRequest.created_at) === today
  );

  return [
    {
      id: "confirm-pending-bookings",
      title: "Confirma tus citas pendientes",
      description: "Acepta o rechaza las solicitudes que todavía esperan respuesta.",
      status: pendingBookings.length === 0 ? "completed" : "pending",
      points: 10,
      progress_label: pendingBookings.length ? `${pendingBookings.length} por responder` : "Sin solicitudes pendientes"
    },
    {
      id: "send-confirmations",
      title: "Envía las confirmaciones por WhatsApp",
      description: "Asegúrate de que los clientes confirmados tienen su mensaje preparado o enviado.",
      status: pendingConfirmations.length === 0 ? "completed" : "pending",
      points: 10,
      progress_label: pendingConfirmations.length ? `${pendingConfirmations.length} por preparar` : "Confirmaciones al día"
    },
    {
      id: "complete-today-bookings",
      title: "Completa las citas atendidas de hoy",
      description: "Marca como completadas las citas que ya se han realizado.",
      status: todayApplicableBookings.length === 0 ? "neutral" : completedToday.length > 0 ? "completed" : "pending",
      points: 10,
      progress_label: todayApplicableBookings.length === 0
        ? "Sin citas aplicables hoy"
        : completedToday.length > 0 ? `${completedToday.length} completada${completedToday.length === 1 ? "" : "s"}` : "Ninguna completada todavía"
    },
    {
      id: "request-review",
      title: "Pide una reseña",
      description: "Envía una solicitud de reseña a un cliente atendido.",
      status: completedToday.length === 0 ? "neutral" : reviewMessageSentToday || reviewHandledToday ? "completed" : "pending",
      points: 10,
      progress_label: completedToday.length === 0
        ? "Sin citas completadas hoy"
        : reviewMessageSentToday || reviewHandledToday ? "Solicitud preparada hoy" : "Una reseña por solicitar"
    },
    {
      id: "day-up-to-date",
      title: "Deja el día al día",
      description: "Sin solicitudes pendientes ni mensajes importantes por gestionar.",
      status: pendingBookings.length === 0 && importantPendingMessages.length === 0 ? "completed" : "pending",
      points: 10,
      progress_label: pendingBookings.length === 0 && importantPendingMessages.length === 0
        ? "Todo gestionado" : `${pendingBookings.length + importantPendingMessages.length} acción${pendingBookings.length + importantPendingMessages.length === 1 ? "" : "es"} pendiente${pendingBookings.length + importantPendingMessages.length === 1 ? "" : "s"}`
    }
  ];
}

function getGrowthStorageKey() {
  return `autonogrow:growth:${getBusinessSlug()}:${getMadridDateKey()}`;
}

function readCelebratedGrowthItems() {
  try {
    return new Set(JSON.parse(localStorage.getItem(getGrowthStorageKey()) || "[]"));
  } catch (error) {
    console.warn("No se pudo leer el progreso celebrado.", error);
    return new Set();
  }
}

function saveCelebratedGrowthItems(items) {
  try {
    localStorage.setItem(getGrowthStorageKey(), JSON.stringify(Array.from(items)));
  } catch (error) {
    console.warn("No se pudo guardar el progreso celebrado.", error);
  }
}

function renderGrowth() {
  if (!Object.values(growthDataReady).every(Boolean)) {
    return;
  }

  const tasks = calculateGrowthTasks();
  const applicableTasks = tasks.filter((task) => task.status !== "neutral");
  const completedTasks = applicableTasks.filter((task) => task.status === "completed");
  const total = applicableTasks.length;
  const completed = completedTasks.length;
  const percentage = total ? Math.round((completed / total) * 100) : 100;
  const allComplete = total > 0 && completed === total;
  const celebrated = readCelebratedGrowthItems();
  const isInitialRender = previousGrowthTaskStates === null;
  const taskTransitions = new Set();

  if (!isInitialRender) {
    tasks.forEach((task) => {
      if (previousGrowthTaskStates.get(task.id) === "pending" && task.status === "completed" && !celebrated.has(task.id)) {
        taskTransitions.add(task.id);
        celebrated.add(task.id);
      }
    });
  }

  const dayTransition = previousGrowthAllComplete === false && allComplete && !celebrated.has("day-complete");
  if (dayTransition) {
    celebrated.add("day-complete");
  }
  if (taskTransitions.size || dayTransition) {
    saveCelebratedGrowthItems(celebrated);
  }

  document.getElementById("growth-progress-count").textContent = `${completed}/${total} tareas completadas`;
  document.getElementById("growth-points").textContent = `${completed * 10} puntos hoy`;
  document.getElementById("growth-progress-percent").textContent = `${percentage}%`;
  const progress = document.querySelector(".growth-progress");
  progress.setAttribute("aria-valuenow", String(percentage));
  document.getElementById("growth-progress-bar").style.width = `${percentage}%`;
  progress.classList.toggle("growth-progress-complete", allComplete);

  document.getElementById("growth-tasks-list").innerHTML = tasks.map((task) => `
    <article class="growth-task growth-task-${task.status} ${taskTransitions.has(task.id) ? "growth-task-completed-pulse" : ""}" data-growth-task="${task.id}">
      <span class="growth-task-status" aria-label="${task.status === "completed" ? "Completada" : task.status === "pending" ? "Pendiente" : "No aplicable"}">
        ${task.status === "completed" ? "Completada" : ""}
      </span>
      <div class="growth-task-copy">
        <h3>${task.title}</h3>
        <p>${task.description}</p>
        <span>${task.progress_label || ""}</span>
      </div>
      <div class="growth-task-points">${task.status === "completed" ? `+${task.points} puntos` : `${task.points} puntos`}</div>
      ${taskTransitions.has(task.id) ? `<div class="growth-task-feedback">Tarea completada · +${task.points} puntos</div>` : ""}
    </article>
  `).join("");

  const dayComplete = document.getElementById("growth-day-complete");
  dayComplete.hidden = !allComplete;
  dayComplete.classList.toggle("growth-day-complete-animation", dayTransition);

  const nextTask = tasks.find((task) => task.status === "pending");
  document.getElementById("growth-summary-count").textContent = `${completed}/${total} tareas completadas`;
  document.getElementById("growth-summary-next").textContent = nextTask
    ? `Próxima tarea: ${nextTask.title}`
    : allComplete ? "Has dejado tu negocio al día." : "No hay acciones aplicables pendientes.";
  document.getElementById("growth-summary-progress-bar").style.width = `${percentage}%`;

  previousGrowthTaskStates = new Map(tasks.map((task) => [task.id, task.status]));
  previousGrowthAllComplete = allComplete;
}

async function loadAdminPanel() {
  const slug = getBusinessSlug();

  try {
    const businessResponse = await fetch(`${API_BASE_URL}/api/admin/businesses/${slug}/settings`);

    if (!businessResponse.ok) {
      if (businessResponse.status === 401) return showAdminLogin();
      if (businessResponse.status === 403) return showAdminLogin("Tu cuenta no tiene acceso a este negocio.", true);
      renderError("No se encontró el negocio.");
      return;
    }

    currentBusiness = await businessResponse.json();
    applyBusinessData(currentBusiness);
    renderBusinessSettings();
    await Promise.all([
      loadAdminServices(),
      loadAvailabilitySettings(),
      loadAvailabilityExceptions(),
      loadBookings(),
      loadMessageOutbox(),
      loadAdminGallery()
    ]);
    restoreAdminMediaStatus();
  } catch (error) {
    console.error(error);
    renderError("No se pudo conectar con el backend.");
  }
}

const WEEKDAYS = [
  { value: "1", label: "Lunes" },
  { value: "2", label: "Martes" },
  { value: "3", label: "Miércoles" },
  { value: "4", label: "Jueves" },
  { value: "5", label: "Viernes" },
  { value: "6", label: "Sábado" },
  { value: "0", label: "Domingo" }
];

async function loadAvailabilitySettings() {
  const slug = getBusinessSlug();

  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/${slug}/availability-settings`);

    if (!response.ok) {
      throw new Error("No se pudieron cargar los horarios.");
    }

    availabilitySettings = await response.json();
    renderAvailabilitySettings();
  } catch (error) {
    console.error(error);
    document.getElementById("weekly-schedule-editor").innerHTML = `
      <p class="empty-state">No se pudieron cargar los horarios.</p>
    `;
  }
}

function renderAvailabilitySettings() {
  document.getElementById("availability-timezone").value = availabilitySettings.timezone || "Europe/Madrid";
  document.getElementById("slot-interval-minutes").value = availabilitySettings.slot_interval_minutes || 15;
  document.getElementById("buffer-between-bookings-minutes").value = availabilitySettings.buffer_between_bookings_minutes || 0;
  document.getElementById("min-notice-minutes").value = availabilitySettings.min_notice_minutes || 120;
  document.getElementById("max-days-ahead").value = availabilitySettings.max_days_ahead || 30;
  renderWeeklyScheduleEditor();
}

function renderWeeklyScheduleEditor() {
  const container = document.getElementById("weekly-schedule-editor");
  const schedule = availabilitySettings.weekly_schedule || {};
  container.innerHTML = "";

  WEEKDAYS.forEach((day) => {
    const windows = schedule[day.value] || [];
    const isClosed = windows.length === 0;
    const block = document.createElement("article");
    block.className = `schedule-day ${isClosed ? "schedule-day-closed" : ""}`;
    block.dataset.weekday = day.value;
    block.innerHTML = `
      <div class="day-header">
        <div class="day-identity">
          <strong>${day.label}</strong>
          <label class="closed-toggle">
            <input type="checkbox" aria-label="Marcar ${day.label} como cerrado" ${isClosed ? "checked" : ""} onchange="toggleDayClosed('${day.value}', this.checked)" />
            <span>${isClosed ? "Cerrado" : "Abierto"}</span>
          </label>
        </div>
        <button class="btn btn-small btn-secondary" type="button" onclick="addScheduleWindow('${day.value}')">
          Añadir tramo
        </button>
      </div>
      <div class="windows-list" id="windows-${day.value}">
        ${isClosed ? `<p class="empty-state">Día cerrado.</p>` : ""}
      </div>
    `;
    container.appendChild(block);

    if (!isClosed) {
      windows.forEach((windowItem) => {
        appendWindowRow(`windows-${day.value}`, windowItem.start, windowItem.end);
      });
    }
  });
}

function toggleDayClosed(weekday, checked) {
  const schedule = availabilitySettings.weekly_schedule || {};
  schedule[weekday] = checked ? [] : [{ start: "10:00", end: "14:00" }];
  availabilitySettings.weekly_schedule = schedule;
  renderWeeklyScheduleEditor();
}

function addScheduleWindow(weekday, start = "10:00", end = "14:00") {
  const schedule = availabilitySettings.weekly_schedule || {};
  schedule[weekday] = schedule[weekday] || [];
  schedule[weekday].push({ start, end });
  availabilitySettings.weekly_schedule = schedule;
  renderWeeklyScheduleEditor();
}

function appendWindowRow(containerId, start = "10:00", end = "14:00") {
  const container = document.getElementById(containerId);
  const row = document.createElement("div");
  row.className = "window-row";
  row.innerHTML = `
    <input type="time" class="window-start" value="${escapeHtml(start)}" />
    <span>hasta</span>
    <input type="time" class="window-end" value="${escapeHtml(end)}" />
    <button class="btn btn-small btn-danger" type="button" onclick="removeWindowRow(this)">
      Eliminar
    </button>
  `;
  container.appendChild(row);
}

function removeWindowRow(button) {
  button.closest(".window-row")?.remove();
}

function collectWeeklySchedule() {
  const schedule = {};

  WEEKDAYS.forEach((day) => {
    const block = document.querySelector(`.schedule-day[data-weekday="${day.value}"]`);
    const rows = Array.from(block?.querySelectorAll(".window-row") || []);
    schedule[day.value] = rows
      .map((row) => ({
        start: row.querySelector(".window-start").value,
        end: row.querySelector(".window-end").value
      }))
      .filter((windowItem) => windowItem.start && windowItem.end && windowItem.start < windowItem.end);
  });

  return schedule;
}

async function saveAvailabilitySettings() {
  const slug = getBusinessSlug();
  const feedback = document.getElementById("availability-settings-feedback");
  feedback.className = "inline-feedback";
  feedback.textContent = "Guardando...";

  const payload = {
    timezone: document.getElementById("availability-timezone").value.trim() || "Europe/Madrid",
    slot_interval_minutes: Number(document.getElementById("slot-interval-minutes").value || 15),
    buffer_between_bookings_minutes: Number(document.getElementById("buffer-between-bookings-minutes").value || 0),
    min_notice_minutes: Number(document.getElementById("min-notice-minutes").value || 120),
    max_days_ahead: Number(document.getElementById("max-days-ahead").value || 30),
    weekly_schedule: collectWeeklySchedule()
  };

  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/${slug}/availability-settings`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      const error = await response.json().catch(() => null);
      throw new Error(error?.detail || "No se pudieron guardar los horarios.");
    }

    const result = await response.json();
    availabilitySettings = result.settings;
    renderAvailabilitySettings();
    feedback.className = "inline-feedback success";
    feedback.textContent = "Horarios guardados correctamente.";
  } catch (error) {
    console.error(error);
    feedback.className = "inline-feedback error";
    feedback.textContent = error.message || "No se pudieron guardar los horarios.";
  }
}

async function loadAvailabilityExceptions() {
  const slug = getBusinessSlug();

  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/${slug}/availability-exceptions`);

    if (!response.ok) {
      throw new Error("No se pudieron cargar las excepciones.");
    }

    const data = await response.json();
    availabilityExceptions = data.exceptions || [];
    renderAvailabilityExceptions();
  } catch (error) {
    console.error(error);
    document.getElementById("availability-exceptions-list").innerHTML = `
      <p class="empty-state">No se pudieron cargar las excepciones.</p>
    `;
  }
}

function setupExceptionForm() {
  const typeSelect = document.getElementById("exception-type");
  typeSelect.addEventListener("change", () => {
    const panel = document.getElementById("exception-windows-panel");
    panel.style.display = typeSelect.value === "custom_hours" ? "block" : "none";

    if (typeSelect.value === "custom_hours" && exceptionDraftWindows.length === 0) {
      addExceptionWindow();
    }
  });
}

function addExceptionWindow(start = "10:00", end = "14:00") {
  exceptionDraftWindows.push({ start, end });
  renderExceptionWindows();
}

function removeExceptionWindow(index) {
  exceptionDraftWindows.splice(index, 1);
  renderExceptionWindows();
}

function renderExceptionWindows() {
  const container = document.getElementById("exception-windows");
  container.innerHTML = "";

  if (exceptionDraftWindows.length === 0) {
    container.innerHTML = `<p class="empty-state">Añade al menos un tramo.</p>`;
    return;
  }

  exceptionDraftWindows.forEach((windowItem, index) => {
    const row = document.createElement("div");
    row.className = "window-row";
    row.innerHTML = `
      <input type="time" value="${escapeHtml(windowItem.start)}" onchange="updateExceptionWindow(${index}, 'start', this.value)" />
      <span>hasta</span>
      <input type="time" value="${escapeHtml(windowItem.end)}" onchange="updateExceptionWindow(${index}, 'end', this.value)" />
      <button class="btn btn-small btn-danger" type="button" onclick="removeExceptionWindow(${index})">
        Eliminar
      </button>
    `;
    container.appendChild(row);
  });
}

function updateExceptionWindow(index, field, value) {
  if (!exceptionDraftWindows[index]) {
    return;
  }

  exceptionDraftWindows[index][field] = value;
}

async function saveAvailabilityException() {
  const slug = getBusinessSlug();
  const feedback = document.getElementById("availability-exceptions-feedback");
  const type = document.getElementById("exception-type").value;
  const date = document.getElementById("exception-date").value;
  const reason = document.getElementById("exception-reason").value.trim();
  feedback.className = "inline-feedback";
  feedback.textContent = "Guardando...";

  if (!date) {
    feedback.className = "inline-feedback error";
    feedback.textContent = "Selecciona una fecha.";
    return;
  }

  const windows = exceptionDraftWindows.filter((item) => item.start && item.end && item.start < item.end);

  if (type === "custom_hours" && windows.length === 0) {
    feedback.className = "inline-feedback error";
    feedback.textContent = "Añade al menos un tramo válido.";
    return;
  }

  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/${slug}/availability-exceptions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        date,
        type,
        windows: type === "custom_hours" ? windows : null,
        reason: reason || null
      })
    });

    if (!response.ok) {
      const error = await response.json().catch(() => null);
      throw new Error(error?.detail || "No se pudo guardar la excepción.");
    }

    feedback.className = "inline-feedback success";
    feedback.textContent = "Excepción guardada correctamente.";
    document.getElementById("exception-date").value = "";
    document.getElementById("exception-reason").value = "";
    exceptionDraftWindows = [];
    renderExceptionWindows();
    await loadAvailabilityExceptions();
  } catch (error) {
    console.error(error);
    feedback.className = "inline-feedback error";
    feedback.textContent = error.message || "No se pudo guardar la excepción.";
  }
}

function renderAvailabilityExceptions() {
  const container = document.getElementById("availability-exceptions-list");

  if (!availabilityExceptions.length) {
    container.innerHTML = `<p class="empty-state">No hay excepciones configuradas.</p>`;
    return;
  }

  container.innerHTML = "";

  availabilityExceptions.forEach((exception) => {
    const item = document.createElement("article");
    item.className = "exception-item";
    const windowsText = exception.type === "closed"
      ? "Cerrado todo el día"
      : (exception.windows || []).map((windowItem) => `${windowItem.start}-${windowItem.end}`).join(", ");
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(exception.date)} · ${exception.type === "closed" ? "Cerrado" : "Horario especial"}</strong>
        <p>${escapeHtml(windowsText || "Sin tramos")}</p>
        ${exception.reason ? `<p>${escapeHtml(exception.reason)}</p>` : ""}
      </div>
      <button class="btn btn-small btn-danger" type="button" onclick="deleteAvailabilityException(${exception.id})">
        Eliminar
      </button>
    `;
    container.appendChild(item);
  });
}

async function deleteAvailabilityException(exceptionId) {
  const confirmed = window.confirm("¿Eliminar esta excepción?");

  if (!confirmed) {
    return;
  }

  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/${getBusinessSlug()}/availability-exceptions/${exceptionId}`, {
      method: "DELETE"
    });

    if (!response.ok) {
      throw new Error("No se pudo eliminar la excepción.");
    }

    await loadAvailabilityExceptions();
  } catch (error) {
    console.error(error);
    alert(error.message || "No se pudo eliminar la excepción.");
  }
}

function applyBusinessData(business) {
  document.title = `${business.name} | Panel AutonoGrow`;
  document.documentElement.style.setProperty("--primary", business.primary_color || "#2563eb");
  document.getElementById("business-name").textContent = business.name;
  document.getElementById("business-subtitle").textContent =
    `${business.category || "Negocio local"} · ${business.city || ""}`;
  document.getElementById("public-page-link").href = `../autonogrow-landing/index.html?b=${getBusinessSlug()}`;
  const status = document.getElementById("stat-business-status");
  status.textContent = business.active ? "Activo" : "Inactivo";
  status.classList.toggle("stat-status-inactive", !business.active);
}

function renderBusinessSettings() {
  const fields = {
    "business-setting-name": currentBusiness.name,
    "business-setting-category": currentBusiness.category,
    "business-setting-headline": currentBusiness.headline,
    "business-setting-description": currentBusiness.description,
    "business-setting-phone": currentBusiness.phone,
    "business-setting-city": currentBusiness.city,
    "business-setting-address": currentBusiness.address,
    "business-setting-schedule": currentBusiness.schedule,
    "business-setting-maps-url": currentBusiness.maps_url,
    "business-setting-instagram-url": currentBusiness.instagram_url,
    "business-setting-reviews-url": currentBusiness.reviews_url
  };

  Object.entries(fields).forEach(([id, value]) => {
    document.getElementById(id).value = value || "";
  });
  document.getElementById("business-setting-active").checked = Boolean(currentBusiness.active);
  document.getElementById("business-setting-logo-alt").value = currentBusiness.logo_alt || "";
  document.getElementById("business-setting-theme").value = currentBusiness.theme_key || "slate_gold";
  document.getElementById("business-setting-template").value = currentBusiness.template_key || "classic";
  renderAdminTemplateDescription();
  BRAND_COLOR_NAMES.forEach((name) => setAdminColor(name, currentBusiness[`${name}_color`] || BRAND_PALETTES.slate_gold[BRAND_COLOR_NAMES.indexOf(name)]));
  const logo = document.getElementById("admin-logo-preview");
  logo.hidden = !currentBusiness.logo_url;
  if (currentBusiness.logo_url) logo.src = resolveMediaUrl(currentBusiness.logo_url, true);
}

async function saveBusinessSettings() {
  const feedback = document.getElementById("business-settings-feedback");
  const value = (id) => document.getElementById(id).value.trim();
  const payload = {
    name: value("business-setting-name"),
    category: value("business-setting-category"),
    headline: value("business-setting-headline"),
    description: value("business-setting-description"),
    phone: value("business-setting-phone"),
    city: value("business-setting-city"),
    address: value("business-setting-address"),
    schedule: value("business-setting-schedule"),
    maps_url: value("business-setting-maps-url"),
    instagram_url: value("business-setting-instagram-url"),
    reviews_url: value("business-setting-reviews-url"),
    logo_alt: value("business-setting-logo-alt"),
    theme_key: value("business-setting-theme"),
    template_key: value("business-setting-template"),
    primary_color: value("business-setting-primary-hex"),
    secondary_color: value("business-setting-secondary-hex"),
    accent_color: value("business-setting-accent-hex"),
    background_color: value("business-setting-background-hex"),
    active: document.getElementById("business-setting-active").checked
  };

  if (!payload.name) {
    feedback.className = "inline-feedback error";
    feedback.textContent = "El nombre es obligatorio.";
    return;
  }

  feedback.className = "inline-feedback";
  feedback.textContent = "Guardando...";

  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/settings`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }
    );
    const result = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(result?.detail || "Error al guardar.");
    }

    currentBusiness = result.settings;
    applyBusinessData(currentBusiness);
    renderBusinessSettings();
    feedback.className = "inline-feedback success";
    feedback.textContent = "Guardado correctamente";
  } catch (error) {
    console.error(error);
    feedback.className = "inline-feedback error";
    feedback.textContent = error.message || "Error al guardar";
  }
}

function setAdminColor(name, color) {
  document.getElementById(`business-setting-${name}-color`).value = color;
  document.getElementById(`business-setting-${name}-hex`).value = color;
}

function setupAdminBranding() {
  document.getElementById("business-setting-template").addEventListener("change", renderAdminTemplateDescription);
  document.getElementById("business-setting-theme").addEventListener("change", (event) => {
    const colors = BRAND_PALETTES[event.target.value];
    if (colors) BRAND_COLOR_NAMES.forEach((name, index) => setAdminColor(name, colors[index]));
  });
  BRAND_COLOR_NAMES.forEach((name) => {
    const picker = document.getElementById(`business-setting-${name}-color`);
    const hex = document.getElementById(`business-setting-${name}-hex`);
    picker.addEventListener("input", () => { hex.value = picker.value; document.getElementById("business-setting-theme").value = "custom"; });
    hex.addEventListener("input", () => { if (/^#[0-9a-f]{6}$/i.test(hex.value)) picker.value = hex.value; document.getElementById("business-setting-theme").value = "custom"; });
  });
  document.getElementById("upload-admin-logo").addEventListener("click", () => document.getElementById("admin-logo-file").click());
  document.getElementById("admin-logo-file").addEventListener("change", (event) => uploadAdminMedia("logo", event.target));
  document.getElementById("delete-admin-logo").addEventListener("click", deleteAdminLogo);
  document.getElementById("upload-admin-gallery").addEventListener("click", () => document.getElementById("admin-gallery-file").click());
  document.getElementById("admin-gallery-file").addEventListener("change", (event) => uploadAdminMedia("gallery", event.target));
  document.getElementById("admin-gallery-list").addEventListener("click", updateAdminGalleryImage);
}

function renderAdminTemplateDescription() {
  const key = document.getElementById("business-setting-template").value;
  document.getElementById("admin-template-description").textContent = TEMPLATE_DESCRIPTIONS[key] || TEMPLATE_DESCRIPTIONS.classic;
}

function restoreAdminMediaStatus() {
  const raw = sessionStorage.getItem("adminMediaPending");
  if (!raw) return;
  try {
    const pending = JSON.parse(raw);
    if (pending.slug !== getBusinessSlug()) return;
    showAdminBrandFeedback(pending.kind === "logo" ? "Logo actualizado." : "Foto añadida a la galería.");
    sessionStorage.removeItem("adminMediaPending");
  } catch {
    sessionStorage.removeItem("adminMediaPending");
  }
}

async function readAdminResponseBody(response) {
  const text = await response.text();
  if (!text) return {};
  try { return JSON.parse(text); } catch { return { detail: text }; }
}

function adminMediaError(action, response, body) {
  const detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail || body || {});
  console.error("Error de media", { action, url: response.url, status: response.status, body });
  return `No se pudo ${action}. Error ${response.status}: ${detail || response.statusText}`;
}

async function reloadAdminBusiness() {
  const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/settings`);
  const body = await readAdminResponseBody(response);
  if (!response.ok) throw new Error(adminMediaError("recargar el negocio", response, body));
  currentBusiness = body;
  applyBusinessData(currentBusiness);
  renderBusinessSettings();
}

async function uploadAdminMedia(kind, input) {
  const file = input.files?.[0];
  if (!file) {
    showAdminBrandFeedback("Selecciona una imagen JPG, PNG o WEBP.", true);
    return;
  }
  const form = new FormData(); form.append("file", input.files[0]);
  if (kind === "gallery") form.append("alt_text", document.getElementById("admin-gallery-alt").value.trim());
  const action = kind === "logo" ? "subir el logo" : "subir la foto";
  const url = `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/media/${kind}`;
  showAdminBrandFeedback("Subiendo imagen...");
  sessionStorage.setItem("adminMediaPending", JSON.stringify({ slug: getBusinessSlug(), kind }));
  try {
    const response = await fetch(url, { method: "POST", body: form });
    const result = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(adminMediaError(action, response, result));
    input.value = "";
    sessionStorage.removeItem("adminMediaPending");
    if (kind === "logo") await reloadAdminBusiness();
    else await loadAdminGallery();
    showAdminBrandFeedback(kind === "logo" ? "Logo actualizado." : "Foto añadida a la galería.");
  } catch (error) {
    sessionStorage.removeItem("adminMediaPending");
    console.error("Fallo de subida en Admin", { action, url, error });
    showAdminBrandFeedback(error.message || `No se pudo ${action}.`, true);
  }
}

async function deleteAdminLogo() {
  const url = `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/media/logo`;
  try {
    const response = await fetch(url, { method: "DELETE" });
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(adminMediaError("eliminar el logo", response, body));
    await reloadAdminBusiness();
    showAdminBrandFeedback("Logo eliminado.");
  } catch (error) {
    console.error("Fallo eliminando logo en Admin", { url, error });
    showAdminBrandFeedback(error.message, true);
  }
}

async function loadAdminGallery() {
  const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/media/gallery`);
  const body = await readAdminResponseBody(response);
  if (!response.ok) {
    showAdminBrandFeedback(adminMediaError("cargar la galería", response, body), true);
    return;
  }
  adminGallery = body.images || [];
  document.getElementById("admin-gallery-list").innerHTML = adminGallery.map((image) => `<article><img src="${escapeHtml(resolveMediaUrl(image.url, true))}" alt="${escapeHtml(image.alt_text || "Foto")}"><input data-alt-id="${image.id}" value="${escapeHtml(image.alt_text || "")}" placeholder="Texto alternativo"><input data-position-id="${image.id}" type="number" min="0" value="${image.position}"><button class="btn btn-secondary" data-toggle-image="${image.id}" data-active="${!image.active}">${image.active ? "Desactivar" : "Activar"}</button><button class="btn btn-danger" data-delete-image="${image.id}">Eliminar</button></article>`).join("") || "<p>No hay fotos.</p>";
}

async function updateAdminGalleryImage(event) {
  const button = event.target.closest("button"); if (!button) return;
  const id = button.dataset.toggleImage || button.dataset.deleteImage; if (!id) return;
  const url = `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/media/gallery/${id}`;
  try {
    const response = button.dataset.deleteImage
      ? await fetch(url, { method: "DELETE" })
      : await fetch(url, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ active: button.dataset.active === "true", alt_text: document.querySelector(`[data-alt-id="${id}"]`).value, position: Number(document.querySelector(`[data-position-id="${id}"]`).value) }) });
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(adminMediaError("actualizar la galería", response, body));
    await loadAdminGallery();
    showAdminBrandFeedback(button.dataset.deleteImage ? "Foto eliminada." : "Foto actualizada.");
  } catch (error) {
    console.error("Fallo gestionando galería en Admin", { url, error });
    showAdminBrandFeedback(error.message, true);
  }
}

function showAdminBrandFeedback(message, error = false) { const el = document.getElementById("admin-brand-feedback"); el.textContent = message; el.className = `inline-feedback ${error ? "error" : "success"}`; }

async function loadAdminServices() {
  const container = document.getElementById("admin-services-list");
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/services`
    );
    if (!response.ok) {
      throw new Error("No se pudieron cargar los servicios.");
    }
    const data = await response.json();
    adminServices = data.services || [];
    renderAdminServices();
  } catch (error) {
    console.error(error);
    container.innerHTML = `<p class="empty-state">No se pudieron cargar los servicios.</p>`;
  }
}

function renderAdminServices() {
  const container = document.getElementById("admin-services-list");
  document.getElementById("stat-services-active").textContent =
    adminServices.filter((service) => service.active).length;
  if (!adminServices.length) {
    container.innerHTML = `<p class="empty-state">Todavía no hay servicios configurados.</p>`;
    return;
  }

  container.innerHTML = adminServices.map((service) => `
    <article class="admin-service-item ${service.active ? "" : "inactive"}" data-service-id="${service.id}">
      <div class="service-edit-grid">
        <label>Nombre<input class="service-name" type="text" value="${escapeHtml(service.name)}" /></label>
        <label>Precio<input class="service-price" type="text" value="${escapeHtml(service.price_text || "")}" /></label>
        <label>Duración<input class="service-duration" type="number" min="1" max="1440" value="${service.duration_minutes || ""}" /></label>
        <label class="field-wide">Descripción<textarea class="service-description" rows="2">${escapeHtml(service.description || "")}</textarea></label>
        <label class="active-setting"><input class="service-active" type="checkbox" ${service.active ? "checked" : ""} />Activo</label>
      </div>
      <button class="btn btn-small btn-secondary" type="button" onclick="saveAdminService(${service.id})">Guardar servicio</button>
    </article>
  `).join("");
}

function readServiceForm(container) {
  return {
    name: container.querySelector(".service-name").value.trim(),
    description: container.querySelector(".service-description").value.trim(),
    price_text: container.querySelector(".service-price").value.trim(),
    duration_minutes: Number(container.querySelector(".service-duration").value),
    active: container.querySelector(".service-active").checked
  };
}

function validateServicePayload(payload) {
  if (!payload.name) {
    throw new Error("El nombre del servicio es obligatorio.");
  }
  if (!Number.isInteger(payload.duration_minutes) || payload.duration_minutes <= 0) {
    throw new Error("La duración debe ser mayor que cero.");
  }
}

async function saveAdminService(serviceId) {
  const feedback = document.getElementById("services-feedback");
  try {
    const container = document.querySelector(`[data-service-id="${serviceId}"]`);
    const payload = readServiceForm(container);
    validateServicePayload(payload);
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/services/${serviceId}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }
    );
    const result = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(result?.detail || "No se pudo guardar el servicio.");
    }
    feedback.className = "inline-feedback success";
    feedback.textContent = "Servicio guardado correctamente.";
    await loadAdminServices();
  } catch (error) {
    console.error(error);
    feedback.className = "inline-feedback error";
    feedback.textContent = error.message || "No se pudo guardar el servicio.";
  }
}

async function createAdminService() {
  const feedback = document.getElementById("services-feedback");
  const payload = {
    name: document.getElementById("new-service-name").value.trim(),
    description: document.getElementById("new-service-description").value.trim(),
    price_text: document.getElementById("new-service-price").value.trim(),
    duration_minutes: Number(document.getElementById("new-service-duration").value),
    active: true
  };

  try {
    validateServicePayload(payload);
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/services`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }
    );
    const result = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(result?.detail || "No se pudo crear el servicio.");
    }

    ["new-service-name", "new-service-description", "new-service-price", "new-service-duration"]
      .forEach((id) => { document.getElementById(id).value = ""; });
    feedback.className = "inline-feedback success";
    feedback.textContent = "Servicio creado correctamente.";
    await loadAdminServices();
  } catch (error) {
    console.error(error);
    feedback.className = "inline-feedback error";
    feedback.textContent = error.message || "No se pudo crear el servicio.";
  }
}

async function loadBookings() {
  const slug = getBusinessSlug();
  const list = document.getElementById("bookings-list");
  list.innerHTML = `<p class="empty-state">Cargando reservas...</p>`;

  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${slug}/bookings`);

    if (!response.ok) {
      list.innerHTML = `<p class="empty-state">No se pudieron cargar las reservas.</p>`;
      return;
    }

    const data = await response.json();
    allBookings = data.bookings || [];

    await Promise.all([enrichBookingsWithAttachments(), loadReviewRequests()]);
    growthDataReady.bookings = true;
    renderStats(allBookings);
    renderReviewStats();
    renderReviewRequests();
    renderBookings();
    renderGrowth();
  } catch (error) {
    console.error(error);
    list.innerHTML = `<p class="empty-state">Error conectando con el backend.</p>`;
  }
}

async function loadReviewRequests() {
  const response = await fetch(
    `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/review-requests`
  );

  if (!response.ok) {
    reviewRequestsByBooking = new Map();
    throw new Error("No se pudieron cargar las solicitudes de reseña.");
  }

  const data = await response.json();
  reviewRequestsByBooking = new Map(
    (data.review_requests || []).map((reviewRequest) => [reviewRequest.booking_id, reviewRequest])
  );
  growthDataReady.reviews = true;
}

async function loadMessageOutbox() {
  const container = document.getElementById("message-outbox-list");

  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/message-outbox`
    );

    if (!response.ok) {
      throw new Error("No se pudieron cargar los mensajes.");
    }

    const data = await response.json();
    messageOutbox = data.messages || [];
    growthDataReady.messages = true;
    renderMessageOutboxMetrics();
    renderMessageOutbox();
    renderGrowth();
  } catch (error) {
    console.error(error);
    container.innerHTML = `<p class="empty-state">No se pudieron cargar los mensajes.</p>`;
    document.getElementById("message-outbox-history-list").innerHTML =
      `<p class="empty-state">No se pudo cargar el historial.</p>`;
  }
}

function renderMessageOutboxMetrics() {
  const operationalMessages = messageOutbox.filter(
    (message) => message.message_type !== "booking_requested"
  );
  ["pending", "opened", "sent", "skipped"].forEach((status) => {
    const count = operationalMessages.filter((message) => message.status === status).length;
    document.getElementById(`message-count-${status}`).textContent = count;
    const summaryMetric = document.getElementById(`stat-messages-${status}`);
    if (summaryMetric) {
      summaryMetric.textContent = count;
    }
  });
}

function renderMessageOutbox() {
  const activeContainer = document.getElementById("message-outbox-list");
  const historyContainer = document.getElementById("message-outbox-history-list");
  const selectedStatus = document.getElementById("message-status-filter").value;
  const activeStatuses = ["pending", "opened", "failed"];
  const historyStatuses = ["sent", "skipped"];
  let activeMessages = messageOutbox.filter(
    (message) => message.message_type !== "booking_requested" && activeStatuses.includes(message.status)
  );
  let historyMessages = messageOutbox.filter(
    (message) => message.message_type === "booking_requested" || historyStatuses.includes(message.status)
  );

  if (!["active", "all"].includes(selectedStatus)) {
    activeMessages = activeMessages.filter((message) => message.status === selectedStatus);
    historyMessages = historyMessages.filter((message) => message.status === selectedStatus);
  }

  activeContainer.innerHTML = renderMessageCards(activeMessages);
  historyContainer.innerHTML = renderMessageCards(historyMessages, "No hay mensajes enviados u omitidos en el historial.");
}

function renderMessageCards(messages, emptyMessage = "No hay mensajes para este filtro.") {
  if (!messages.length) {
    return `<p class="empty-state">${emptyMessage}</p>`;
  }

  return messages.map((message) => {
    const phoneIsValid = Boolean(message.whatsapp_url);
    const isClosed = ["sent", "skipped"].includes(message.status);
    return `
      <article class="message-outbox-item">
        <div class="message-outbox-header">
          <div>
            <span class="message-type">${getMessageTypeLabel(message.message_type)}</span>
            <h3>${escapeHtml(message.customer_name)}</h3>
            <p>${escapeHtml(message.customer_phone || "Sin teléfono")} ${message.booking_id ? `· Cita #${message.booking_id}` : ""}</p>
          </div>
          <span class="status-pill ${getMessageStatusClass(message.status)}">${getMessageStatusLabel(message.status)}</span>
        </div>
        <p class="message-preview">${escapeHtml(message.message)}</p>
        ${phoneIsValid ? "" : `<p class="message-phone-warning">Este cliente no tiene un teléfono válido para WhatsApp.</p>`}
        <div class="message-actions">
          <button class="btn btn-small btn-whatsapp" type="button" onclick="openWhatsAppMessage(${message.id})" ${!phoneIsValid || isClosed ? "disabled" : ""}>
            Enviar por WhatsApp
          </button>
          <button class="btn btn-small btn-success" type="button" onclick="updateOutboxStatus(${message.id}, 'sent')" ${message.status === "sent" ? "disabled" : ""}>
            Marcar como enviado
          </button>
          <button class="btn btn-small btn-secondary" type="button" onclick="updateOutboxStatus(${message.id}, 'skipped')" ${message.status === "skipped" ? "disabled" : ""}>
            Omitir
          </button>
        </div>
      </article>
    `;
  }).join("");
}

function getMessageTypeLabel(messageType) {
  const labels = {
    booking_requested: "Solicitud recibida",
    booking_confirmed: "Cita confirmada",
    booking_rejected: "Cita rechazada",
    booking_rescheduled: "Cita reagendada",
    booking_completed_review: "Solicitud de reseña"
  };
  return labels[messageType] || messageType;
}

function getMessageStatusLabel(status) {
  const labels = {
    pending: "Pendiente",
    opened: "Preparado",
    sent: "Enviado",
    skipped: "Omitido",
    failed: "Error"
  };
  return labels[status] || status;
}

function getMessageStatusClass(status) {
  const classes = {
    pending: "status-requested",
    opened: "status-completed",
    sent: "status-confirmed",
    skipped: "status-rejected",
    failed: "status-rejected"
  };
  return classes[status] || "status-requested";
}

async function openWhatsAppMessage(messageId) {
  const message = messageOutbox.find((item) => item.id === messageId);
  const whatsappWindow = openBlankWhatsAppWindow();

  await openPreparedWhatsAppMessage(message, whatsappWindow);
}

function openBlankWhatsAppWindow() {
  const whatsappWindow = window.open("about:blank", "_blank");

  if (whatsappWindow) {
    whatsappWindow.opener = null;
  }

  return whatsappWindow;
}

async function openPreparedWhatsAppMessage(message, whatsappWindow) {
  if (!message?.whatsapp_url) {
    whatsappWindow?.close();
    alert("No se puede abrir WhatsApp porque el teléfono del cliente no es válido.");
    return false;
  }

  if (!whatsappWindow) {
    alert("El navegador ha bloqueado la nueva pestaña de WhatsApp.");
    return false;
  }

  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/message-outbox/${message.id}/opened`,
      { method: "PATCH" }
    );
    const result = await response.json().catch(() => null);

    if (!response.ok) {
      throw new Error(result?.detail || "No se pudo preparar el mensaje.");
    }

    replaceOutboxMessage(result.message);
    whatsappWindow.location.href = result.message.whatsapp_url;
    return true;
  } catch (error) {
    whatsappWindow.close();
    console.error(error);
    alert(error.message || "No se pudo preparar el mensaje.");
    return false;
  }
}

async function updateOutboxStatus(messageId, status) {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/message-outbox/${messageId}/status`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status })
      }
    );
    const result = await response.json().catch(() => null);

    if (!response.ok) {
      throw new Error(result?.detail || "No se pudo actualizar el mensaje.");
    }

    replaceOutboxMessage(result.message);
  } catch (error) {
    console.error(error);
    alert(error.message || "No se pudo actualizar el mensaje.");
  }
}

function replaceOutboxMessage(updatedMessage) {
  const exists = messageOutbox.some((message) => message.id === updatedMessage.id);
  messageOutbox = exists
    ? messageOutbox.map((message) => message.id === updatedMessage.id ? updatedMessage : message)
    : [updatedMessage, ...messageOutbox];
  renderMessageOutboxMetrics();
  renderMessageOutbox();
  renderGrowth();
}

async function refreshOperationalData() {
  await Promise.all([loadBookings(), loadMessageOutbox()]);
}

async function enrichBookingsWithAttachments() {
  const slug = getBusinessSlug();
  const promises = allBookings.map(async (booking) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/businesses/${slug}/bookings/${booking.id}/attachments`);

      if (!response.ok) {
        booking.attachments = [];
        return;
      }

      const data = await response.json();
      booking.attachments = data.attachments || [];
    } catch (error) {
      console.error(error);
      booking.attachments = [];
    }
  });

  await Promise.all(promises);
}

function renderStats(bookings) {
  const total = bookings.length;
  const requested = bookings.filter((booking) => ["requested", "pending"].includes(booking.status)).length;
  const confirmed = bookings.filter((booking) => booking.status === "confirmed").length;
  const completed = bookings.filter((booking) => booking.status === "completed").length;

  document.getElementById("stat-total").textContent = total;
  document.getElementById("stat-requested").textContent = requested;
  document.getElementById("stat-confirmed").textContent = confirmed;
  document.getElementById("stat-completed").textContent = completed;
}

function renderReviewStats() {
  const reviewRequests = Array.from(reviewRequestsByBooking.values());
  document.getElementById("stat-reviews-pending").textContent =
    reviewRequests.filter((item) => item.status === "pending").length;
  document.getElementById("stat-reviews-copied").textContent =
    reviewRequests.filter((item) => item.status === "copied").length;
  document.getElementById("stat-reviews-sent").textContent =
    reviewRequests.filter((item) => item.status === "sent").length;
}

function renderReviewRequests() {
  const pendingContainer = document.getElementById("review-requests-pending-list");
  const historyContainer = document.getElementById("review-requests-history-list");
  const reviewRequests = Array.from(reviewRequestsByBooking.values());
  const pending = reviewRequests.filter((item) => ["pending", "copied"].includes(item.status));
  const history = reviewRequests.filter((item) => ["sent", "skipped"].includes(item.status));

  pendingContainer.innerHTML = pending.length
    ? pending.map(renderReviewSummaryCard).join("")
    : `<p class="empty-state">No hay solicitudes de reseña pendientes.</p>`;
  historyContainer.innerHTML = history.length
    ? history.map(renderReviewSummaryCard).join("")
    : `<p class="empty-state">No hay solicitudes enviadas u omitidas.</p>`;
}

function renderReviewSummaryCard(reviewRequest) {
  return `
    <article class="review-summary-card">
      <div class="review-request-header">
        <div>
          <h3>${escapeHtml(reviewRequest.customer_name)}</h3>
          <p>Cita #${reviewRequest.booking_id}</p>
        </div>
        <span class="review-status review-status-${escapeHtml(reviewRequest.status)}">
          ${getReviewStatusLabel(reviewRequest.status)}
        </span>
      </div>
      <p class="review-message">${escapeHtml(reviewRequest.message)}</p>
      <textarea data-review-fallback="${reviewRequest.id}" class="review-copy-fallback" readonly>${escapeHtml(reviewRequest.message)}</textarea>
      <div class="review-actions">
        <button class="btn btn-small btn-whatsapp" type="button" onclick="openReviewWhatsApp(${reviewRequest.id})" ${["sent", "skipped"].includes(reviewRequest.status) ? "disabled" : ""}>
          Enviar por WhatsApp
        </button>
        <button class="btn btn-small btn-success" type="button" onclick="updateReviewRequestStatus(${reviewRequest.id}, 'sent')" ${reviewRequest.status === "sent" ? "disabled" : ""}>
          Marcar como enviada
        </button>
        <button class="btn btn-small btn-secondary" type="button" onclick="updateReviewRequestStatus(${reviewRequest.id}, 'skipped')" ${reviewRequest.status === "skipped" ? "disabled" : ""}>
          Omitir
        </button>
      </div>
      <p data-review-feedback="${reviewRequest.id}" class="inline-feedback"></p>
    </article>
  `;
}

function getBookingsForView(view) {
  const today = getMadridDateKey();
  const tomorrow = addDaysToDateKey(today, 1);
  const isPending = (booking) => ["requested", "pending"].includes(booking.status);
  const isClosed = (booking) => ["completed", "rejected", "cancelled"].includes(booking.status);
  const bookingDate = (booking) => getBookingDateKey(booking);
  let bookings;

  if (view === "pending") {
    bookings = allBookings.filter(isPending);
  } else if (view === "today") {
    bookings = allBookings.filter((booking) => !isPending(booking) && !isClosed(booking) && bookingDate(booking) === today);
  } else if (view === "tomorrow") {
    bookings = allBookings.filter((booking) => !isPending(booking) && !isClosed(booking) && bookingDate(booking) === tomorrow);
  } else if (view === "upcoming") {
    bookings = allBookings.filter((booking) =>
      !isPending(booking) && !isClosed(booking) && (!bookingDate(booking) || bookingDate(booking) > tomorrow)
    );
  } else {
    bookings = allBookings.filter((booking) =>
      !isPending(booking) && (isClosed(booking) || (bookingDate(booking) && bookingDate(booking) < today))
    );
  }

  if (["today", "tomorrow", "upcoming"].includes(view)) {
    return bookings.sort((first, second) =>
      (first.start_datetime || first.preferred_date || "").localeCompare(second.start_datetime || second.preferred_date || "")
    );
  }

  return bookings;
}

function renderBookings() {
  const list = document.getElementById("bookings-list");
  const bookings = getBookingsForView(currentBookingView);
  const emptyMessages = {
    pending: "No hay citas pendientes.",
    today: "No tienes citas para hoy.",
    tomorrow: "No tienes citas para mañana.",
    upcoming: "No hay próximas citas.",
    history: "Todavía no hay historial."
  };

  if (!bookings.length) {
    list.innerHTML = `<p class="empty-state">${emptyMessages[currentBookingView]}</p>`;
    return;
  }

  list.innerHTML = "";

  bookings.forEach((booking) => {
    const card = document.createElement("article");
    card.className = "booking-card";
    card.innerHTML = `
      <div class="booking-top">
        <div class="booking-title">
          <h3>${escapeHtml(booking.customer_name)}</h3>
          <p>${escapeHtml(booking.service_name)}</p>
        </div>
        <span class="status-pill ${getStatusClass(booking.status)}">${getStatusLabel(booking.status)}</span>
      </div>
      <div class="booking-grid">
        <div class="booking-field">
          <span>Teléfono</span>
          <strong>${escapeHtml(booking.customer_phone || "No indicado")}</strong>
        </div>
        <div class="booking-field">
          <span>Fecha y hora</span>
          <strong>${escapeHtml(formatBookingSlot(booking))}</strong>
        </div>
        <div class="booking-field">
          <span>Duración</span>
          <strong>${booking.duration_minutes ? `${booking.duration_minutes} min` : "No indicada"}</strong>
        </div>
        <div class="booking-field">
          <span>Creada</span>
          <strong>${formatDateTime(booking.created_at)}</strong>
        </div>
      </div>
      ${renderNotes(booking.notes)}
      ${renderBookingActions(booking)}
      ${renderReviewRequest(booking)}
      ${renderAttachments(booking.attachments || [])}
    `;

    list.appendChild(card);
  });
}

function renderReviewRequest(booking) {
  if (booking.status !== "completed") {
    return "";
  }

  const reviewRequest = reviewRequestsByBooking.get(booking.id);

  if (!reviewRequest && !currentBusiness?.reviews_url?.trim()) {
    return `
      <div class="review-request review-request-warning">
        <strong>Solicitud de reseña</strong>
        <p>Este negocio todavía no tiene enlace de reseñas configurado.</p>
      </div>
    `;
  }

  if (!reviewRequest) {
    return `
      <div class="review-request">
        <div class="review-request-header">
          <strong>Solicitud de reseña</strong>
          <span class="review-status">No creada</span>
        </div>
        <button class="btn btn-small btn-secondary" type="button" onclick="createReviewRequest(${booking.id})">
          Crear solicitud
        </button>
      </div>
    `;
  }

  return `
    <div class="review-request">
      <div class="review-request-header">
        <strong>Solicitud de reseña</strong>
        <span class="review-status review-status-${escapeHtml(reviewRequest.status)}">
          ${getReviewStatusLabel(reviewRequest.status)}
        </span>
      </div>
      <p class="review-message">${escapeHtml(reviewRequest.message)}</p>
      <textarea data-review-fallback="${reviewRequest.id}" class="review-copy-fallback" readonly>${escapeHtml(reviewRequest.message)}</textarea>
      <div class="review-actions">
        <button class="btn btn-small btn-whatsapp" type="button" onclick="openReviewWhatsApp(${reviewRequest.id})" ${["sent", "skipped"].includes(reviewRequest.status) ? "disabled" : ""}>
          Enviar por WhatsApp
        </button>
        <button class="btn btn-small btn-success" type="button" onclick="updateReviewRequestStatus(${reviewRequest.id}, 'sent')" ${reviewRequest.status === "sent" ? "disabled" : ""}>
          Marcar como enviada
        </button>
        <button class="btn btn-small btn-secondary" type="button" onclick="updateReviewRequestStatus(${reviewRequest.id}, 'skipped')" ${reviewRequest.status === "skipped" ? "disabled" : ""}>
          Omitir
        </button>
      </div>
      <p data-review-feedback="${reviewRequest.id}" class="inline-feedback"></p>
    </div>
  `;
}

function getReviewStatusLabel(status) {
  const labels = {
    pending: "Pendiente",
    copied: "Copiada",
    sent: "Enviada",
    skipped: "Omitida"
  };
  return labels[status] || status;
}

async function createReviewRequest(bookingId) {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/bookings/${bookingId}/review-request`,
      { method: "POST" }
    );
    const result = await response.json().catch(() => null);

    if (!response.ok) {
      throw new Error(result?.detail || "No se pudo crear la solicitud de reseña.");
    }

    reviewRequestsByBooking.set(bookingId, result.review_request);
    renderReviewStats();
    renderReviewRequests();
    renderBookings();
    renderGrowth();
    await loadMessageOutbox();
  } catch (error) {
    console.error(error);
    alert(error.message || "No se pudo crear la solicitud de reseña.");
  }
}

async function openReviewWhatsApp(reviewRequestId) {
  const reviewRequest = Array.from(reviewRequestsByBooking.values())
    .find((item) => item.id === reviewRequestId);
  const whatsappWindow = openBlankWhatsAppWindow();

  if (!reviewRequest) {
    whatsappWindow?.close();
    alert("No se encontró la solicitud de reseña.");
    return;
  }

  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/bookings/${reviewRequest.booking_id}/review-request`,
      { method: "POST" }
    );
    const result = await response.json().catch(() => null);

    if (!response.ok) {
      throw new Error(result?.detail || "No se pudo preparar la solicitud de reseña.");
    }

    reviewRequestsByBooking.set(reviewRequest.booking_id, result.review_request);
    renderReviewStats();
    renderReviewRequests();
    renderBookings();
    renderGrowth();
    await openPreparedWhatsAppMessage(result.outbox_message, whatsappWindow);
  } catch (error) {
    whatsappWindow?.close();
    console.error(error);
    alert(error.message || "No se pudo preparar el mensaje de WhatsApp.");
  }
}

async function copyReviewMessage(reviewRequestId) {
  const reviewRequest = Array.from(reviewRequestsByBooking.values())
    .find((item) => item.id === reviewRequestId);

  if (!reviewRequest) {
    return;
  }

  try {
    await navigator.clipboard.writeText(reviewRequest.message);
    await updateReviewRequestStatus(reviewRequestId, "copied", false);
    document.querySelectorAll(`[data-review-feedback="${reviewRequestId}"]`).forEach((feedback) => {
      feedback.className = "inline-feedback success";
      feedback.textContent = "Mensaje copiado";
    });
  } catch (error) {
    console.error(error);
    const textareas = document.querySelectorAll(`[data-review-fallback="${reviewRequestId}"]`);
    textareas.forEach((textarea) => textarea.classList.add("visible"));
    const visibleTextarea = Array.from(textareas).find((textarea) => textarea.offsetParent !== null) || textareas[0];
    visibleTextarea?.focus();
    visibleTextarea?.select();
    document.querySelectorAll(`[data-review-feedback="${reviewRequestId}"]`).forEach((feedback) => {
      feedback.className = "inline-feedback error";
      feedback.textContent = "No se pudo copiar automáticamente. Selecciona el mensaje para copiarlo manualmente.";
    });
  }
}

async function updateReviewRequestStatus(reviewRequestId, status, showFeedback = true) {
  const response = await fetch(
    `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/review-requests/${reviewRequestId}/status`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status })
    }
  );
  const result = await response.json().catch(() => null);

  if (!response.ok) {
    if (showFeedback) {
      alert(result?.detail || "No se pudo actualizar la solicitud de reseña.");
    }
    throw new Error(result?.detail || "No se pudo actualizar la solicitud de reseña.");
  }

  reviewRequestsByBooking.set(result.review_request.booking_id, result.review_request);
  renderReviewStats();
  renderReviewRequests();
  renderBookings();
  renderGrowth();

  if (showFeedback) {
    document.querySelectorAll(`[data-review-feedback="${reviewRequestId}"]`).forEach((feedback) => {
      feedback.className = "inline-feedback success";
      feedback.textContent = status === "sent" ? "Solicitud marcada como enviada." : "Estado actualizado.";
    });
  }
}

function formatBookingSlot(booking) {
  if (booking.start_datetime) {
    const value = new Date(booking.start_datetime);
    return value.toLocaleString("es-ES", {
      dateStyle: "medium",
      timeStyle: "short"
    });
  }

  return `${booking.preferred_day_label || ""} · ${booking.preferred_time || ""}`.trim();
}

function renderNotes(notes) {
  if (!notes) {
    return `<div class="booking-notes">Sin comentarios adicionales.</div>`;
  }

  return `<div class="booking-notes">${escapeHtml(notes)}</div>`;
}

function renderAttachments(attachments) {
  if (!attachments.length) {
    return `
      <div class="attachments">
        <p class="attachments-title">Fotos adjuntas</p>
        <p class="empty-state">No hay fotos adjuntas.</p>
      </div>
    `;
  }

  const items = attachments.map((attachment) => {
    const imageUrl = `${API_BASE_URL}${attachment.url}`;
    return `
      <a href="${imageUrl}" target="_blank" rel="noopener noreferrer">
        <img src="${imageUrl}" alt="${escapeHtml(attachment.original_filename || "Foto adjunta")}" />
      </a>
    `;
  }).join("");

  return `
    <div class="attachments">
      <p class="attachments-title">Fotos adjuntas</p>
      <div class="attachments-grid">${items}</div>
    </div>
  `;
}

function renderBookingActions(booking) {
  const isCompleted = booking.status === "completed";
  const isRejected = booking.status === "rejected";
  const isCancelled = booking.status === "cancelled";
  const isClosed = isCompleted || isRejected || isCancelled;

  return `
    <div class="booking-actions">
      <button class="btn btn-small btn-success" type="button" onclick="updateBookingStatus(${booking.id}, 'confirmed')" ${booking.status === "confirmed" || isClosed ? "disabled" : ""}>
        Confirmar
      </button>
      <button class="btn btn-small btn-warning" type="button" onclick="rescheduleBooking(${booking.id})" ${isClosed || !booking.service_id ? "disabled" : ""}>
        Reagendar
      </button>
      <button class="btn btn-small btn-danger" type="button" onclick="updateBookingStatus(${booking.id}, 'rejected')" ${booking.status === "rejected" || isCompleted || isCancelled ? "disabled" : ""}>
        Rechazar
      </button>
      <button class="btn btn-small btn-secondary" type="button" onclick="updateBookingStatus(${booking.id}, 'completed')" ${booking.status === "completed" || isRejected || isCancelled ? "disabled" : ""}>
        Completada
      </button>
    </div>
  `;
}

function rescheduleBooking(bookingId) {
  const booking = allBookings.find((item) => item.id === bookingId);

  if (!booking) {
    alert("No se encontró la reserva.");
    return;
  }

  if (!booking.service_id) {
    alert("Esta reserva antigua no tiene servicio asociado y no se puede reagendar con huecos reales.");
    return;
  }

  openRescheduleModal(booking);
}

function openRescheduleModal(booking) {
  const modal = document.getElementById("reschedule-modal");
  const modalTitle = document.getElementById("reschedule-modal-title");
  const modalContent = document.getElementById("reschedule-modal-content");

  rescheduleState = {
    booking,
    date: "",
    dayLabel: "",
    slot: null
  };

  modalTitle.textContent = `Reagendar cita de ${booking.customer_name}`;
  modalContent.innerHTML = `
    <div class="reschedule-summary">
      <p><strong>Servicio actual:</strong> ${escapeHtml(booking.service_name)}</p>
      <p><strong>Cita actual:</strong> ${escapeHtml(formatBookingSlot(booking))}</p>
    </div>
    <div>
      <p class="calendar-title">1. Elige un día</p>
      <div id="reschedule-days" class="calendar-days"></div>
    </div>
    <div>
      <p class="calendar-title">2. Elige un hueco disponible</p>
      <div id="reschedule-slots" class="reschedule-slots">
        <p class="empty-state">Selecciona primero un día.</p>
      </div>
    </div>
    <button id="confirm-reschedule-button" class="btn btn-primary btn-full" type="button" disabled>
      Confirmar cambio
    </button>
  `;

  modal.classList.add("open");
  renderRescheduleDays();
  document.getElementById("confirm-reschedule-button").addEventListener("click", confirmSelectedReschedule);
}

function renderRescheduleDays() {
  const container = document.getElementById("reschedule-days");
  container.innerHTML = "";

  getNextDays(availabilitySettings?.max_days_ahead || 21).forEach((day) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "calendar-day";

    const firstPart = day.day_label.split(" ")[0];
    const secondPart = day.day_label.replace(`${firstPart} `, "");

    button.innerHTML = `
      <strong>${firstPart}</strong>
      <span>${secondPart}</span>
    `;

    button.addEventListener("click", async () => {
      rescheduleState.date = day.date;
      rescheduleState.dayLabel = day.day_label;
      rescheduleState.slot = null;
      document.getElementById("confirm-reschedule-button").disabled = true;
      document.querySelectorAll("#reschedule-days .calendar-day").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      await loadRescheduleSlots();
    });

    container.appendChild(button);
  });
}

async function loadRescheduleSlots() {
  const container = document.getElementById("reschedule-slots");
  const booking = rescheduleState.booking;
  container.innerHTML = `<p class="empty-state">Cargando huecos disponibles...</p>`;

  try {
    const response = await fetch(
      `${API_BASE_URL}/api/businesses/${getBusinessSlug()}/available-slots?service_id=${encodeURIComponent(booking.service_id)}&date=${encodeURIComponent(rescheduleState.date)}&exclude_booking_id=${encodeURIComponent(booking.id)}`
    );

    if (!response.ok) {
      throw new Error("No se pudo cargar la disponibilidad.");
    }

    const data = await response.json();
    renderRescheduleSlots(data.slots || []);
  } catch (error) {
    console.error(error);
    container.innerHTML = `<p class="empty-state">No se pudo cargar la disponibilidad.</p>`;
  }
}

function renderRescheduleSlots(slots) {
  const container = document.getElementById("reschedule-slots");
  container.innerHTML = "";

  if (!slots.length) {
    container.innerHTML = `<p class="empty-state">No hay huecos disponibles para este día</p>`;
    return;
  }

  slots.forEach((slot) => {
    const button = document.createElement("button");
    button.className = "time-slot";
    button.type = "button";
    button.textContent = slot.label;

    button.addEventListener("click", () => {
      rescheduleState.slot = slot;
      document.querySelectorAll("#reschedule-slots .time-slot").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      document.getElementById("confirm-reschedule-button").disabled = false;
    });

    container.appendChild(button);
  });
}

async function confirmSelectedReschedule() {
  const { booking, slot, dayLabel } = rescheduleState;

  if (!booking || !slot) {
    alert("Selecciona un hueco disponible.");
    return;
  }

  const confirmed = window.confirm(`¿Reagendar esta cita a ${dayLabel} a las ${slot.label}?`);

  if (!confirmed) {
    return;
  }

  const whatsappWindow = openBlankWhatsAppWindow();

  try {
    const response = await fetch(`${API_BASE_URL}/api/bookings/${booking.id}/reschedule`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        start_datetime: slot.start,
        preferred_day_label: dayLabel
      })
    });

    if (!response.ok) {
      const error = await response.json().catch(() => null);
      whatsappWindow?.close();
      console.error("Error reagendando cita:", error);
      alert(error?.detail || "Ese hueco ya no está disponible");
      await loadRescheduleSlots();
      return;
    }

    const result = await response.json();
    await openPreparedWhatsAppMessage(result.outbox_message, whatsappWindow);
    alert("Cita reagendada correctamente");
    closeRescheduleModal();
    await refreshOperationalData();
  } catch (error) {
    whatsappWindow?.close();
    console.error(error);
    alert("No se pudo conectar con el backend.");
  }
}

function getNextDays(count) {
  const formatter = new Intl.DateTimeFormat("es-ES", {
    weekday: "short",
    day: "2-digit",
    month: "short"
  });
  const days = [];

  for (let index = 0; index < count; index += 1) {
    const value = new Date();
    value.setDate(value.getDate() + index);
    days.push({
      date: value.toISOString().slice(0, 10),
      day_label: formatter.format(value).replace(",", "")
    });
  }

  return days;
}

function closeRescheduleModal() {
  document.getElementById("reschedule-modal")?.classList.remove("open");
}

async function updateBookingStatus(bookingId, status) {
  const slug = getBusinessSlug();
  const confirmMessages = {
    confirmed: "¿Confirmar esta cita?",
    rejected: "¿Rechazar esta cita?",
    completed: "¿Marcar esta cita como completada?"
  };
  const confirmed = window.confirm(confirmMessages[status] || "¿Cambiar estado?");

  if (!confirmed) {
    return;
  }

  const shouldOpenWhatsApp = ["confirmed", "rejected", "completed"].includes(status);
  const whatsappWindow = shouldOpenWhatsApp ? openBlankWhatsAppWindow() : null;

  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${slug}/bookings/${bookingId}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status })
    });

    const result = await response.json().catch(() => null);

    if (!response.ok) {
      throw new Error(result?.detail || "No se pudo cambiar el estado de la cita.");
    }

    if (shouldOpenWhatsApp) {
      if (result?.outbox_message) {
        await openPreparedWhatsAppMessage(result.outbox_message, whatsappWindow);
      } else {
        whatsappWindow?.close();
        alert(result?.review_request_warning || "No se pudo preparar el mensaje de WhatsApp.");
      }
    }

    await refreshOperationalData();
  } catch (error) {
    whatsappWindow?.close();
    console.error(error);
    alert(error.message || "No se pudo conectar con el backend.");
  }
}

function getStatusClass(status) {
  const classes = {
    requested: "status-requested",
    pending: "status-requested",
    confirmed: "status-confirmed",
    completed: "status-completed",
    rejected: "status-rejected",
    cancelled: "status-rejected"
  };

  return classes[status] || "status-requested";
}

function getStatusLabel(status) {
  const labels = {
    requested: "Pendiente",
    pending: "Pendiente",
    confirmed: "Confirmada",
    completed: "Completada",
    rejected: "Rechazada",
    cancelled: "Cancelada"
  };

  return labels[status] || status;
}

function formatDateTime(value) {
  if (!value) {
    return "No disponible";
  }

  const date = new Date(value);
  return date.toLocaleString("es-ES", {
    dateStyle: "short",
    timeStyle: "short"
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderError(message) {
  document.body.innerHTML = `
    <main class="admin-page">
      <section class="section">
        <h1>Error</h1>
        <p>${escapeHtml(message)}</p>
      </section>
    </main>
  `;
}

document.addEventListener("DOMContentLoaded", () => {
  setupAdminNavigation();
  setupBookingViews();
  document.getElementById("refresh-button").addEventListener("click", refreshOperationalData);
  document.getElementById("message-status-filter").addEventListener("change", renderMessageOutbox);
  document.getElementById("save-business-settings").addEventListener("click", saveBusinessSettings);
  document.getElementById("create-service").addEventListener("click", createAdminService);
  document.getElementById("save-availability-settings").addEventListener("click", saveAvailabilitySettings);
  document.getElementById("save-availability-exception").addEventListener("click", saveAvailabilityException);
  setupExceptionForm();
  setupAdminBranding();
  document.getElementById("admin-logout").addEventListener("click", adminLogout);
  document.getElementById("admin-gate-logout").addEventListener("click", adminLogout);
  bootstrapAdminAuth();
});

async function showAdminLogin(message = "Inicia sesión con la cuenta asignada al negocio.", denied = false) {
  document.getElementById("admin-app").hidden = true;
  document.getElementById("admin-auth-gate").hidden = false;
  document.getElementById("admin-auth-message").textContent = message;
  document.getElementById("admin-gate-logout").hidden = !denied;
  if (!denied) {
    await AutonoGrowAuth.renderGoogleButton(document.getElementById("admin-google-button"), bootstrapAdminAuth, (error) => {
      document.getElementById("admin-auth-message").textContent = error.message;
    });
  } else document.getElementById("admin-google-button").innerHTML = "";
}

async function bootstrapAdminAuth() {
  try {
    adminAuthUser = await AutonoGrowAuth.getMe();
    if (!adminAuthUser) return showAdminLogin();
    const slug = getBusinessSlug();
    const allowed = adminAuthUser.is_owner || adminAuthUser.businesses.some((item) => item.slug === slug);
    if (!allowed) return showAdminLogin("Tu cuenta no tiene acceso a este negocio.", true);
    document.getElementById("admin-auth-gate").hidden = true;
    document.getElementById("admin-app").hidden = false;
    document.getElementById("admin-auth-user").textContent = adminAuthUser.name || adminAuthUser.email;
    await loadAdminPanel();
  } catch (error) {
    console.error("Admin authentication failed", error);
    await showAdminLogin(error.message);
  }
}

async function adminLogout() {
  await AutonoGrowAuth.logout();
  adminAuthUser = null;
  await showAdminLogin();
}
