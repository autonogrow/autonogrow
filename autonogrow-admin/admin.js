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
let adminMembership = null;
let staffMembers = [];
let selectedStaffFilter = "";
let conversations = [];
let conversationTemplates = [];
let conversationAutomation = null;
let businessIntegrationStatus = null;
let businessChannelOnboarding = null;
let conversationSuggestions = [];
let selectedConversationSuggestionId = null;
let conversationSuggestionNotice = null;
const sendingConversationSuggestionIds = new Set();
let selectedConversationId = null;
let conversationSearchTimer = null;
let conversationLoadVersion = 0;
let conversationDetailVersion = 0;
let conversationAutomationLoadVersion = 0;
let conversationListFingerprint = "";
let conversationDetailFingerprint = "";
let bookingsFingerprint = "";
let messageOutboxFingerprint = "";
const ADMIN_POLL_INTERVALS = {
  conversationThread: { visible: 5000, hidden: 15000 },
  conversationList: { visible: 10000, hidden: 15000 },
  operations: { visible: 15000, hidden: 30000 }
};
const ADMIN_POLL_MAX_BACKOFF_MULTIPLIER = 4;
let adminPollingActive = false;
let adminPollingLastSuccessAt = null;
const adminPollingTasks = new Map();
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

function isBusinessStaff() {
  return adminMembership?.role === "business_staff" && !adminAuthUser?.is_owner;
}

function canManageConversationTemplates() {
  return Boolean(adminAuthUser?.is_owner || adminMembership?.role === "business_admin");
}

function applyRoleVisibility() {
  const staffOnly = isBusinessStaff();
  const allowed = new Set(["summary", "bookings", "conversations"]);
  document.querySelectorAll(".admin-tab[data-section]").forEach((tab) => {
    tab.hidden = staffOnly && !allowed.has(tab.dataset.section);
  });
  document.querySelectorAll("[data-admin-section]").forEach((section) => {
    if (staffOnly && !allowed.has(section.dataset.adminSection)) section.hidden = true;
  });
  document.getElementById("booking-staff-filter-field").hidden = staffOnly;
  document.querySelectorAll("[data-conversation-admin-only]").forEach((element) => {
    element.hidden = !canManageConversationTemplates() ||
      element.id === "conversation-create-panel";
  });
  document.querySelector(".growth-summary-card").hidden = staffOnly;
  ["stat-reviews-pending", "stat-reviews-copied", "stat-reviews-sent", "stat-messages-pending", "stat-messages-opened", "stat-messages-sent", "stat-services-active"]
    .forEach((id) => { document.getElementById(id)?.closest(".stat-card")?.toggleAttribute("hidden", staffOnly); });
  if (staffOnly && !allowed.has(window.location.hash.slice(1))) showAdminSection("bookings");
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
      const url = new URL(window.location.href);
      url.searchParams.delete("booking");
      window.history.replaceState(null, "", `${url.pathname}${url.search}#bookings`);
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
    if (isBusinessStaff()) {
      const panelResponse = await fetch(`${API_BASE_URL}/api/admin/businesses/${slug}/panel`);
      if (!panelResponse.ok) throw new Error("No se pudo cargar tu agenda.");
      const panel = await panelResponse.json();
      currentBusiness = { ...panel.business, active: panel.business.status === "active" };
      applyBusinessData(currentBusiness);
      document.getElementById("business-subtitle").textContent = "Mi agenda y reservas asignadas";
      await Promise.all([
        loadBookings(),
        loadMyStaffAvailability(),
        loadConversationTemplates(),
        loadConversations()
      ]);
      return;
    }
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
      loadStaffMembers(),
      loadAvailabilitySettings(),
      loadAvailabilityExceptions(),
      loadBookings(),
      loadMessageOutbox(),
      loadAdminGallery(),
      loadConversationTemplates(),
      loadConversationAutomation(),
      loadBusinessChannelOnboarding(),
      loadConversations()
    ]);
    restoreAdminMediaStatus();
  } catch (error) {
    console.error(error);
    renderError("No se pudo conectar con el backend.");
  }
}

function channelOnboardingStatusLabel(status) {
  return ({
    not_allowed: "Aún no disponible",
    available: "Listo para solicitar",
    pending_approval: "Pendiente de revisión",
    approved: "Aprobado",
    suspended: "Suspendido",
    revoked: "Revocado"
  })[status] || status;
}

function renderBusinessChannelOnboarding() {
  const container = document.getElementById("channel-onboarding-list");
  if (!container || !businessChannelOnboarding) return;
  const names = { instagram: "Instagram", whatsapp: "WhatsApp" };
  container.innerHTML = businessChannelOnboarding.channels.map((channel) => {
    const capabilities = channel.status === "approved"
      ? `<ul class="channel-capability-list"><li>Envío integrado: <strong>${channel.integrated_delivery_enabled ? "activo" : "pendiente de activación"}</strong></li><li>Automatización: <strong>${channel.automation_enabled ? "activa" : "pendiente de activación"}</strong></li></ul>`
      : "";
    let action = "";
    if (channel.can_request) {
      action = `<button class="btn btn-primary" type="button" data-channel-request="${escapeHtml(channel.channel)}">Conectar ${escapeHtml(names[channel.channel])}</button>`;
    } else if (channel.status === "available" && channel.connector_policy === "owner_only") {
      action = '<p class="channel-guidance">La conexión debe realizarla el Owner de AutonoGrow.</p>';
    } else if (channel.status === "not_allowed") {
      action = '<p class="channel-guidance">Contacta con AutonoGrow para habilitar este canal.</p>';
    } else if (channel.status === "pending_approval") {
      action = '<p class="channel-guidance">No necesitas hacer nada más. El Owner revisará la solicitud.</p>';
    }
    const account = channel.channel === "instagram" && channel.connected_account_name ? `<p class="channel-guidance">Cuenta: <strong>@${escapeHtml(String(channel.connected_account_name).replace(/^@/, ""))}</strong></p>` : "";
    const precheck = channel.channel === "instagram" && channel.can_request ? `<ul class="channel-capability-list"><li>Usa una cuenta profesional Business o Creator.</li><li>Debes tener acceso a esa cuenta.</li><li>Mantén esta ventana abierta durante la autorización.</li><li>AutonoGrow nunca te pedirá tu contraseña de Instagram.</li></ul><p class="channel-guidance">AutonoGrow necesita estos permisos para recibir y responder mensajes de tu cuenta profesional.</p>` : "";
    return `<article class="channel-onboarding-card">
      <div class="channel-onboarding-heading"><h3>${escapeHtml(names[channel.channel])}</h3><span class="channel-status channel-status-${escapeHtml(channel.status)}">${escapeHtml(channelOnboardingStatusLabel(channel.status))}</span></div>
      <p>${channel.channel === "instagram" ? "Prepara tu cuenta profesional de Instagram." : "Prepara el acceso administrador de tu cuenta de WhatsApp Business."}</p>
      ${account}${capabilities}${precheck}${action}
    </article>`;
  }).join("");
}

async function loadBusinessChannelOnboarding() {
  const container = document.getElementById("channel-onboarding-list");
  if (!container) return;
  const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/channel-onboarding`);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    container.innerHTML = `<p class="empty-state">${escapeHtml(body.detail || "No se pudieron cargar los canales.")}</p>`;
    return;
  }
  businessChannelOnboarding = body;
  renderBusinessChannelOnboarding();
}

async function requestBusinessChannelConnection(channel, button) {
  const feedback = document.getElementById("channel-onboarding-feedback");
  const confirmed = window.confirm("Confirmo que soy administrador autorizado de los activos de Meta del negocio.");
  if (!confirmed) return;
  button.disabled = true;
  feedback.textContent = "Enviando solicitud...";
  try {
    if (channel === "instagram") {
      const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/integrations/instagram/oauth/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ purpose: null })
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "No se pudo iniciar Instagram Login.");
      if (!String(body.authorization_url || "").startsWith("https://www.instagram.com/oauth/authorize?")) throw new Error("Meta devolvió una URL de autorización no válida.");
      window.location.assign(body.authorization_url);
      return;
    }
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/channel-onboarding/${encodeURIComponent(channel)}/request`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm_meta_authority: true })
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || "No se pudo solicitar la conexión.");
    feedback.textContent = "Solicitud registrada. Queda pendiente de revisión por el Owner.";
    await loadBusinessChannelOnboarding();
  } catch (error) {
    feedback.textContent = error.message;
    button.disabled = false;
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
    if (staffMembers.length) renderStaffMembers();
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

async function loadStaffMembers() {
  const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/staff`);
  if (!response.ok) throw new Error("No se pudo cargar el equipo.");
  const data = await response.json();
  staffMembers = data.staff || [];
  renderStaffMembers();
  const filter = document.getElementById("booking-staff-filter");
  filter.innerHTML = `<option value="">Todos</option>` + staffMembers
    .filter((member) => member.active)
    .map((member) => `<option value="${member.id}">${escapeHtml(member.public_name || member.name || member.email)}</option>`)
    .join("");
}

async function loadMyStaffAvailability() {
  const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/my-staff-availability`);
  if (!response.ok) return;
  const data = await response.json();
  let panel = document.getElementById("my-staff-availability");
  if (!panel) {
    panel = document.createElement("article");
    panel.id = "my-staff-availability";
    panel.className = "growth-summary-card my-staff-availability";
    document.querySelector('[data-admin-section="summary"] .stats-grid').after(panel);
  }
  panel.hidden = false;
  panel.innerHTML = `
    <div class="growth-summary-copy">
      <span class="stat-label">Mi horario semanal</span>
      <strong>${data.inherits_business_schedule ? "Horario general del negocio" : "Horario propio"}</strong>
      <div class="my-schedule-grid">
        ${WEEKDAYS.map((day) => {
          const windows = data.weekly_schedule[day.value] || [];
          const text = windows.length ? windows.map((item) => `${item.start}-${item.end}`).join(", ") : "Cerrado";
          return `<span><b>${escapeHtml(day.label)}</b>${escapeHtml(text)}</span>`;
        }).join("")}
      </div>
    </div>`;
}

function renderStaffMembers() {
  const container = document.getElementById("admin-staff-list");
  const inactiveContainer = document.getElementById("admin-inactive-staff-list");
  const activeMembers = staffMembers.filter((member) => member.active);
  const inactiveMembers = staffMembers.filter((member) => !member.active);
  const canRemoveMembers = adminAuthUser?.is_owner ||
    adminMembership?.role === "business_admin";
  const activeAdminCount = activeMembers.filter(
    (member) => member.role === "business_admin"
  ).length;
  const activeServices = adminServices.filter((service) => service.active);

  document.getElementById("inactive-staff-count").textContent = inactiveMembers.length;
  container.innerHTML = activeMembers.map((member) => {
    const assignedServiceIds = new Set(member.service_ids || []);
    const isOnlyActiveAdmin =
      member.role === "business_admin" && activeAdminCount === 1;
    const serviceSelector = activeServices.length
      ? activeServices.map((service) => `
          <label class="staff-service-option">
            <input class="staff-service-checkbox" type="checkbox" value="${service.id}"
              ${assignedServiceIds.has(service.id) ? "checked" : ""} />
            ${escapeHtml(service.name)}
          </label>
        `).join("")
      : `<span class="staff-services-empty">No hay servicios activos.</span>`;
    const removeAction = canRemoveMembers
      ? `<button class="btn btn-small btn-danger" type="button"
          onclick="removeStaffMember(${member.id})"
          ${isOnlyActiveAdmin ? 'disabled title="No puedes eliminar al único administrador activo"' : ""}>
          Eliminar del equipo
        </button>
        ${isOnlyActiveAdmin ? '<small class="staff-admin-protection">Añade otro administrador activo antes de eliminar este perfil.</small>' : ""}`
      : "";
    return `
    <article class="admin-service-item staff-member-card" data-staff-id="${member.id}">
      <div class="service-edit-grid">
        <label>Email<input value="${escapeHtml(member.email)}" disabled /></label>
        <label>Nombre publico<input class="staff-public-name" value="${escapeHtml(member.public_name || "")}" /></label>
        <label>Rol<select class="staff-role"><option value="business_staff" ${member.role === "business_staff" ? "selected" : ""}>Personal</option><option value="business_admin" ${member.role === "business_admin" ? "selected" : ""}>Administrador</option></select></label>
        <label class="active-setting"><input class="staff-active" type="checkbox" checked disabled />Activo</label>
        <label class="active-setting"><input class="staff-bookable" type="checkbox" ${member.bookable ? "checked" : ""} onchange="toggleStaffServiceControls(${member.id}, this.checked)" />Reservable</label>
        <label class="active-setting"><input class="staff-show-schedule" type="checkbox" ${member.show_schedule ? "checked" : ""} />Visible en agenda</label>
        <label class="field-wide">Bio<textarea class="staff-bio" rows="2">${escapeHtml(member.bio || "")}</textarea></label>
      </div>
      <fieldset class="staff-services-field" ${member.bookable ? "" : "disabled"}>
        <legend>Servicios que puede realizar</legend>
        <div class="staff-services-options">${serviceSelector}</div>
        <small>${member.bookable && assignedServiceIds.size === 0
          ? "Este profesional no aparecerá en reservas hasta que tenga al menos un servicio asignado."
          : member.bookable
            ? "Solo aparecerá al reservar los servicios seleccionados."
            : "Activa ‘Reservable’ para asignar servicios."}</small>
      </fieldset>
      <div class="staff-statuses">
        <span class="staff-state-active">Activo</span>
        <span>${member.bookable && member.show_schedule ? "Visible en reservas online" : "No visible en reservas online"}</span>
        ${member.bookable && assignedServiceIds.size === 0 ? '<span class="staff-services-warning">Sin servicios asignados</span>' : ""}
      </div>
      <div class="settings-actions">
        <button class="btn btn-small btn-primary" type="button" onclick="saveStaffMember(${member.id})">Guardar ficha</button>
        <button class="btn btn-small btn-secondary" type="button" onclick="editStaffSchedule(${member.id})">Editar horario</button>
        ${removeAction}
      </div>
    </article>
  `; }).join("") || `<p class="empty-state">No hay miembros activos en el equipo.</p>`;

  inactiveContainer.innerHTML = inactiveMembers.map((member) => `
    <article class="inactive-staff-card" data-inactive-staff-id="${member.id}">
      <div class="inactive-staff-copy">
        <div class="staff-statuses"><span class="staff-state-inactive">Inactivo</span><span>${member.role === "business_admin" ? "Administrador" : "Personal"}</span></div>
        <strong>${escapeHtml(member.name || member.email)}</strong>
        <span>${escapeHtml(member.email)}</span>
        ${member.public_name ? `<span>Nombre público: ${escapeHtml(member.public_name)}</span>` : ""}
        <small>${member.removed_at ? `Eliminado el ${escapeHtml(formatStaffRemovedAt(member.removed_at))}` : "Desactivado sin fecha registrada"}</small>
      </div>
      ${canRemoveMembers ? `<button class="btn btn-small btn-secondary" type="button" onclick="reactivateStaffMember(${member.id})">Reactivar</button>` : ""}
    </article>
  `).join("") || `<p class="empty-state">No hay miembros inactivos.</p>`;
}

function toggleStaffServiceControls(memberId, enabled) {
  const fieldset = document.querySelector(
    `[data-staff-id="${memberId}"] .staff-services-field`
  );
  if (fieldset) fieldset.disabled = !enabled;
}

function formatStaffRemovedAt(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("es-ES", { dateStyle: "medium", timeStyle: "short" });
}

async function createStaffMember() {
  const feedback = document.getElementById("staff-feedback");
  const payload = {
    email: document.getElementById("new-staff-email").value.trim(),
    role: document.getElementById("new-staff-role").value,
    public_name: document.getElementById("new-staff-public-name").value.trim() || null,
    bookable: document.getElementById("new-staff-bookable").checked,
    show_schedule: true,
    active: true
  };
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/staff`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
    });
    const result = await response.json().catch(() => null);
    if (!response.ok) throw new Error(result?.detail || "No se pudo añadir el miembro.");
    feedback.className = "inline-feedback success";
    feedback.textContent = "Miembro añadido.";
    await loadStaffMembers();
  } catch (error) {
    feedback.className = "inline-feedback error";
    feedback.textContent = error.message;
  }
}

async function saveStaffMember(memberId) {
  const card = document.querySelector(`[data-staff-id="${memberId}"]`);
  const payload = {
    public_name: card.querySelector(".staff-public-name").value.trim() || null,
    role: card.querySelector(".staff-role").value,
    bookable: card.querySelector(".staff-bookable").checked,
    show_schedule: card.querySelector(".staff-show-schedule").checked,
    bio: card.querySelector(".staff-bio").value.trim() || null
  };
  const serviceIds = [...card.querySelectorAll(".staff-service-checkbox:checked")]
    .map((input) => Number(input.value));
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/staff/${memberId}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
    });
    const result = await response.json().catch(() => null);
    if (!response.ok) throw new Error(result?.message || result?.detail || "No se pudo guardar la ficha.");

    if (payload.bookable) {
      const servicesResponse = await fetch(
        `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/staff/${memberId}/services`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ service_ids: serviceIds })
        }
      );
      const servicesResult = await servicesResponse.json().catch(() => null);
      if (!servicesResponse.ok) {
        throw new Error(
          servicesResult?.message || servicesResult?.detail ||
          "La ficha se guardó, pero no se pudieron asignar los servicios."
        );
      }
    }
    await loadStaffMembers();
    const feedback = document.getElementById("staff-feedback");
    feedback.className = "inline-feedback success";
    feedback.textContent = "Ficha y servicios guardados correctamente.";
  } catch (error) {
    const feedback = document.getElementById("staff-feedback");
    feedback.className = "inline-feedback error";
    feedback.textContent = typeof error?.message === "string"
      ? error.message
      : "No se pudo guardar la ficha.";
  }
}

async function reactivateStaffMember(memberId) {
  const feedback = document.getElementById("staff-feedback");
  const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/staff/${memberId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ active: true })
  });
  const result = await response.json().catch(() => null);
  if (!response.ok) {
    feedback.className = "inline-feedback error";
    feedback.textContent = result?.detail || "No se pudo reactivar al miembro.";
    return;
  }
  await loadStaffMembers();
  feedback.className = "inline-feedback success";
  feedback.textContent = "Miembro reactivado. Configura si debe aparecer como profesional reservable.";
}

async function removeStaffMember(memberId) {
  const member = staffMembers.find((item) => item.id === memberId);
  if (!member) return;
  const displayName = member.public_name || member.name || member.email;
  if (!window.confirm(`¿Eliminar a ${displayName} del equipo? Perderá el acceso y dejará de estar disponible para nuevas reservas.`)) return;

  const feedback = document.getElementById("staff-feedback");
  feedback.className = "inline-feedback";
  feedback.textContent = "Comprobando citas asignadas...";
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/staff/${memberId}`, {
      method: "DELETE"
    });
    const result = await response.json().catch(() => null);
    if (response.status === 409 && result?.detail === "member_has_future_bookings") {
      feedback.textContent = "";
      openStaffRemovalModal(member, result);
      return;
    }
    if (!response.ok) throw new Error(result?.message || result?.detail || "No se pudo eliminar al miembro del equipo.");
    feedback.className = "inline-feedback success";
    feedback.textContent = `${displayName} ya no forma parte del equipo.`;
    await loadStaffMembers();
  } catch (error) {
    console.error(error);
    feedback.className = "inline-feedback error";
    feedback.textContent = error.message || "No se pudo eliminar al miembro del equipo.";
  }
}

function openStaffRemovalModal(member, result) {
  const modal = document.getElementById("staff-removal-modal");
  const bookings = result.bookings || [];
  document.getElementById("staff-removal-modal-title").textContent = `No se puede eliminar a ${member.public_name || member.name || member.email}`;
  document.getElementById("staff-removal-modal-message").textContent = result.message || "Gestiona primero las citas asignadas.";
  document.getElementById("staff-removal-bookings").innerHTML = bookings.map((booking) => `
    <article class="staff-removal-booking">
      <div>
        <strong>${escapeHtml(formatBlockingBookingDate(booking.date, booking.start_time))}</strong>
        <span>${escapeHtml(booking.customer_name)}${booking.customer_phone ? ` · ${escapeHtml(booking.customer_phone)}` : ""}</span>
        <span>${escapeHtml(booking.service_name)} · ${escapeHtml(getStatusLabel(booking.status))}</span>
        <small>Reserva #${booking.id}</small>
      </div>
      <button class="btn btn-small btn-primary" type="button" onclick="goToBooking(${booking.id})">Ir a la cita</button>
    </article>
  `).join("");
  modal.classList.add("open");
}

function closeStaffRemovalModal() {
  document.getElementById("staff-removal-modal")?.classList.remove("open");
}

function formatBlockingBookingDate(date, time) {
  if (!date) return time || "Fecha pendiente";
  const value = new Date(`${date}T${time || "00:00"}:00`);
  if (Number.isNaN(value.getTime())) return `${date} · ${time || ""}`.trim();
  return value.toLocaleString("es-ES", { dateStyle: "medium", timeStyle: time ? "short" : undefined });
}

function parseStaffWindows(value) {
  if (!value.trim()) return [];
  return value.split(",").map((segment) => {
    const [start, end] = segment.trim().split("-");
    if (!/^\d{2}:\d{2}$/.test(start || "") || !/^\d{2}:\d{2}$/.test(end || "")) throw new Error("Usa HH:MM-HH:MM y separa tramos con comas.");
    return { start, end };
  });
}

async function editStaffSchedule(memberId) {
  const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/staff/${memberId}/availability`);
  if (!response.ok) return alert("No se pudo cargar el horario.");
  const data = await response.json();
  const weeklySchedule = {};
  try {
    for (const day of WEEKDAYS) {
      const current = (data.weekly_schedule[day.value] || []).map((window) => `${window.start}-${window.end}`).join(",");
      const value = window.prompt(`Tramos de ${day.label} (HH:MM-HH:MM, separados por comas). Vacio = cerrado.`, current);
      if (value === null) return;
      weeklySchedule[day.value] = parseStaffWindows(value);
    }
  } catch (error) {
    return alert(error.message);
  }
  const saveResponse = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/staff/${memberId}/availability`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ weekly_schedule: weeklySchedule })
  });
  if (!saveResponse.ok) return alert("No se pudo guardar el horario.");
  alert("Horario del profesional guardado.");
}

function captureBookingEditorState() {
  const drafts = new Map();
  document.querySelectorAll("[data-internal-notes]").forEach((field) => {
    drafts.set(String(field.dataset.internalNotes), field.value);
  });
  const active = document.activeElement?.matches?.("[data-internal-notes]")
    ? document.activeElement
    : null;
  return {
    drafts,
    focusedBookingId: active ? String(active.dataset.internalNotes) : null,
    selectionStart: active?.selectionStart,
    selectionEnd: active?.selectionEnd,
    scrollX: window.scrollX,
    scrollY: window.scrollY
  };
}

function restoreBookingEditorState(state) {
  if (!state) return;
  state.drafts.forEach((value, bookingId) => {
    const field = document.querySelector(`[data-internal-notes="${bookingId}"]`);
    if (field) field.value = value;
  });
  if (state.focusedBookingId) {
    const field = document.querySelector(`[data-internal-notes="${state.focusedBookingId}"]`);
    if (field) {
      field.focus({ preventScroll: true });
      field.setSelectionRange(state.selectionStart, state.selectionEnd);
    }
  }
  window.scrollTo(state.scrollX, state.scrollY);
}

async function loadBookings({ background = false } = {}) {
  const slug = getBusinessSlug();
  const list = document.getElementById("bookings-list");
  if (!background && !allBookings.length) {
    list.innerHTML = `<p class="empty-state">Cargando reservas...</p>`;
  }

  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${slug}/bookings`);

    if (!response.ok) throw new Error("No se pudieron cargar las reservas.");

    const data = await response.json();
    const previousBookings = new Map(allBookings.map((booking) => [booking.id, booking]));
    allBookings = (data.bookings || []).map((booking) => ({
      ...booking,
      attachments: background
        ? (previousBookings.get(booking.id)?.attachments || [])
        : (booking.attachments || [])
    }));

    if (!background && isBusinessStaff()) {
      reviewRequestsByBooking = new Map();
      await enrichBookingsWithAttachments();
    } else if (!background) {
      await Promise.all([enrichBookingsWithAttachments(), loadReviewRequests()]);
    }
    const nextFingerprint = JSON.stringify(allBookings);
    const changed = nextFingerprint !== bookingsFingerprint;
    bookingsFingerprint = nextFingerprint;
    growthDataReady.bookings = true;
    if (!changed && background) return;
    const editorState = background ? captureBookingEditorState() : null;
    renderStats(allBookings);
    renderReviewStats();
    renderReviewRequests();
    renderBookings();
    const requestedBookingId = Number(new URLSearchParams(window.location.search).get("booking"));
    if (!background && Number.isInteger(requestedBookingId) && requestedBookingId > 0) {
      goToBooking(requestedBookingId, false);
    }
    restoreBookingEditorState(editorState);
    if (!isBusinessStaff()) renderGrowth();
  } catch (error) {
    console.error(error);
    if (background) throw error;
    if (!allBookings.length) {
      list.innerHTML = `<p class="empty-state">Error conectando con el backend.</p>`;
    }
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

function conversationErrorMessage(body, fallback) {
  if (typeof body === "string") return body;
  if (typeof body?.message === "string") return body.message;
  if (typeof body?.detail === "string") return body.detail;
  if (typeof body?.detail?.message === "string") return body.detail.message;
  if (body?.detail) return JSON.stringify(body.detail);
  return fallback;
}

function showConversationFeedback(message, isError = false) {
  const feedback = document.getElementById("conversation-feedback");
  feedback.textContent = message || "";
  feedback.className = `inline-feedback ${message ? (isError ? "error" : "success") : ""}`;
}

function conversationDisplayName(item) {
  return item.customer_name || item.customer_username || item.customer_phone || "Cliente sin nombre";
}

function conversationStatusLabel(status) {
  return { pending: "Pendiente", replied: "Respondida", closed: "Cerrada" }[status] || status;
}

function conversationChannelLabel(channel) {
  return { manual: "Manual", whatsapp: "WhatsApp", instagram: "Instagram" }[channel] || channel;
}

function conversationIntentLabel(intent) {
  return {
    welcome_intent: "Bienvenida",
    booking_intent: "Reserva",
    price_intent: "Precio",
    service_intent: "Servicios",
    location_intent: "Ubicación",
    hours_intent: "Horario",
    human_intent: "Atención humana",
    complaint_intent: "Queja",
    cancel_reschedule_intent: "Cancelar o cambiar cita",
    unknown: "Desconocida"
  }[intent] || intent;
}

function conversationIntentBadge(item) {
  if (!item.detected_intent) return "";
  const confidence = Number.isFinite(Number(item.intent_confidence)) ? ` · ${Number(item.intent_confidence)}%` : "";
  return `<span class="conversation-intent-badge">${escapeHtml(conversationIntentLabel(item.detected_intent))}${confidence}</span>`;
}

function conversationDeliveryLabel(status) {
  return {
    queued: "En cola",
    processing: "Enviando",
    sent: "Enviado",
    delivered: "Entregado",
    read: "Leído",
    retry: "Error temporal",
    blocked: "No enviado por conexión",
    failed: "Error definitivo",
    cancelled: "Error definitivo",
    simulated: "Modo interno",
    pending: "Pendiente"
  }[status] || status;
}

function conversationProviderBadge(conversation) {
  if (conversation.channel === "instagram") {
    return conversation.instagram_provider_configured
      ? `<span class="conversation-provider conversation-provider-connected">Instagram conectado</span>`
      : `<span class="conversation-provider conversation-provider-internal">Instagram no conectado · modo interno</span>`;
  }
  if (conversation.channel === "whatsapp") {
    if (
      conversation.provider_configured
      && ["connected", "degraded"].includes(conversation.integration_status)
    ) {
      return `<span class="conversation-provider conversation-provider-connected">WhatsApp conectado</span>`;
    }
    return conversation.assisted_delivery_available
      ? `<span class="conversation-provider conversation-provider-internal">Envío asistido</span>`
      : `<span class="conversation-provider conversation-provider-internal">WhatsApp no disponible</span>`;
  }
  return "";
}

function formatConversationDate(value) {
  if (!value) return "Sin actividad";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" });
}

function conversationAutomationLabel(automation) {
  if (automation?.mode === "manual") return "Modo manual";
  if (automation?.block_reason === "conversation_automation_paused") {
    const minutes = Math.max(1, Math.ceil(Number(automation.remaining_seconds || 0) / 60));
    return `Pausada ${minutes} min`;
  }
  return "Automatización activa";
}

function conversationAutomationReason(automation) {
  if (automation?.pause_reason !== "human_reply") return "";
  if (automation.mode === "manual") return "Pausada por respuesta humana hasta reactivarla.";
  if (!automation.paused_until) return "";
  const until = new Date(automation.paused_until);
  if (Number.isNaN(until.getTime())) return "Pausada por respuesta humana.";
  return `Pausada por respuesta humana hasta las ${until.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })}.`;
}

async function loadConversations({ background = false, refreshDetail = true } = {}) {
  const requestVersion = ++conversationLoadVersion;
  const container = document.getElementById("conversation-list");
  const params = new URLSearchParams({ limit: "100", offset: "0" });
  const status = document.getElementById("conversation-status-filter")?.value;
  const channel = document.getElementById("conversation-channel-filter")?.value;
  const query = document.getElementById("conversation-search")?.value.trim();
  if (status) params.set("status", status);
  if (channel) params.set("channel", channel);
  if (query) params.set("q", query);
  if (!background && !conversations.length) {
    container.innerHTML = `<p class="empty-state">Cargando conversaciones...</p>`;
  }
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversations?${params}`
    );
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudieron cargar las conversaciones."));
    if (requestVersion !== conversationLoadVersion) return;
    const nextConversations = body.conversations || [];
    const nextFingerprint = JSON.stringify(nextConversations);
    const changed = nextFingerprint !== conversationListFingerprint;
    conversations = nextConversations;
    conversationListFingerprint = nextFingerprint;
    if (changed || !background) renderConversationList();
    if (selectedConversationId && conversations.some((item) => item.id === selectedConversationId)) {
      if (refreshDetail) await selectConversation(selectedConversationId, false, { background });
    } else if (selectedConversationId && background) {
      return;
    } else if (conversations.length) {
      await selectConversation(conversations[0].id, false, { background });
    } else {
      selectedConversationId = null;
      document.getElementById("conversation-detail").innerHTML = `<p class="empty-state">Todavía no hay conversaciones.</p>`;
    }
  } catch (error) {
    if (requestVersion !== conversationLoadVersion) return;
    console.error(error);
    if (background) throw error;
    if (!conversations.length) {
      container.innerHTML = `<p class="empty-state">${escapeHtml(error.message)}</p>`;
    }
  }
}

function renderConversationList() {
  const container = document.getElementById("conversation-list");
  const previousScrollTop = container.scrollTop;
  if (!conversations.length) {
    container.innerHTML = `<p class="empty-state">Todavía no hay conversaciones.</p>`;
    return;
  }
  container.innerHTML = conversations.map((item) => `
    <button class="conversation-list-item ${item.id === selectedConversationId ? "active" : ""}" type="button" onclick="selectConversation(${item.id})">
      <span class="conversation-list-head">
        <strong>${escapeHtml(conversationDisplayName(item))}</strong>
        <span class="conversation-status conversation-status-${item.status}">${escapeHtml(conversationStatusLabel(item.status))}</span>
      </span>
      <span class="conversation-channel">${escapeHtml(conversationChannelLabel(item.channel))}</span>
      ${conversationProviderBadge(item)}
      ${conversationIntentBadge(item)}
      <p>${escapeHtml(item.last_message_text || "Sin mensajes")}</p>
      <small>${escapeHtml(formatConversationDate(item.last_message_at))}${item.unread_count ? ` · ${item.unread_count} sin responder` : ""}</small>
    </button>
  `).join("");
  container.scrollTop = previousScrollTop;
}

function captureConversationUiState(conversationId) {
  if (selectedConversationId !== Number(conversationId)) return null;
  const textarea = document.getElementById("conversation-reply-body");
  const thread = document.getElementById("conversation-thread");
  const newMessagesIndicator = document.getElementById("conversation-new-messages");
  const distanceFromBottom = thread
    ? thread.scrollHeight - thread.scrollTop - thread.clientHeight
    : 0;
  return {
    conversationId: Number(conversationId),
    draft: textarea?.value || "",
    replyFocused: document.activeElement === textarea,
    selectionStart: textarea?.selectionStart,
    selectionEnd: textarea?.selectionEnd,
    threadScrollTop: thread?.scrollTop || 0,
    threadNearBottom: !thread || distanceFromBottom <= 80,
    lastMessageId: thread?.dataset.lastMessageId || "",
    messageCount: Number(thread?.dataset.messageCount || 0),
    newMessagesVisible: Boolean(newMessagesIndicator && !newMessagesIndicator.hidden),
    automationDuration: document.getElementById("conversation-automation-duration")?.value || "60",
    automationControlFocusId: document.activeElement?.closest?.(".conversation-automation-controls")
      ? document.activeElement.id
      : null
  };
}

function scrollConversationThreadToBottom() {
  const thread = document.getElementById("conversation-thread");
  if (!thread) return;
  thread.scrollTop = thread.scrollHeight;
  document.getElementById("conversation-new-messages")?.setAttribute("hidden", "");
}

async function selectConversation(conversationId, showLoading = true, { background = false } = {}) {
  const requestVersion = ++conversationDetailVersion;
  const uiState = captureConversationUiState(conversationId);
  const selectionChanged = selectedConversationId !== Number(conversationId);
  if (selectionChanged) {
    selectedConversationSuggestionId = null;
    conversationDetailFingerprint = "";
  }
  selectedConversationId = Number(conversationId);
  if (selectionChanged) renderConversationList();
  const detail = document.getElementById("conversation-detail");
  if (showLoading && !background) detail.innerHTML = `<p class="empty-state">Cargando conversación...</p>`;
  try {
    const [response, suggestionsResponse] = await Promise.all([
      fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversations/${selectedConversationId}`),
      fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversations/${selectedConversationId}/suggestions`)
    ]);
    const [body, suggestionsBody] = await Promise.all([
      readAdminResponseBody(response),
      readAdminResponseBody(suggestionsResponse)
    ]);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudo cargar la conversación."));
    if (!suggestionsResponse.ok) throw new Error(conversationErrorMessage(suggestionsBody, "No se pudieron cargar las sugerencias."));
    if (requestVersion !== conversationDetailVersion || selectedConversationId !== Number(conversationId)) return;
    conversationSuggestions = suggestionsBody.suggestions || [];
    conversationSuggestionNotice = suggestionsBody.notice || null;
    if (!conversationSuggestions.some((item) => item.id === selectedConversationSuggestionId && item.status === "pending")) {
      selectedConversationSuggestionId = null;
    }
    const nextFingerprint = JSON.stringify({
      conversation: body.conversation,
      suggestions: conversationSuggestions,
      notice: conversationSuggestionNotice
    });
    if (background && nextFingerprint === conversationDetailFingerprint) return;
    conversationDetailFingerprint = nextFingerprint;
    renderConversationDetail(body.conversation, uiState);
  } catch (error) {
    if (requestVersion !== conversationDetailVersion) return;
    console.error(error);
    if (background) throw error;
    detail.innerHTML = `<p class="empty-state">${escapeHtml(error.message)}</p>`;
  }
}

function renderConversationDetail(conversation, uiState = null) {
  const detail = document.getElementById("conversation-detail");
  const contactParts = [conversation.customer_username ? `@${conversation.customer_username}` : null, conversation.customer_phone].filter(Boolean);
  const messages = conversation.messages || [];
  const quickReplies = conversationTemplates.filter((item) => item.active).map((template) => `
    <button class="btn btn-secondary" type="button" onclick="fillConversationReply(${template.id})">${escapeHtml(template.name)}</button>
  `).join("");
  const pendingSuggestions = conversationSuggestions.filter((item) => item.status === "pending");
  const automation = conversation.automation || { mode: "automatic", is_active: true };
  const automationDuration = uiState?.automationDuration || "60";
  const automationReason = conversationAutomationReason(automation);
  const deliveryNotice = conversation.channel === "instagram"
    ? (conversation.instagram_provider_configured
      ? "El mensaje se enviará mediante Instagram."
      : "Instagram real no está conectado; este mensaje solo se registra internamente.")
    : conversation.channel === "whatsapp"
      ? (conversation.integrated_delivery_available
        ? "Envío integrado disponible mediante WhatsApp Cloud API."
        : conversation.delivery_unavailable_reason === "whatsapp_template_required"
          ? "Se requiere una plantilla aprobada de WhatsApp para iniciar de nuevo la conversación."
          : "El envío se completará fuera de AutonoGrow mediante Abrir en WhatsApp.")
      : "El mensaje se registra como enviado sin contactar a un proveedor externo.";
  const suggestionsMarkup = pendingSuggestions.length || conversationSuggestionNotice ? `
    <div class="conversation-suggestions">
      ${conversationSuggestionNotice ? `<p class="conversation-automation-warning">${escapeHtml(conversationSuggestionNotice)}</p>` : ""}
      ${pendingSuggestions.map((suggestion) => `
        <article class="conversation-suggestion">
          <strong>Respuesta sugerida</strong>
          <span class="conversation-intent-badge">${escapeHtml(suggestion.intent_label)} · ${suggestion.confidence}%</span>
          <p>${escapeHtml(suggestion.body)}</p>
          <div class="conversation-suggestion-actions">
            <button class="btn btn-primary btn-small" type="button" onclick="sendConversationSuggestion(${suggestion.id})">Enviar sugerencia</button>
            <button class="btn btn-secondary btn-small" type="button" onclick="modifyConversationSuggestion(${suggestion.id})">Modificar</button>
            <button class="btn btn-secondary btn-small" type="button" onclick="dismissConversationSuggestion(${suggestion.id})">Descartar</button>
          </div>
        </article>
      `).join("")}
    </div>
  ` : "";
  detail.innerHTML = `
    <header class="conversation-detail-header">
      <div class="conversation-detail-header-copy">
        <strong>${escapeHtml(conversationDisplayName(conversation))}</strong>
        <span>${escapeHtml(contactParts.join(" · ") || "Sin datos adicionales")}</span>
        <span class="conversation-channel">${escapeHtml(conversationChannelLabel(conversation.channel))}</span>
        ${conversationProviderBadge(conversation)}
        ${conversationIntentBadge(conversation)}
      </div>
      <div class="conversation-detail-actions">
        <span class="conversation-status conversation-status-${conversation.status}">${escapeHtml(conversationStatusLabel(conversation.status))}</span>
        ${conversation.status === "closed"
          ? `<button class="btn btn-small btn-secondary" type="button" onclick="changeConversationStatus('pending')">Reabrir</button>`
          : `<button class="btn btn-small btn-secondary" type="button" onclick="changeConversationStatus('pending')">Marcar pendiente</button><button class="btn btn-small btn-danger" type="button" onclick="changeConversationStatus('closed')">Marcar cerrada</button>`}
      </div>
      <div class="conversation-automation-controls">
        <div class="conversation-automation-state-copy">
          <span class="conversation-automation-state ${automation.is_active ? "is-active" : "is-paused"}">${escapeHtml(conversationAutomationLabel(automation))}</span>
          ${automationReason ? `<small>${escapeHtml(automationReason)}</small>` : ""}
        </div>
        <select id="conversation-automation-duration" aria-label="Duración de la pausa">
          <option value="15" ${automationDuration === "15" ? "selected" : ""}>15 min</option>
          <option value="60" ${automationDuration === "60" ? "selected" : ""}>1 h</option>
          <option value="240" ${automationDuration === "240" ? "selected" : ""}>4 h</option>
          <option value="-1" ${automationDuration === "-1" ? "selected" : ""}>Hasta reactivarla</option>
        </select>
        <button id="conversation-automation-toggle" class="btn btn-small ${automation.is_active ? "btn-secondary" : "btn-primary"}" type="button" onclick="toggleConversationAutomation(${automation.is_active ? "true" : "false"})">${automation.is_active ? "Pausar automatización" : "Activar automatización"}</button>
        <small class="conversation-automation-suggestion-note">Las sugerencias pueden seguir apareciendo durante la pausa.</small>
      </div>
    </header>
    <div id="conversation-thread" class="conversation-thread" data-last-message-id="${messages.at(-1)?.id || ""}" data-message-count="${messages.length}">
      ${messages.length ? messages.map((message) => `
        <div class="conversation-message conversation-message-${message.direction}">
          <span>${escapeHtml(message.body)}</span>
          <small>${message.sender_type === "automation" ? "Automatización" : (message.direction === "outbound" ? "Negocio" : "Cliente")} · ${escapeHtml(formatConversationDate(message.created_at))}${message.delivery_status ? ` · <span class="conversation-delivery conversation-delivery-${escapeHtml(message.delivery_status)}">${escapeHtml(conversationDeliveryLabel(message.delivery_status))}</span>` : ""}</small>
        </div>
      `).join("") : `<p class="empty-state">Todavía no hay mensajes.</p>`}
      <button id="conversation-new-messages" class="btn btn-primary btn-small conversation-new-messages" type="button" onclick="scrollConversationThreadToBottom()" hidden>Hay mensajes nuevos</button>
    </div>
    ${suggestionsMarkup}
    <div class="conversation-reply">
      <div class="conversation-quick-replies">${quickReplies || `<small>No hay respuestas rápidas activas.</small>`}</div>
      <textarea id="conversation-reply-body" placeholder="Escribe una respuesta..."></textarea>
      <div class="conversation-composer-actions">
        <small>${escapeHtml(deliveryNotice)}</small>
        ${conversation.channel === "whatsapp"
          ? `<button class="btn btn-primary" type="button" onclick="sendConversationReply()" ${conversation.integrated_delivery_available ? "" : "disabled"}>Enviar desde AutonoGrow</button>${conversation.assisted_delivery_available ? `<button class="btn btn-whatsapp" type="button" onclick="openConversationWhatsApp()">Abrir en WhatsApp</button>` : ""}`
          : `<button class="btn btn-primary" type="button" onclick="sendConversationReply()">Enviar</button>`}
      </div>
    </div>
  `;
  const thread = document.getElementById("conversation-thread");
  const textarea = document.getElementById("conversation-reply-body");
  if (uiState?.conversationId === selectedConversationId && textarea) {
    textarea.value = uiState.draft;
    if (uiState.replyFocused) {
      textarea.focus({ preventScroll: true });
      textarea.setSelectionRange(uiState.selectionStart, uiState.selectionEnd);
    }
  }
  if (uiState?.automationControlFocusId) {
    document.getElementById(uiState.automationControlFocusId)?.focus({ preventScroll: true });
  }
  if (thread) {
    const lastMessageId = String(messages.at(-1)?.id || "");
    const hasNewMessages = Boolean(
      uiState &&
      (messages.length > uiState.messageCount || (uiState.lastMessageId && lastMessageId !== uiState.lastMessageId))
    );
    if (!uiState || uiState.threadNearBottom) {
      thread.scrollTop = thread.scrollHeight;
    } else {
      thread.scrollTop = uiState.threadScrollTop;
      if (hasNewMessages || uiState.newMessagesVisible) {
        document.getElementById("conversation-new-messages")?.removeAttribute("hidden");
      }
    }
    thread.addEventListener("scroll", () => {
      const distanceFromBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight;
      if (distanceFromBottom <= 80) {
        document.getElementById("conversation-new-messages")?.setAttribute("hidden", "");
      }
    });
  }
}

async function toggleConversationAutomation(isCurrentlyActive) {
  if (!selectedConversationId) return;
  const duration = Number(document.getElementById("conversation-automation-duration")?.value || 60);
  const payload = isCurrentlyActive
    ? (duration === -1 ? { action: "manual", duration_minutes: -1 } : { action: "pause", duration_minutes: duration })
    : { action: "resume" };
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversations/${selectedConversationId}/automation`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }
    );
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudo cambiar la automatización."));
    showConversationFeedback(payload.action === "resume" ? "Automatización reactivada." : "Automatización pausada.");
    await requestAdminRefresh(["conversationList", "conversationThread"]);
  } catch (error) {
    showConversationFeedback(error.message, true);
  }
}

function fillConversationReply(templateId) {
  const template = conversationTemplates.find((item) => item.id === Number(templateId));
  const textarea = document.getElementById("conversation-reply-body");
  if (!template || !textarea) return;
  selectedConversationSuggestionId = null;
  textarea.value = template.rendered_body || template.body;
  textarea.focus();
}

async function sendConversationReply() {
  if (!selectedConversationId) return;
  const textarea = document.getElementById("conversation-reply-body");
  const bodyText = textarea?.value.trim();
  if (!bodyText) return showConversationFeedback("Escribe un mensaje antes de enviarlo.", true);
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversations/${selectedConversationId}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: bodyText, suggestion_id: selectedConversationSuggestionId })
      }
    );
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudo enviar el mensaje."));
    selectedConversationSuggestionId = null;
    if (textarea) textarea.value = "";
    showConversationFeedback(body.message?.delivery_status === "queued" ? "Respuesta en cola." : "Respuesta registrada correctamente.");
    await requestAdminRefresh(["conversationList", "conversationThread", "operations"]);
  } catch (error) {
    showConversationFeedback(error.message, true);
    if (selectedConversationId) await requestAdminRefresh(["conversationList", "conversationThread"]);
  }
}

async function openConversationWhatsApp() {
  if (!selectedConversationId) return;
  const textarea = document.getElementById("conversation-reply-body");
  const bodyText = textarea?.value.trim();
  if (!bodyText) return showConversationFeedback("Escribe un mensaje antes de abrir WhatsApp.", true);
  const whatsappWindow = openBlankWhatsAppWindow();
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversations/${selectedConversationId}/assisted-delivery`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: bodyText })
      }
    );
    const body = await readAdminResponseBody(response);
    if (!response.ok || !body.whatsapp_url) throw new Error(conversationErrorMessage(body, "No se pudo abrir WhatsApp."));
    if (!whatsappWindow) throw new Error("El navegador bloqueó la nueva ventana de WhatsApp.");
    whatsappWindow.location.href = body.whatsapp_url;
    showConversationFeedback("WhatsApp abierto. El mensaje aún no se considera enviado.");
  } catch (error) {
    whatsappWindow?.close();
    showConversationFeedback(error.message, true);
  }
}

async function sendConversationSuggestion(suggestionId) {
  const suggestion = conversationSuggestions.find((item) => item.id === Number(suggestionId) && item.status === "pending");
  if (!suggestion || sendingConversationSuggestionIds.has(suggestion.id)) return;
  sendingConversationSuggestionIds.add(suggestion.id);
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversation-suggestions/${suggestion.id}/send`,
      { method: "POST" }
    );
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudo enviar la sugerencia."));
    selectedConversationSuggestionId = null;
    showConversationFeedback("Sugerencia enviada correctamente.");
    await requestAdminRefresh(["conversationList", "conversationThread", "operations"]);
  } catch (error) {
    showConversationFeedback(error.message || "No se pudo enviar la sugerencia.", true);
    if (selectedConversationId) await requestAdminRefresh(["conversationList", "conversationThread"]);
  } finally {
    sendingConversationSuggestionIds.delete(suggestion.id);
  }
}

function modifyConversationSuggestion(suggestionId) {
  const suggestion = conversationSuggestions.find((item) => item.id === Number(suggestionId) && item.status === "pending");
  const textarea = document.getElementById("conversation-reply-body");
  if (!suggestion || !textarea) return;
  selectedConversationSuggestionId = suggestion.id;
  textarea.value = suggestion.body;
  textarea.focus();
  showConversationFeedback("Puedes modificar la sugerencia. Se marcará como usada al enviar.");
}

async function dismissConversationSuggestion(suggestionId) {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversation-suggestions/${suggestionId}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "dismissed" })
      }
    );
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudo descartar la sugerencia."));
    if (selectedConversationSuggestionId === Number(suggestionId)) selectedConversationSuggestionId = null;
    showConversationFeedback("Sugerencia descartada.");
    await requestAdminRefresh(["conversationList", "conversationThread"]);
  } catch (error) {
    showConversationFeedback(error.message, true);
  }
}

async function changeConversationStatus(status) {
  if (!selectedConversationId) return;
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversations/${selectedConversationId}/status`,
      { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) }
    );
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudo cambiar el estado."));
    showConversationFeedback("Estado actualizado.");
    await requestAdminRefresh(["conversationList", "conversationThread", "operations"]);
  } catch (error) {
    showConversationFeedback(error.message, true);
  }
}

async function createConversation() {
  const payload = {
    channel: document.getElementById("conversation-create-channel").value,
    customer_name: document.getElementById("conversation-create-name").value.trim() || null,
    customer_phone: document.getElementById("conversation-create-phone").value.trim() || null,
    customer_username: document.getElementById("conversation-create-username").value.trim() || null,
    initial_message: document.getElementById("conversation-create-message").value.trim() || null
  };
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversations`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }
    );
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudo crear la conversación."));
    selectedConversationId = body.conversation.id;
    ["conversation-create-name", "conversation-create-phone", "conversation-create-username", "conversation-create-message"]
      .forEach((id) => { document.getElementById(id).value = ""; });
    document.getElementById("conversation-create-panel").hidden = true;
    showConversationFeedback("Conversación creada.");
    await requestAdminRefresh(["conversationList", "conversationThread"]);
  } catch (error) {
    showConversationFeedback(error.message, true);
  }
}

async function loadConversationTemplates() {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversation-templates`
    );
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudieron cargar las plantillas."));
    conversationTemplates = body.templates || [];
    renderConversationTemplates();
    if (selectedConversationId) await selectConversation(selectedConversationId, false);
  } catch (error) {
    console.error(error);
    conversationTemplates = [];
    renderConversationTemplates();
  }
}

function renderConversationTemplates() {
  const container = document.getElementById("conversation-template-list");
  if (!container || !canManageConversationTemplates()) return;
  container.innerHTML = conversationTemplates.map((template) => `
    <article class="conversation-template-item" data-conversation-template-id="${template.id}">
      <input class="conversation-template-item-name" value="${escapeHtml(template.name)}" />
      <textarea class="conversation-template-item-body" rows="3">${escapeHtml(template.body)}</textarea>
      <label class="active-setting"><input class="conversation-template-item-active" type="checkbox" ${template.active ? "checked" : ""} />Activa</label>
      <span><button class="btn btn-small btn-secondary" type="button" onclick="saveConversationTemplate(${template.id})">Guardar</button> <button class="btn btn-small btn-danger" type="button" onclick="deleteConversationTemplate(${template.id})">Eliminar</button></span>
    </article>
  `).join("") || `<p class="empty-state">No hay plantillas.</p>`;
}

async function createConversationTemplate() {
  const payload = {
    name: document.getElementById("conversation-template-name").value.trim(),
    body: document.getElementById("conversation-template-body").value.trim(),
    active: true
  };
  if (!payload.name || !payload.body) return showConversationFeedback("Completa nombre y texto de la plantilla.", true);
  const saved = await mutateConversationTemplate(
    `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversation-templates`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }
  );
  if (!saved) return;
  document.getElementById("conversation-template-name").value = "";
  document.getElementById("conversation-template-body").value = "";
}

async function saveConversationTemplate(templateId) {
  const row = document.querySelector(`[data-conversation-template-id="${templateId}"]`);
  await mutateConversationTemplate(
    `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversation-templates/${templateId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: row.querySelector(".conversation-template-item-name").value.trim(),
        body: row.querySelector(".conversation-template-item-body").value.trim(),
        active: row.querySelector(".conversation-template-item-active").checked
      })
    }
  );
}

async function deleteConversationTemplate(templateId) {
  if (!window.confirm("¿Eliminar esta plantilla?")) return;
  await mutateConversationTemplate(
    `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversation-templates/${templateId}`,
    { method: "DELETE" }
  );
}

async function mutateConversationTemplate(url, options) {
  try {
    const response = await fetch(url, options);
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudo guardar la plantilla."));
    showConversationFeedback("Plantillas actualizadas.");
    await Promise.all([loadConversationTemplates(), loadConversationAutomation()]);
    if (selectedConversationId) await selectConversation(selectedConversationId, false);
    return true;
  } catch (error) {
    showConversationFeedback(error.message, true);
    return false;
  }
}

async function loadConversationAutomation({ background = false } = {}) {
  const requestVersion = ++conversationAutomationLoadVersion;
  const container = document.getElementById("conversation-automation-content");
  if (!container || !canManageConversationTemplates()) return;
  try {
    const [response, integrationResponse] = await Promise.all([
      fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversation-automation`, { cache: "no-store" }),
      fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/integrations/status`, { cache: "no-store" })
    ]);
    const body = await readAdminResponseBody(response);
    const integrationBody = await readAdminResponseBody(integrationResponse);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudo cargar la automatización."));
    if (requestVersion !== conversationAutomationLoadVersion) return;
    conversationAutomation = body;
    businessIntegrationStatus = integrationResponse.ok ? integrationBody : null;
    renderConversationAutomation();
  } catch (error) {
    if (requestVersion !== conversationAutomationLoadVersion) return;
    console.error(error);
    if (background) throw error;
    if (!conversationAutomation) {
      container.innerHTML = `<p class="empty-state">${escapeHtml(error.message)}</p>`;
    }
  }
}

function renderConversationAutomation() {
  const container = document.getElementById("conversation-automation-content");
  if (!container || !conversationAutomation || !canManageConversationTemplates()) return;
  const settings = conversationAutomation.settings;
  const usage = conversationAutomation.usage;
  const usageStatusLabels = {
    available: "Disponible",
    near_limit: "Cerca del límite",
    limit_reached: "Límite alcanzado",
    automation_paused: "Automatización pausada",
    pending_renewal: "Pendiente de renovación",
    suspended: "Suspendido"
  };
  const allowedLimitBehaviors = settings.allowed_limit_behaviors || ["disabled"];
  const limitBehaviorLabels = {
    semi_automatic: "Pasar a sugerencias",
    disabled: "No responder"
  };
  const periodSummary = usage.period_status === "active"
    ? `Inicio del periodo: ${new Date(usage.period_start).toLocaleString("es-ES")} · Periodo activo hasta: ${new Date(usage.period_end).toLocaleString("es-ES")} · ${usage.days_remaining} días restantes.`
    : usage.period_status === "suspended"
      ? `Periodo suspendido · Inicio: ${usage.period_start ? new Date(usage.period_start).toLocaleString("es-ES") : "sin fecha"} · Vencimiento: ${usage.period_end ? new Date(usage.period_end).toLocaleString("es-ES") : "sin fecha"}.`
      : `Periodo pendiente de renovación · Inicio anterior: ${usage.period_start ? new Date(usage.period_start).toLocaleString("es-ES") : "sin fecha"} · Vencimiento anterior: ${usage.period_end ? new Date(usage.period_end).toLocaleString("es-ES") : "sin fecha"}.`;
  const templates = conversationAutomation.templates || [];
  const templateOptions = (selectedId) => `
    <option value="">Plantilla recomendada</option>
    ${templates.map((template) => `
      <option value="${template.id}" ${template.id === selectedId ? "selected" : ""}>${escapeHtml(template.name)}${template.active ? "" : " (inactiva)"}</option>
    `).join("")}
  `;
  container.innerHTML = `
    <article class="conversation-integration-status state-${escapeHtml(businessIntegrationStatus?.state || "disconnected")}"><div><p>Integración de canal</p><strong>${escapeHtml(businessIntegrationStatus?.message || "Instagram no está conectado.")}</strong></div>${businessIntegrationStatus?.token_expires_at ? `<span>Caducidad: ${escapeHtml(new Date(businessIntegrationStatus.token_expires_at).toLocaleString("es-ES"))}</span>` : ""}</article>
    <div class="conversation-automation-settings">
      <label class="active-setting"><input id="conversation-automation-enabled" type="checkbox" ${settings.automation_enabled ? "checked" : ""} ${settings.automation_feature_enabled ? "" : "disabled"} />Activar automatización</label>
      <label>Umbral automático (%)<input id="conversation-automation-threshold" type="number" min="0" max="100" value="${settings.auto_threshold}" /></label>
      <label>Al alcanzar el límite<select id="conversation-automation-limit-mode" ${allowedLimitBehaviors.length === 1 ? "disabled" : ""}>${allowedLimitBehaviors.map((value) => `<option value="${value}" ${settings.on_limit_reached === value ? "selected" : ""}>${limitBehaviorLabels[value]}</option>`).join("")}</select></label>
      <label>Pausa tras respuesta humana<select id="conversation-human-reply-pause"><option value="0" ${settings.human_reply_pause_minutes === 0 ? "selected" : ""}>No pausar</option><option value="15" ${settings.human_reply_pause_minutes === 15 ? "selected" : ""}>15 minutos</option><option value="60" ${settings.human_reply_pause_minutes === 60 ? "selected" : ""}>1 hora</option><option value="240" ${settings.human_reply_pause_minutes === 240 ? "selected" : ""}>4 horas</option><option value="-1" ${settings.human_reply_pause_minutes === -1 ? "selected" : ""}>Hasta reactivarla</option></select></label>
      <button class="btn btn-primary" type="button" onclick="saveConversationAutomationSettings()">Guardar configuración</button>
    </div>
    <article class="conversation-automation-usage-card">
      <div><p>Créditos de automatización</p><strong>${usage.total_available} disponibles</strong><span class="conversation-automation-usage-state state-${escapeHtml(usage.status)}">${usageStatusLabels[usage.status] || usage.status}</span></div>
      <div class="conversation-credit-breakdown"><span><strong>${usage.included_credits_remaining} de ${usage.included_credits_per_period}</strong>Incluidos disponibles</span><span><strong>${usage.additional_credits_balance}</strong>Créditos adicionales acumulados</span><span><strong>${usage.total_available}</strong>Total disponible</span></div>
      <div class="conversation-automation-quota-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${usage.percentage}"><span style="width:${usage.percentage}%"></span></div>
      <p>${usage.percentage}% utilizado · ${escapeHtml(periodSummary)}</p>
      <p>${usage.period_status === "pending_renewal" ? "El periodo de automatización está pendiente de renovación. El equipo de AutonoGrow gestionará la reactivación." : "El límite de mensajes forma parte de tu plan de AutonoGrow. Para modificarlo, contacta con el equipo de AutonoGrow."}</p>
      ${usage.included_credits_remaining === 0 && usage.additional_credits_balance > 0 ? "<p>Has utilizado los mensajes incluidos en tu plan. A partir de ahora se utilizarán tus créditos adicionales.</p>" : ""}
      ${usage.total_available === 0 ? "<p class=\"conversation-automation-warning\">No quedan créditos de automatización disponibles. El equipo de AutonoGrow gestionará la ampliación del servicio.</p>" : ""}
      ${settings.automation_feature_enabled ? "" : "<p class=\"conversation-automation-warning\">La automatización está pausada por AutonoGrow para este negocio.</p>"}
    </article>
    ${usage.limit_reached ? `<p class="conversation-automation-warning">${settings.on_limit_reached === "semi_automatic" ? "Sin créditos disponibles. Las respuestas automáticas pasan a modo sugerencia." : "Sin créditos disponibles. No se enviarán más respuestas automáticas."}</p>` : ""}
    <div class="conversation-automation-rules">
      <h3>Modo por intención</h3>
      ${(conversationAutomation.rules || []).map((rule) => `
        <article class="conversation-automation-rule" data-automation-intent="${escapeHtml(rule.intent)}">
          <strong>${escapeHtml(rule.intent_label)}</strong>
          <select class="conversation-automation-rule-mode">
            <option value="disabled" ${rule.mode === "disabled" ? "selected" : ""}>Desactivado</option>
            <option value="semi_automatic" ${rule.mode === "semi_automatic" ? "selected" : ""}>Sugerir</option>
            <option value="automatic" ${rule.mode === "automatic" ? "selected" : ""}>Automático seguro</option>
          </select>
          <select class="conversation-automation-rule-template">${templateOptions(rule.template_id)}</select>
          <label class="active-setting"><input class="conversation-automation-rule-active" type="checkbox" ${rule.active ? "checked" : ""} />Activa</label>
          <button class="btn btn-small btn-secondary" type="button" onclick="saveConversationAutomationRule('${rule.intent}')">Guardar</button>
        </article>
      `).join("")}
    </div>
  `;
}

async function saveConversationAutomationSettings() {
  const payload = {
    automation_enabled: document.getElementById("conversation-automation-enabled").checked,
    auto_threshold: Number(document.getElementById("conversation-automation-threshold").value),
    on_limit_reached: document.getElementById("conversation-automation-limit-mode").value,
    human_reply_pause_minutes: Number(document.getElementById("conversation-human-reply-pause").value)
  };
  await mutateConversationAutomation(
    `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversation-automation/settings`,
    payload,
    "Configuración de automatización actualizada."
  );
}

async function saveConversationAutomationRule(intent) {
  const row = document.querySelector(`[data-automation-intent="${intent}"]`);
  if (!row) return;
  const templateValue = row.querySelector(".conversation-automation-rule-template").value;
  const payload = {
    mode: row.querySelector(".conversation-automation-rule-mode").value,
    template_id: templateValue ? Number(templateValue) : null,
    active: row.querySelector(".conversation-automation-rule-active").checked
  };
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversation-automation/rules/${intent}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }
    );
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudo guardar la regla."));
    if (body.rule?.mode !== payload.mode) throw new Error("El backend no confirmó el modo seleccionado.");
    await loadConversationAutomation();
    await requestAdminRefresh(["conversationList", "conversationThread", "operations"]);
    const persistedRule = conversationAutomation?.rules?.find((rule) => rule.intent === intent);
    if (persistedRule?.mode !== payload.mode) throw new Error("La regla no se recargó con el modo guardado.");
    showConversationFeedback(`Regla de ${conversationIntentLabel(intent)} actualizada.`);
  } catch (error) {
    showConversationFeedback(error.message, true);
  }
}

async function mutateConversationAutomation(url, payload, successMessage) {
  try {
    const response = await fetch(url, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudo guardar la automatización."));
    showConversationFeedback(successMessage);
    await loadConversationAutomation();
    await requestAdminRefresh(["conversationList", "conversationThread", "operations"]);
    return true;
  } catch (error) {
    showConversationFeedback(error.message, true);
    return false;
  }
}

async function loadMessageOutbox({ background = false } = {}) {
  const container = document.getElementById("message-outbox-list");

  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/message-outbox`
    );

    if (!response.ok) {
      throw new Error("No se pudieron cargar los mensajes.");
    }

    const data = await response.json();
    const nextMessages = data.messages || [];
    const nextFingerprint = JSON.stringify(nextMessages);
    const changed = nextFingerprint !== messageOutboxFingerprint;
    messageOutbox = nextMessages;
    messageOutboxFingerprint = nextFingerprint;
    growthDataReady.messages = true;
    if (!changed && background) return;
    renderMessageOutboxMetrics();
    renderMessageOutbox();
    renderGrowth();
  } catch (error) {
    console.error(error);
    if (background) throw error;
    if (!messageOutbox.length) {
      container.innerHTML = `<p class="empty-state">No se pudieron cargar los mensajes.</p>`;
      document.getElementById("message-outbox-history-list").innerHTML =
        `<p class="empty-state">No se pudo cargar el historial.</p>`;
    }
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
    requestAdminRefresh(["operations"]);
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
    await requestAdminRefresh(["operations"]);
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

function ensureAdminPollingTasks() {
  if (adminPollingTasks.size) return;
  adminPollingTasks.set("conversationThread", {
    run: async () => {
      if (selectedConversationId) {
        await selectConversation(selectedConversationId, false, { background: true });
      }
    },
    inFlight: false,
    rerunRequested: false,
    failures: 0,
    error: false,
    timer: null,
    promise: null
  });
  adminPollingTasks.set("conversationList", {
    run: () => loadConversations({ background: true, refreshDetail: false }),
    inFlight: false,
    rerunRequested: false,
    failures: 0,
    error: false,
    timer: null,
    promise: null
  });
  adminPollingTasks.set("operations", {
    run: async () => {
      const requests = [loadBookings({ background: true })];
      if (!isBusinessStaff()) requests.push(loadMessageOutbox({ background: true }));
      await Promise.all(requests);
    },
    inFlight: false,
    rerunRequested: false,
    failures: 0,
    error: false,
    timer: null,
    promise: null
  });
}

function updateAdminSyncIndicator() {
  const container = document.getElementById("admin-sync-status");
  const label = document.getElementById("admin-sync-status-label");
  const updated = document.getElementById("admin-sync-last-updated");
  if (!container || !label || !updated) return;
  const tasks = Array.from(adminPollingTasks.values());
  const isUpdating = tasks.some((task) => task.inFlight);
  const hasTemporaryError = tasks.some((task) => task.error);
  container.classList.toggle("admin-sync-updating", isUpdating);
  container.classList.toggle("admin-sync-error", !isUpdating && hasTemporaryError);
  container.classList.toggle("admin-sync-connected", !isUpdating && !hasTemporaryError);
  label.textContent = isUpdating
    ? "Actualizando"
    : hasTemporaryError ? "Error temporal" : "Conectado";
  updated.textContent = adminPollingLastSuccessAt
    ? `Última actualización: ${adminPollingLastSuccessAt.toLocaleTimeString("es-ES")}`
    : "Esperando actualización";
}

function adminPollDelay(taskName, task) {
  const visibility = document.hidden ? "hidden" : "visible";
  const baseDelay = ADMIN_POLL_INTERVALS[taskName][visibility];
  const multiplier = Math.min(
    2 ** task.failures,
    ADMIN_POLL_MAX_BACKOFF_MULTIPLIER
  );
  return baseDelay * multiplier;
}

function scheduleAdminPollTask(taskName, delay = null) {
  const task = adminPollingTasks.get(taskName);
  if (!adminPollingActive || !task || task.inFlight) return;
  window.clearTimeout(task.timer);
  task.timer = window.setTimeout(
    () => runAdminPollTask(taskName),
    delay ?? adminPollDelay(taskName, task)
  );
}

function runAdminPollTask(taskName) {
  ensureAdminPollingTasks();
  const task = adminPollingTasks.get(taskName);
  if (!task) return Promise.resolve();
  if (task.inFlight) {
    task.rerunRequested = true;
    return task.promise || Promise.resolve();
  }
  window.clearTimeout(task.timer);
  task.inFlight = true;
  updateAdminSyncIndicator();
  task.promise = (async () => {
    try {
      await task.run();
      task.failures = 0;
      task.error = false;
      adminPollingLastSuccessAt = new Date();
    } catch (error) {
      task.failures += 1;
      task.error = true;
      console.warn("Actualización automática temporalmente no disponible", { task: taskName });
    } finally {
      task.inFlight = false;
      task.promise = null;
      const rerunRequested = task.rerunRequested;
      task.rerunRequested = false;
      updateAdminSyncIndicator();
      if (adminPollingActive) scheduleAdminPollTask(taskName, rerunRequested ? 0 : null);
    }
  })();
  return task.promise;
}

function requestAdminRefresh(taskNames = null) {
  ensureAdminPollingTasks();
  const names = Array.isArray(taskNames)
    ? taskNames
    : ["conversationList", "conversationThread", "operations"];
  return Promise.all(names.map((taskName) => runAdminPollTask(taskName)));
}

function startAdminPolling() {
  ensureAdminPollingTasks();
  if (adminPollingActive) return;
  adminPollingActive = true;
  adminPollingLastSuccessAt = new Date();
  adminPollingTasks.forEach((task, taskName) => {
    task.failures = 0;
    task.error = false;
    scheduleAdminPollTask(taskName);
  });
  updateAdminSyncIndicator();
}

function stopAdminPolling() {
  adminPollingActive = false;
  adminPollingTasks.forEach((task) => {
    window.clearTimeout(task.timer);
    task.timer = null;
    task.rerunRequested = false;
  });
}

function handleAdminVisibilityChange() {
  if (!adminPollingActive) return;
  if (!document.hidden) {
    requestAdminRefresh(["conversationList", "conversationThread", "operations"]);
    return;
  }
  adminPollingTasks.forEach((task, taskName) => {
    if (!task.inFlight) scheduleAdminPollTask(taskName);
  });
}

async function refreshOperationalData({ includeAutomation = false } = {}) {
  const requests = [
    requestAdminRefresh(["conversationList", "conversationThread", "operations"])
  ];
  if (includeAutomation && canManageConversationTemplates()) {
    requests.push(loadConversationAutomation({ background: true }));
  }
  await Promise.allSettled(requests);
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
  const isClosed = (booking) => ["completed", "rejected", "cancelled", "no_show"].includes(booking.status);
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

  if (selectedStaffFilter) {
    bookings = bookings.filter((booking) => String(booking.staff_business_user_id || "") === selectedStaffFilter);
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
    card.id = `booking-${booking.id}`;
    card.dataset.bookingId = booking.id;
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
        <div class="booking-field">
          <span>Profesional</span>
          <strong>${escapeHtml(booking.staff_display_name || "Sin asignar")}</strong>
        </div>
      </div>
      ${renderNotes(booking.notes)}
      <div class="booking-notes internal-notes-editor">
        <label>Notas internas<textarea data-internal-notes="${booking.id}" rows="2">${escapeHtml(booking.internal_notes || "")}</textarea></label>
        <button class="btn btn-small btn-secondary" type="button" onclick="saveInternalNotes(${booking.id})">Guardar notas</button>
      </div>
      ${renderBookingActions(booking)}
      ${renderReviewRequest(booking)}
      ${renderAttachments(booking.attachments || [])}
    `;

    list.appendChild(card);
  });
}

function getViewForBooking(booking) {
  if (["requested", "pending"].includes(booking.status)) return "pending";
  const isClosed = ["completed", "rejected", "cancelled", "no_show"].includes(booking.status);
  const date = getBookingDateKey(booking);
  const today = getMadridDateKey();
  const tomorrow = addDaysToDateKey(today, 1);
  if (isClosed || (date && date < today)) return "history";
  if (date === today) return "today";
  if (date === tomorrow) return "tomorrow";
  return "upcoming";
}

function goToBooking(bookingId, updateUrl = true) {
  // TODO: sustituir esta navegacion por una accion de reasignacion cuando exista
  // un endpoint para cambiar el profesional de una reserva.
  const booking = allBookings.find((item) => item.id === bookingId);
  if (!booking) {
    alert(`No se encontró la reserva #${bookingId}.`);
    return;
  }

  closeStaffRemovalModal();
  selectedStaffFilter = "";
  document.getElementById("booking-staff-filter").value = "";
  currentBookingView = getViewForBooking(booking);
  document.querySelectorAll("[data-booking-view]").forEach((tab) => {
    tab.classList.toggle("booking-view-tab-active", tab.dataset.bookingView === currentBookingView);
  });
  if (updateUrl) {
    const url = new URL(window.location.href);
    url.searchParams.set("booking", bookingId);
    window.history.replaceState(null, "", `${url.pathname}${url.search}#bookings`);
  }
  showAdminSection("bookings");
  renderBookings();

  const card = document.getElementById(`booking-${bookingId}`);
  if (!card) return;
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  card.classList.add("booking-card-highlight");
  window.setTimeout(() => card.classList.remove("booking-card-highlight"), 4000);
}

function renderReviewRequest(booking) {
  if (isBusinessStaff()) {
    return "";
  }
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
    await requestAdminRefresh(["operations"]);
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
  const isNoShow = booking.status === "no_show";
  const isClosed = isCompleted || isRejected || isCancelled || isNoShow;

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
      <button class="btn btn-small btn-danger" type="button" onclick="updateBookingStatus(${booking.id}, 'cancelled')" ${isClosed ? "disabled" : ""}>
        Cancelar
      </button>
      <button class="btn btn-small btn-secondary" type="button" onclick="updateBookingStatus(${booking.id}, 'completed')" ${booking.status === "completed" || isRejected || isCancelled ? "disabled" : ""}>
        Completada
      </button>
      <button class="btn btn-small btn-secondary" type="button" onclick="updateBookingStatus(${booking.id}, 'no_show')" ${isClosed ? "disabled" : ""}>
        No presentado
      </button>
    </div>
  `;
}

async function saveInternalNotes(bookingId) {
  const field = document.querySelector(`[data-internal-notes="${bookingId}"]`);
  const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/bookings/${bookingId}/internal-notes`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ internal_notes: field.value.trim() || null })
  });
  const result = await response.json().catch(() => null);
  if (!response.ok) return alert(result?.detail || "No se pudieron guardar las notas.");
  const index = allBookings.findIndex((item) => item.id === bookingId);
  if (index >= 0) allBookings[index] = { ...allBookings[index], ...result.booking };
  alert("Notas internas guardadas.");
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
    const params = new URLSearchParams({
      service_id: booking.service_id,
      date: rescheduleState.date,
      exclude_booking_id: booking.id
    });
    if (booking.staff_business_user_id) params.set("staff_business_user_id", booking.staff_business_user_id);
    const response = await fetch(`${API_BASE_URL}/api/businesses/${getBusinessSlug()}/available-slots?${params.toString()}`);

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
    cancelled: "status-rejected",
    no_show: "status-rejected"
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
    cancelled: "Cancelada",
    no_show: "No presentado"
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
  document.getElementById("refresh-button").addEventListener("click", () => {
    refreshOperationalData({ includeAutomation: true });
  });
  document.addEventListener("visibilitychange", handleAdminVisibilityChange);
  document.getElementById("message-status-filter").addEventListener("change", renderMessageOutbox);
  document.getElementById("save-business-settings").addEventListener("click", saveBusinessSettings);
  document.getElementById("create-service").addEventListener("click", createAdminService);
  document.getElementById("create-staff-member").addEventListener("click", createStaffMember);
  document.getElementById("toggle-conversation-create").addEventListener("click", () => {
    const panel = document.getElementById("conversation-create-panel");
    panel.hidden = !panel.hidden;
  });
  document.getElementById("create-conversation").addEventListener("click", createConversation);
  document.getElementById("create-conversation-template").addEventListener("click", createConversationTemplate);
  document.getElementById("conversation-status-filter").addEventListener("change", () => {
    requestAdminRefresh(["conversationList", "conversationThread"]);
  });
  document.getElementById("conversation-channel-filter").addEventListener("change", () => {
    requestAdminRefresh(["conversationList", "conversationThread"]);
  });
  document.getElementById("conversation-search").addEventListener("input", () => {
    clearTimeout(conversationSearchTimer);
    conversationSearchTimer = setTimeout(
      () => requestAdminRefresh(["conversationList", "conversationThread"]),
      250
    );
  });
  document.getElementById("booking-staff-filter").addEventListener("change", (event) => {
    selectedStaffFilter = event.target.value;
    renderBookings();
  });
  document.getElementById("save-availability-settings").addEventListener("click", saveAvailabilitySettings);
  document.getElementById("save-availability-exception").addEventListener("click", saveAvailabilityException);
  setupExceptionForm();
  setupAdminBranding();
  document.getElementById("channel-onboarding-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-channel-request]");
    if (button) requestBusinessChannelConnection(button.dataset.channelRequest, button);
  });
  document.getElementById("admin-logout").addEventListener("click", adminLogout);
  document.getElementById("admin-gate-logout").addEventListener("click", adminLogout);
  bootstrapAdminAuth();
});

async function showAdminLogin(message = "Inicia sesión con la cuenta asignada al negocio.", denied = false) {
  stopAdminPolling();
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
    adminMembership = adminAuthUser.businesses.find((item) => item.slug === slug) || null;
    const allowed = adminAuthUser.is_owner || Boolean(adminMembership);
    if (!allowed) return showAdminLogin("Tu cuenta no tiene acceso a este negocio.", true);
    document.getElementById("admin-auth-gate").hidden = true;
    document.getElementById("admin-app").hidden = false;
    document.getElementById("admin-auth-user").textContent = adminAuthUser.name || adminAuthUser.email;
    applyRoleVisibility();
    const oauthResult = new URLSearchParams(window.location.search).get("instagram_oauth");
    if (oauthResult) {
      const feedback = document.getElementById("channel-onboarding-feedback");
      if (feedback) feedback.textContent = oauthResult === "pending_review" ? "Instagram conectado. La cuenta queda pendiente de revisión por el Owner." : "No se pudo completar Instagram Login. Inicia un nuevo intento.";
    }
    await loadAdminPanel();
    if (currentBusiness) startAdminPolling();
  } catch (error) {
    console.error("Admin authentication failed", error);
    await showAdminLogin(error.message);
  }
}

async function adminLogout() {
  stopAdminPolling();
  await AutonoGrowAuth.logout();
  adminAuthUser = null;
  await showAdminLogin();
}
