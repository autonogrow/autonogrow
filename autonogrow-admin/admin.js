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
    const payload = await response.clone().json().catch(() => null);
    if (payload?.detail?.code === "business_not_operational") {
      lastBusinessOperationalStatus = payload.detail.business_status;
      queueMicrotask(() => applyOperationalBusinessState(payload.detail.business_status));
    } else {
      queueMicrotask(() => showAdminLogin("Tu cuenta no tiene acceso a este negocio.", true));
    }
  }
  return response;
};

let currentBusiness = null;
let lastBusinessOperationalStatus = null;
let businessCapabilities = {
  essential: { available: true }, growth: { available: true }, social: { available: true }
};
let pilotReadiness = null;
let pilotValueSummary = null;
let adminAuthUser = null;
let allBookings = [];
let bookingCloseTasks = [];
let reviewRequestsByBooking = new Map();
let messageOutbox = [];
let adminServices = [];
let customerOpportunities = [];
let businessGrowthSignals = [];
let growthSignalsSummary = null;
let growthActionMetrics = null;
let selectedOpportunityAction = null;
let selectedOpportunityForAction = null;
let growthActionReturnFocus = null;
let opportunityAssistedOpening = false;
const opportunityMutationIds = new Set();
const growthSignalMutationIds = new Set();
let availabilitySettings = null;
let availabilityExceptions = [];
let exceptionDraftWindows = [];
let currentBookingView = "day";
let agendaSelectedDate = "";
let agendaSelectedBookingId = null;
let selectedBookingStatusFilter = "";
let selectedBookingServiceFilter = "";
let bookingCustomerSearch = "";
let adminGallery = [];
let adminMembership = null;
let staffMembers = [];
let selectedStaffFilter = "";
let conversations = [];
let dashboardConversations = [];
let conversationTemplates = [];
let conversationAutomation = null;
let businessIntegrationStatus = null;
let businessChannelOnboarding = null;
let businessChannelHealth = [];
let adminInstagramSettings = null;
let adminInstagramContents = [];
let adminInstagramMetrics = null;
let adminInstagramCalendarView = "week";
let adminInstagramCalendarDate = "";
let adminInstagramSelectedContentId = null;
let adminInstagramStateFilter = "";
let adminInstagramFormatFilter = "";
let socialContentProposals = [];
const socialContentProposalMutationIds = new Set();
let conversationSuggestions = [];
let selectedConversationSuggestionId = null;
let conversationSuggestionNotice = null;
const sendingConversationSuggestionIds = new Set();
let selectedConversationId = null;
let selectedConversation = null;
let conversationSearchTimer = null;
let conversationReplySending = false;
let conversationAssistedOpening = false;
let conversationStatusUpdating = false;
let conversationCustomerPanelOpen = false;
let conversationCustomerReturnFocus = null;
let conversationCustomerSearchState = { open: false, loading: false, query: "", results: [] };
let conversationCustomerAssociationUpdating = false;
const customerMemorySummaries = new Map();
const customerMemoryLoadingIds = new Set();
let customerMemoryFormState = null;
const customerMemoryMutationIds = new Set();
const BOOKING_CUSTOMER_MEMORY_HIDE_MS = 60_000;
const bookingCustomerMemoryDrafts = new Map();
let bookingCustomerMemoryTimer = null;
let bookingCustomerMemoryPanelState = {
  bookingId: null,
  customerId: null,
  open: false,
  formOpen: false,
  draft: "",
  saving: false,
  feedback: "",
  feedbackError: false
};
let conversationLoadVersion = 0;
let conversationDetailVersion = 0;
let conversationAutomationLoadVersion = 0;
let conversationTemplatesLoadVersion = 0;
let channelOnboardingLoadVersion = 0;
let reviewRequestsLoadVersion = 0;
let conversationListFingerprint = "";
let conversationDetailFingerprint = "";
let bookingsFingerprint = "";
let bookingsLoadVersion = 0;
let bookingCloseTasksLoadVersion = 0;
let rescheduleSlotsLoadVersion = 0;
let rescheduleReturnFocus = null;
let rescheduleSubmitting = false;
const bookingMutationIds = new Set();
let messageOutboxFingerprint = "";
let messageOutboxLoadVersion = 0;
let reviewRequestsFingerprint = "";
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
const growthLoadState = { reviews: "loading", outbox: "loading", opportunities: "loading", signals: "loading" };
const dashboardDataState = {
  business: "loading",
  bookings: "loading",
  closeTasks: "loading",
  conversations: "loading",
  services: "loading",
  availability: "loading",
  channels: "loading"
};
let dashboardAnnouncementFingerprint = "";
const dashboardRetryInFlight = new Set();
let rescheduleState = {
  booking: null,
  date: "",
  dayLabel: "",
  slot: null
};
const CONFIGURATION_SECTIONS = new Set(["configuration", "business", "services", "staff", "schedule", "public-page"]);
const CHANNEL_HUB_SECTIONS = new Set(["channels", "channel-instagram", "channel-whatsapp", "messages"]);
const GROWTH_HUB_SECTIONS = new Set(["growth", "reviews", "growth-opportunities"]);
const GROWTH_HUB_CATEGORIES = [
  { id: "growth", label: "Resumen", description: "Prioridades y actividad" },
  { id: "reviews", label: "Reseñas", description: "Clientes y solicitudes" },
  { id: "growth-opportunities", label: "Oportunidades", description: "Mejoras basadas en datos" }
];
const CHANNEL_HUB_CATEGORIES = [
  { id: "channels", label: "Resumen", description: "Estado de los canales" },
  { id: "channel-instagram", label: "Instagram", description: "Conexión y diagnóstico" },
  { id: "channel-whatsapp", label: "WhatsApp", description: "Entrega y diagnóstico" },
  { id: "messages", label: "Respuestas automáticas", description: "Reglas, plantillas y créditos" }
];
const CONFIGURATION_CATEGORIES = [
  { id: "configuration", label: "Resumen", description: "Qué está listo y qué falta" },
  { id: "business", label: "Información", description: "Datos públicos y contacto" },
  { id: "services", label: "Servicios", description: "Catálogo, duración y precio" },
  { id: "staff", label: "Equipo", description: "Acceso y profesionales" },
  { id: "schedule", label: "Horarios", description: "Disponibilidad y reglas" },
  { id: "public-page", label: "Página pública", description: "Publicación, tema e imágenes" }
];
const configurationSnapshots = new Map();
const configurationDirtyKeys = new Set();
const configurationMutationKeys = new Set();
const channelActionKeys = new Set();
const reviewMutationKeys = new Set();
const channelHubLoadState = { onboarding: "loading", health: "loading", automation: "loading", templates: "loading" };
const configurationLoadState = { staff: "loading", gallery: "loading", exceptions: "loading" };
let staffRemovalReturnFocus = null;

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

function moduleAvailable(moduleKey) {
  return businessCapabilities?.[moduleKey]?.available === true;
}

function applyOperationalBusinessState(status = currentBusiness?.status) {
  const operational = status === "active";
  const banner = document.getElementById("business-operational-banner");
  const title = document.getElementById("business-operational-banner-title");
  const message = document.getElementById("business-operational-banner-message");
  document.body.classList.toggle("business-non-operational", !operational);
  if (!banner || !title || !message) return;
  banner.hidden = operational || !status;
  if (operational || !status) return;
  const archived = status === "archived";
  title.textContent = archived ? "Este negocio está archivado" : "Este negocio está suspendido";
  message.textContent = archived
    ? "Puedes consultar el histórico, pero las operaciones y acciones externas están deshabilitadas."
    : "Las operaciones están temporalmente deshabilitadas. Puedes consultar el histórico mientras Owner revisa la reactivación.";
}

document.addEventListener("submit", (event) => {
  if (currentBusiness?.status && currentBusiness.status !== "active") {
    event.preventDefault();
    applyOperationalBusinessState(currentBusiness.status);
  }
}, true);

function configurationCategoryForKey(key) {
  if (key === "business-info") return "business";
  if (key === "public-page" || key.startsWith("gallery-")) return "public-page";
  if (key.startsWith("service-")) return "services";
  if (key.startsWith("staff-")) return "staff";
  if (key === "availability" || key === "exception") return "schedule";
  if (key === "template-new" || key.startsWith("template-") || key === "automation-settings" || key.startsWith("automation-rule-")) return "messages";
  return null;
}

function configurationFormElement(key) {
  return [...document.querySelectorAll("[data-config-dirty-key]")]
    .find((element) => element.dataset.configDirtyKey === key) || null;
}

function serializeConfigurationForm(element) {
  if (!element) return "";
  return JSON.stringify([...element.querySelectorAll("input, select, textarea")]
    .filter((field) => field.type !== "file" && !field.disabled && !field.hasAttribute("data-ignore-dirty") && field.closest("[data-config-dirty-key]") === element)
    .map((field) => ({
      key: field.id || field.name || field.className,
      value: ["checkbox", "radio"].includes(field.type) ? field.checked : field.value
    })));
}

function snapshotConfigurationForm(key) {
  const element = configurationFormElement(key);
  if (!element) return;
  configurationSnapshots.set(key, serializeConfigurationForm(element));
  configurationDirtyKeys.delete(key);
  updateConfigurationDirtyUi(key);
}

function ensureConfigurationSnapshot(key) {
  if (!configurationSnapshots.has(key)) snapshotConfigurationForm(key);
}

function snapshotConfigurationForms(selector = "[data-config-dirty-key]") {
  document.querySelectorAll(selector).forEach((element) => {
    snapshotConfigurationForm(element.dataset.configDirtyKey);
  });
}

function updateConfigurationDirtyState(key) {
  const element = configurationFormElement(key);
  if (!element || !configurationSnapshots.has(key)) return;
  const dirty = serializeConfigurationForm(element) !== configurationSnapshots.get(key);
  configurationDirtyKeys[dirty ? "add" : "delete"](key);
  updateConfigurationDirtyUi(key);
}

function updateConfigurationDirtyUi(key) {
  const dirty = configurationDirtyKeys.has(key);
  const element = configurationFormElement(key);
  element?.classList.toggle("has-unsaved-changes", dirty);
  const itemState = element?.querySelector(".configuration-item-save-state");
  if (itemState) itemState.textContent = dirty ? "Cambios sin guardar" : "Sin cambios";
  const stateId = key === "business-info"
    ? "business-settings-save-state"
    : key === "public-page" ? "public-page-save-state" : key === "availability" ? "availability-save-state" : null;
  if (stateId) document.getElementById(stateId).textContent = dirty ? "Cambios sin guardar" : "Sin cambios";
}

function configurationSectionHasDirty(section) {
  return [...configurationDirtyKeys].some((key) => configurationCategoryForKey(key) === section);
}

function confirmConfigurationNavigation(nextSection) {
  const current = document.querySelector("[data-admin-section].admin-section-active")?.dataset.adminSection;
  const guardedSections = new Set([...CONFIGURATION_SECTIONS, ...CHANNEL_HUB_SECTIONS]);
  if (!current || current === nextSection || !guardedSections.has(current) || !configurationSectionHasDirty(current)) return true;
  return window.confirm("Hay cambios sin guardar en este apartado. Puedes cambiar de sección y volver a guardarlos antes de salir de la página. ¿Continuar?");
}

function configurationState(section) {
  if (section === "business") {
    if (!currentBusiness) return { state: "loading", label: "Comprobando…", detail: "Cargando información" };
    return currentBusiness.name?.trim()
      ? { state: "complete", label: "Completo", detail: "Información básica disponible" }
      : { state: "missing", label: "Faltan datos", detail: "Falta el nombre del negocio" };
  }
  if (section === "services") {
    if (dashboardDataState.services === "error") return { state: "error", label: "Error al cargar", detail: "Reintenta cargar los servicios" };
    if (dashboardDataState.services !== "ready") return { state: "loading", label: "Comprobando…", detail: "Cargando servicios" };
    const active = adminServices.filter((service) => service.active).length;
    return active
      ? { state: "complete", label: "Completo", detail: `${active} ${active === 1 ? "servicio activo" : "servicios activos"}` }
      : { state: "missing", label: "Faltan datos", detail: "No hay servicios activos" };
  }
  if (section === "staff") {
    if (configurationLoadState.staff === "error") return { state: "error", label: "Error al cargar", detail: "Reintenta cargar el equipo" };
    if (configurationLoadState.staff !== "ready") return { state: "loading", label: "Comprobando…", detail: "Cargando equipo" };
    const professionals = staffMembers.filter((member) => member.active && member.bookable).length;
    return professionals
      ? { state: "complete", label: "Completo", detail: `${professionals} ${professionals === 1 ? "profesional reservable" : "profesionales reservables"}` }
      : { state: "missing", label: "Faltan datos", detail: "No hay profesionales reservables" };
  }
  if (section === "schedule") {
    if (dashboardDataState.availability === "error") return { state: "error", label: "Error al cargar", detail: "Reintenta cargar los horarios" };
    if (dashboardDataState.availability !== "ready") return { state: "loading", label: "Comprobando…", detail: "Cargando horarios" };
    const hasWindows = Object.values(availabilitySettings?.weekly_schedule || {}).some((windows) => windows.length);
    return hasWindows
      ? { state: "complete", label: "Completo", detail: "Horario semanal configurado" }
      : { state: "missing", label: "Faltan datos", detail: "No hay tramos de apertura" };
  }
  if (section === "public-page") {
    if (!currentBusiness || configurationLoadState.gallery === "loading") return { state: "loading", label: "Comprobando…", detail: "Cargando página pública" };
    if (configurationLoadState.gallery === "error") return { state: "error", label: "Error al cargar", detail: "La galería necesita reintento" };
    return currentBusiness.active
      ? { state: "complete", label: "Completo", detail: "Página pública activa" }
      : { state: "review", label: "Necesita revisión", detail: "La página pública está desactivada" };
  }
  return { state: "loading", label: "Comprobando…", detail: "" };
}

function configurationNavigationMarkup(activeSection) {
  return `<nav class="configuration-navigation" aria-label="Apartados de configuración"><p>Configuración</p>${CONFIGURATION_CATEGORIES.map((category) => {
    const state = category.id === "configuration" ? null : configurationState(category.id);
    return `<button type="button" data-configuration-target="${category.id}" ${category.id === activeSection ? 'aria-current="page"' : ""}><span><strong>${category.label}</strong><small>${category.description}</small></span>${state ? `<em class="configuration-nav-state configuration-nav-state--${state.state}">${state.label}</em>` : ""}</button>`;
  }).join("")}</nav>`;
}

function renderConfigurationOverview() {
  if (!document.getElementById("configuration-overview-list")) return;
  const activeSection = document.querySelector("[data-admin-section].admin-section-active")?.dataset.adminSection || "configuration";
  document.querySelectorAll("[data-configuration-navigation]").forEach((container) => {
    container.innerHTML = configurationNavigationMarkup(activeSection);
  });
  const sections = CONFIGURATION_CATEGORIES.filter((category) => category.id !== "configuration");
  const states = sections.map((category) => ({ category, status: configurationState(category.id) }));
  const ready = states.filter(({ status }) => status.state === "complete").length;
  document.getElementById("configuration-business-name").textContent = currentBusiness?.name || "Negocio sin nombre";
  document.getElementById("configuration-ready-summary").textContent = `${ready} de ${states.length} apartados preparados`;
  document.getElementById("configuration-overview-list").innerHTML = states.map(({ category, status }) => `
    <article class="configuration-overview-item configuration-overview-item--${status.state}">
      <div><h3>${category.label}</h3><p>${escapeHtml(status.detail)}</p></div>
      <span class="configuration-status configuration-status--${status.state}">${status.label}</span>
      <button class="ag-button ag-button--secondary ag-button--small" type="button" data-configuration-target="${category.id}">Revisar</button>
    </article>`).join("");
  const pending = states.filter(({ status }) => !["complete", "loading"].includes(status.state));
  document.getElementById("configuration-task-list").innerHTML = pending.length
    ? pending.map(({ category, status }) => `<button type="button" data-configuration-target="${category.id}"><strong>${category.label}</strong><span>${escapeHtml(status.detail)}</span></button>`).join("")
    : `<p class="configuration-all-ready">Todos los apartados disponibles están preparados.</p>`;
  for (const { category, status } of states) {
    const badge = document.getElementById(`configuration-status-${category.id}`);
    if (badge) {
      badge.className = `configuration-status configuration-status--${status.state}`;
      badge.textContent = status.label;
    }
  }
}

function growthNavigationMarkup(activeSection) {
  const categories = isBusinessStaff()
    ? GROWTH_HUB_CATEGORIES.filter((category) => category.id !== "reviews")
    : GROWTH_HUB_CATEGORIES;
  return `<nav class="growth-navigation" aria-label="Crecimiento"><p>Crecimiento</p>${categories.map((category) => `<button type="button" data-growth-target="${category.id}" ${category.id === activeSection ? 'aria-current="page"' : ""}><span><strong>${category.label}</strong><small>${category.description}</small></span></button>`).join("")}</nav>`;
}

function renderGrowthNavigation() {
  const active = document.querySelector("[data-admin-section].admin-section-active")?.dataset.adminSection || "growth";
  document.querySelectorAll("[data-growth-navigation]").forEach((container) => { container.innerHTML = growthNavigationMarkup(active); });
}

function navigateToGrowthAction(button) {
  const action = button.dataset.growthAction;
  if (action === "reviews") return showAdminSection("reviews");
  if (action === "opportunities") return showAdminSection("growth-opportunities");
  if (action === "bookings-pending") {
    if (!showAdminSection("bookings")) return;
    setBookingView("pending");
    return;
  }
  if (action === "booking") return goToBooking(Number(button.dataset.bookingId));
  if (action === "configuration-reviews") {
    if (showAdminSection("business")) window.requestAnimationFrame(() => document.getElementById("business-setting-reviews-url")?.focus());
    return;
  }
  if (action === "services") return showAdminSection("services");
  if (action === "schedule") return showAdminSection("schedule");
  if (action === "public-page") return showAdminSection("public-page");
  if (action === "conversations") return showAdminSection("conversations");
  if (action === "automations") return showAdminSection("messages");
  if (action === "channel") return showAdminSection(`channel-${button.dataset.channel}`);
}

function setupGrowthHub() {
  const main = document.getElementById("admin-main-content");
  main.addEventListener("click", (event) => {
    const navigation = event.target.closest("[data-growth-target]");
    if (navigation) {
      const section = navigation.dataset.growthTarget;
      if (showAdminSection(section)) window.requestAnimationFrame(() => {
        const heading = document.querySelector(`[data-admin-section="${section}"] h2`);
        heading?.setAttribute("tabindex", "-1");
        heading?.focus({ preventScroll: true });
      });
      return;
    }
    const action = event.target.closest("[data-growth-action]");
    if (action) { navigateToGrowthAction(action); return; }
    const create = event.target.closest("[data-review-create]");
    if (create) { createReviewRequest(Number(create.dataset.reviewCreate)); return; }
    const open = event.target.closest("[data-review-open]");
    if (open) { openReviewWhatsApp(Number(open.dataset.reviewOpen)); return; }
    const copy = event.target.closest("[data-review-copy]");
    if (copy) { copyReviewMessage(Number(copy.dataset.reviewCopy)); return; }
    const status = event.target.closest("[data-review-status]");
    if (status) updateReviewRequestStatus(Number(status.dataset.reviewRequest), status.dataset.reviewStatus);
    const opportunity = event.target.closest("[data-opportunity-action]");
    if (opportunity) {
      const opportunityId = Number(opportunity.dataset.opportunityId);
      const opportunityAction = opportunity.dataset.opportunityAction;
      if (opportunityAction === "prepare") prepareOpportunityMessage(opportunityId, opportunity);
      else if (opportunityAction === "conversation") openOpportunityConversation(opportunityId);
      else updateCustomerOpportunity(opportunityId, opportunityAction);
    }
    const signalAction = event.target.closest("[data-growth-signal-action]");
    if (signalAction?.dataset.growthSignalAction === "dismiss") dismissGrowthSignal(Number(signalAction.dataset.growthSignalId));
    if (signalAction?.dataset.growthSignalAction === "opportunities") openSignalOpportunities(Number(signalAction.dataset.growthSignalId));
    const modalAction = event.target.closest("[data-growth-action-modal]");
    if (modalAction?.dataset.growthActionModal === "close") closeGrowthActionModal();
    if (modalAction?.dataset.growthActionModal === "copy") copyGrowthOpportunityText();
    if (modalAction?.dataset.growthActionModal === "send") sendGrowthOpportunityAction();
    if (modalAction?.dataset.growthActionModal === "whatsapp") openGrowthOpportunityWhatsApp();
  });
  document.getElementById("growth-action-modal")?.addEventListener("click", (event) => {
    if (event.target.id === "growth-action-modal") closeGrowthActionModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && document.getElementById("growth-action-modal")?.classList.contains("open")) {
      event.preventDefault();
      closeGrowthActionModal();
    }
  });
  renderGrowthNavigation();
}

function setupChannelHub() {
  const main = document.getElementById("admin-main-content");
  main.addEventListener("click", (event) => {
    const navigation = event.target.closest("[data-channel-hub-target]");
    if (navigation) {
      const section = navigation.dataset.channelHubTarget;
      if (showAdminSection(section)) {
        window.requestAnimationFrame(() => {
          const heading = document.querySelector(`[data-admin-section="${section}"] h2`);
          heading?.setAttribute("tabindex", "-1");
          heading?.focus({ preventScroll: true });
        });
      }
      return;
    }
    const requestButton = event.target.closest("[data-channel-request]");
    if (requestButton) { requestBusinessChannelConnection(requestButton.dataset.channelRequest, requestButton); return; }
    const healthButton = event.target.closest("[data-channel-health-action]");
    if (healthButton) { handleChannelHealthAction(healthButton); return; }
    const retryButton = event.target.closest("[data-channel-retry]");
    if (!retryButton) return;
    if (retryButton.dataset.channelRetry === "onboarding") loadBusinessChannelOnboarding();
    if (retryButton.dataset.channelRetry === "automation") loadConversationAutomation();
    if (retryButton.dataset.channelRetry === "templates") loadConversationTemplates();
  });
  main.addEventListener("input", (event) => {
    if (event.target.id === "conversation-template-body") renderNewTemplatePreview();
    const item = event.target.closest("[data-conversation-template-id]");
    if (item && event.target.classList.contains("conversation-template-item-body")) {
      const preview = item.querySelector(".conversation-template-item-preview");
      if (preview) preview.textContent = templatePreviewText(event.target.value);
    }
  });
  renderChannelHubNavigation();
}

function setupBusinessConfiguration() {
  document.getElementById("admin-main-content").addEventListener("click", (event) => {
    const target = event.target.closest("[data-configuration-target]");
    if (!target) return;
    const section = target.dataset.configurationTarget;
    if (showAdminSection(section)) {
      window.requestAnimationFrame(() => {
        const heading = document.querySelector(`[data-admin-section="${section}"] h2`);
        if (!heading) return;
        heading.setAttribute("tabindex", "-1");
        heading.focus({ preventScroll: true });
      });
    }
  });
  document.getElementById("admin-main-content").addEventListener("input", (event) => {
    const form = event.target.closest("[data-config-dirty-key]");
    if (form) updateConfigurationDirtyState(form.dataset.configDirtyKey);
  });
  document.getElementById("admin-main-content").addEventListener("change", (event) => {
    const form = event.target.closest("[data-config-dirty-key]");
    if (form) {
      if (form.dataset.configDirtyKey === "availability" && event.target.closest("#weekly-schedule-editor")) {
        availabilitySettings.weekly_schedule = collectWeeklySchedule();
      }
      updateConfigurationDirtyState(form.dataset.configDirtyKey);
    }
  });
  window.addEventListener("beforeunload", (event) => {
    if (!configurationDirtyKeys.size) return;
    event.preventDefault();
    event.returnValue = "";
  });
  snapshotConfigurationForms();
  renderConfigurationOverview();
}

function applyRoleVisibility() {
  const staffOnly = isBusinessStaff();
  const allowed = new Set(["summary", "growth", "growth-opportunities", "instagram-content", "bookings", "conversations"]);
  document.querySelectorAll(".admin-tab[data-section]").forEach((tab) => {
    const growthDisabled = !moduleAvailable("growth");
    const socialDisabled = !moduleAvailable("social");
    const reviewsFallback = tab.dataset.section === "reviews" && growthDisabled && !staffOnly;
    if (tab.dataset.section === "reviews") tab.classList.toggle("admin-tab--legacy", !reviewsFallback);
    tab.hidden = (!reviewsFallback && tab.classList.contains("admin-tab--legacy")) ||
      (staffOnly && !allowed.has(tab.dataset.section)) ||
      (tab.dataset.section === "growth" && growthDisabled) ||
      (tab.dataset.section === "instagram-content" && socialDisabled);
    if (tab.dataset.section === "instagram-content" && adminAuthUser?.is_owner) tab.hidden = true;
  });
  document.querySelectorAll("[data-admin-section]").forEach((section) => {
    if (staffOnly && !allowed.has(section.dataset.adminSection)) section.hidden = true;
    if (["growth", "growth-opportunities"].includes(section.dataset.adminSection)) section.hidden = !moduleAvailable("growth");
    if (["instagram-content", "channel-instagram"].includes(section.dataset.adminSection)) section.hidden = !moduleAvailable("social");
    if (section.dataset.adminSection === "instagram-content" && adminAuthUser?.is_owner) section.hidden = true;
  });
  document.getElementById("booking-staff-filter-field").hidden = staffOnly;
  document.querySelectorAll("[data-conversation-admin-only]").forEach((element) => {
    element.hidden = !canManageConversationTemplates() ||
      element.id === "conversation-create-panel";
  });
  document.querySelector(".growth-summary-card").hidden = staffOnly || !moduleAvailable("growth");
  ["stat-reviews-pending", "stat-reviews-copied", "stat-reviews-sent", "stat-messages-pending", "stat-messages-opened", "stat-messages-sent", "stat-services-active"]
    .forEach((id) => { document.getElementById(id)?.closest(".stat-card")?.toggleAttribute("hidden", staffOnly); });
  if (staffOnly && !allowed.has(window.location.hash.slice(1))) showAdminSection("bookings");
  if (!moduleAvailable("growth") && ["growth", "growth-opportunities"].includes(window.location.hash.slice(1))) showAdminSection("summary");
  if (!moduleAvailable("social") && ["instagram-content", "channel-instagram"].includes(window.location.hash.slice(1))) showAdminSection("summary");
}

function resolveMediaUrl(url, cacheBust = false) {
  if (!url) return "";
  const resolved = /^https?:\/\//i.test(url) ? url : (url.startsWith("/") ? `${API_BASE_URL}${url}` : url);
  if (!cacheBust) return resolved;
  return `${resolved}${resolved.includes("?") ? "&" : "?"}v=${Date.now()}`;
}

function resolveSafeAdminMediaUrl(url, cacheBust = false) {
  const resolved = resolveMediaUrl(url, cacheBust);
  if (!resolved) return "";
  try {
    const parsed = new URL(resolved, window.location.href);
    const apiOrigin = new URL(API_BASE_URL, window.location.href).origin;
    if (!["https:", "http:"].includes(parsed.protocol) || ![window.location.origin, apiOrigin].includes(parsed.origin)) return "";
    return parsed.href;
  } catch (_error) {
    return "";
  }
}

function showAdminSection(sectionName, updateHash = true, { skipDirtyCheck = false } = {}) {
  if (!moduleAvailable("growth") && ["growth", "growth-opportunities"].includes(sectionName)) sectionName = "summary";
  if (!moduleAvailable("social") && ["instagram-content", "channel-instagram"].includes(sectionName)) sectionName = "summary";
  const availableSections = Array.from(document.querySelectorAll("[data-admin-section]"));
  const sectionExists = availableSections.some((section) => section.dataset.adminSection === sectionName);
  const targetSection = sectionExists ? sectionName : "summary";
  if (!skipDirtyCheck && !confirmConfigurationNavigation(targetSection)) return false;
  if (targetSection !== "conversations" && conversationCustomerPanelOpen) {
    closeConversationCustomerPanel({ restoreFocus: false });
  }

  availableSections.forEach((section) => {
    section.classList.toggle("admin-section-active", section.dataset.adminSection === targetSection);
  });
  if (targetSection === "conversations" && window.matchMedia("(max-width: 639px)").matches) {
    closeConversationMobileDetail();
  }

  const primarySection = CONFIGURATION_SECTIONS.has(targetSection) ? "configuration"
    : CHANNEL_HUB_SECTIONS.has(targetSection) ? "channels"
      : targetSection === "reviews" && !moduleAvailable("growth") ? "reviews"
        : GROWTH_HUB_SECTIONS.has(targetSection) ? "growth" : targetSection;
  document.querySelectorAll(".admin-tab[data-section]").forEach((tab) => {
    const isActive = tab.dataset.section === primarySection;
    tab.classList.toggle("admin-tab-active", isActive);
    tab.setAttribute("aria-selected", String(isActive));
    if (isActive) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  });

  if (updateHash || (sectionName && !sectionExists)) {
    window.history.replaceState(null, "", `#${targetSection}`);
  }
  if (CONFIGURATION_SECTIONS.has(targetSection)) renderConfigurationOverview();
  if (CHANNEL_HUB_SECTIONS.has(targetSection)) renderChannelHubNavigation();
  if (GROWTH_HUB_SECTIONS.has(targetSection)) renderGrowthNavigation();
  if (targetSection === "instagram-content") loadAdminInstagramPanel();
  return true;
}

function setupAdminNavigation() {
  document.querySelectorAll(".admin-tab[data-section]").forEach((tab) => {
    tab.addEventListener("click", () => showAdminSection(tab.dataset.section));
  });

  showAdminSection(window.location.hash.slice(1) || "summary", false);
}

function setupBookingViews() {
  agendaSelectedDate = getMadridDateKey();
  document.querySelectorAll("[data-booking-view]").forEach((tab) => {
    tab.addEventListener("click", () => {
      setBookingView(tab.dataset.bookingView);
    });
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const tabs = Array.from(document.querySelectorAll("[data-booking-view]"));
      const currentIndex = tabs.indexOf(tab);
      const nextIndex = event.key === "Home" ? 0
        : event.key === "End" ? tabs.length - 1
          : (currentIndex + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      tabs[nextIndex].focus();
      setBookingView(tabs[nextIndex].dataset.bookingView);
    });
  });
  document.querySelectorAll("[data-agenda-nav]").forEach((button) => {
    button.addEventListener("click", () => {
      const step = Number(button.dataset.agendaNav);
      if (currentBookingView === "month") {
        const value = new Date(`${agendaSelectedDate.slice(0, 7)}-01T12:00:00Z`);
        value.setUTCMonth(value.getUTCMonth() + step);
        agendaSelectedDate = value.toISOString().slice(0, 10);
      } else {
        agendaSelectedDate = addDaysToDateKey(agendaSelectedDate, step * (currentBookingView === "week" ? 7 : 1));
      }
      agendaSelectedBookingId = null;
      const url = new URL(window.location.href);
      url.searchParams.delete("booking");
      window.history.replaceState(null, "", `${url.pathname}${url.search}#bookings`);
      loadBookings();
    });
  });
  document.getElementById("agenda-today-button")?.addEventListener("click", () => {
    agendaSelectedDate = getMadridDateKey();
    agendaSelectedBookingId = null;
    loadBookings();
  });
  document.getElementById("agenda-week-days")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-agenda-date]");
    if (!button) return;
    agendaSelectedDate = button.dataset.agendaDate;
    currentBookingView = "day";
    agendaSelectedBookingId = null;
    renderBookings();
  });
  document.getElementById("agenda-attention")?.addEventListener("click", () => {
    currentBookingView = "day";
    selectedBookingStatusFilter = "attention";
    const status = document.getElementById("agenda-status-filter");
    if (status) status.value = "attention";
    const firstPending = sortBookingsChronologically(allBookings.filter((booking) => ["requested", "pending"].includes(booking.status)))[0];
    if (firstPending) {
      agendaSelectedDate = getBookingDateKey(firstPending) || getMadridDateKey();
      agendaSelectedBookingId = Number(firstPending.id);
    }
    renderBookings();
  });
  document.getElementById("bookings-list")?.addEventListener("click", (event) => {
    const day = event.target.closest("[data-agenda-month-day]");
    if (day) {
      agendaSelectedDate = day.dataset.agendaMonthDay;
      currentBookingView = "day";
      agendaSelectedBookingId = null;
      loadBookings();
      return;
    }
    const block = event.target.closest("[data-agenda-booking-open]");
    if (block) {
      agendaSelectedBookingId = Number(block.dataset.agendaBookingOpen);
      renderBookings();
      window.setTimeout(() => document.getElementById(`booking-${agendaSelectedBookingId}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 0);
    }
  });
  document.getElementById("agenda-status-filter")?.addEventListener("change", (event) => {
    selectedBookingStatusFilter = event.target.value;
    renderBookings();
  });
  document.getElementById("agenda-service-filter")?.addEventListener("change", (event) => {
    selectedBookingServiceFilter = event.target.value;
    renderBookings();
  });
  document.getElementById("agenda-customer-search")?.addEventListener("input", (event) => {
    bookingCustomerSearch = event.target.value.trim().toLocaleLowerCase("es");
    renderBookings();
  });
  document.getElementById("agenda-reset-filters")?.addEventListener("click", () => resetAgendaFilters());
  const bookingsList = document.getElementById("bookings-list");
  for (const activity of ["click", "keydown", "input", "focusin"]) {
    bookingsList?.addEventListener(activity, handleBookingCustomerMemoryActivity);
  }
  bookingsList?.addEventListener("scroll", handleBookingCustomerMemoryActivity, true);
  bookingsList?.addEventListener("submit", (event) => {
    if (!event.target?.matches?.("[data-booking-customer-memory-form]")) return;
    event.preventDefault();
    void submitBookingCustomerMemoryForm(event.target);
  });
  if (window.matchMedia("(max-width: 639px)").matches) {
    document.getElementById("agenda-filter-panel")?.removeAttribute("open");
  }
  document.addEventListener("keydown", handleRescheduleModalKeydown);
  document.getElementById("reschedule-modal")?.addEventListener("mousedown", (event) => {
    if (event.target === event.currentTarget) closeRescheduleModal();
  });
}

function setBookingView(view, { clearDeepLink = true } = {}) {
  const normalizedView = ["day", "week", "month"].includes(view) ? view : "day";
  if (view === "tomorrow") agendaSelectedDate = addDaysToDateKey(getMadridDateKey(), 1);
  if (view === "upcoming") agendaSelectedDate = addDaysToDateKey(getMadridDateKey(), 2);
  if (view === "history") agendaSelectedDate = getMadridDateKey();
  currentBookingView = normalizedView;
  agendaSelectedBookingId = null;
  if (clearDeepLink) {
    const url = new URL(window.location.href);
    url.searchParams.delete("booking");
    window.history.replaceState(null, "", `${url.pathname}${url.search}#bookings`);
  }
  updateBookingViewTabs();
  renderBookings();
}

function getBusinessTimeZone() {
  const candidate = availabilitySettings?.timezone || currentBusiness?.timezone || "Europe/Madrid";
  try {
    new Intl.DateTimeFormat("es-ES", { timeZone: candidate }).format();
    return candidate;
  } catch (error) {
    console.warn("Zona horaria no válida; se usa Europe/Madrid.", { timezone: candidate });
    return "Europe/Madrid";
  }
}

function updateBookingViewTabs() {
  document.querySelectorAll("[data-booking-view]").forEach((tab) => {
    const active = tab.dataset.bookingView === currentBookingView;
    tab.classList.toggle("booking-view-tab-active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  const list = document.getElementById("bookings-list");
  const activeTab = document.querySelector(`[data-booking-view="${currentBookingView}"]`);
  if (list && activeTab?.id) list.setAttribute("aria-labelledby", activeTab.id);
}

function resetAgendaFilters({ render = true } = {}) {
  selectedStaffFilter = "";
  selectedBookingStatusFilter = "";
  selectedBookingServiceFilter = "";
  bookingCustomerSearch = "";
  const values = {
    "booking-staff-filter": "",
    "agenda-status-filter": "",
    "agenda-service-filter": "",
    "agenda-customer-search": ""
  };
  Object.entries(values).forEach(([id, value]) => {
    const field = document.getElementById(id);
    if (field) field.value = value;
  });
  if (render) renderBookings();
}

function getMadridDateKey(value = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: getBusinessTimeZone(),
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

function setDashboardDataState(source, status) {
  if (!(source in dashboardDataState)) return;
  dashboardDataState[source] = status;
  renderDashboard();
  if (!isBusinessStaff()) renderGrowth();
}

function getMadridTimeKey(value = new Date()) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Madrid",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23"
  }).formatToParts(value);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.hour}:${values.minute}`;
}

function formatDashboardDate(value = new Date()) {
  const formatted = new Intl.DateTimeFormat("es-ES", {
    timeZone: "Europe/Madrid",
    weekday: "long",
    day: "numeric",
    month: "long"
  }).format(value);
  return formatted.charAt(0).toUpperCase() + formatted.slice(1);
}

function getDashboardGreeting(value = new Date()) {
  const hour = Number(getMadridTimeKey(value).slice(0, 2));
  if (hour < 13) return "Buenos días";
  if (hour < 20) return "Buenas tardes";
  return "Buenas noches";
}

function getDashboardTodayBookings() {
  const today = getMadridDateKey();
  return allBookings
    .filter((booking) => getBookingDateKey(booking) === today && !["rejected", "cancelled"].includes(booking.status))
    .sort(compareDashboardBookings);
}

function getDashboardPendingBookings() {
  return allBookings.filter((booking) => ["requested", "pending"].includes(booking.status));
}

function getDashboardPendingConversations() {
  return dashboardConversations.filter(conversationNeedsReply);
}

function getDashboardGrowthFollowUps() {
  const byCustomer = new Map();
  customerOpportunities
    .filter((opportunity) => opportunity.status === "pending" && opportunity.customer?.id)
    .sort((first, second) => String(first.due_at || "").localeCompare(String(second.due_at || "")))
    .forEach((opportunity) => {
      if (!byCustomer.has(opportunity.customer.id)) byCustomer.set(opportunity.customer.id, opportunity);
    });
  return Array.from(byCustomer.values());
}

function growthOpportunityConversationId(opportunity) {
  const resolvedConversationId = Number(opportunity.channel?.conversation_id);
  if (Number.isInteger(resolvedConversationId) && resolvedConversationId > 0) {
    return resolvedConversationId;
  }
  const customerId = Number(opportunity.customer?.id);
  return dashboardConversations.find((conversation) => conversation.customer_id === customerId)?.id || null;
}

function dashboardBookingSortKey(booking) {
  if (booking.start_datetime) return booking.start_datetime;
  return `${booking.preferred_date || "9999-12-31"}T${booking.preferred_time || "23:59"}`;
}

function compareDashboardBookings(first, second) {
  return dashboardBookingSortKey(first).localeCompare(dashboardBookingSortKey(second));
}

function isDashboardUpcomingBooking(booking) {
  if (["completed", "rejected", "cancelled", "no_show"].includes(booking.status)) return false;
  const dateKey = getBookingDateKey(booking);
  const today = getMadridDateKey();
  if (!dateKey || dateKey < today) return false;
  if (dateKey > today) return true;
  if (booking.start_datetime) {
    const startsAt = new Date(booking.start_datetime);
    return Number.isNaN(startsAt.getTime()) || startsAt.getTime() >= Date.now();
  }
  return !booking.preferred_time || booking.preferred_time >= getMadridTimeKey();
}

function getDashboardNextBooking() {
  return allBookings.filter(isDashboardUpcomingBooking).sort(compareDashboardBookings)[0] || null;
}

function getDashboardBookingStatusLabel(status) {
  return ({
    requested: "Por confirmar",
    pending: "Pendiente",
    confirmed: "Confirmada",
    completed: "Completada",
    cancelled: "Cancelada",
    rejected: "Rechazada",
    no_show: "No presentado"
  })[status] || "Estado pendiente";
}

function getDashboardStatusVariant(status) {
  if (status === "confirmed") return "success";
  if (status === "completed") return "info";
  if (["rejected", "cancelled", "no_show"].includes(status)) return "danger";
  return "warning";
}

function formatDashboardBookingTime(booking) {
  if (booking.start_datetime) {
    const value = new Date(booking.start_datetime);
    if (!Number.isNaN(value.getTime())) {
      return value.toLocaleTimeString("es-ES", {
        timeZone: "Europe/Madrid",
        hour: "2-digit",
        minute: "2-digit"
      });
    }
  }
  return booking.preferred_time || "Hora pendiente";
}

function formatDashboardBookingDay(booking) {
  const dateKey = getBookingDateKey(booking);
  const today = getMadridDateKey();
  if (dateKey === today) return "Hoy";
  if (dateKey === addDaysToDateKey(today, 1)) return "Mañana";
  if (!dateKey) return "Fecha pendiente";
  const value = new Date(`${dateKey}T12:00:00Z`);
  return Number.isNaN(value.getTime())
    ? dateKey
    : new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", timeZone: "UTC" }).format(value);
}

function truncateDashboardText(value, maxLength = 88) {
  const normalized = String(value || "").replace(/\s+/g, " ").trim();
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength - 1).trimEnd()}…` : normalized;
}

function renderDashboardHeader() {
  const title = document.getElementById("dashboard-title");
  const date = document.getElementById("dashboard-date");
  const summary = document.getElementById("dashboard-summary-copy");
  if (!title || !date || !summary) return;
  const firstName = String(adminAuthUser?.name || "").trim().split(/\s+/)[0];
  title.textContent = `${getDashboardGreeting()}${firstName ? `, ${firstName}` : ""}`;
  date.textContent = formatDashboardDate();
  if (dashboardDataState.bookings === "ready") {
    const todayCount = getDashboardTodayBookings().length;
    const pendingCount = getDashboardPendingBookings().length;
    summary.textContent = todayCount || pendingCount
      ? `Hoy tienes ${todayCount} cita${todayCount === 1 ? "" : "s"} y ${pendingCount} solicitud${pendingCount === 1 ? "" : "es"} por revisar.`
      : "Tu agenda está tranquila y no hay solicitudes por confirmar.";
  } else if (dashboardDataState.bookings === "error") {
    summary.textContent = "No hemos podido cargar la actividad de hoy. Puedes reintentar sin salir de Inicio.";
  } else {
    summary.textContent = "Estamos preparando el estado de tu negocio.";
  }
}

function dashboardHasConfiguredAvailability() {
  const schedule = availabilitySettings?.weekly_schedule || {};
  return Object.values(schedule).some((windows) => Array.isArray(windows) && windows.length > 0);
}

function getDashboardBusinessStatus() {
  if (dashboardDataState.business === "loading") {
    return { label: "Comprobando", context: "Revisando la configuración.", variant: "neutral" };
  }
  if (currentBusiness?.status === "suspended") {
    return { label: "Suspendido", context: "Las operaciones están temporalmente deshabilitadas.", variant: "danger" };
  }
  if (currentBusiness?.status === "archived") {
    return { label: "Archivado", context: "Solo está disponible la consulta histórica.", variant: "danger" };
  }
  if (!currentBusiness?.active) {
    return { label: "No está activo", context: "Revisa la publicación del negocio.", variant: "danger" };
  }
  if (!isBusinessStaff() && dashboardDataState.channels === "ready") {
    const affectedChannel = businessChannelHealth.find((channel) =>
      channel.reconnection_required || !["healthy", "unknown"].includes(channel.health_status)
    );
    if (affectedChannel) {
      const name = affectedChannel.channel === "whatsapp" ? "WhatsApp" : "Instagram";
      return { label: "Revisa un canal", context: `${name} necesita atención.`, variant: "warning" };
    }
  }
  if (!isBusinessStaff() && dashboardDataState.services === "ready" && !adminServices.some((service) => service.active)) {
    return { label: "Configuración pendiente", context: "Activa al menos un servicio.", variant: "warning" };
  }
  if (!isBusinessStaff() && dashboardDataState.availability === "ready" && !dashboardHasConfiguredAvailability()) {
    return { label: "Configuración pendiente", context: "Define los horarios del negocio.", variant: "warning" };
  }
  const relevantStates = isBusinessStaff()
    ? [dashboardDataState.bookings, dashboardDataState.conversations]
    : [dashboardDataState.bookings, dashboardDataState.conversations, dashboardDataState.services, dashboardDataState.availability, dashboardDataState.channels];
  if (relevantStates.some((state) => state === "loading")) {
    return { label: "Comprobando", context: "Terminando de revisar la actividad.", variant: "neutral" };
  }
  if (relevantStates.some((state) => state === "error")) {
    return { label: "Revisión pendiente", context: "Hay información que no hemos podido comprobar.", variant: "warning" };
  }
  return { label: "Todo funciona", context: "No vemos bloqueos operativos.", variant: "success" };
}

function setDashboardMetric(id, contextId, value, context) {
  const metric = document.getElementById(id);
  const contextElement = document.getElementById(contextId);
  if (metric) metric.textContent = value;
  if (contextElement) contextElement.textContent = context;
}

function renderDashboardMetrics() {
  const metrics = document.querySelector(".dashboard-metrics");
  if (!metrics) return;
  const bookingsReady = dashboardDataState.bookings === "ready";
  const conversationsReady = dashboardDataState.conversations === "ready";
  if (bookingsReady) {
    const todayCount = getDashboardTodayBookings().length;
    const pendingCount = getDashboardPendingBookings().length;
    setDashboardMetric("dashboard-stat-today", "dashboard-stat-today-context", String(todayCount), todayCount === 1 ? "Una cita prevista para hoy." : `${todayCount} citas previstas para hoy.`);
    setDashboardMetric("dashboard-stat-pending", "dashboard-stat-pending-context", String(pendingCount), pendingCount ? "Solicitudes que esperan respuesta." : "No hay solicitudes pendientes.");
  } else if (dashboardDataState.bookings === "error") {
    setDashboardMetric("dashboard-stat-today", "dashboard-stat-today-context", "—", "No se pudieron cargar las citas.");
    setDashboardMetric("dashboard-stat-pending", "dashboard-stat-pending-context", "—", "No se pudieron cargar las solicitudes.");
  }
  if (conversationsReady) {
    const pendingMessages = getDashboardPendingConversations().length;
    setDashboardMetric("dashboard-stat-messages", "dashboard-stat-messages-context", String(pendingMessages), pendingMessages ? "Conversaciones que requieren respuesta." : "No hay conversaciones pendientes.");
  } else if (dashboardDataState.conversations === "error") {
    setDashboardMetric("dashboard-stat-messages", "dashboard-stat-messages-context", "—", "No se pudieron cargar los mensajes.");
  }
  const businessStatus = getDashboardBusinessStatus();
  const status = document.getElementById("stat-business-status");
  if (status) {
    status.textContent = businessStatus.label;
    status.className = `stat-status ag-badge ag-badge--${businessStatus.variant}`;
  }
  const statusContext = document.getElementById("dashboard-business-status-context");
  if (statusContext) statusContext.textContent = businessStatus.context;
  metrics.setAttribute("aria-busy", String(
    dashboardDataState.bookings === "loading" || dashboardDataState.conversations === "loading"
  ));
}

function renderDashboardBlockError(container, message, retrySource, announce = false) {
  container.setAttribute("aria-busy", "false");
  container.innerHTML = `
    <div class="dashboard-block-state dashboard-block-state--error" role="${announce ? "alert" : "group"}">
      <strong>No hemos podido cargar este bloque</strong>
      <p>${escapeHtml(message)}</p>
      <button class="ag-button ag-button--secondary ag-button--small" type="button" data-dashboard-retry="${escapeHtml(retrySource)}">Reintentar</button>
    </div>`;
}

function renderDashboardEmptyState(container, title, description, action = null) {
  container.setAttribute("aria-busy", "false");
  container.innerHTML = `
    <div class="dashboard-block-state dashboard-block-state--empty">
      <span class="dashboard-state-mark" aria-hidden="true">✓</span>
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(description)}</p>
      ${action ? `<button class="ag-button ag-button--secondary ag-button--small" type="button" data-dashboard-section="${escapeHtml(action.section)}"${action.view ? ` data-dashboard-booking-view="${escapeHtml(action.view)}"` : ""}>${escapeHtml(action.label)}</button>` : ""}
    </div>`;
}

function renderTodayBookings() {
  const container = document.getElementById("dashboard-today-bookings");
  if (!container) return;
  if (dashboardDataState.bookings === "loading") return;
  if (dashboardDataState.bookings === "error") {
    renderDashboardBlockError(container, "No hemos podido cargar la agenda de hoy.", "bookings", true);
    return;
  }
  const todayBookings = getDashboardTodayBookings();
  if (!todayBookings.length) {
    renderDashboardEmptyState(container, "No tienes citas para hoy", "Puedes revisar próximas reservas o la disponibilidad.", { section: "bookings", view: "upcoming", label: "Ver próximas citas" });
    return;
  }
  container.setAttribute("aria-busy", "false");
  container.innerHTML = todayBookings.slice(0, 5).map((booking) => {
    const bookingId = Number(booking.id);
    const professional = booking.staff_display_name ? `<span>${escapeHtml(booking.staff_display_name)}</span>` : "";
    return `
      <article class="dashboard-booking-row" role="listitem">
        <time class="dashboard-booking-row__time">${escapeHtml(formatDashboardBookingTime(booking))}</time>
        <div class="dashboard-booking-row__copy">
          <strong>${escapeHtml(booking.customer_name || "Cliente sin nombre")}</strong>
          <span>${escapeHtml(booking.service_name || "Servicio sin indicar")}</span>
          ${professional}
        </div>
        <span class="ag-badge ag-badge--${getDashboardStatusVariant(booking.status)}">${escapeHtml(getDashboardBookingStatusLabel(booking.status))}</span>
        ${Number.isInteger(bookingId) && bookingId > 0 ? `<button class="ag-button ag-button--ghost ag-button--small" type="button" data-dashboard-booking-id="${bookingId}">Ver</button>` : ""}
      </article>`;
  }).join("");
}

function renderNextBooking() {
  const container = document.getElementById("dashboard-next-booking");
  if (!container) return;
  if (dashboardDataState.bookings === "loading") return;
  if (dashboardDataState.bookings === "error") {
    renderDashboardBlockError(container, "No hemos podido identificar la próxima cita.", "bookings");
    return;
  }
  const booking = getDashboardNextBooking();
  if (!booking) {
    renderDashboardEmptyState(container, "No hay una próxima cita", "La agenda no tiene citas futuras pendientes.", { section: "bookings", view: "upcoming", label: "Revisar agenda" });
    return;
  }
  const bookingId = Number(booking.id);
  container.setAttribute("aria-busy", "false");
  container.innerHTML = `
    <div class="dashboard-next-booking">
      <p class="dashboard-next-booking__time"><span>${escapeHtml(formatDashboardBookingDay(booking))}</span><strong>${escapeHtml(formatDashboardBookingTime(booking))}</strong></p>
      <div class="dashboard-next-booking__copy">
        <h4>${escapeHtml(booking.customer_name || "Cliente sin nombre")}</h4>
        <p>${escapeHtml(booking.service_name || "Servicio sin indicar")}</p>
        <p>${escapeHtml(booking.staff_display_name || "Profesional sin asignar")}</p>
      </div>
      <span class="ag-badge ag-badge--${getDashboardStatusVariant(booking.status)}">${escapeHtml(getDashboardBookingStatusLabel(booking.status))}</span>
      ${Number.isInteger(bookingId) && bookingId > 0 ? `<button class="ag-button ag-button--secondary ag-button--small" type="button" data-dashboard-booking-id="${bookingId}">Ver reserva</button>` : ""}
    </div>`;
}

function getDashboardAttentionItems() {
  const items = [];
  if (dashboardDataState.closeTasks === "error") {
    items.push({ severity: "danger", title: "No pudimos comprobar las citas por cerrar", description: "Reintenta para revisar los cierres pendientes.", retry: "closeTasks", action: "Reintentar" });
  }
  if (dashboardDataState.bookings === "ready") {
    const pending = getDashboardPendingBookings().length;
    if (pending) items.push({ severity: "warning", title: `${pending} reserva${pending === 1 ? "" : "s"} necesita${pending === 1 ? "" : "n"} confirmación`, description: "Revisa las solicitudes que esperan respuesta.", section: "bookings", view: "pending", action: "Revisar" });
  } else if (dashboardDataState.bookings === "error") {
    items.push({ severity: "danger", title: "No pudimos comprobar las reservas", description: "Reintenta para conocer las solicitudes pendientes.", retry: "bookings", action: "Reintentar" });
  }
  if (dashboardDataState.conversations === "ready") {
    const pending = getDashboardPendingConversations().length;
    if (pending) items.push({ severity: "info", title: `${pending} conversación${pending === 1 ? "" : "es"} requiere${pending === 1 ? "" : "n"} respuesta`, description: "Abre Mensajes para continuar la conversación.", section: "conversations", action: "Responder" });
  } else if (dashboardDataState.conversations === "error") {
    items.push({ severity: "danger", title: "No pudimos comprobar los mensajes", description: "Reintenta para revisar las conversaciones pendientes.", retry: "conversations", action: "Reintentar" });
  }
  if (!isBusinessStaff()) {
    const reviewCandidates = getReviewCandidates();
    const failedReviewMessages = getFailedReviewMessages();
    const pendingReviewRequests = Array.from(reviewRequestsByBooking.values())
      .filter((request) => ["pending", "copied"].includes(request.status));
    if (failedReviewMessages.length) {
      items.push({ severity: "warning", title: `${failedReviewMessages.length} solicitud${failedReviewMessages.length === 1 ? "" : "es"} de reseña necesita${failedReviewMessages.length === 1 ? "" : "n"} atención`, description: "El envío asistido no quedó preparado correctamente.", section: "reviews", action: "Revisar" });
    } else if (growthLoadState.reviews === "ready" && reviewCandidates.length && !getSafeReviewUrl()) {
      items.push({ severity: "warning", title: "Falta el enlace de reseñas", description: `${reviewCandidates.length} cliente${reviewCandidates.length === 1 ? "" : "s"} atendido${reviewCandidates.length === 1 ? "" : "s"} no puede${reviewCandidates.length === 1 ? "" : "n"} recibir una solicitud todavía.`, section: "reviews", action: "Configurar" });
    } else if (growthLoadState.reviews === "ready" && (pendingReviewRequests.length || reviewCandidates.length)) {
      const count = pendingReviewRequests.length || reviewCandidates.length;
      const prepared = pendingReviewRequests.length > 0;
      items.push({ severity: "info", title: prepared ? `${count} solicitud${count === 1 ? "" : "es"} de reseña pendiente${count === 1 ? "" : "s"}` : `${count} cliente${count === 1 ? "" : "s"} puede${count === 1 ? "" : "n"} recibir una solicitud`, description: prepared ? "Continúa el envío asistido o cierra la solicitud." : "Prepara la solicitud desde Crecimiento.", section: "reviews", action: "Revisar" });
    }
    if (!currentBusiness?.active && dashboardDataState.business === "ready") {
      items.push({ severity: "danger", title: "El negocio no está activo", description: "Revisa su estado antes de compartir la página pública.", section: "business", action: "Revisar" });
    }
    if (dashboardDataState.services === "ready" && !adminServices.some((service) => service.active)) {
      items.push({ severity: "warning", title: "Activa al menos un servicio", description: "Los clientes necesitan un servicio disponible para reservar.", section: "services", action: "Configurar" });
    } else if (dashboardDataState.services === "error") {
      items.push({ severity: "danger", title: "No pudimos comprobar los servicios", description: "Reintenta para revisar la configuración.", retry: "services", action: "Reintentar" });
    }
    if (dashboardDataState.availability === "ready" && !dashboardHasConfiguredAvailability()) {
      items.push({ severity: "warning", title: "Configura los horarios", description: "Define cuándo pueden reservar tus clientes.", section: "schedule", action: "Configurar" });
    } else if (dashboardDataState.availability === "error") {
      items.push({ severity: "danger", title: "No pudimos comprobar los horarios", description: "Reintenta para revisar la disponibilidad.", retry: "availability", action: "Reintentar" });
    }
    if (dashboardDataState.channels === "ready") {
      businessChannelHealth.filter((channel) => channel.reconnection_required || !["healthy", "unknown"].includes(channel.health_status)).slice(0, 2).forEach((channel) => {
        const name = channel.channel === "whatsapp" ? "WhatsApp" : "Instagram";
        items.push({ severity: channel.reconnection_required ? "danger" : "warning", title: `${name} necesita atención`, description: channel.reconnection_required ? "Vuelve a conectar el canal para recuperar la mensajería." : "Revisa el estado del canal.", section: "channels", action: channel.reconnection_required ? "Volver a conectar" : "Revisar" });
      });
    } else if (dashboardDataState.channels === "error") {
      items.push({ severity: "danger", title: "No pudimos comprobar los canales", description: "Reintenta para revisar su estado.", retry: "channels", action: "Reintentar" });
    }
  }
  return items;
}

function renderAttentionItems() {
  const container = document.getElementById("dashboard-attention-list");
  if (!container) return;
  const growthAvailable = moduleAvailable("growth");
  const relevantStates = isBusinessStaff()
    ? [dashboardDataState.bookings, dashboardDataState.closeTasks, dashboardDataState.conversations]
    : [dashboardDataState.bookings, dashboardDataState.closeTasks, dashboardDataState.conversations, dashboardDataState.services, dashboardDataState.availability, dashboardDataState.channels, growthLoadState.reviews, growthLoadState.outbox];
  if (growthAvailable) relevantStates.push(growthLoadState.opportunities);
  const items = getDashboardAttentionItems();
  const closeTasksReady = dashboardDataState.closeTasks === "ready";
  const growthFollowUps = growthLoadState.opportunities === "ready" ? getDashboardGrowthFollowUps() : [];
  if (!items.length && !bookingCloseTasks.length && !growthFollowUps.length && relevantStates.some((state) => state === "loading")) return;
  if (!items.length && !growthFollowUps.length && (!closeTasksReady || !bookingCloseTasks.length)) {
    renderDashboardEmptyState(container, "Todo está al día", "No hay tareas urgentes en este momento.");
    return;
  }
  container.setAttribute("aria-busy", "false");
  const growthTaskItems = growthFollowUps.length ? `
    <section class="dashboard-growth-tasks" aria-labelledby="dashboard-growth-tasks-title">
      <h4 id="dashboard-growth-tasks-title">Seguimientos Growth pendientes</h4>
      ${growthFollowUps.slice(0, 5).map((opportunity) => `
        <article class="dashboard-attention-item dashboard-attention-item--info dashboard-growth-task">
          <span class="dashboard-attention-item__mark" aria-hidden="true">•</span>
          <div>
            <h5>${escapeHtml(opportunity.customer?.name || "Cliente sin nombre")}</h5>
            <p>${escapeHtml(opportunity.reason_text || "Seguimiento comercial pendiente.")}</p>
            <p>Fecha relevante: ${escapeHtml(formatDateTime(opportunity.due_at))}</p>
          </div>
          <button class="ag-button ag-button--ghost ag-button--small" type="button" data-dashboard-opportunity-id="${Number(opportunity.id)}">${growthOpportunityConversationId(opportunity) ? "Abrir conversación" : "Ver oportunidad"}</button>
        </article>`).join("")}
    </section>` : "";
  const closeTaskItems = closeTasksReady && bookingCloseTasks.length ? `
    <section class="dashboard-close-tasks" aria-labelledby="dashboard-close-tasks-title">
      <h4 id="dashboard-close-tasks-title">Citas pendientes de cerrar</h4>
      ${bookingCloseTasks.map((booking) => `
        <article class="dashboard-attention-item dashboard-attention-item--warning dashboard-close-task" data-close-task-booking-id="${Number(booking.id)}">
          <span class="dashboard-attention-item__mark" aria-hidden="true">!</span>
          <div>
            <h5>${escapeHtml(booking.customer_name || "Cliente sin nombre")}</h5>
            <p>${escapeHtml(booking.service_name || "Servicio sin indicar")} · ${escapeHtml(formatBookingSlot(booking))}</p>
            <p>${escapeHtml(booking.staff_display_name || "Profesional sin asignar")} · ${escapeHtml(getStatusLabel(booking.status))}</p>
          </div>
          <div class="dashboard-close-task__actions">
            <button class="ag-button ag-button--primary ag-button--small" type="button" data-booking-action="completed" data-booking-id="${Number(booking.id)}">Marcar completada</button>
            <button class="ag-button ag-button--ghost ag-button--small" type="button" data-booking-action="no_show" data-booking-id="${Number(booking.id)}">No se presentó</button>
          </div>
        </article>`).join("")}
    </section>` : "";
  const attentionItems = items.slice(0, Math.max(0, 5 - bookingCloseTasks.length)).map((item) => `
    <article class="dashboard-attention-item dashboard-attention-item--${escapeHtml(item.severity)}">
      <span class="dashboard-attention-item__mark" aria-hidden="true">${item.severity === "danger" ? "!" : "•"}</span>
      <div><h4>${escapeHtml(item.title)}</h4><p>${escapeHtml(item.description)}</p></div>
      <button class="ag-button ag-button--ghost ag-button--small" type="button" ${item.retry ? `data-dashboard-retry="${escapeHtml(item.retry)}"` : `data-dashboard-section="${escapeHtml(item.section)}"${item.view ? ` data-dashboard-booking-view="${escapeHtml(item.view)}"` : ""}`}>${escapeHtml(item.action)}</button>
    </article>`).join("");
  container.innerHTML = `${growthTaskItems}${closeTaskItems}${attentionItems}`;
}

function renderMessageSummary() {
  const container = document.getElementById("dashboard-message-summary");
  if (!container) return;
  if (dashboardDataState.conversations === "loading") return;
  if (dashboardDataState.conversations === "error") {
    renderDashboardBlockError(container, "No hemos podido cargar los mensajes recientes.", "conversations", true);
    return;
  }
  const pending = getDashboardPendingConversations().sort((first, second) =>
    String(second.last_message_at || "").localeCompare(String(first.last_message_at || ""))
  );
  if (!pending.length) {
    renderDashboardEmptyState(container, "No hay mensajes pendientes", "Las conversaciones están al día.", { section: "conversations", label: "Ver conversaciones" });
    return;
  }
  container.setAttribute("aria-busy", "false");
  container.innerHTML = pending.slice(0, 4).map((conversation) => `
    <article class="dashboard-message-row">
      <div class="dashboard-message-row__header">
        <strong>${escapeHtml(conversationDisplayName(conversation))}</strong>
        <span>${escapeHtml(conversationChannelLabel(conversation.channel))}</span>
      </div>
      <p>${escapeHtml(truncateDashboardText(conversation.last_message_text || "Conversación pendiente de respuesta."))}</p>
      <small>${escapeHtml(formatConversationDate(conversation.last_message_at))} · Pendiente de respuesta</small>
    </article>`).join("");
}

function renderRecentActivity() {
  const container = document.getElementById("dashboard-weekly-activity");
  if (!container) return;
  if (dashboardDataState.bookings === "loading") return;
  if (dashboardDataState.bookings === "error") {
    renderDashboardBlockError(container, "No hemos podido calcular la actividad reciente.", "bookings");
    return;
  }
  const today = getMadridDateKey();
  const firstDay = addDaysToDateKey(today, -6);
  const inRange = (dateKey) => Boolean(dateKey && dateKey >= firstDay && dateKey <= today);
  const created = allBookings.filter((booking) => inRange(getTimestampDateKey(booking.created_at))).length;
  const completed = allBookings.filter((booking) => booking.status === "completed" && inRange(getBookingDateKey(booking))).length;
  const cancelled = allBookings.filter((booking) => ["cancelled", "rejected"].includes(booking.status) && inRange(getBookingDateKey(booking))).length;
  if (!created && !completed && !cancelled) {
    renderDashboardEmptyState(container, "Aún no hay actividad reciente", "Las reservas de los últimos siete días aparecerán aquí.");
    return;
  }
  container.setAttribute("aria-busy", "false");
  container.innerHTML = `
    <dl class="dashboard-activity-list">
      <div><dt>Reservas recibidas</dt><dd>${created}</dd></div>
      <div><dt>Citas completadas</dt><dd>${completed}</dd></div>
      <div><dt>Canceladas o rechazadas</dt><dd>${cancelled}</dd></div>
    </dl>`;
}

function announceDashboardUpdate() {
  const liveRegion = document.getElementById("dashboard-live-region");
  const failedSources = Object.entries(dashboardDataState)
    .filter(([, state]) => state === "error")
    .map(([source]) => source);
  if (failedSources.length) {
    const errorFingerprint = `error:${failedSources.sort().join(",")}`;
    if (liveRegion && errorFingerprint !== dashboardAnnouncementFingerprint) {
      liveRegion.textContent = "Hay información de Inicio que no hemos podido cargar. Revisa los avisos para reintentar.";
    }
    dashboardAnnouncementFingerprint = errorFingerprint;
    return;
  }
  if (dashboardDataState.bookings !== "ready" || dashboardDataState.closeTasks !== "ready" || dashboardDataState.conversations !== "ready") return;
  const fingerprint = `${getDashboardTodayBookings().length}:${getDashboardPendingBookings().length}:${bookingCloseTasks.length}:${getDashboardPendingConversations().length}`;
  if (fingerprint === dashboardAnnouncementFingerprint) return;
  if (liveRegion && dashboardAnnouncementFingerprint) liveRegion.textContent = "La información de Inicio se ha actualizado.";
  dashboardAnnouncementFingerprint = fingerprint;
}

function renderDashboard() {
  if (!document.getElementById("dashboard-title")) return;
  renderDashboardHeader();
  renderDashboardMetrics();
  renderTodayBookings();
  renderNextBooking();
  renderAttentionItems();
  renderMessageSummary();
  renderRecentActivity();
  announceDashboardUpdate();
}

async function navigateFromDashboard(button) {
  const opportunityId = Number(button.dataset.dashboardOpportunityId);
  if (Number.isInteger(opportunityId) && opportunityId > 0) {
    const opportunity = customerOpportunities.find((item) => item.id === opportunityId);
    const conversationId = Number(growthOpportunityConversationId(opportunity || {}));
    if (Number.isInteger(conversationId) && conversationId > 0) {
      showAdminSection("conversations");
      await selectConversation(conversationId);
      return;
    }
    showAdminSection("growth-opportunities");
    window.requestAnimationFrame(() => {
      const card = document.querySelector(`[data-customer-opportunity="${opportunityId}"]`);
      card?.scrollIntoView?.({ block: "center" });
      card?.querySelector("button")?.focus?.({ preventScroll: true });
    });
    return;
  }
  const bookingId = Number(button.dataset.dashboardBookingId);
  if (Number.isInteger(bookingId) && bookingId > 0) {
    goToBooking(bookingId);
    return;
  }
  const section = button.dataset.dashboardSection;
  const bookingView = button.dataset.dashboardBookingView;
  if (section === "bookings" && bookingView) {
    currentBookingView = bookingView;
    if (bookingView === "today") agendaSelectedDate = getMadridDateKey();
    setBookingView(bookingView, { clearDeepLink: false });
  }
  if (section) {
    showAdminSection(section);
    document.getElementById("admin-main-content")?.focus({ preventScroll: true });
  }
}

async function retryDashboardSource(source, button) {
  if (dashboardRetryInFlight.has(source)) return;
  const loaders = {
    bookings: () => loadBookings(),
    closeTasks: () => loadBookingCloseTasks(),
    conversations: () => loadConversations(),
    services: () => loadAdminServices(),
    availability: () => loadAvailabilitySettings(),
    channels: () => loadBusinessChannelOnboarding()
  };
  if (!loaders[source]) return;
  dashboardRetryInFlight.add(source);
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  setDashboardDataState(source, "loading");
  try {
    await loaders[source]();
  } finally {
    dashboardRetryInFlight.delete(source);
    if (button.isConnected) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  }
}

function setupDashboardInteractions() {
  const dashboard = document.querySelector('[data-admin-section="summary"]');
  if (!dashboard) return;
  dashboard.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button || !dashboard.contains(button)) return;
    if (button.dataset.dashboardRetry) {
      retryDashboardSource(button.dataset.dashboardRetry, button);
      return;
    }
    if (button.dataset.dashboardSection || button.dataset.dashboardBookingId || button.dataset.dashboardOpportunityId) void navigateFromDashboard(button);
  });
}

function calculateGrowthTasks() {
  const pendingBookings = allBookings.filter((booking) => ["requested", "pending"].includes(booking.status));
  const pendingConversations = dashboardDataState.conversations === "ready" ? getDashboardPendingConversations() : [];
  const candidates = getReviewCandidates();
  const failedReviews = getFailedReviewMessages();
  const pendingReviews = Array.from(reviewRequestsByBooking.values()).filter((request) => ["pending", "copied"].includes(request.status));
  const hasReviewLink = Boolean(getSafeReviewUrl());
  const tasks = [
    {
      id: "review-link",
      title: "Configura el enlace de reseñas",
      description: "Hace falta un destino válido antes de preparar nuevas solicitudes.",
      dependency: "Configuración del negocio",
      status: hasReviewLink ? "completed" : "blocked",
      priority: 1,
      action: "configuration-reviews",
      action_label: "Configurar enlace"
    },
    {
      id: "review-pending",
      title: "Continúa las solicitudes preparadas",
      description: pendingReviews.length ? `${pendingReviews.length} solicitud${pendingReviews.length === 1 ? "" : "es"} necesita${pendingReviews.length === 1 ? "" : "n"} envío o una decisión.` : "No hay solicitudes preparadas pendientes.",
      dependency: "Envío manual o cierre por una persona",
      status: pendingReviews.length ? "needs_attention" : "completed",
      priority: 2,
      action: "reviews",
      action_label: "Revisar solicitudes"
    },
    {
      id: "review-failures",
      title: "Revisa las solicitudes con error",
      description: failedReviews.length ? `${failedReviews.length} solicitud${failedReviews.length === 1 ? "" : "es"} no se pudo${failedReviews.length === 1 ? "" : "ieron"} preparar correctamente.` : "No hay solicitudes con error.",
      dependency: "Outbox asistido de WhatsApp",
      status: failedReviews.length ? "needs_attention" : growthLoadState.outbox === "error" ? "not_available" : "completed",
      priority: 3,
      action: "reviews",
      action_label: "Revisar solicitudes"
    },
    {
      id: "review-candidates",
      title: "Solicita reseñas a clientes atendidos",
      description: candidates.length ? `${candidates.length} cliente${candidates.length === 1 ? "" : "s"} todavía no ${candidates.length === 1 ? "tiene" : "tienen"} una solicitud preparada.` : "No hay clientes atendidos pendientes de solicitud.",
      dependency: hasReviewLink ? "Solicitud asistida por WhatsApp" : "Falta el enlace de reseñas",
      status: candidates.length ? (hasReviewLink ? "recommended" : "blocked") : "completed",
      priority: 4,
      action: "reviews",
      action_label: "Ver clientes"
    },
    {
      id: "pending-bookings",
      title: "Confirma las reservas pendientes",
      description: pendingBookings.length ? `${pendingBookings.length} reserva${pendingBookings.length === 1 ? "" : "s"} espera${pendingBookings.length === 1 ? "" : "n"} respuesta.` : "No hay reservas pendientes de confirmación.",
      dependency: "Agenda",
      status: pendingBookings.length ? "needs_attention" : "completed",
      priority: 5,
      action: "bookings-pending",
      action_label: "Abrir pendientes"
    },
    {
      id: "pending-conversations",
      title: "Responde los mensajes pendientes",
      description: pendingConversations.length ? `${pendingConversations.length} conversación${pendingConversations.length === 1 ? "" : "es"} requiere${pendingConversations.length === 1 ? "" : "n"} respuesta.` : "Las conversaciones están al día.",
      dependency: "Clientes y mensajes",
      status: dashboardDataState.conversations === "error" ? "not_available" : dashboardDataState.conversations === "loading" ? "neutral" : pendingConversations.length ? "recommended" : "completed",
      priority: 6,
      action: "conversations",
      action_label: "Responder mensajes"
    },
    {
      id: "active-services",
      title: "Activa un servicio reservable",
      description: "Los clientes necesitan al menos un servicio activo para reservar.",
      dependency: "Configuración / Servicios",
      status: dashboardDataState.services === "error" ? "not_available" : dashboardDataState.services === "loading" ? "neutral" : adminServices.some((service) => service.active) ? "completed" : "blocked",
      priority: 7,
      action: "services",
      action_label: "Configurar servicios"
    },
    {
      id: "business-hours",
      title: "Completa los horarios del negocio",
      description: "Sin tramos de apertura no se pueden ofrecer horas de reserva.",
      dependency: "Configuración / Horarios",
      status: dashboardDataState.availability === "error" ? "not_available" : dashboardDataState.availability === "loading" ? "neutral" : dashboardHasConfiguredAvailability() ? "completed" : "blocked",
      priority: 8,
      action: "schedule",
      action_label: "Configurar horarios"
    },
    {
      id: "public-business",
      title: "Activa la página pública",
      description: "El negocio debe estar activo para aceptar nuevas reservas públicas.",
      dependency: "Configuración / Página pública",
      status: dashboardDataState.business === "loading" ? "neutral" : currentBusiness?.active ? "completed" : "blocked",
      priority: 9,
      action: "public-page",
      action_label: "Revisar publicación"
    }
  ];
  if (configurationLoadState.gallery === "ready") tasks.push({
    id: "business-gallery",
    title: "Añade una imagen a la página pública",
    description: "La galería está vacía; puedes añadir una imagen real del negocio.",
    dependency: "Configuración / Página pública",
    status: adminGallery.length ? "completed" : "recommended",
    priority: 10,
    action: "public-page",
    action_label: "Revisar galería"
  });
  businessChannelHealth.filter((health) => health.reconnection_required).forEach((health) => tasks.push({
    id: `channel-${health.channel}`,
    title: `${health.channel === "whatsapp" ? "WhatsApp" : "Instagram"} necesita reconexión`,
    description: "La conexión del canal ya no es válida y necesita el flujo oficial de Meta.",
    dependency: "Canales y automatizaciones",
    status: "blocked",
    priority: 1,
    action: "channel",
    channel: health.channel,
    action_label: "Revisar canal"
  }));
  const priorityGroup = (task) => {
    if (["blocked", "not_available"].includes(task.status)) return 0;
    if (task.id === "review-pending") return 1;
    if (task.id === "review-failures") return 2;
    if (task.id === "review-candidates") return 3;
    if (task.status === "needs_attention") return 4;
    if (task.status === "recommended") return 5;
    if (task.status === "completed") return 6;
    return 7;
  };
  return tasks.sort((first, second) => priorityGroup(first) - priorityGroup(second) || first.priority - second.priority);
}

function getSafeReviewUrl() {
  const value = String(currentBusiness?.reviews_url || "").trim();
  return value && isSafePublicUrl(value) ? value : "";
}

function getReviewCandidates() {
  return allBookings.filter((booking) => booking.status === "completed" && !reviewRequestsByBooking.has(booking.id))
    .sort((first, second) => getBookingSortValue(second).localeCompare(getBookingSortValue(first)));
}

function getReviewOutboxMessage(bookingId) {
  return messageOutbox.find((message) => message.booking_id === bookingId && message.message_type === "booking_completed_review") || null;
}

function getFailedReviewMessages() {
  return messageOutbox.filter((message) => message.message_type === "booking_completed_review" && message.status === "failed");
}

function hasUsableReviewPhone(booking) {
  let digits = String(booking?.customer_phone || "").replace(/\D/g, "");
  if (digits.startsWith("00")) digits = digits.slice(2);
  return digits.length >= 8 && digits.length <= 15 && !digits.startsWith("0");
}

function growthSourcesSettled() {
  return dashboardDataState.bookings !== "loading" && growthLoadState.reviews !== "loading" && growthLoadState.outbox !== "loading" && growthLoadState.opportunities !== "loading" && growthLoadState.signals !== "loading";
}

function growthSourceErrors() {
  const errors = [];
  if (dashboardDataState.bookings === "error") errors.push("No se pudieron comprobar las reservas.");
  if (growthLoadState.reviews === "error") errors.push("No se pudieron actualizar las solicitudes de reseña.");
  if (growthLoadState.outbox === "error") errors.push("No se pudo comprobar el estado de los mensajes asistidos.");
  if (growthLoadState.opportunities === "error") errors.push("No se pudieron actualizar las oportunidades de clientes.");
  if (growthLoadState.signals === "error") errors.push("No se pudieron actualizar las señales agregadas del negocio.");
  return errors;
}

function growthTaskStateLabel(status) {
  return ({ recommended: "Recomendada", needs_attention: "Necesita atención", blocked: "Bloqueada", completed: "Completada", not_available: "No disponible", neutral: "Comprobando" })[status] || "Estado no disponible";
}

function renderGrowthActivity() {
  const container = document.getElementById("growth-activity-list");
  if (!container) return;
  const activity = Array.from(reviewRequestsByBooking.values()).map((request) => {
    const outbox = getReviewOutboxMessage(request.booking_id);
    if (outbox?.status === "failed") return { label: "No se pudo preparar la solicitud", customer: request.customer_name, at: outbox.created_at };
    if (request.status === "sent") return { label: "Solicitud marcada como enviada", customer: request.customer_name, at: request.sent_at };
    if (request.status === "skipped") return { label: "Solicitud omitida", customer: request.customer_name, at: request.created_at };
    if (outbox?.status === "opened") return { label: "Solicitud abierta en WhatsApp", customer: request.customer_name, at: outbox.opened_at };
    if (request.status === "copied") return { label: "Mensaje de reseña copiado", customer: request.customer_name, at: request.copied_at };
    return { label: "Solicitud preparada", customer: request.customer_name, at: request.created_at };
  }).sort((first, second) => String(second.at || "").localeCompare(String(first.at || ""))).slice(0, 6);
  container.setAttribute("aria-busy", "false");
  container.innerHTML = activity.length ? activity.map((item) => `<article><div><strong>${escapeHtml(item.label)}</strong><p>${escapeHtml(item.customer || "Cliente sin nombre")}</p></div><time>${escapeHtml(formatConversationDate(item.at))}</time></article>`).join("") : `<div class="growth-empty-state"><strong>Aún no hay actividad de reseñas</strong><p>Las solicitudes preparadas aparecerán aquí.</p></div>`;
}

function renderGrowthOverview(tasks) {
  const candidates = getReviewCandidates();
  const requests = Array.from(reviewRequestsByBooking.values());
  const prepared = requests.filter((request) => ["pending", "copied"].includes(request.status)).length;
  const sent = requests.filter((request) => request.status === "sent").length;
  const failed = getFailedReviewMessages().length;
  const activeTasks = tasks.filter((task) => ["recommended", "needs_attention", "blocked", "not_available"].includes(task.status));
  const completed = tasks.filter((task) => task.status === "completed").length;
  const percentage = tasks.length ? Math.round((completed / tasks.length) * 100) : 100;
  const metricValues = { "growth-metric-candidates": candidates.length, "growth-metric-prepared": prepared, "growth-metric-sent": sent, "growth-metric-failed": failed, "growth-metric-opportunities": customerOpportunities.filter((item) => item.status === "pending").length };
  Object.entries(metricValues).forEach(([id, value]) => { document.getElementById(id).textContent = String(value); });
  document.querySelector(".growth-metrics")?.setAttribute("aria-busy", "false");
  document.getElementById("growth-progress-count").textContent = `${completed} de ${tasks.length} condiciones resueltas`;
  document.getElementById("growth-points").textContent = "Basado en datos operativos reales";
  document.getElementById("growth-progress-percent").textContent = `${percentage}%`;
  const progress = document.querySelector(".growth-progress");
  progress.setAttribute("aria-valuenow", String(percentage));
  document.getElementById("growth-progress-bar").style.width = `${percentage}%`;
  progress.classList.toggle("growth-progress-complete", activeTasks.length === 0);
  const priority = document.getElementById("growth-priority-list");
  priority.setAttribute("aria-busy", "false");
  priority.innerHTML = activeTasks.length ? activeTasks.slice(0, 5).map((task) => `<article class="growth-priority-item growth-priority-item--${task.status}"><div><span>${growthTaskStateLabel(task.status)}</span><h4>${escapeHtml(task.title)}</h4><p>${escapeHtml(task.description)}</p><small>Depende de: ${escapeHtml(task.dependency)}</small></div><button class="ag-button ag-button--secondary ag-button--small" type="button" data-growth-action="${escapeHtml(task.action)}"${task.channel ? ` data-channel="${escapeHtml(task.channel)}"` : ""}>${escapeHtml(task.action_label)}</button></article>`).join("") : `<div class="growth-empty-state"><strong>No hay acciones prioritarias</strong><p>Las condiciones comprobadas no requieren intervención.</p></div>`;
  const dayComplete = document.getElementById("growth-day-complete");
  dayComplete.hidden = activeTasks.length > 0 || growthSourceErrors().length > 0;
  const nextTask = activeTasks[0];
  document.getElementById("growth-summary-count").textContent = activeTasks.length ? `${activeTasks.length} acción${activeTasks.length === 1 ? "" : "es"} pendiente${activeTasks.length === 1 ? "" : "s"}` : "Sin acciones pendientes";
  document.getElementById("growth-summary-next").textContent = nextTask ? `Prioridad: ${nextTask.title}` : "No hay bloqueos con los datos disponibles.";
  document.getElementById("growth-summary-progress-bar").style.width = `${percentage}%`;
  document.getElementById("growth-overview-status").textContent = activeTasks.length ? `${activeTasks.length} pendientes` : "Sin pendientes";
  renderGrowthActivity();
}

function renderGrowthOpportunities(tasks) {
  const container = document.getElementById("growth-tasks-list");
  if (!container) return;
  const visible = tasks.filter((task) => ["recommended", "needs_attention", "blocked", "not_available"].includes(task.status));
  container.setAttribute("aria-busy", "false");
  const typeLabels = { cancelled_not_rebooked: "Cancelación sin nueva reserva", no_show_not_rebooked: "No presentado sin nueva reserva", lead_not_converted: "Consulta sin reserva", service_due: "Servicio pendiente de repetición", scheduled_followup: "Seguimiento indicado" };
  const channelLabels = { whatsapp: "WhatsApp", instagram: "Instagram" };
  const actionLabels = { draft: "Borrador", approved: "Pendiente de envío", sending: "Enviando", sent: "Enviado", failed: "Fallido", cancelled: "Cancelado", completed: "Completado" };
  const persisted = customerOpportunities.map((item) => {
    const latest = item.latest_action;
    const channel = item.channel?.channel ? (channelLabels[item.channel.channel] || item.channel.channel) : "Sin canal disponible";
    const prepareLabel = latest?.status === "draft" ? "Continuar borrador" : "Preparar mensaje";
    const memory = item.customer_context?.explicit || [];
    const context = memory.length ? `<div class="growth-customer-context"><strong>Contexto del cliente</strong>${memory.map((entry) => `<p>${escapeHtml(entry.value)}</p>`).join("")}</div>` : "";
    return `<article class="growth-task growth-task-${escapeHtml(item.priority)}" data-customer-opportunity="${item.id}"><span class="growth-task-status">${escapeHtml(typeLabels[item.type] || item.type)}</span><div class="growth-task-copy"><h3>${escapeHtml(item.customer?.name || "Cliente sin nombre")}</h3><p>${escapeHtml(item.reason_text)}</p><div class="growth-opportunity-meta"><span>${escapeHtml(item.source_service_name || "Sin servicio específico")}</span><span>${escapeHtml(channel)}</span><span>${escapeHtml(latest ? actionLabels[latest.status] || latest.status : "Sin acciones")}</span></div><span>Fecha relevante: ${escapeHtml(formatDateTime(item.due_at))}</span><details><summary>Ver contexto</summary><p>${escapeHtml(item.reason_text)}</p>${context}</details></div><div class="growth-opportunity-actions"><button class="ag-button ag-button--primary ag-button--small" type="button" data-opportunity-action="prepare" data-opportunity-id="${item.id}">${escapeHtml(prepareLabel)}</button>${item.channel?.conversation_id ? `<button class="ag-button ag-button--secondary ag-button--small" type="button" data-opportunity-action="conversation" data-opportunity-id="${item.id}">Ver conversación</button>` : ""}<button class="ag-button ag-button--secondary ag-button--small" type="button" data-opportunity-action="actioned" data-opportunity-id="${item.id}">Marcar gestionada</button><button class="ag-button ag-button--ghost ag-button--small" type="button" data-opportunity-action="dismissed" data-opportunity-id="${item.id}">Descartar</button></div></article>`;
  }).join("");
  const operational = visible.length ? `<details class="growth-operational-recommendations"><summary>Mejoras operativas (${visible.length})</summary>${visible.map((task) => `<article class="growth-task growth-task-${task.status}" data-growth-task="${escapeHtml(task.id)}"><span class="growth-task-status">${escapeHtml(growthTaskStateLabel(task.status))}</span><div class="growth-task-copy"><h3>${escapeHtml(task.title)}</h3><p>${escapeHtml(task.description)}</p><span>Depende de: ${escapeHtml(task.dependency)}</span></div><button class="ag-button ag-button--secondary ag-button--small" type="button" data-growth-action="${escapeHtml(task.action)}"${task.channel ? ` data-channel="${escapeHtml(task.channel)}"` : ""}>${escapeHtml(task.action_label)}</button></article>`).join("")}</details>` : "";
  container.innerHTML = persisted || operational ? `${persisted}${operational}` : `<div class="growth-empty-state"><strong>No hay oportunidades activas</strong><p>Cuando venza un seguimiento o una reserva necesite atención, aparecerá aquí.</p></div>`;
  document.getElementById("growth-opportunities-status").textContent = customerOpportunities.length ? `${customerOpportunities.length} pendientes` : "Sin oportunidades";
}

function renderGrowthActionMetrics() {
  const metrics = growthActionMetrics?.summary;
  const values = {
    "growth-result-detected": metrics?.opportunities_detected,
    "growth-result-handled": metrics?.opportunities_handled,
    "growth-result-booked": metrics?.bookings_attributed,
    "growth-result-completed": metrics?.attributed_bookings_completed,
    "growth-result-revenue": metrics?.attributed_revenue == null
      ? "Sin importe fiable"
      : `${metrics.attributed_revenue} ${metrics.revenue_currency || ""}`.trim()
  };
  Object.entries(values).forEach(([id, value]) => {
    const node = document.getElementById(id);
    if (node) node.textContent = value == null ? "—" : String(value);
  });
  document.querySelector(".growth-results-metrics")?.setAttribute("aria-busy", "false");
  const funnel = growthActionMetrics?.funnel;
  const labels = { detected: "Detectadas", viewed: "Vistas", actioned: "Gestionadas", sent: "Enviadas", booked: "Reservadas", completed: "Completadas" };
  const container = document.getElementById("growth-funnel");
  if (container) container.innerHTML = funnel
    ? Object.entries(labels).map(([key, label]) => `<span><small>${escapeHtml(label)}</small><strong>${Number(funnel[key] || 0)}</strong></span>`).join("")
    : "";
}

function renderBusinessGrowthSignals() {
  const container = document.getElementById("growth-signals-list");
  const status = document.getElementById("growth-signals-status");
  if (!container || !status) return;
  container.setAttribute("aria-busy", "false");
  const typeLabels = {
    low_future_occupancy: "Agenda floja",
    high_due_customer_pool: "Retorno de clientes",
    low_return_rate: "Menor tasa de retorno",
    service_demand_drop: "Servicio con menor demanda",
    seasonal_window: "Ventana comercial"
  };
  const severityLabels = { info: "Información", low: "Atención", medium: "Prioritaria", high: "Urgente" };
  const recommendationLabels = {
    increase_booking_visibility: "Dar más visibilidad a la disponibilidad",
    contact_due_customers: "Revisar oportunidades de retorno",
    promote_service: "Dar visibilidad al servicio",
    consider_campaign: "Valorar una comunicación comercial",
    review_service_demand: "Revisar la demanda del servicio"
  };
  container.innerHTML = businessGrowthSignals.length ? businessGrowthSignals.map((signal) => {
    const explanation = signal.explanation || {};
    const related = signal.related_opportunities;
    return `<article class="growth-signal growth-signal--${escapeHtml(signal.severity)}" data-growth-signal="${signal.id}"><div class="growth-signal-heading"><span>${escapeHtml(severityLabels[signal.severity] || signal.severity)}</span><small>${escapeHtml(signal.service?.name || "Todo el negocio")}</small></div><h4>${escapeHtml(explanation.title || typeLabels[signal.type] || signal.type)}</h4><p><strong>${escapeHtml(explanation.what_happened || "Se ha detectado una variación relevante.")}</strong></p><p>${escapeHtml(explanation.comparison || "")}</p><p>${escapeHtml(explanation.why_it_matters || "")}</p><div class="growth-signal-recommendation"><span>Recomendación</span><strong>${escapeHtml(recommendationLabels[signal.recommendation_code] || explanation.suggested_action || signal.recommendation_code)}</strong></div><div class="growth-opportunity-actions">${related ? `<button class="ag-button ag-button--secondary ag-button--small" type="button" data-growth-signal-action="opportunities" data-growth-signal-id="${signal.id}">Ver oportunidades relacionadas</button>` : ""}<button class="ag-button ag-button--ghost ag-button--small" type="button" data-growth-signal-action="dismiss" data-growth-signal-id="${signal.id}">Descartar señal</button></div></article>`;
  }).join("") : `<div class="growth-empty-state"><strong>No hay señales activas</strong><p>${growthSignalsSummary?.data_state === "insufficient_history_or_not_evaluated" ? "Todavía no hay suficiente histórico o no se ha ejecutado el análisis diario." : "Los datos evaluados no superan los umbrales conservadores actuales."}</p></div>`;
  status.textContent = businessGrowthSignals.length ? `${businessGrowthSignals.length} activa${businessGrowthSignals.length === 1 ? "" : "s"}` : "Sin alertas";
}

async function loadBusinessGrowthSignals({ background = false } = {}) {
  if (!businessGrowthSignals.length) growthLoadState.signals = "loading";
  try {
    const slug = getBusinessSlug();
    const [signalsResponse, summaryResponse] = await Promise.all([
      fetch(`${API_BASE_URL}/api/admin/businesses/${slug}/growth-signals?status=active`),
      fetch(`${API_BASE_URL}/api/admin/businesses/${slug}/growth-signals-summary`)
    ]);
    if (!signalsResponse.ok || !summaryResponse.ok) throw new Error("growth_signals_unavailable");
    const [signalsBody, summaryBody] = await Promise.all([signalsResponse.json(), summaryResponse.json()]);
    businessGrowthSignals = signalsBody.signals || [];
    growthSignalsSummary = summaryBody;
    growthLoadState.signals = "ready";
    renderGrowth();
  } catch (error) {
    console.error(error);
    growthLoadState.signals = "error";
    if (!background) {
      businessGrowthSignals = [];
      growthSignalsSummary = null;
    }
    renderGrowth();
  }
}

async function dismissGrowthSignal(signalId) {
  if (growthSignalMutationIds.has(signalId)) return;
  growthSignalMutationIds.add(signalId);
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/growth-signals/${signalId}/dismiss`, { method: "POST" });
    if (!response.ok) throw new Error("No se pudo descartar la señal.");
    businessGrowthSignals = businessGrowthSignals.filter((signal) => signal.id !== signalId);
    if (growthSignalsSummary) growthSignalsSummary.active_count = Math.max(0, growthSignalsSummary.active_count - 1);
    renderGrowth();
  } catch (error) {
    alert(error.message || "No se pudo descartar la señal.");
  } finally {
    growthSignalMutationIds.delete(signalId);
  }
}

async function openSignalOpportunities(signalId) {
  const signal = businessGrowthSignals.find((item) => item.id === signalId);
  if (!signal?.related_opportunities) return;
  const filters = new URLSearchParams({ status: "pending", type: signal.related_opportunities.type });
  if (signal.related_opportunities.service_id) filters.set("service_id", String(signal.related_opportunities.service_id));
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/opportunities?${filters}`);
    if (!response.ok) throw new Error("No se pudieron abrir las oportunidades relacionadas.");
    customerOpportunities = (await response.json()).opportunities || [];
    growthLoadState.opportunities = "ready";
    showAdminSection("growth-opportunities");
    renderGrowth();
  } catch (error) {
    alert(error.message || "No se pudieron abrir las oportunidades relacionadas.");
  }
}

async function loadCustomerOpportunities({ background = false } = {}) {
  if (!customerOpportunities.length) growthLoadState.opportunities = "loading";
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/opportunities?status=pending`);
    if (!response.ok) throw new Error("opportunities_unavailable");
    const data = await response.json();
    customerOpportunities = data.opportunities || [];
    growthLoadState.opportunities = "ready";
    renderGrowth();
    renderDashboard();
  } catch (error) {
    console.error(error);
    growthLoadState.opportunities = "error";
    if (!background) customerOpportunities = [];
    renderGrowth();
    renderDashboard();
  }
}

async function loadGrowthActionMetrics({ background = false } = {}) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/growth-metrics?period=30d`);
    if (!response.ok) throw new Error("growth_metrics_unavailable");
    growthActionMetrics = await response.json();
    renderGrowthActionMetrics();
  } catch (error) {
    console.error(error);
    if (!background) growthActionMetrics = null;
    renderGrowthActionMetrics();
  }
}

function growthActionUnavailableMessage(action) {
  if (action?.delivery_mode === "unavailable" && !action?.assisted_delivery_available) {
    return "Este cliente no tiene un teléfono válido. Puedes copiar el texto para gestionarlo por otro canal.";
  }
  const messages = {
    no_customer_channel: "No hay un canal conectado para este cliente. Puedes copiar el texto y gestionarlo manualmente.",
    whatsapp_template_required: "La ventana de atención de 24 horas está cerrada. No se enviará sin una plantilla oficial; puedes copiar el texto.",
    provider_not_configured: "La integración del canal no está disponible. Puedes copiar el texto.",
    integrated_delivery_not_in_plan: "El envío integrado no está habilitado para este negocio.",
    delivery_not_available: "El canal no está disponible para enviar en este momento."
  };
  return messages[action?.unavailable_reason] || "El envío integrado no está disponible; puedes copiar el texto.";
}

function openGrowthActionModal(action, opportunity, trigger = null) {
  const modal = document.getElementById("growth-action-modal");
  selectedOpportunityAction = action;
  selectedOpportunityForAction = opportunity;
  growthActionReturnFocus = trigger || document.activeElement;
  const channel = { whatsapp: "WhatsApp", instagram: "Instagram" }[action.channel]
    || (action.delivery_mode === "assisted" ? "WhatsApp asistido" : "Sin canal disponible");
  const status = { draft: "Borrador editable", approved: "Aprobado y pendiente", sending: "Enviando", sent: "Enviado", failed: "Fallido", cancelled: "Cancelado", completed: "Completado" }[action.status] || action.status;
  document.getElementById("growth-action-channel").textContent = channel;
  document.getElementById("growth-action-reason").textContent = opportunity.reason_text;
  document.getElementById("growth-action-status").textContent = status;
  const textarea = document.getElementById("growth-action-text");
  textarea.value = action.final_text || action.suggested_text || "";
  textarea.disabled = action.status !== "draft";
  const notice = document.getElementById("growth-action-notice");
  const integrated = action.delivery_mode === "integrated" && action.can_send;
  const assisted = action.assisted_delivery_available === true;
  notice.className = `inline-feedback ${integrated || assisted ? "" : "error"}`;
  notice.textContent = integrated
    ? "Puedes enviarlo desde AutonoGrow o abrir WhatsApp para revisarlo y enviarlo tú."
    : assisted
      ? "Se abrirá WhatsApp con el mensaje preparado para que puedas revisarlo y enviarlo. AutonoGrow no lo marcará como enviado."
      : growthActionUnavailableMessage(action);
  const send = document.getElementById("growth-action-send");
  send.hidden = !integrated;
  send.disabled = action.status !== "draft" || !integrated;
  send.textContent = ["approved", "sending"].includes(action.status) ? "Pendiente" : "Enviar por WhatsApp";
  const whatsapp = document.getElementById("growth-action-whatsapp");
  whatsapp.hidden = !assisted;
  whatsapp.disabled = !assisted || !["draft", "failed"].includes(action.status);
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-scroll-locked");
  window.requestAnimationFrame(() => textarea.focus());
}

function closeGrowthActionModal() {
  const modal = document.getElementById("growth-action-modal");
  if (!modal.classList.contains("open")) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
  document.body.classList.remove("modal-scroll-locked");
  const focus = growthActionReturnFocus;
  growthActionReturnFocus = null;
  selectedOpportunityAction = null;
  selectedOpportunityForAction = null;
  if (focus?.isConnected) focus.focus({ preventScroll: true });
}

async function prepareOpportunityMessage(opportunityId, trigger) {
  if (opportunityMutationIds.has(opportunityId)) return;
  opportunityMutationIds.add(opportunityId);
  trigger.disabled = true;
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/opportunities/${opportunityId}/actions/prepare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action_type: "contact_customer" })
    });
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudo preparar el mensaje."));
    const opportunity = customerOpportunities.find((item) => item.id === opportunityId);
    if (!opportunity) throw new Error("La oportunidad ya no está disponible.");
    opportunity.latest_action = body.action;
    openGrowthActionModal(body.action, opportunity, trigger);
    renderGrowth();
  } catch (error) {
    alert(error.message || "No se pudo preparar el mensaje.");
  } finally {
    opportunityMutationIds.delete(opportunityId);
    if (trigger?.isConnected) trigger.disabled = false;
  }
}

async function persistGrowthActionDraft() {
  const action = selectedOpportunityAction;
  const text = document.getElementById("growth-action-text").value.trim();
  if (!action || action.status !== "draft") return action;
  if (!text) throw new Error("El mensaje no puede estar vacío.");
  if (text === action.final_text) return action;
  const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/actions/${action.id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ final_text: text })
  });
  const body = await readAdminResponseBody(response);
  if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudo guardar el borrador."));
  selectedOpportunityAction = body.action;
  return body.action;
}

async function sendGrowthOpportunityAction() {
  const button = document.getElementById("growth-action-send");
  if (!selectedOpportunityAction || button.disabled) return;
  button.disabled = true;
  button.textContent = "Preparando envío…";
  const notice = document.getElementById("growth-action-notice");
  try {
    const action = await persistGrowthActionDraft();
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/actions/${action.id}/send`, { method: "POST" });
    const body = await readAdminResponseBody(response);
    if (body?.action) selectedOpportunityAction = body.action;
    if (response.status === 429) throw new Error(adminRateLimitMessage(response));
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudo enviar el mensaje."));
    notice.className = "inline-feedback success";
    notice.textContent = body.action.status === "sent"
      ? "Mensaje enviado por el proveedor."
      : "Mensaje aprobado y pendiente de entrega. Todavía no se muestra como enviado.";
    document.getElementById("growth-action-status").textContent = body.action.status === "sent" ? "Enviado" : "Pendiente de entrega";
    document.getElementById("growth-action-text").disabled = true;
    button.textContent = body.action.status === "sent" ? "Enviado" : "Pendiente";
    const opportunity = customerOpportunities.find((item) => item.id === selectedOpportunityForAction?.id);
    if (opportunity) opportunity.latest_action = body.action;
    await Promise.allSettled([loadCustomerOpportunities({ background: true }), loadGrowthActionMetrics({ background: true })]);
  } catch (error) {
    notice.className = "inline-feedback error";
    notice.textContent = error.message || "No se pudo enviar el mensaje. Puedes copiarlo para gestionarlo manualmente.";
    button.disabled = !selectedOpportunityAction?.can_send;
    button.textContent = "Reintentar envío";
    const whatsapp = document.getElementById("growth-action-whatsapp");
    const assisted = selectedOpportunityAction?.assisted_delivery_available === true;
    whatsapp.hidden = !assisted;
    whatsapp.disabled = !assisted;
  }
}

async function openGrowthOpportunityWhatsApp() {
  if (!selectedOpportunityAction || opportunityAssistedOpening) return;
  const whatsappWindow = openBlankWhatsAppWindow();
  const button = document.getElementById("growth-action-whatsapp");
  const send = document.getElementById("growth-action-send");
  const notice = document.getElementById("growth-action-notice");
  opportunityAssistedOpening = true;
  button.disabled = true;
  send.disabled = true;
  button.setAttribute("aria-busy", "true");
  try {
    const action = await persistGrowthActionDraft();
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/actions/${action.id}/assisted-delivery`, { method: "POST" });
    const body = await readAdminResponseBody(response);
    if (response.status === 429) throw new Error(adminRateLimitMessage(response));
    if (!response.ok || !isSafeWhatsAppUrl(body.whatsapp_url)) throw new Error(conversationErrorMessage(body, "No se pudo abrir WhatsApp de forma segura."));
    if (!whatsappWindow) throw new Error("El navegador bloqueó la nueva ventana de WhatsApp.");
    whatsappWindow.location.href = body.whatsapp_url;
    notice.className = "inline-feedback success";
    notice.textContent = "WhatsApp abierto. El mensaje sigue preparado y no se considera enviado.";
  } catch (error) {
    whatsappWindow?.close();
    notice.className = "inline-feedback error";
    notice.textContent = error.message || "No se pudo abrir WhatsApp.";
  } finally {
    opportunityAssistedOpening = false;
    button.removeAttribute("aria-busy");
    button.disabled = !selectedOpportunityAction?.assisted_delivery_available;
    send.disabled = selectedOpportunityAction?.status !== "draft" || !selectedOpportunityAction?.can_send;
  }
}

async function copyGrowthOpportunityText() {
  const text = document.getElementById("growth-action-text").value;
  const notice = document.getElementById("growth-action-notice");
  try {
    await navigator.clipboard.writeText(text);
    notice.className = "inline-feedback success";
    notice.textContent = "Texto copiado. AutonoGrow no lo marca como enviado.";
  } catch (_) {
    notice.className = "inline-feedback error";
    notice.textContent = "No se pudo copiar automáticamente. Selecciona el texto y cópialo manualmente.";
  }
}

async function openOpportunityConversation(opportunityId) {
  const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/opportunities/${opportunityId}/open-conversation`, { method: "POST" });
  const body = await readAdminResponseBody(response);
  if (!response.ok || !body.conversation_id) return alert(conversationErrorMessage(body, "No se pudo abrir la conversación."));
  showAdminSection("conversations");
  await selectConversation(body.conversation_id);
}

async function updateCustomerOpportunity(opportunityId, status) {
  if (opportunityMutationIds.has(opportunityId)) return;
  opportunityMutationIds.add(opportunityId);
  try {
    const action = status === "dismissed" ? "dismiss" : "mark-handled";
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/opportunities/${opportunityId}/${action}`, { method: "POST" });
    if (!response.ok) throw new Error("No se pudo actualizar la oportunidad.");
    customerOpportunities = customerOpportunities.filter((item) => item.id !== opportunityId);
    loadGrowthActionMetrics({ background: true });
    renderGrowth();
    renderDashboard();
  } catch (error) {
    console.error(error);
    alert(error.message || "No se pudo actualizar la oportunidad.");
  } finally {
    opportunityMutationIds.delete(opportunityId);
  }
}

function renderGrowth() {
  renderGrowthNavigation();
  if (!growthSourcesSettled()) return;
  const tasks = calculateGrowthTasks();
  const errors = growthSourceErrors();
  for (const id of ["growth-overview-errors", "growth-opportunities-errors"]) {
    const container = document.getElementById(id);
    container.hidden = errors.length === 0;
    container.innerHTML = errors.length ? `<strong>Hay información que no se pudo actualizar</strong><ul>${errors.map((error) => `<li>${escapeHtml(error)}</li>`).join("")}</ul>` : "";
  }
  renderGrowthOverview(tasks);
  renderGrowthOpportunities(tasks);
  renderGrowthActionMetrics();
  renderBusinessGrowthSignals();
  renderReviewRequests();
}

async function loadAdminPanel() {
  const slug = getBusinessSlug();

  try {
    if (isBusinessStaff()) {
      growthLoadState.reviews = "ready";
      growthLoadState.outbox = "ready";
      dashboardDataState.services = "not_applicable";
      dashboardDataState.availability = "not_applicable";
      dashboardDataState.channels = "not_applicable";
      const [panelResponse, capabilityResponse] = await Promise.all([
        fetch(`${API_BASE_URL}/api/admin/businesses/${slug}/panel`),
        fetch(`${API_BASE_URL}/api/admin/businesses/${slug}/capabilities`)
      ]);
      if (!panelResponse.ok) throw new Error("No se pudo cargar tu agenda.");
      if (!capabilityResponse.ok) throw new Error("No se pudieron comprobar los módulos del negocio.");
      const panel = await panelResponse.json();
      businessCapabilities = (await capabilityResponse.json()).modules;
      currentBusiness = { ...panel.business, active: panel.business.status === "active" };
      dashboardDataState.business = "ready";
      applyBusinessData(currentBusiness);
      document.getElementById("business-subtitle").textContent = "Mi agenda y reservas asignadas";
      applyRoleVisibility();
      const staffLoads = [
        loadBookings(),
        loadBookingCloseTasks(),
        loadMyStaffAvailability(),
        loadConversationTemplates(),
        loadConversations()
      ];
      if (moduleAvailable("growth")) staffLoads.push(loadCustomerOpportunities(), loadGrowthActionMetrics(), loadBusinessGrowthSignals());
      await Promise.all(staffLoads);
      return;
    }
    const [businessResponse, capabilityResponse] = await Promise.all([
      fetch(`${API_BASE_URL}/api/admin/businesses/${slug}/settings`),
      fetch(`${API_BASE_URL}/api/admin/businesses/${slug}/capabilities`)
    ]);

    if (!businessResponse.ok) {
      if (businessResponse.status === 401) return showAdminLogin();
      if (businessResponse.status === 403 && lastBusinessOperationalStatus) {
        dashboardDataState.business = "ready";
        applyOperationalBusinessState(lastBusinessOperationalStatus);
        renderDashboard();
        return;
      }
      if (businessResponse.status === 403) return showAdminLogin("Tu cuenta no tiene acceso a este negocio.", true);
      renderError("No se encontró el negocio.");
      return;
    }

    currentBusiness = await businessResponse.json();
    if (!capabilityResponse.ok) throw new Error("No se pudieron comprobar los módulos del negocio.");
    businessCapabilities = (await capabilityResponse.json()).modules;
    applyRoleVisibility();
    dashboardDataState.business = "ready";
    applyBusinessData(currentBusiness);
    renderBusinessSettings();
    // Automation rules reference the default templates, so initialize templates first.
    await loadConversationTemplates();
    const growthLoads = [];
    if (moduleAvailable("growth")) growthLoads.push(loadCustomerOpportunities(), loadGrowthActionMetrics(), loadBusinessGrowthSignals());
    else {
      customerOpportunities = [];
      businessGrowthSignals = [];
      growthActionMetrics = null;
      growthLoadState.opportunities = "ready";
      growthLoadState.signals = "ready";
    }
    await Promise.all([
      loadAdminServices(),
      loadStaffMembers(),
      loadAvailabilitySettings(),
      loadAvailabilityExceptions(),
      loadBookings(),
      loadBookingCloseTasks(),
      loadMessageOutbox(),
      loadAdminGallery(),
      loadConversationAutomation(),
      loadBusinessChannelOnboarding(),
      loadConversations(),
      loadPilotOperations(),
      ...growthLoads
    ]);
    restoreAdminMediaStatus();
  } catch (error) {
    console.error(error);
    renderError("No se pudo conectar con el backend.");
  }
}

function channelOnboardingStatusLabel(status) {
  return ({ not_allowed: "No disponible", available: "Disponible", pending_approval: "Pendiente de revisión", approved: "Aprobado", suspended: "Suspendido", revoked: "Revocado" })[status] || "Estado no disponible";
}

async function loadPilotOperations() {
  const slug = getBusinessSlug();
  const [readinessResponse, valueResponse] = await Promise.all([
    fetch(`${API_BASE_URL}/api/admin/businesses/${slug}/pilot-readiness`),
    fetch(`${API_BASE_URL}/api/admin/businesses/${slug}/value-summary?period=30d`)
  ]);
  pilotReadiness = readinessResponse.ok ? await readinessResponse.json() : null;
  pilotValueSummary = valueResponse.ok ? await valueResponse.json() : null;
  renderPilotReadiness();
  renderPilotValue();
}

function renderPilotReadiness() {
  const container = document.getElementById("pilot-readiness-summary");
  if (!container) return;
  if (!pilotReadiness) {
    container.innerHTML = '<div class="empty-state"><strong>No se pudo comprobar la preparación.</strong><p>Reintenta más tarde; no se interpreta como listo.</p></div>';
    return;
  }
  const blockers = pilotReadiness.blocking || [];
  const warnings = pilotReadiness.warnings || [];
  const checklist = (pilotReadiness.checks || []).filter((item) => ["identity", "contact", "services", "staff", "schedules", "branding", "landing", "integrations"].includes(item.key));
  container.innerHTML = `<div class="configuration-summary-card"><div><h3>${pilotReadiness.booking_ready ? "Listo para recibir reservas" : "Completa la configuración inicial"}</h3><p>${blockers.length ? `${blockers.length} requisitos obligatorios pendientes.` : "Los requisitos obligatorios de reservas están completos."}</p></div><span class="ag-badge ag-badge--${pilotReadiness.booking_ready ? "success" : "warning"}">${pilotReadiness.booking_ready ? "Booking ready" : "Acción necesaria"}</span></div><div class="configuration-overview-list">${checklist.map((item) => `<article class="configuration-overview-item configuration-overview-item--${item.status === "passed" ? "complete" : item.blocking ? "missing" : "review"}"><div><h3>${escapeHtml(item.label)}</h3><p>${escapeHtml(item.message)}</p></div><span class="configuration-status">${item.status === "passed" ? "Completo" : item.blocking ? "Obligatorio" : "Opcional"}</span></article>`).join("")}</div>${warnings.length ? `<p class="helper">Avisos no bloqueantes: ${warnings.length}.</p>` : ""}`;
}

function renderPilotValue() {
  const container = document.getElementById("pilot-value-summary");
  if (!container || !pilotValueSummary) return;
  const modules = pilotValueSummary.modules || {};
  const growth = modules.growth;
  const social = modules.social;
  const essential = modules.essential;
  const rows = [
    `<article><span>Reservas gestionadas</span><strong>${essential?.metrics?.bookings_managed ?? "—"}</strong><small>Volumen gestionado, no ingreso incremental</small></article>`,
    growth?.state === "active" ? `<article><span>Growth · reservas atribuidas</span><strong>${growth.metrics?.bookings_attributed ?? 0}</strong><small>${growth.directly_attributable_revenue ? `${escapeHtml(growth.directly_attributable_revenue.amount)} ${escapeHtml(growth.directly_attributable_revenue.currency)} directamente atribuibles` : "Valor monetario aún incompleto"}</small></article>` : "",
    social?.state === "active" ? `<article><span>Social · publicaciones</span><strong>${social.metrics?.publications_recorded ?? 0}</strong><small>Valor operativo; sin atribución de ventas suficiente</small></article>` : ""
  ].join("");
  container.innerHTML = rows;
}

function channelHealthStatus(status) {
  return ({
    unknown: { label: "Aún no comprobado", tone: "neutral", message: "Todavía no hay una comprobación fiable de esta conexión." },
    healthy: { label: "Funciona correctamente", tone: "success", message: "La última comprobación no detectó problemas." },
    warning: { label: "Puede necesitar atención", tone: "warning", message: "La conexión funciona, pero conviene revisarla." },
    degraded: { label: "Funciona con problemas", tone: "warning", message: "Algunas funciones pueden no estar disponibles temporalmente." },
    action_required: { label: "Necesita tu atención", tone: "danger", message: "Comprueba la conexión o vuelve a conectarla para recuperar el servicio." },
    revoked: { label: "Debes volver a conectar", tone: "danger", message: "La autorización ya no es válida." },
    suspended: { label: "Canal suspendido", tone: "warning", message: "AutonoGrow ha suspendido temporalmente este canal." },
    error: { label: "No se ha podido comprobar", tone: "danger", message: "Reintenta la comprobación más tarde." }
  })[status] || { label: "Aún no comprobado", tone: "neutral", message: "Todavía no hay una comprobación fiable de esta conexión." };
}

function channelHubNavigationMarkup(activeSection) {
  const categories = CHANNEL_HUB_CATEGORIES.filter((category) => category.id !== "channel-instagram" || moduleAvailable("social"));
  return `<nav class="channel-hub-navigation" aria-label="Canales y automatizaciones"><p>Canales</p>${categories.map((category) => `<button type="button" data-channel-hub-target="${category.id}" ${category.id === activeSection ? 'aria-current="page"' : ""}><span><strong>${category.label}</strong><small>${category.description}</small></span></button>`).join("")}</nav>`;
}

function renderChannelHubNavigation() {
  const active = document.querySelector("[data-admin-section].admin-section-active")?.dataset.adminSection || "channels";
  document.querySelectorAll("[data-channel-hub-navigation]").forEach((container) => { container.innerHTML = channelHubNavigationMarkup(active); });
}

function channelRecord(name) {
  return businessChannelOnboarding?.channels?.find((channel) => channel.channel === name) || null;
}

function channelHealthRecord(name) {
  return businessChannelHealth.find((health) => health.channel === name) || null;
}

function channelConnectionLabel(channel, health) {
  if (!channel) return "No se ha podido comprobar";
  if (health?.reconnection_required || channel.status === "revoked") return "Necesita reconexión";
  if (["pending_approval", "approved"].includes(channel.status)) return "Conectado";
  return "Pendiente de conexión";
}

function channelApprovalLabel(channel) {
  if (!channel) return "No se ha podido comprobar";
  if (channel.status === "pending_approval") return "Pendiente de revisión";
  if (channel.status === "approved") return "Aprobado";
  if (channel.status === "revoked") return "Revocado";
  if (channel.status === "suspended") return "Suspendido";
  return "No solicitada";
}

function channelCapabilityLabel(channel, capability) {
  if (!channel || channel.status === "not_allowed") return "No disponible";
  if (channel.status === "pending_approval") return "Pendiente de revisión";
  if (["suspended", "revoked"].includes(channel.status)) return "Bloqueado temporalmente";
  return channel.status === "approved" && channel[capability] ? "Activado" : "Desactivado";
}

function channelStateRows(channel, health, { compact = false } = {}) {
  const state = channelHealthStatus(health?.health_status || "unknown");
  const rows = [
    ["Disponibilidad", channelOnboardingStatusLabel(channel?.status)],
    ["Conexión", channelConnectionLabel(channel, health)],
    ["Aprobación", channelApprovalLabel(channel)],
    ["Envío desde AutonoGrow", channelCapabilityLabel(channel, "integrated_delivery_enabled")],
    ["Respuestas automáticas", channelCapabilityLabel(channel, "automation_enabled")],
    ["Salud", channelHubLoadState.health === "error" ? "No se ha podido comprobar" : state.label]
  ];
  return `<dl class="channel-state-list${compact ? " channel-state-list--compact" : ""}">${rows.map(([label, value]) => `<div><dt>${label}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>`;
}

function channelActionMarkup(channel, health, name) {
  if (!channel) return `<button class="ag-button ag-button--secondary" type="button" data-channel-retry="onboarding">Reintentar</button>`;
  const label = name === "instagram" ? "Instagram" : "WhatsApp";
  const actions = [];
  const needsReconnect = health?.reconnection_required || channel.status === "revoked";
  if (channel.can_request && !needsReconnect) actions.push(`<button class="ag-button ag-button--primary" type="button" data-channel-request="${name}">Conectar ${label}</button>`);
  if (channel.status === "approved") actions.push(`<button class="ag-button ag-button--secondary" type="button" data-channel-health-action="check" data-channel="${name}">Comprobar ahora</button>`);
  if (needsReconnect) actions.push(`<button class="ag-button ag-button--primary" type="button" data-channel-health-action="reconnect" data-channel="${name}">Volver a conectar</button>`);
  return actions.length ? `<div class="channel-actions">${actions.join("")}</div>` : "";
}

function renderChannelOverviewCard(name) {
  const channel = channelRecord(name);
  const health = channelHealthRecord(name);
  const title = name === "instagram" ? "Instagram" : "WhatsApp";
  const attention = health?.reconnection_required || ["revoked", "suspended"].includes(channel?.status);
  return `<article class="channel-overview-card${attention ? " channel-overview-card--attention" : ""}"><div class="channel-overview-card__heading"><div><p>Canal</p><h3>${title}</h3></div><span class="channel-status-text">${escapeHtml(channelConnectionLabel(channel, health))}</span></div>${channelStateRows(channel, health, { compact: true })}<button class="ag-button ag-button--secondary ag-button--small" type="button" data-channel-hub-target="channel-${name}">Ver ${title}</button></article>`;
}

function renderChannelDetail(name) {
  const container = document.getElementById(`channel-${name}-content`);
  const status = document.getElementById(`channel-${name}-status`);
  if (!container || !status) return;
  const title = name === "instagram" ? "Instagram" : "WhatsApp";
  const channel = channelRecord(name);
  const health = channelHealthRecord(name);
  if (!channel && channelHubLoadState.onboarding === "error") {
    status.textContent = "Error al cargar";
    container.innerHTML = `<div class="channel-partial-error"><strong>No se pudo cargar ${title}.</strong><p>El resto de apartados sigue disponible.</p><button class="ag-button ag-button--secondary" type="button" data-channel-retry="onboarding">Reintentar</button></div>`;
    return;
  }
  const healthState = channelHealthStatus(health?.health_status || "unknown");
  status.textContent = channelConnectionLabel(channel, health);
  const account = name === "instagram" && channel?.connected_account_name
    ? `<p class="channel-safe-identity">Cuenta conectada: <strong>@${escapeHtml(String(channel.connected_account_name).replace(/^@/, ""))}</strong></p>`
    : name === "whatsapp" && health?.display_phone_number_redacted ? `<p class="channel-safe-identity">Número terminado en <strong>${escapeHtml(health.display_phone_number_redacted)}</strong></p>` : "";
  const onboardingHelp = channel?.can_request ? (name === "instagram"
    ? `<div class="ag-alert ag-alert--info"><div><strong>Antes de empezar</strong><p>Usa una cuenta profesional Business o Creator que puedas administrar. Meta realizará el inicio de sesión oficial; AutonoGrow nunca te pedirá la contraseña.</p></div></div>`
    : `<div class="ag-alert ag-alert--info"><div><strong>Antes de empezar</strong><p>Debes administrar el portfolio empresarial y la cuenta de WhatsApp Business. Meta abrirá su flujo oficial. AutonoGrow no te pedirá ni guardará ningún PIN.</p></div></div>`) : "";
  const availabilityHelp = channel?.status === "not_allowed"
    ? `<div class="ag-alert ag-alert--warning"><div><strong>Canal no disponible</strong><p>Contacta con AutonoGrow si necesitas habilitarlo para este negocio.</p></div></div>`
    : channel?.status === "available" && channel.connector_policy === "owner_only"
      ? `<div class="ag-alert ag-alert--info"><div><strong>Conexión gestionada por AutonoGrow</strong><p>Tu configuración comercial actual no permite iniciar este flujo desde el Business Admin.</p></div></div>` : "";
  const approval = channel?.status === "pending_approval" ? `<div class="ag-alert ag-alert--info"><div><strong>Conectado, pendiente de revisión</strong><p>No necesitas hacer nada más. Conectar una cuenta no activa el envío ni las respuestas automáticas; AutonoGrow revisará la conexión.</p></div></div>` : "";
  const healthMarkup = `<article class="channel-health-card channel-health-card--${healthState.tone}"><div><p>Salud de la conexión</p><h3>${channelHubLoadState.health === "error" ? "No se ha podido comprobar" : healthState.label}</h3><p>${channelHubLoadState.health === "error" ? "Instagram y WhatsApp se cargan de forma independiente. Reintenta solo este diagnóstico." : healthState.message}</p>${health?.last_health_check_at ? `<small>Última comprobación: ${escapeHtml(formatDateTime(health.last_health_check_at))}</small>` : ""}</div></article>`;
  const delivery = name === "whatsapp" ? `<article class="channel-delivery-help"><h3>Cómo puedes responder</h3><p><strong>Envío desde AutonoGrow:</strong> ${escapeHtml(channelCapabilityLabel(channel, "integrated_delivery_enabled"))}.</p><p><strong>Modo asistido:</strong> disponible cuando la conversación tiene teléfono. “Abrir en WhatsApp” prepara el texto, pero la persona completa el envío fuera de AutonoGrow.</p><p>WhatsApp permite respuestas libres durante 24 horas desde el último mensaje del cliente.</p></article>` : "";
  const reconnect = health?.reconnection_required || channel?.status === "revoked" ? `<div class="ag-alert ag-alert--warning"><div><strong>Vuelve a conectar ${title}</strong><p>Volverás a iniciar sesión con Meta. La conexión actual seguirá funcionando hasta que la nueva conexión sea revisada y aprobada.</p></div></div>` : "";
  container.innerHTML = `${availabilityHelp}${onboardingHelp}${approval}${reconnect}<article class="channel-detail-card"><div class="section-header"><div><h3>Estado y capacidades</h3><p>La conexión, la aprobación y cada capacidad se gestionan por separado.</p></div></div>${account}${channelStateRows(channel, health)}</article>${healthMarkup}${delivery}${channelActionMarkup(channel, health, name)}`;
  container.setAttribute("aria-busy", "false");
}

function renderBusinessChannelOnboarding() {
  renderChannelHubNavigation();
  const container = document.getElementById("channel-onboarding-list");
  if (container) {
    container.setAttribute("aria-busy", "false");
    container.innerHTML = channelHubLoadState.onboarding === "error" && !businessChannelOnboarding
      ? `<div class="channel-partial-error"><strong>No se pudieron cargar los canales.</strong><button class="ag-button ag-button--secondary" type="button" data-channel-retry="onboarding">Reintentar</button></div>`
      : ["instagram", "whatsapp"].map(renderChannelOverviewCard).join("");
  }
  const attention = document.getElementById("channel-overview-attention");
  if (attention) {
    const pending = ["instagram", "whatsapp"].flatMap((name) => {
      const channel = channelRecord(name); const health = channelHealthRecord(name); const title = name === "instagram" ? "Instagram" : "WhatsApp";
      if (health?.reconnection_required || channel?.status === "revoked") return [`${title} necesita reconexión.`];
      if (channel?.status === "pending_approval") return [`${title} está pendiente de revisión por AutonoGrow.`];
      return [];
    });
    attention.setAttribute("aria-busy", "false");
    attention.innerHTML = pending.length ? `<div class="ag-alert ag-alert--warning"><div><strong>Requiere atención</strong><ul>${pending.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div></div>` : `<div class="ag-alert ag-alert--success"><div><strong>Sin acciones pendientes</strong><p>Esto no implica que el envío o las respuestas automáticas estén activados; consulta cada capacidad por separado.</p></div></div>`;
  }
  renderChannelDetail("instagram");
  renderChannelDetail("whatsapp");
}

async function loadBusinessChannelOnboarding({ background = false } = {}) {
  if (!document.getElementById("channel-onboarding-list")) return;
  const requestVersion = ++channelOnboardingLoadVersion;
  if (!businessChannelOnboarding) setDashboardDataState("channels", "loading");
  const onboardingRequest = fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/channel-onboarding`);
  const healthRequest = fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/channels/health`);
  const [onboardingResult, healthResult] = await Promise.allSettled([onboardingRequest, healthRequest]);
  if (requestVersion !== channelOnboardingLoadVersion) return;
  const nextOnboarding = onboardingResult.status === "fulfilled" && onboardingResult.value.ok
    ? await onboardingResult.value.json().catch(() => null) : null;
  const nextHealth = healthResult.status === "fulfilled" && healthResult.value.ok
    ? await healthResult.value.json().catch(() => null) : null;
  if (requestVersion !== channelOnboardingLoadVersion) return;
  if (nextOnboarding) businessChannelOnboarding = nextOnboarding;
  if (Array.isArray(nextHealth?.channels)) businessChannelHealth = nextHealth.channels;
  channelHubLoadState.onboarding = nextOnboarding ? "ready" : "error";
  channelHubLoadState.health = Array.isArray(nextHealth?.channels) ? "ready" : "error";
  setDashboardDataState("channels", channelHubLoadState.onboarding === "ready" ? "ready" : "error");
  renderBusinessChannelOnboarding();
  if (conversationAutomation && (!background || !configurationSectionHasDirty("messages"))) renderConversationAutomation();
}

let metaSdkPromise = null;

function isTrustedMetaEventOrigin(origin) {
  try {
    const url = new URL(origin);
    return url.protocol === "https:" && (url.hostname === "facebook.com" || url.hostname.endsWith(".facebook.com"));
  } catch (_error) {
    return false;
  }
}

function isSafeInstagramAuthorizationUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === "www.instagram.com" && url.pathname === "/oauth/authorize" && !url.username && !url.password;
  } catch (_error) {
    return false;
  }
}

function channelFeedbackElement(channel) {
  return document.getElementById(`channel-${channel}-feedback`) || document.getElementById("channel-onboarding-feedback");
}

function safeChannelActionError(channel, action) {
  const title = channel === "instagram" ? "Instagram" : "WhatsApp";
  if (action === "check") return `No se pudo comprobar ${title}. Reinténtalo más tarde.`;
  if (action === "reconnect") return `No se pudo iniciar la reconexión de ${title}. Reinténtalo más tarde.`;
  return `No se pudo iniciar la conexión de ${title}. Reinténtalo más tarde.`;
}

function loadMetaEmbeddedSignupSdk(configuration) {
  if (configuration.sdk_url !== "https://connect.facebook.net/en_US/sdk.js") throw new Error("Configuración pública de Meta no válida.");
  if (metaSdkPromise) return metaSdkPromise;
  metaSdkPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector('script[data-meta-embedded-signup="true"]');
    if (existing && window.FB) { resolve(window.FB); return; }
    const script = existing || document.createElement("script");
    script.async = true;
    script.defer = true;
    script.crossOrigin = "anonymous";
    script.dataset.metaEmbeddedSignup = "true";
    script.src = configuration.sdk_url;
    script.onload = () => window.FB ? resolve(window.FB) : reject(new Error("El SDK oficial de Meta no está disponible."));
    script.onerror = () => reject(new Error("No se pudo cargar el SDK oficial de Meta."));
    if (!existing) document.head.appendChild(script);
  });
  return metaSdkPromise;
}

async function completeWhatsAppEmbeddedSignup(start, eventPayload, authorizationCode) {
  const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/integrations/whatsapp/embedded-signup/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      state: start.state,
      code: authorizationCode || null,
      event_type: eventPayload.type,
      event_name: eventPayload.event,
      meta_business_id: eventPayload.data?.business_id || null,
      waba_id: eventPayload.data?.waba_id || null,
      phone_number_id: eventPayload.data?.phone_number_id || null
    })
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "No se pudo verificar la conexión con Meta.");
  return body;
}

async function launchWhatsAppEmbeddedSignup(purpose = null) {
  const startResponse = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/integrations/whatsapp/embedded-signup/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ purpose })
  });
  const start = await startResponse.json().catch(() => ({}));
  if (!startResponse.ok) throw new Error(start.detail || "No se pudo iniciar WhatsApp Embedded Signup.");
  const configuration = start.public_configuration || {};
  if (!/^\d{6,40}$/.test(String(configuration.app_id || "")) || !/^\d{6,40}$/.test(String(configuration.config_id || "")) || !/^v\d+\.\d+$/.test(String(configuration.graph_api_version || "")) || configuration.event_type !== "WA_EMBEDDED_SIGNUP" || configuration.finish_event !== "FINISH") throw new Error("Configuración pública de Meta no válida.");
  const FB = await loadMetaEmbeddedSignupSdk(configuration);
  FB.init({ appId: configuration.app_id, autoLogAppEvents: true, xfbml: true, version: configuration.graph_api_version });
  return new Promise((resolve, reject) => {
    let authorizationCode = null;
    let signupEvent = null;
    let loginCompleted = false;
    let finished = false;
    const cleanup = () => { window.clearTimeout(timeout); window.removeEventListener("message", onMessage); };
    const finish = async (error) => {
      if (finished) return;
      if (error) { finished = true; cleanup(); reject(error); return; }
      if (!signupEvent) return;
      if (signupEvent.event === "FINISH" && !authorizationCode) {
        if (loginCompleted) finish(new Error("Meta no devolvió el código de autorización."));
        return;
      }
      finished = true;
      cleanup();
      try { resolve(await completeWhatsAppEmbeddedSignup(start, signupEvent, authorizationCode)); }
      catch (completionError) { reject(completionError); }
    };
    const onMessage = (message) => {
      if (!isTrustedMetaEventOrigin(message.origin)) return;
      let payload = message.data;
      if (typeof payload === "string") { try { payload = JSON.parse(payload); } catch (_error) { return; } }
      if (!payload || payload.type !== configuration.event_type || !["FINISH", "CANCEL"].includes(payload.event)) return;
      signupEvent = payload;
      finish();
    };
    const timeout = window.setTimeout(() => finish(new Error("El flujo de Meta tardó demasiado. Inicia un intento nuevo.")), 10 * 60 * 1000);
    window.addEventListener("message", onMessage);
    FB.login((response) => {
      loginCompleted = true;
      authorizationCode = response?.authResponse?.code || null;
      finish();
    }, {
      config_id: configuration.config_id,
      response_type: "code",
      override_default_response_type: true,
      extras: { setup: {} }
    });
  });
}

async function requestBusinessChannelConnection(channel, button) {
  const feedback = channelFeedbackElement(channel);
  const confirmed = window.confirm("Confirmo que soy administrador autorizado de los activos de Meta del negocio.");
  if (!confirmed) return;
  const actionKey = `${channel}:connect`;
  if (channelActionKeys.has(actionKey)) return;
  channelActionKeys.add(actionKey);
  document.querySelectorAll(`[data-channel-request="${channel}"]`).forEach((action) => { action.disabled = true; });
  feedback.textContent = "Estamos preparando la conexión oficial…";
  try {
    if (channel === "instagram") {
      const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/integrations/instagram/oauth/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ purpose: null })
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error("instagram_start_failed");
      if (!isSafeInstagramAuthorizationUrl(body.authorization_url)) throw new Error("instagram_url_invalid");
      window.location.assign(body.authorization_url);
      return;
    }
    if (channel === "whatsapp") {
      feedback.textContent = "Abriendo el flujo oficial de Meta...";
      const result = await launchWhatsAppEmbeddedSignup();
      feedback.textContent = result.status === "candidate_ready" ? "Cuenta verificada. Queda pendiente de revisión por AutonoGrow." : "La conexión no se completó. Inicia un intento nuevo.";
      await loadBusinessChannelOnboarding();
      return;
    }
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/channel-onboarding/${encodeURIComponent(channel)}/request`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm_meta_authority: true })
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error("channel_request_failed");
    feedback.textContent = "Solicitud registrada. Queda pendiente de revisión por AutonoGrow.";
    await loadBusinessChannelOnboarding();
  } catch (_error) {
    feedback.textContent = safeChannelActionError(channel, "connect");
  } finally {
    channelActionKeys.delete(actionKey);
    document.querySelectorAll(`[data-channel-request="${channel}"]`).forEach((action) => { action.disabled = false; });
  }
}

async function handleChannelHealthAction(button) {
  const channel = button.dataset.channel;
  const action = button.dataset.channelHealthAction;
  const feedback = channelFeedbackElement(channel);
  const actionKey = `${channel}:${action}`;
  if (channelActionKeys.has(actionKey)) return;
  channelActionKeys.add(actionKey);
  document.querySelectorAll(`[data-channel="${channel}"][data-channel-health-action]`).forEach((control) => { control.disabled = true; });
  feedback.textContent = action === "check" ? "Estamos comprobando la conexión…" : "Estamos preparando la reconexión oficial…";
  try {
    if (action === "reconnect" && channel === "instagram") {
      const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/channels/instagram/reconnect`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error("instagram_reconnect_failed");
      if (!isSafeInstagramAuthorizationUrl(body.authorization_url)) throw new Error("instagram_url_invalid");
      window.location.assign(body.authorization_url);
      return;
    }
    if (action === "reconnect" && channel === "whatsapp") {
      feedback.textContent = "Abriendo el flujo oficial de Meta...";
      const result = await launchWhatsAppEmbeddedSignup("reconnect");
      feedback.textContent = result.status === "candidate_ready" ? "Nueva conexión pendiente de revisión por AutonoGrow. La anterior no se sustituirá todavía." : "La reconexión no se completó. Inicia un intento nuevo.";
      await loadBusinessChannelOnboarding();
      return;
    }
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/channels/${encodeURIComponent(channel)}/health-check`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error("health_check_failed");
    feedback.textContent = body.created ? "Comprobación solicitada. El estado se actualizará cuando termine." : "Ya existe una comprobación en curso.";
    await loadBusinessChannelOnboarding();
    await requestAdminRefresh(["conversationList", "conversationThread", "operations"]);
  } catch (_error) {
    feedback.textContent = safeChannelActionError(channel, action);
  } finally {
    channelActionKeys.delete(actionKey);
    document.querySelectorAll(`[data-channel="${channel}"][data-channel-health-action]`).forEach((control) => { control.disabled = false; });
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
  document.getElementById("weekly-schedule-editor").setAttribute("aria-busy", "true");
  if (!availabilitySettings) setDashboardDataState("availability", "loading");

  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/${slug}/availability-settings`);

    if (!response.ok) {
      throw new Error("No se pudieron cargar los horarios.");
    }

    availabilitySettings = await response.json();
    setDashboardDataState("availability", "ready");
    renderAvailabilitySettings();
  } catch (error) {
    console.error(error);
    setDashboardDataState("availability", "error");
    document.getElementById("weekly-schedule-editor").innerHTML = `
      <div class="configuration-partial-error" role="alert"><p>No se pudieron cargar los horarios.</p><button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="retry-availability-settings">Reintentar horarios</button></div>
    `;
    document.getElementById("weekly-schedule-editor").setAttribute("aria-busy", "false");
    renderConfigurationOverview();
  }
}

function renderAvailabilitySettings() {
  document.getElementById("availability-timezone").value = availabilitySettings.timezone || "Europe/Madrid";
  document.getElementById("slot-interval-minutes").value = availabilitySettings.slot_interval_minutes || 15;
  document.getElementById("buffer-between-bookings-minutes").value = availabilitySettings.buffer_between_bookings_minutes || 0;
  document.getElementById("min-notice-minutes").value = availabilitySettings.min_notice_minutes || 120;
  document.getElementById("max-days-ahead").value = availabilitySettings.max_days_ahead || 30;
  renderWeeklyScheduleEditor();
  snapshotConfigurationForm("availability");
  renderConfigurationOverview();
}

function renderWeeklyScheduleEditor() {
  const container = document.getElementById("weekly-schedule-editor");
  const schedule = availabilitySettings.weekly_schedule || {};
  container.innerHTML = "";
  container.setAttribute("aria-busy", "false");

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
            <input type="checkbox" aria-label="Marcar ${day.label} como cerrado" ${isClosed ? "checked" : ""} data-admin-change="toggle-day-closed" data-day="${day.value}" />
            <span>${isClosed ? "Cerrado" : "Abierto"}</span>
          </label>
        </div>
        <button class="btn btn-small btn-secondary" type="button" data-admin-action="add-schedule-window" data-day="${day.value}">
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
  updateConfigurationDirtyState("availability");
}

function addScheduleWindow(weekday, start = "10:00", end = "14:00") {
  const schedule = availabilitySettings.weekly_schedule || {};
  schedule[weekday] = schedule[weekday] || [];
  schedule[weekday].push({ start, end });
  availabilitySettings.weekly_schedule = schedule;
  renderWeeklyScheduleEditor();
  updateConfigurationDirtyState("availability");
}

function appendWindowRow(containerId, start = "10:00", end = "14:00") {
  const container = document.getElementById(containerId);
  const row = document.createElement("div");
  row.className = "window-row";
  row.innerHTML = `
    <input type="time" class="window-start" value="${escapeHtml(start)}" />
    <span>hasta</span>
    <input type="time" class="window-end" value="${escapeHtml(end)}" />
    <button class="btn btn-small btn-danger" type="button" data-admin-action="remove-window-row">
      Eliminar
    </button>
  `;
  container.appendChild(row);
}

function removeWindowRow(button) {
  button.closest(".window-row")?.remove();
  availabilitySettings.weekly_schedule = collectWeeklySchedule();
  updateConfigurationDirtyState("availability");
}

function collectWeeklySchedule() {
  const schedule = {};

  WEEKDAYS.forEach((day) => {
    const block = document.querySelector(`.schedule-day[data-weekday="${day.value}"]`);
    const rows = Array.from(block?.querySelectorAll(".window-row") || []);
    schedule[day.value] = rows.map((row) => ({
        start: row.querySelector(".window-start").value,
        end: row.querySelector(".window-end").value
      }));
  });

  return schedule;
}

function validateAvailabilityPayload(payload) {
  const errors = [];
  const limits = [
    ["slot-interval-minutes", payload.slot_interval_minutes, 5, 120, "El inicio de citas debe estar entre 5 y 120 minutos."],
    ["buffer-between-bookings-minutes", payload.buffer_between_bookings_minutes, 0, 240, "El margen entre citas debe estar entre 0 y 240 minutos."],
    ["min-notice-minutes", payload.min_notice_minutes, 0, 10080, "La antelación mínima debe estar entre 0 y 10080 minutos."],
    ["max-days-ahead", payload.max_days_ahead, 1, 365, "El máximo de días debe estar entre 1 y 365."]
  ];
  for (const [id, value, min, max, message] of limits) {
    if (!Number.isInteger(value) || value < min || value > max) errors.push({ field: document.getElementById(id), message });
  }
  for (const day of WEEKDAYS) {
    const windows = payload.weekly_schedule[day.value] || [];
    const sorted = [...windows].sort((left, right) => left.start.localeCompare(right.start));
    sorted.forEach((windowItem, index) => {
      if (!windowItem.start || !windowItem.end || windowItem.start >= windowItem.end) {
        errors.push({ field: document.querySelector(`.schedule-day[data-weekday="${day.value}"] .window-start`), message: `La hora de cierre de ${day.label} debe ser posterior a la de apertura.` });
      } else if (index > 0 && sorted[index - 1].end > windowItem.start) {
        errors.push({ field: document.querySelector(`.schedule-day[data-weekday="${day.value}"] .window-start`), message: `Los tramos de ${day.label} no pueden solaparse.` });
      }
    });
  }
  document.querySelectorAll("[data-config-dirty-key='availability'] [aria-invalid='true']").forEach((field) => field.removeAttribute("aria-invalid"));
  if (errors.length) {
    const summary = document.getElementById("availability-errors");
    summary.hidden = false;
    summary.textContent = errors.map((error) => error.message).join(" ");
    errors.forEach((error) => error.field?.setAttribute("aria-invalid", "true"));
    summary.focus();
    errors[0].field?.focus();
  } else {
    document.getElementById("availability-errors").hidden = true;
  }
  return errors.length === 0;
}

async function saveAvailabilitySettings() {
  const mutationKey = "availability";
  if (configurationMutationKeys.has(mutationKey)) return;
  const slug = getBusinessSlug();
  const feedback = document.getElementById("availability-settings-feedback");
  const button = document.getElementById("save-availability-settings");
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
  if (!validateAvailabilityPayload(payload)) return;
  configurationMutationKeys.add(mutationKey);
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = "Guardando…";
  document.getElementById("availability-save-state").textContent = "Guardando";

  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/${slug}/availability-settings`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      const error = await response.json().catch(() => null);
      throw new Error(safeConfigurationError(error, "No se pudieron guardar los horarios."));
    }

    const result = await response.json();
    availabilitySettings = result.settings;
    setDashboardDataState("availability", "ready");
    renderAvailabilitySettings();
    feedback.className = "inline-feedback success";
    feedback.textContent = "Horarios guardados correctamente.";
    document.getElementById("availability-save-state").textContent = "Guardado";
  } catch (error) {
    console.error(error);
    feedback.className = "inline-feedback error";
    feedback.textContent = error.message || "No se pudieron guardar los horarios.";
    document.getElementById("availability-save-state").textContent = "No se pudo guardar";
  } finally {
    configurationMutationKeys.delete(mutationKey);
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = "Guardar horarios";
  }
}

async function loadAvailabilityExceptions() {
  const slug = getBusinessSlug();
  configurationLoadState.exceptions = "loading";
  document.getElementById("availability-exceptions-list").setAttribute("aria-busy", "true");

  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/${slug}/availability-exceptions`);

    if (!response.ok) {
      throw new Error("No se pudieron cargar las excepciones.");
    }

    const data = await response.json();
    availabilityExceptions = data.exceptions || [];
    configurationLoadState.exceptions = "ready";
    document.getElementById("availability-exceptions-list").setAttribute("aria-busy", "false");
    renderAvailabilityExceptions();
  } catch (error) {
    console.error(error);
    configurationLoadState.exceptions = "error";
    document.getElementById("availability-exceptions-list").setAttribute("aria-busy", "false");
    document.getElementById("availability-exceptions-list").innerHTML = `<div class="configuration-partial-error" role="alert"><p>No se pudieron cargar las excepciones.</p><button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="retry-availability-exceptions">Reintentar excepciones</button></div>`;
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
  updateConfigurationDirtyState("exception");
}

function removeExceptionWindow(index) {
  exceptionDraftWindows.splice(index, 1);
  renderExceptionWindows();
  updateConfigurationDirtyState("exception");
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
      <input type="time" value="${escapeHtml(windowItem.start)}" data-admin-change="update-exception-window" data-index="${index}" data-field="start" />
      <span>hasta</span>
      <input type="time" value="${escapeHtml(windowItem.end)}" data-admin-change="update-exception-window" data-index="${index}" data-field="end" />
      <button class="btn btn-small btn-danger" type="button" data-admin-action="remove-exception-window" data-index="${index}">
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
  updateConfigurationDirtyState("exception");
}

async function saveAvailabilityException() {
  const mutationKey = "exception";
  if (configurationMutationKeys.has(mutationKey)) return;
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

  configurationMutationKeys.add(mutationKey);
  const button = document.getElementById("save-availability-exception");
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = "Guardando…";
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
      throw new Error(safeConfigurationError(error, "No se pudo guardar la excepción."));
    }

    feedback.className = "inline-feedback success";
    feedback.textContent = "Excepción guardada correctamente.";
    document.getElementById("exception-date").value = "";
    document.getElementById("exception-reason").value = "";
    exceptionDraftWindows = [];
    renderExceptionWindows();
    snapshotConfigurationForm("exception");
    await loadAvailabilityExceptions();
  } catch (error) {
    console.error(error);
    feedback.className = "inline-feedback error";
    feedback.textContent = error.message || "No se pudo guardar la excepción.";
  } finally {
    configurationMutationKeys.delete(mutationKey);
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = "Guardar excepción";
  }
}

function renderAvailabilityExceptions() {
  const container = document.getElementById("availability-exceptions-list");

  if (!availabilityExceptions.length) {
    container.innerHTML = `<div class="configuration-empty-state"><strong>Sin excepciones</strong><p>No hay cierres ni horarios especiales configurados.</p><button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="focus-control" data-control="exception-date">Añadir excepción</button></div>`;
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
      <button class="btn btn-small btn-danger" type="button" data-admin-action="delete-availability-exception" data-id="${exception.id}">
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
  document.getElementById("public-page-link").href = `../autonogrow-landing/index.html?b=${encodeURIComponent(getBusinessSlug())}`;
  const publicHref = `../autonogrow-landing/index.html?b=${encodeURIComponent(getBusinessSlug())}`;
  for (const id of ["configuration-public-link", "public-page-preview-link"]) {
    const link = document.getElementById(id);
    if (link) link.href = publicHref;
  }
  if (!allBookings.length) agendaSelectedDate = getMadridDateKey();
  applyOperationalBusinessState(business.status);
  renderDashboard();
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
  if (currentBusiness.logo_url) logo.src = resolveSafeAdminMediaUrl(currentBusiness.logo_url, true);
  document.getElementById("delete-admin-logo").disabled = !currentBusiness.logo_url;
  document.getElementById("public-page-preview-name").textContent = currentBusiness.name || "Tu negocio";
  document.getElementById("public-page-preview-copy").textContent = currentBusiness.headline || currentBusiness.description || "Una estructura funcional con seis estilos visuales.";
  snapshotConfigurationForm("business-info");
  snapshotConfigurationForm("public-page");
  renderConfigurationOverview();
}

function isSafePublicUrl(value) {
  if (!value) return true;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password;
  } catch (_error) {
    return false;
  }
}

function clearBusinessSettingsErrors() {
  const summary = document.getElementById("business-settings-errors");
  summary.hidden = true;
  summary.textContent = "";
  for (const id of ["name", "maps-url", "instagram-url", "reviews-url"]) {
    const error = document.getElementById(`business-setting-${id}-error`);
    if (error) error.textContent = "";
  }
  document.querySelectorAll("#business-settings-errors ~ .business-settings-grid [aria-invalid='true']")
    .forEach((field) => field.removeAttribute("aria-invalid"));
}

function validateBusinessSettings(payload, scope) {
  if (scope === "public-page") {
    const colors = ["primary_color", "secondary_color", "accent_color", "background_color"];
    const invalid = colors.find((field) => !/^#[0-9a-f]{6}$/i.test(payload[field]));
    const summary = document.getElementById("public-page-errors");
    if (!invalid) {
      summary.hidden = true;
      return true;
    }
    summary.hidden = false;
    summary.textContent = "Introduce los colores en formato hexadecimal, por ejemplo #1e90ff.";
    summary.focus();
    const colorName = invalid.replace("_color", "");
    document.getElementById(`business-setting-${colorName}-hex`)?.focus();
    return false;
  }
  clearBusinessSettingsErrors();
  const errors = [];
  if (!payload.name) errors.push({ id: "business-setting-name", message: "El nombre es obligatorio." });
  for (const [field, label] of [["maps_url", "Google Maps"], ["instagram_url", "Instagram"], ["reviews_url", "reseñas"]]) {
    if (!isSafePublicUrl(payload[field])) errors.push({ id: `business-setting-${field.replaceAll("_", "-")}`, message: `Introduce un enlace válido de ${label} que empiece por http:// o https://.` });
  }
  for (const error of errors) {
    const field = document.getElementById(error.id);
    field?.setAttribute("aria-invalid", "true");
    document.getElementById(`${error.id}-error`).textContent = error.message;
  }
  if (errors.length) {
    const summary = document.getElementById("business-settings-errors");
    summary.hidden = false;
    summary.textContent = `${errors.length === 1 ? "Revisa este campo" : `Revisa estos ${errors.length} campos`}: ${errors.map((error) => error.message).join(" ")}`;
    summary.focus();
    document.getElementById(errors[0].id)?.focus();
  }
  return errors.length === 0;
}

async function saveBusinessSettings(scope = "business") {
  const mutationKey = "business-settings";
  if (configurationMutationKeys.has(mutationKey)) return;
  const isPublicPage = scope === "public-page";
  const feedback = document.getElementById(isPublicPage ? "admin-brand-feedback" : "business-settings-feedback");
  const button = document.getElementById(isPublicPage ? "save-public-page-settings" : "save-business-settings");
  const state = document.getElementById(isPublicPage ? "public-page-save-state" : "business-settings-save-state");
  const otherKey = isPublicPage ? "business-info" : "public-page";
  if (configurationDirtyKeys.has(otherKey)) {
    feedback.className = "inline-feedback error";
    feedback.textContent = isPublicPage
      ? "Hay cambios pendientes en Información. Guárdalos o revísalos antes de guardar la Página pública."
      : "Hay cambios pendientes en Página pública. Guárdalos o revísalos antes de guardar Información.";
    return;
  }
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

  if (!validateBusinessSettings(payload, isPublicPage ? "public-page" : "business")) return;

  configurationMutationKeys.add(mutationKey);
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = "Guardando…";
  state.textContent = "Guardando";
  feedback.className = "inline-feedback";
  feedback.textContent = "Guardando…";

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
      throw new Error(safeConfigurationError(result, "No se han podido guardar los cambios."));
    }

    currentBusiness = result.settings;
    applyBusinessData(currentBusiness);
    renderBusinessSettings();
    feedback.className = "inline-feedback success";
    feedback.textContent = "Guardado correctamente.";
    state.textContent = "Guardado";
  } catch (error) {
    console.error(error);
    feedback.className = "inline-feedback error";
    feedback.textContent = typeof error?.message === "string" ? error.message : "No se han podido guardar los cambios. Revísalos e inténtalo de nuevo.";
    state.textContent = "No se pudo guardar";
  } finally {
    configurationMutationKeys.delete(mutationKey);
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = isPublicPage ? "Guardar página pública" : "Guardar cambios";
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

function safeConfigurationError(body, fallback) {
  const candidate = typeof body?.message === "string"
    ? body.message
    : typeof body?.detail === "string" ? body.detail : "";
  if (!candidate || candidate.length > 300 || /^[a-z0-9_]+$/i.test(candidate) || /traceback|exception|payload|sql|token/i.test(candidate)) return fallback;
  return candidate;
}

function adminMediaError(action, response, body) {
  console.error("Error de media", { action, status: response.status });
  const detail = typeof body?.detail === "string" ? body.detail : "";
  const safeDetail = /^(Solo se permiten|El archivo está vacío|La imagen supera|El contenido del archivo|Máximo 10 imágenes)/.test(detail)
    ? ` ${detail}.`
    : "";
  return `No se pudo ${action}.${safeDetail}`;
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
  const mutationKey = `media-${kind}`;
  if (configurationMutationKeys.has(mutationKey)) return;
  if (kind === "logo" && ["business-info", "public-page"].some((key) => configurationDirtyKeys.has(key))) {
    showAdminBrandFeedback("Guarda primero los cambios de Información o Página pública antes de subir el logo.", true);
    input.value = "";
    return;
  }
  if (kind === "gallery" && [...configurationDirtyKeys].some((key) => key.startsWith("gallery-"))) {
    showAdminBrandFeedback("Guarda o revisa primero las fotos modificadas antes de subir otra.", true);
    input.value = "";
    return;
  }
  const file = input.files?.[0];
  if (!file) {
    showAdminBrandFeedback("Selecciona una imagen JPG, PNG o WEBP.", true);
    return;
  }
  if (!new Set(["image/jpeg", "image/png", "image/webp"]).has(file.type)) {
    showAdminBrandFeedback("Solo se permiten imágenes JPG, PNG o WEBP.", true);
    input.value = "";
    return;
  }
  const form = new FormData(); form.append("file", input.files[0]);
  if (kind === "gallery") form.append("alt_text", document.getElementById("admin-gallery-alt").value.trim());
  const action = kind === "logo" ? "subir el logo" : "subir la foto";
  const url = `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/media/${kind}`;
  const button = document.getElementById(kind === "logo" ? "upload-admin-logo" : "upload-admin-gallery");
  configurationMutationKeys.add(mutationKey);
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = "Subiendo…";
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
  } finally {
    configurationMutationKeys.delete(mutationKey);
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = kind === "logo" ? "Subir/cambiar" : "Subir foto";
  }
}

async function deleteAdminLogo() {
  if (configurationMutationKeys.has("media-logo-delete")) return;
  if (["business-info", "public-page"].some((key) => configurationDirtyKeys.has(key))) {
    showAdminBrandFeedback("Guarda primero los cambios de Información o Página pública antes de eliminar el logo.", true);
    return;
  }
  if (!window.confirm("¿Eliminar el logo de la página pública?")) return;
  const url = `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/media/logo`;
  const button = document.getElementById("delete-admin-logo");
  configurationMutationKeys.add("media-logo-delete");
  button.disabled = true;
  try {
    const response = await fetch(url, { method: "DELETE" });
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(adminMediaError("eliminar el logo", response, body));
    await reloadAdminBusiness();
    showAdminBrandFeedback("Logo eliminado.");
  } catch (error) {
    console.error("Fallo eliminando logo en Admin", { url, error });
    showAdminBrandFeedback(error.message, true);
  } finally {
    configurationMutationKeys.delete("media-logo-delete");
    button.disabled = false;
  }
}

async function loadAdminGallery() {
  configurationLoadState.gallery = "loading";
  document.getElementById("admin-gallery-list")?.setAttribute("aria-busy", "true");
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/media/gallery`);
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(adminMediaError("cargar la galería", response, body));
    configurationLoadState.gallery = "ready";
    adminGallery = body.images || [];
    const gallery = document.getElementById("admin-gallery-list");
    gallery.setAttribute("aria-busy", "false");
    gallery.innerHTML = adminGallery.map((image) => `<article data-config-dirty-key="gallery-${image.id}"><img src="${escapeHtml(resolveSafeAdminMediaUrl(image.url, true))}" alt="${escapeHtml(image.alt_text || "Foto")}"><label>Texto alternativo<input data-alt-id="${image.id}" value="${escapeHtml(image.alt_text || "")}"></label><label>Orden<input data-position-id="${image.id}" type="number" min="0" value="${image.position}"></label><button class="btn btn-secondary" type="button" data-toggle-image="${image.id}" data-active="${!image.active}">${image.active ? "Desactivar" : "Activar"}</button><button class="btn btn-danger" type="button" data-delete-image="${image.id}">Eliminar</button></article>`).join("") || `<div class="configuration-empty-state"><strong>Sin imágenes</strong><p>Añade una foto si quieres mostrar una galería en tu página pública.</p></div>`;
    snapshotConfigurationForms("#admin-gallery-list [data-config-dirty-key]");
  } catch (error) {
    console.error(error);
    configurationLoadState.gallery = "error";
    document.getElementById("admin-gallery-list")?.setAttribute("aria-busy", "false");
    showAdminBrandFeedback(error.message || "No se pudo cargar la galería.", true);
    document.getElementById("admin-gallery-list").innerHTML = `<div class="configuration-partial-error" role="alert"><p>No se pudo cargar la galería. Puedes seguir editando el resto de la página.</p><button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="retry-gallery">Reintentar galería</button></div>`;
  }
  renderConfigurationOverview();
}

async function updateAdminGalleryImage(event) {
  const button = event.target.closest("button"); if (!button) return;
  const id = button.dataset.toggleImage || button.dataset.deleteImage; if (!id) return;
  const mutationKey = `gallery-${id}`;
  if (configurationMutationKeys.has(mutationKey)) return;
  if ([...configurationDirtyKeys].some((key) => key.startsWith("gallery-") && key !== mutationKey)) {
    showAdminBrandFeedback("Guarda o revisa primero las otras fotos modificadas.", true);
    return;
  }
  if (button.dataset.deleteImage && !window.confirm("¿Eliminar esta foto de la página pública?")) return;
  const url = `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/media/gallery/${id}`;
  configurationMutationKeys.add(mutationKey);
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
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
  } finally {
    configurationMutationKeys.delete(mutationKey);
    if (button.isConnected) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  }
}

function showAdminBrandFeedback(message, error = false) { const el = document.getElementById("admin-brand-feedback"); el.textContent = message; el.className = `inline-feedback ${error ? "error" : "success"}`; }

async function loadAdminServices() {
  const container = document.getElementById("admin-services-list");
  container.setAttribute("aria-busy", "true");
  if (!adminServices.length) setDashboardDataState("services", "loading");
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/services`
    );
    if (!response.ok) {
      throw new Error("No se pudieron cargar los servicios.");
    }
    const data = await response.json();
    adminServices = data.services || [];
    setDashboardDataState("services", "ready");
    container.setAttribute("aria-busy", "false");
    renderAdminServices();
    syncAgendaServiceFilter();
    if (staffMembers.length && ![...configurationDirtyKeys].some((key) => configurationCategoryForKey(key) === "staff")) renderStaffMembers();
  } catch (error) {
    console.error(error);
    setDashboardDataState("services", "error");
    container.setAttribute("aria-busy", "false");
    container.innerHTML = `<div class="configuration-partial-error" role="alert"><p>No se pudieron cargar los servicios.</p><button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="retry-services">Reintentar servicios</button></div>`;
    renderConfigurationOverview();
  }
}

function renderAdminServices() {
  const container = document.getElementById("admin-services-list");
  document.getElementById("stat-services-active").textContent =
    adminServices.filter((service) => service.active).length;
  if (!adminServices.length) {
    container.innerHTML = `<div class="configuration-empty-state"><strong>Sin servicios</strong><p>Todavía no has añadido servicios. Añade el primero para que tus clientes puedan reservar.</p><button class="ag-button ag-button--primary ag-button--small" type="button" data-admin-action="focus-control" data-control="new-service-name">Añadir el primer servicio</button></div>`;
    ensureConfigurationSnapshot("service-new");
    renderConfigurationOverview();
    return;
  }

  container.innerHTML = adminServices.map((service) => {
    const professionals = staffMembers.filter((member) => member.active && (member.service_ids || []).includes(service.id)).length;
    return `
    <article class="admin-service-item ${service.active ? "" : "inactive"}" data-service-id="${service.id}" data-config-dirty-key="service-${service.id}" data-initial-active="${service.active}">
      <header class="configuration-item-header"><div><h3>${escapeHtml(service.name)}</h3><p>${service.duration_minutes} min${service.price_text ? ` · ${escapeHtml(service.price_text)}` : ""} · ${professionals} ${professionals === 1 ? "profesional" : "profesionales"}</p></div><span class="configuration-status ${service.active ? "configuration-status--complete" : "configuration-status--review"}">${service.active ? "Activo" : "Inactivo"}</span></header>
      <div class="service-edit-grid">
        <label>Nombre<input class="service-name" type="text" value="${escapeHtml(service.name)}" aria-describedby="service-${service.id}-name-error" /><small id="service-${service.id}-name-error" class="ag-field-error"></small></label>
        <label>Precio<input class="service-price" type="text" value="${escapeHtml(service.price_text || "")}" /></label>
        <label>Duración<input class="service-duration" type="number" min="1" max="1440" value="${service.duration_minutes || ""}" aria-describedby="service-${service.id}-duration-error" /><small id="service-${service.id}-duration-error" class="ag-field-error"></small></label>
        <label class="field-wide">Descripción<textarea class="service-description" rows="2">${escapeHtml(service.description || "")}</textarea></label>
        <label class="active-setting"><input class="service-active" type="checkbox" ${service.active ? "checked" : ""} />Activo</label>
        <fieldset class="service-follow-up field-wide"><legend>Seguimiento del cliente</legend><label class="active-setting"><input class="service-follow-up-enabled" type="checkbox" ${service.follow_up_enabled ? "checked" : ""} /> Recomendar que el cliente vuelva después de este servicio</label><label>Volver aproximadamente en<input class="service-follow-up-interval" type="number" min="1" max="3650" value="${service.follow_up_interval_days || ""}" /><small>Días desde la cita completada.</small></label><label>Ventana opcional<input class="service-follow-up-window" type="number" min="0" max="365" value="${service.follow_up_window_days ?? 0}" /><small>Días antes y después.</small></label></fieldset>
      </div>
      <p class="configuration-impact-note">Al desactivar un servicio dejará de ofrecerse para nuevas reservas; las reservas existentes se conservan.</p>
      <div class="settings-actions"><span class="configuration-item-save-state">Sin cambios</span><button class="btn btn-small btn-secondary" data-save-service type="button" data-admin-action="save-service" data-id="${service.id}">Guardar servicio</button></div>
    </article>
  `; }).join("");
  ensureConfigurationSnapshot("service-new");
  snapshotConfigurationForms("#admin-services-list [data-config-dirty-key]");
  renderConfigurationOverview();
}

function readServiceForm(container) {
  return {
    name: container.querySelector(".service-name").value.trim(),
    description: container.querySelector(".service-description").value.trim(),
    price_text: container.querySelector(".service-price").value.trim(),
    duration_minutes: Number(container.querySelector(".service-duration").value),
    active: container.querySelector(".service-active").checked,
    follow_up_enabled: container.querySelector(".service-follow-up-enabled").checked,
    follow_up_interval_days: container.querySelector(".service-follow-up-interval").value ? Number(container.querySelector(".service-follow-up-interval").value) : null,
    follow_up_window_days: Number(container.querySelector(".service-follow-up-window").value || 0)
  };
}

function validateServicePayload(payload, container) {
  container?.querySelectorAll("[aria-invalid='true']").forEach((field) => field.removeAttribute("aria-invalid"));
  container?.querySelectorAll(".ag-field-error").forEach((error) => { error.textContent = ""; });
  if (!payload.name) {
    const field = container?.querySelector(".service-name, #new-service-name");
    field?.setAttribute("aria-invalid", "true");
    const error = container?.querySelector("[id$='name-error']");
    if (error) error.textContent = "El nombre del servicio es obligatorio.";
    throw new Error("El nombre del servicio es obligatorio.");
  }
  if (!Number.isInteger(payload.duration_minutes) || payload.duration_minutes < 1 || payload.duration_minutes > 1440) {
    const field = container?.querySelector(".service-duration, #new-service-duration");
    field?.setAttribute("aria-invalid", "true");
    const error = container?.querySelector("[id$='duration-error']");
    if (error) error.textContent = "Introduce una duración válida entre 1 y 1440 minutos.";
    throw new Error("Introduce una duración válida entre 1 y 1440 minutos.");
  }
  if (payload.follow_up_enabled && (!Number.isInteger(payload.follow_up_interval_days) || payload.follow_up_interval_days < 1 || payload.follow_up_interval_days > 3650)) {
    throw new Error("Indica cada cuántos días conviene que vuelva el cliente.");
  }
  if (!Number.isInteger(payload.follow_up_window_days) || payload.follow_up_window_days < 0 || payload.follow_up_window_days > 365) {
    throw new Error("La ventana de seguimiento debe estar entre 0 y 365 días.");
  }
}

async function saveAdminService(serviceId) {
  const mutationKey = `service-${serviceId}`;
  if (configurationMutationKeys.has(mutationKey)) return;
  const feedback = document.getElementById("services-feedback");
  const otherDirtyService = [...configurationDirtyKeys].find((key) => configurationCategoryForKey(key) === "services" && key !== mutationKey);
  if (otherDirtyService) {
    feedback.className = "inline-feedback error";
    feedback.textContent = "Guarda o revisa los otros cambios de Servicios antes de continuar.";
    return;
  }
  const container = document.querySelector(`[data-service-id="${serviceId}"]`);
  const button = container?.querySelector("[data-save-service]");
  try {
    const payload = readServiceForm(container);
    validateServicePayload(payload, container);
    if (container.dataset.initialActive === "true" && !payload.active && !window.confirm("Este servicio dejará de ofrecerse para nuevas reservas y desaparecerá del catálogo público. Las reservas existentes se conservarán. ¿Continuar?")) return;
    configurationMutationKeys.add(mutationKey);
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.textContent = "Guardando…";
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
      throw new Error(safeConfigurationError(result, "No se pudo guardar el servicio."));
    }
    feedback.className = "inline-feedback success";
    feedback.textContent = "Servicio guardado correctamente.";
    await loadAdminServices();
  } catch (error) {
    console.error(error);
    feedback.className = "inline-feedback error";
    feedback.textContent = error.message || "No se pudo guardar el servicio.";
    document.getElementById("services-errors").hidden = false;
    document.getElementById("services-errors").textContent = feedback.textContent;
    document.getElementById("services-errors").focus();
    container?.querySelector("[aria-invalid='true']")?.focus();
  } finally {
    configurationMutationKeys.delete(mutationKey);
    if (button?.isConnected) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.textContent = "Guardar servicio";
    }
  }
}

async function createAdminService() {
  const mutationKey = "service-new";
  if (configurationMutationKeys.has(mutationKey)) return;
  const feedback = document.getElementById("services-feedback");
  if ([...configurationDirtyKeys].some((key) => configurationCategoryForKey(key) === "services" && key !== mutationKey)) {
    feedback.className = "inline-feedback error";
    feedback.textContent = "Guarda o revisa los servicios modificados antes de crear otro.";
    return;
  }
  const button = document.getElementById("create-service");
  const payload = {
    name: document.getElementById("new-service-name").value.trim(),
    description: document.getElementById("new-service-description").value.trim(),
    price_text: document.getElementById("new-service-price").value.trim(),
    duration_minutes: Number(document.getElementById("new-service-duration").value),
    active: true,
    follow_up_enabled: document.getElementById("new-service-follow-up-enabled").checked,
    follow_up_interval_days: document.getElementById("new-service-follow-up-interval").value ? Number(document.getElementById("new-service-follow-up-interval").value) : null,
    follow_up_window_days: Number(document.getElementById("new-service-follow-up-window").value || 0)
  };

  try {
    validateServicePayload(payload, configurationFormElement(mutationKey));
    configurationMutationKeys.add(mutationKey);
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.textContent = "Creando…";
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
      throw new Error(safeConfigurationError(result, "No se pudo crear el servicio."));
    }

    ["new-service-name", "new-service-description", "new-service-price", "new-service-duration", "new-service-follow-up-interval"]
      .forEach((id) => { document.getElementById(id).value = ""; });
    document.getElementById("new-service-follow-up-enabled").checked = false;
    document.getElementById("new-service-follow-up-window").value = "0";
    snapshotConfigurationForm("service-new");
    feedback.className = "inline-feedback success";
    feedback.textContent = "Servicio creado correctamente.";
    await loadAdminServices();
  } catch (error) {
    console.error(error);
    feedback.className = "inline-feedback error";
    feedback.textContent = error.message || "No se pudo crear el servicio.";
    document.getElementById("services-errors").hidden = false;
    document.getElementById("services-errors").textContent = feedback.textContent;
    document.getElementById("services-errors").focus();
    configurationFormElement(mutationKey)?.querySelector("[aria-invalid='true']")?.focus();
  } finally {
    configurationMutationKeys.delete(mutationKey);
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = "Crear servicio";
  }
}

async function loadStaffMembers() {
  const container = document.getElementById("admin-staff-list");
  container.setAttribute("aria-busy", "true");
  configurationLoadState.staff = "loading";
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/staff`);
    if (!response.ok) throw new Error("No se pudo cargar el equipo.");
    const data = await response.json();
    staffMembers = data.staff || [];
    configurationLoadState.staff = "ready";
    container.setAttribute("aria-busy", "false");
    renderStaffMembers();
    const filter = document.getElementById("booking-staff-filter");
    filter.innerHTML = `<option value="">Todos</option>` + staffMembers
      .filter((member) => member.active)
      .map((member) => `<option value="${member.id}">${escapeHtml(member.public_name || member.name || member.email)}</option>`)
      .join("");
    filter.value = selectedStaffFilter;
  } catch (error) {
    console.error(error);
    configurationLoadState.staff = "error";
    container.setAttribute("aria-busy", "false");
    container.innerHTML = `<div class="configuration-partial-error" role="alert"><p>No se pudo cargar el equipo. El resto de la configuración sigue disponible.</p><button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="retry-staff">Reintentar equipo</button></div>`;
    renderConfigurationOverview();
  }
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
    document.querySelector('[data-admin-section="summary"] .dashboard-metrics')?.after(panel);
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
      ? `<button class="btn btn-small btn-danger" type="button" data-admin-action="remove-staff" data-id="${member.id}"
          ${isOnlyActiveAdmin ? 'disabled title="No puedes eliminar al único administrador activo"' : ""}>
          Eliminar del equipo
        </button>
        ${isOnlyActiveAdmin ? '<small class="staff-admin-protection">Añade otro administrador activo antes de eliminar este perfil.</small>' : ""}`
      : "";
    return `
    <article class="admin-service-item staff-member-card" data-staff-id="${member.id}" data-config-dirty-key="staff-${member.id}">
      <header class="configuration-item-header"><div><h3>${escapeHtml(member.public_name || member.name || member.email)}</h3><p>${member.bookable ? `${(member.service_ids || []).length} servicios asignados` : "Acceso al panel, no reservable"}</p></div><span class="configuration-status configuration-status--complete">Activo</span></header>
      <div class="service-edit-grid">
        <label>Email<input value="${escapeHtml(member.email)}" disabled /></label>
        <label>Nombre público<input class="staff-public-name" value="${escapeHtml(member.public_name || "")}" /></label>
        <label>Rol de acceso<select class="staff-role"><option value="business_staff" ${member.role === "business_staff" ? "selected" : ""}>Personal</option><option value="business_admin" ${member.role === "business_admin" ? "selected" : ""}>Administrador</option></select></label>
        <label class="active-setting"><input class="staff-active" type="checkbox" checked disabled />Activo</label>
        <label class="active-setting"><input class="staff-bookable" type="checkbox" ${member.bookable ? "checked" : ""} data-admin-change="toggle-staff-services" data-id="${member.id}" />Reservable</label>
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
        <span class="configuration-item-save-state">Sin cambios</span>
        <button class="btn btn-small btn-primary" type="button" data-admin-action="save-staff" data-id="${member.id}">Guardar ficha</button>
        <button class="btn btn-small btn-secondary" type="button" data-admin-action="edit-staff-schedule" data-id="${member.id}">Editar horario</button>
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
      ${canRemoveMembers ? `<button class="btn btn-small btn-secondary" type="button" data-admin-action="reactivate-staff" data-id="${member.id}">Reactivar</button>` : ""}
    </article>
  `).join("") || `<p class="empty-state">No hay miembros inactivos.</p>`;
  if (!activeMembers.length) {
    container.innerHTML = `<div class="configuration-empty-state"><strong>Sin profesionales activos</strong><p>Añade un miembro si necesitas asignar servicios y horarios por profesional.</p><button class="ag-button ag-button--primary ag-button--small" type="button" data-admin-action="focus-control" data-control="new-staff-email">Añadir miembro</button></div>`;
  }
  ensureConfigurationSnapshot("staff-new");
  snapshotConfigurationForms("#admin-staff-list [data-config-dirty-key]");
  renderConfigurationOverview();
}

function toggleStaffServiceControls(memberId, enabled) {
  const fieldset = document.querySelector(
    `[data-staff-id="${memberId}"] .staff-services-field`
  );
  if (fieldset) fieldset.disabled = !enabled;
}

function formatStaffRemovedAt(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Fecha no disponible";
  return date.toLocaleString("es-ES", { dateStyle: "medium", timeStyle: "short" });
}

async function createStaffMember() {
  const mutationKey = "staff-new";
  if (configurationMutationKeys.has(mutationKey)) return;
  const feedback = document.getElementById("staff-feedback");
  if ([...configurationDirtyKeys].some((key) => configurationCategoryForKey(key) === "staff" && key !== mutationKey)) {
    feedback.className = "inline-feedback error";
    feedback.textContent = "Guarda o revisa las fichas modificadas antes de añadir otro miembro.";
    return;
  }
  const button = document.getElementById("create-staff-member");
  const payload = {
    email: document.getElementById("new-staff-email").value.trim(),
    role: document.getElementById("new-staff-role").value,
    public_name: document.getElementById("new-staff-public-name").value.trim() || null,
    bookable: document.getElementById("new-staff-bookable").checked,
    show_schedule: true,
    active: true
  };
  if (!/^\S+@\S+\.\S+$/.test(payload.email)) {
    document.getElementById("staff-errors").hidden = false;
    document.getElementById("staff-errors").textContent = "Introduce un email válido para dar acceso al miembro.";
    document.getElementById("staff-errors").focus();
    document.getElementById("new-staff-email").focus();
    return;
  }
  configurationMutationKeys.add(mutationKey);
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = "Añadiendo…";
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/staff`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
    });
    const result = await response.json().catch(() => null);
    if (!response.ok) throw new Error(safeConfigurationError(result, "No se pudo añadir el miembro."));
    document.getElementById("new-staff-email").value = "";
    document.getElementById("new-staff-public-name").value = "";
    document.getElementById("new-staff-role").value = "business_staff";
    document.getElementById("new-staff-bookable").checked = false;
    snapshotConfigurationForm("staff-new");
    feedback.className = "inline-feedback success";
    feedback.textContent = "Miembro añadido.";
    await loadStaffMembers();
  } catch (error) {
    feedback.className = "inline-feedback error";
    feedback.textContent = error.message;
  } finally {
    configurationMutationKeys.delete(mutationKey);
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = "Añadir miembro";
  }
}

async function saveStaffMember(memberId) {
  const mutationKey = `staff-${memberId}`;
  if (configurationMutationKeys.has(mutationKey)) return;
  const card = document.querySelector(`[data-staff-id="${memberId}"]`);
  const otherDirtyStaff = [...configurationDirtyKeys].find((key) => configurationCategoryForKey(key) === "staff" && key !== mutationKey);
  if (otherDirtyStaff) {
    const feedback = document.getElementById("staff-feedback");
    feedback.className = "inline-feedback error";
    feedback.textContent = "Guarda o revisa las otras fichas modificadas antes de continuar.";
    return;
  }
  const button = [...card.querySelectorAll("button")].find((item) => item.textContent.includes("Guardar ficha"));
  const payload = {
    public_name: card.querySelector(".staff-public-name").value.trim() || null,
    role: card.querySelector(".staff-role").value,
    bookable: card.querySelector(".staff-bookable").checked,
    show_schedule: card.querySelector(".staff-show-schedule").checked,
    bio: card.querySelector(".staff-bio").value.trim() || null
  };
  const serviceIds = [...card.querySelectorAll(".staff-service-checkbox:checked")]
    .map((input) => Number(input.value));
  configurationMutationKeys.add(mutationKey);
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = "Guardando…";
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/staff/${memberId}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
    });
    const result = await response.json().catch(() => null);
    if (!response.ok) throw new Error(safeConfigurationError(result, "No se pudo guardar la ficha."));

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
          safeConfigurationError(servicesResult, "La ficha se guardó, pero no se pudieron asignar los servicios.")
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
  } finally {
    configurationMutationKeys.delete(mutationKey);
    if (button?.isConnected) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.textContent = "Guardar ficha";
    }
  }
}

async function reactivateStaffMember(memberId) {
  const feedback = document.getElementById("staff-feedback");
  if ([...configurationDirtyKeys].some((key) => configurationCategoryForKey(key) === "staff")) {
    feedback.className = "inline-feedback error";
    feedback.textContent = "Guarda o revisa los cambios pendientes del Equipo antes de reactivar un miembro.";
    return;
  }
  const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/staff/${memberId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ active: true })
  });
  const result = await response.json().catch(() => null);
  if (!response.ok) {
    feedback.className = "inline-feedback error";
    feedback.textContent = safeConfigurationError(result, "No se pudo reactivar al miembro.");
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
  if ([...configurationDirtyKeys].some((key) => configurationCategoryForKey(key) === "staff")) {
    const feedback = document.getElementById("staff-feedback");
    feedback.className = "inline-feedback error";
    feedback.textContent = "Guarda o revisa los cambios pendientes del Equipo antes de eliminar un miembro.";
    return;
  }
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
    if (!response.ok) throw new Error(safeConfigurationError(result, "No se pudo eliminar al miembro del equipo."));
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
  staffRemovalReturnFocus = document.activeElement;
  const bookings = result.bookings || [];
  document.getElementById("staff-removal-modal-title").textContent = `No se puede eliminar a ${member.public_name || member.name || member.email}`;
  document.getElementById("staff-removal-modal-message").textContent = result.message || "Gestiona primero las citas asignadas.";
  document.getElementById("staff-removal-bookings").innerHTML = bookings.map((booking) => `
    <article class="staff-removal-booking">
      <div>
        <strong>${escapeHtml(formatBlockingBookingDate(booking.date, booking.start_time))}</strong>
        <span>${escapeHtml(booking.customer_name)}</span>
        <span>${escapeHtml(booking.service_name)} · ${escapeHtml(getStatusLabel(booking.status))}</span>
      </div>
      <button class="btn btn-small btn-primary" type="button" data-admin-action="go-to-booking" data-id="${booking.id}">Ir a la cita</button>
    </article>
  `).join("");
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-scroll-locked");
  window.requestAnimationFrame(() => modal.querySelector(".ag-modal__close")?.focus());
}

function closeStaffRemovalModal() {
  const modal = document.getElementById("staff-removal-modal");
  if (!modal?.classList.contains("open")) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
  document.body.classList.remove("modal-scroll-locked");
  const returnFocus = staffRemovalReturnFocus;
  staffRemovalReturnFocus = null;
  if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
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
    openBookingDetails: new Set([...document.querySelectorAll(".agenda-booking-details[open]")].map((details) => String(details.closest("[data-booking-id]")?.dataset.bookingId || ""))),
    openInternalNotes: new Set([...document.querySelectorAll("[data-internal-notes-details][open]")].map((details) => String(details.dataset.internalNotesDetails))),
    focusedBookingId: active ? String(active.dataset.internalNotes) : null,
    selectionStart: active?.selectionStart,
    selectionEnd: active?.selectionEnd,
    scrollX: window.scrollX,
    scrollY: window.scrollY
  };
}

function restoreBookingEditorState(state) {
  if (!state) return;
  state.openBookingDetails?.forEach((bookingId) => {
    document.querySelector(`[data-booking-id="${bookingId}"] .agenda-booking-details`)?.setAttribute("open", "");
  });
  state.openInternalNotes?.forEach((bookingId) => {
    document.querySelector(`[data-internal-notes-details="${bookingId}"]`)?.setAttribute("open", "");
  });
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
  const loadVersion = ++bookingsLoadVersion;
  if (!background && !allBookings.length) {
    setDashboardDataState("bookings", "loading");
    list.setAttribute("aria-busy", "true");
    list.innerHTML = `<div class="ag-skeleton ag-skeleton--card" aria-hidden="true"></div><span class="ag-visually-hidden">Cargando reservas.</span>`;
  }

  try {
    const center = agendaSelectedDate || getMadridDateKey();
    const range = new URLSearchParams({
      from: addDaysToDateKey(center, -31),
      to: addDaysToDateKey(center, 31)
    });
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${slug}/bookings?${range.toString()}`);

    if (!response.ok) throw new Error("No se pudieron cargar las reservas.");

    const data = await response.json();
    if (loadVersion !== bookingsLoadVersion) return;
    const previousBookings = new Map(allBookings.map((booking) => [booking.id, booking]));
    const loadedBookings = (data.bookings || []).map((booking) => ({
      ...booking,
      attachments: background
        ? (previousBookings.get(booking.id)?.attachments || [])
        : (booking.attachments || [])
    }));
    const loadedIds = new Set(loadedBookings.map((booking) => booking.id));
    allBookings = [
      ...loadedBookings,
      ...allBookings.filter((booking) => !loadedIds.has(booking.id))
    ];
    setDashboardDataState("bookings", "ready");

    if (!background && isBusinessStaff()) {
      reviewRequestsByBooking = new Map();
      await enrichBookingsWithAttachments();
    } else if (!background) {
      await Promise.allSettled([enrichBookingsWithAttachments(), loadReviewRequests()]);
    }
    if (loadVersion !== bookingsLoadVersion) return;
    const nextFingerprint = JSON.stringify(allBookings);
    const changed = nextFingerprint !== bookingsFingerprint;
    bookingsFingerprint = nextFingerprint;
    if (!changed && background) return;
    const editorState = background ? captureBookingEditorState() : null;
    syncAgendaServiceFilter();
    renderStats(allBookings);
    renderReviewStats();
    renderReviewRequests();
    renderBookings();
    if (selectedConversation) renderConversationCustomerPanel(selectedConversation);
    const requestedBookingId = Number(new URLSearchParams(window.location.search).get("booking"));
    if (!background && Number.isInteger(requestedBookingId) && requestedBookingId > 0) {
      goToBooking(requestedBookingId, false);
    }
    restoreBookingEditorState(editorState);
    if (!isBusinessStaff()) renderGrowth();
  } catch (error) {
    if (loadVersion !== bookingsLoadVersion) return;
    console.error(error);
    if (background) throw error;
    if (!allBookings.length) {
      setDashboardDataState("bookings", "error");
      list.setAttribute("aria-busy", "false");
      list.innerHTML = `<div class="agenda-state agenda-state--error" role="alert"><strong>No pudimos cargar la agenda.</strong><p>Comprueba la conexión y vuelve a intentarlo.</p><button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="retry-bookings">Reintentar</button></div>`;
    }
  }
}

async function loadBookingCloseTasks({ background = false } = {}) {
  const loadVersion = ++bookingCloseTasksLoadVersion;
  if (!background && !bookingCloseTasks.length) {
    setDashboardDataState("closeTasks", "loading");
  }
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/booking-close-tasks`);
    if (!response.ok) throw new Error("No se pudieron cargar las citas pendientes de cerrar.");
    const data = await response.json();
    if (loadVersion !== bookingCloseTasksLoadVersion) return;
    bookingCloseTasks = data.tasks || [];
    setDashboardDataState("closeTasks", "ready");
  } catch (error) {
    if (loadVersion !== bookingCloseTasksLoadVersion) return;
    console.error(error);
    if (!background || !bookingCloseTasks.length) setDashboardDataState("closeTasks", "error");
    if (background) throw error;
  }
}

async function loadReviewRequests({ background = false } = {}) {
  const requestVersion = ++reviewRequestsLoadVersion;
  if (!reviewRequestsByBooking.size) growthLoadState.reviews = "loading";
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/review-requests`);
    if (!response.ok) throw new Error("review_requests_unavailable");
    const data = await response.json();
    if (requestVersion !== reviewRequestsLoadVersion) return;
    const nextRequests = data.review_requests || [];
    const nextFingerprint = JSON.stringify(nextRequests);
    const changed = nextFingerprint !== reviewRequestsFingerprint;
    reviewRequestsByBooking = new Map(nextRequests.map((reviewRequest) => [reviewRequest.booking_id, reviewRequest]));
    reviewRequestsFingerprint = nextFingerprint;
    growthLoadState.reviews = "ready";
    if (!changed && background) {
      renderReviewRequests();
      renderGrowth();
      renderDashboard();
      return;
    }
    renderReviewStats();
    renderReviewRequests();
    renderGrowth();
    renderDashboard();
  } catch (error) {
    if (requestVersion !== reviewRequestsLoadVersion) return;
    growthLoadState.reviews = "error";
    renderReviewRequests();
    renderGrowth();
    renderDashboard();
    if (background) throw error;
  }
}

function adminRetryAfterSeconds(response) {
  const raw = response.headers.get("Retry-After");
  const seconds = Number.parseInt(raw || "", 10);
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}

function adminRateLimitMessage(response) {
  const seconds = adminRetryAfterSeconds(response);
  return seconds
    ? `Hay demasiadas solicitudes. Vuelve a intentarlo en ${seconds} segundos.`
    : "Hay demasiadas solicitudes. Espera un momento antes de volver a intentarlo.";
}

function conversationErrorMessage(body, fallback) {
  const normalized = typeof body?.detail?.message === "string"
    ? { message: body.detail.message }
    : body;
  return safeConfigurationError(normalized, fallback);
}

function showConversationFeedback(message, isError = false) {
  const feedback = document.getElementById("conversation-feedback");
  feedback.textContent = message || "";
  feedback.className = `inline-feedback ${message ? (isError ? "error" : "success") : ""}`;
}

function conversationDisplayName(item) {
  const identity = item.channel_identity || {};
  if (item.customer?.name) return item.customer.name;
  if (identity.display_name) return identity.display_name;
  if (item.channel === "instagram" && identity.username) return `@${identity.username}`;
  if (item.channel === "whatsapp" && (identity.phone_normalized || identity.phone)) {
    return formatConversationPhone(identity.phone_normalized || identity.phone);
  }
  return item.channel === "instagram" ? "Contacto de Instagram" : "Cliente sin asociar";
}

function formatConversationPhone(value) {
  const phone = String(value || "").trim();
  const spanish = phone.match(/^\+34(\d{3})(\d{3})(\d{3})$/);
  return spanish ? `+34 ${spanish[1]} ${spanish[2]} ${spanish[3]}` : phone;
}

function conversationChannelIdentity(item) {
  const identity = item.channel_identity || {};
  if (item.channel === "whatsapp") {
    const phone = identity.phone_normalized || identity.phone;
    return phone ? formatConversationPhone(phone) : "Número de WhatsApp no disponible";
  }
  if (item.channel === "instagram") {
    return identity.username ? `@${identity.username}` : "Usuario de Instagram no disponible";
  }
  return identity.phone || identity.username || "Identidad de canal no disponible";
}

function conversationAssociationLabel(item) {
  return item.association_status === "associated" ? "Cliente asociado" : "Cliente sin asociar";
}

function conversationStatusLabel(status) {
  return { pending: "Pendiente", replied: "Respondida", closed: "Cerrada" }[status] || "Estado sin identificar";
}

function conversationNeedsReply(item) {
  return item.needs_reply === true || (item.needs_reply == null && Number(item.unread_count || 0) > 0);
}

function conversationNeedsGrowthFollowUp(item) {
  return item.growth_follow_up === true;
}

function conversationIsManualPending(item) {
  return item.manual_pending === true || (item.manual_pending == null && item.status === "pending");
}

function conversationAttentionBadges(item) {
  const states = [];
  if (conversationNeedsReply(item)) {
    states.push(`<span class="conversation-status conversation-status-needs-reply">Necesita respuesta</span>`);
  }
  if (conversationNeedsGrowthFollowUp(item)) {
    states.push(`<span class="conversation-status conversation-status-follow-up">Requiere seguimiento</span>`);
  }
  if (conversationIsManualPending(item)) {
    states.push(`<span class="conversation-status conversation-status-pending">Pendiente</span>`);
  }
  if (item.status === "closed") {
    states.push(`<span class="conversation-status conversation-status-closed">Cerrada</span>`);
  }
  if (!states.length) {
    states.push(`<span class="conversation-status conversation-status-replied">Respondida</span>`);
  }
  return `<span class="conversation-attention-states">${states.join("")}</span>`;
}

function conversationFilterLabel(value) {
  return value === "needs_reply" ? "Necesitan respuesta" : conversationStatusLabel(value);
}

function conversationChannelLabel(channel) {
  return { manual: "Manual", whatsapp: "WhatsApp", instagram: "Instagram" }[channel] || "Canal no disponible";
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
  }[intent] || "Sin clasificar";
}

function conversationIntentBadge(item) {
  if (!item.detected_intent) return "";
  const confidence = Number.isFinite(Number(item.intent_confidence)) ? ` · ${Number(item.intent_confidence)}%` : "";
  return `<span class="conversation-intent-badge">${escapeHtml(conversationIntentLabel(item.detected_intent))}${confidence}</span>`;
}

function conversationDeliveryLabel(status) {
  return {
    queued: "Preparando",
    processing: "Enviando",
    sent: "Enviado",
    delivered: "Entregado",
    read: "Leído",
    retry: "Reintentando",
    blocked: "No entregado",
    failed: "No entregado",
    cancelled: "No entregado",
    simulated: "Registrado",
    pending: "Pendiente"
  }[status] || "Estado pendiente";
}

function conversationProviderBadge(conversation) {
  if (!["instagram", "whatsapp"].includes(conversation.channel)) return "";
  if (conversation.provider_configured && conversation.delivery_supported) {
    const health = businessChannelHealth.find((item) => item.channel === conversation.channel);
    const state = health?.reconnection_required || conversation.integration_status === "degraded"
      ? "Necesita tu atención"
      : conversation.integration_status === "connected" ? "Conectado" : "Revisión necesaria";
    return `<span class="conversation-provider conversation-provider-connected">${escapeHtml(conversationChannelLabel(conversation.channel))} · ${state}</span>`;
  }
  if (conversation.assisted_delivery_available) {
    return `<span class="conversation-provider conversation-provider-assisted">Respuesta asistida</span>`;
  }
  return `<span class="conversation-provider conversation-provider-internal">Canal no disponible</span>`;
}

function formatConversationDate(value) {
  if (!value) return "Sin actividad";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Sin actividad";
  return date.toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" });
}

function formatConversationMessageTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Hora sin identificar";
  return date.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
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

function prioritizeConversations(items) {
  return items
    .map((item, index) => ({ item, index }))
    .sort((left, right) => {
      const leftPriority = conversationNeedsReply(left.item) ? 0 : conversationNeedsGrowthFollowUp(left.item) ? 1 : conversationIsManualPending(left.item) ? 2 : 3;
      const rightPriority = conversationNeedsReply(right.item) ? 0 : conversationNeedsGrowthFollowUp(right.item) ? 1 : conversationIsManualPending(right.item) ? 2 : 3;
      return leftPriority - rightPriority || left.index - right.index;
    })
    .map(({ item }) => item);
}

function updateConversationFilterSummary() {
  const status = document.getElementById("conversation-status-filter")?.value || "";
  const channel = document.getElementById("conversation-channel-filter")?.value || "";
  const query = document.getElementById("conversation-search")?.value.trim() || "";
  const parts = [];
  if (status) parts.push(conversationFilterLabel(status));
  if (channel) parts.push(conversationChannelLabel(channel));
  if (query) parts.push(`“${query}”`);
  const summary = document.getElementById("conversation-filter-summary");
  if (summary) summary.textContent = parts.length ? parts.join(" · ") : "Sin filtros adicionales";
  document.querySelectorAll("[data-conversation-quick-filter]").forEach((button) => {
    const value = button.dataset.conversationQuickFilter;
    const active = value === "all"
      ? !status && !channel
      : value === status || value === channel;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function updateConversationInboxSummary() {
  const pending = dashboardConversations.filter(conversationNeedsReply).length;
  const summary = document.getElementById("conversation-inbox-summary");
  if (summary) {
    summary.textContent = pending
      ? `${pending} ${pending === 1 ? "conversación necesita" : "conversaciones necesitan"} respuesta.`
      : "Todo atendido. Las conversaciones nuevas aparecerán aquí.";
  }
}

async function loadConversations({ background = false, refreshDetail = true } = {}) {
  const requestVersion = ++conversationLoadVersion;
  const container = document.getElementById("conversation-list");
  const params = new URLSearchParams({ limit: "100", offset: "0" });
  const status = document.getElementById("conversation-status-filter")?.value;
  const channel = document.getElementById("conversation-channel-filter")?.value;
  const query = document.getElementById("conversation-search")?.value.trim();
  if (status === "needs_reply") params.set("attention", status);
  else if (status) params.set("status", status);
  if (channel) params.set("channel", channel);
  if (query) params.set("q", query);
  if (!background && !conversations.length) {
    if (!dashboardConversations.length) setDashboardDataState("conversations", "loading");
    container.setAttribute("aria-busy", "true");
    container.innerHTML = `<div class="conversation-list-skeleton" aria-hidden="true"><span></span><span></span><span></span></div><span class="ag-visually-hidden">Cargando conversaciones…</span>`;
  }
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversations?${params}`
    );
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudieron cargar las conversaciones."));
    if (requestVersion !== conversationLoadVersion) return;
    const rawConversations = body.conversations || [];
    const nextConversations = prioritizeConversations(rawConversations);
    const nextFingerprint = JSON.stringify(nextConversations);
    const changed = nextFingerprint !== conversationListFingerprint;
    conversations = nextConversations;
    conversationListFingerprint = nextFingerprint;
    if (!status && !channel && !query) {
      dashboardConversations = rawConversations;
      setDashboardDataState("conversations", "ready");
      updateConversationInboxSummary();
    }
    if (changed || !background) renderConversationList();
    if (selectedConversationId && conversations.some((item) => item.id === selectedConversationId)) {
      if (refreshDetail) await selectConversation(selectedConversationId, false, { background, focusDetail: false });
    } else if (selectedConversationId && background) {
      return;
    } else if (conversations.length) {
      await selectConversation(conversations[0].id, false, { background, focusDetail: false });
    } else {
      selectedConversationId = null;
      selectedConversation = null;
      const hasFilters = Boolean(status || channel || query);
      document.getElementById("conversation-detail").innerHTML = hasFilters
        ? `<div class="conversation-state"><strong>No hay conversaciones con estos filtros</strong><p>Prueba a limpiar la búsqueda.</p><button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="reset-conversation-filters">Limpiar filtros</button></div>`
        : `<div class="conversation-state"><strong>Todavía no hay conversaciones</strong><p>Los mensajes de Instagram y WhatsApp aparecerán aquí.</p></div>`;
      renderConversationCustomerPanel(null);
    }
  } catch (error) {
    if (requestVersion !== conversationLoadVersion) return;
    console.error(error);
    if (background) throw error;
    if (!conversations.length) {
      if (!dashboardConversations.length) setDashboardDataState("conversations", "error");
      container.setAttribute("aria-busy", "false");
      container.innerHTML = `<div class="conversation-state conversation-state--error" role="alert"><strong>No pudimos cargar las conversaciones</strong><p>Comprueba la conexión y vuelve a intentarlo.</p><button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="retry-conversations">Reintentar</button></div>`;
    }
  }
}

function renderConversationList() {
  const container = document.getElementById("conversation-list");
  const previousScrollTop = container.scrollTop;
  container.setAttribute("aria-busy", "false");
  const count = document.getElementById("conversation-result-count");
  if (count) count.textContent = `${conversations.length} ${conversations.length === 1 ? "resultado" : "resultados"}`;
  updateConversationFilterSummary();
  if (!conversations.length) {
    const hasFilters = Boolean(
      document.getElementById("conversation-status-filter")?.value
      || document.getElementById("conversation-channel-filter")?.value
      || document.getElementById("conversation-search")?.value.trim()
    );
    container.innerHTML = hasFilters
      ? `<div class="conversation-state conversation-state--compact"><strong>Sin resultados</strong><p>No hay conversaciones que coincidan con estos filtros.</p></div>`
      : `<div class="conversation-state conversation-state--compact"><strong>Todavía no hay conversaciones</strong><p>Los mensajes de Instagram y WhatsApp aparecerán aquí.</p></div>`;
    return;
  }
  container.innerHTML = conversations.map((item) => `
    <button id="conversation-list-item-${item.id}" class="conversation-list-item ${item.id === selectedConversationId ? "active" : ""}" type="button" role="option" aria-selected="${item.id === selectedConversationId}" data-admin-action="select-conversation" data-id="${item.id}">
      <span class="conversation-list-head">
        <strong>${escapeHtml(conversationDisplayName(item))}</strong>
        ${conversationAttentionBadges(item)}
      </span>
      <span class="conversation-channel">${escapeHtml(conversationChannelLabel(item.channel))}</span>
      <span class="conversation-channel-identity">${escapeHtml(conversationChannelIdentity(item))}</span>
      <span class="conversation-association-status">${escapeHtml(conversationAssociationLabel(item))}</span>
      ${conversationProviderBadge(item)}
      ${conversationIntentBadge(item)}
      <p>${escapeHtml(item.last_message_text || "Sin mensajes")}</p>
      <small>${escapeHtml(formatConversationDate(item.last_message_at))}${item.unread_count ? ` · ${item.unread_count} ${item.unread_count === 1 ? "mensaje pendiente" : "mensajes pendientes"}` : ""}</small>
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
    templatesOpen: Boolean(document.getElementById("conversation-templates-control")?.open),
    automationOpen: Boolean(document.getElementById("conversation-automation-control")?.open),
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

async function selectConversation(conversationId, showLoading = true, { background = false, focusDetail = true } = {}) {
  const requestVersion = ++conversationDetailVersion;
  const uiState = captureConversationUiState(conversationId);
  const selectionChanged = selectedConversationId !== Number(conversationId);
  if (selectionChanged) {
    selectedConversationSuggestionId = null;
    conversationDetailFingerprint = "";
    conversationCustomerSearchState = { open: false, loading: false, query: "", results: [] };
  }
  selectedConversationId = Number(conversationId);
  if (focusDetail && !background) {
    document.getElementById("conversation-center")?.classList.add("conversation-mobile-detail-open");
  }
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
    if (requestVersion !== conversationDetailVersion || selectedConversationId !== Number(conversationId)) return;
    conversationSuggestions = suggestionsResponse.ok ? (suggestionsBody.suggestions || []) : [];
    conversationSuggestionNotice = suggestionsResponse.ok
      ? (suggestionsBody.notice || null)
      : "Las sugerencias no están disponibles ahora. Puedes seguir revisando la conversación.";
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
    selectedConversation = body.conversation;
    renderConversationDetail(body.conversation, uiState);
    renderConversationCustomerPanel(body.conversation);
    if (selectionChanged && focusDetail && !background) {
      document.getElementById("conversation-detail-title")?.focus({ preventScroll: true });
    }
  } catch (error) {
    if (requestVersion !== conversationDetailVersion) return;
    console.error(error);
    if (background) throw error;
    detail.innerHTML = `<div class="conversation-state conversation-state--error" role="alert"><strong>No pudimos abrir esta conversación</strong><p>El historial sigue intacto. Vuelve a intentarlo.</p><button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="select-conversation" data-id="${Number(conversationId)}">Reintentar</button></div>`;
  }
}

function conversationMessageKind(message) {
  if (["failed", "blocked", "cancelled"].includes(message.delivery_status)) return "error";
  if (message.direction === "inbound") return "inbound";
  if (message.sender_type === "automation") return "automation";
  if (message.direction === "outbound") return "manual";
  return "system";
}

function conversationMessageLabel(message) {
  return {
    inbound: "Entrante · Cliente",
    manual: "Saliente manual",
    automation: "Saliente automático",
    system: "Sistema",
    error: "Error de entrega"
  }[conversationMessageKind(message)];
}

function conversationDayLabel(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Fecha sin identificar";
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const key = date.toLocaleDateString("en-CA");
  if (key === today.toLocaleDateString("en-CA")) return "Hoy";
  if (key === yesterday.toLocaleDateString("en-CA")) return "Ayer";
  return date.toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" });
}

function renderConversationMessages(messages) {
  let previousDay = "";
  return [...messages]
    .sort((left, right) => new Date(left.created_at) - new Date(right.created_at) || Number(left.id) - Number(right.id))
    .map((message) => {
      const day = conversationDayLabel(message.created_at);
      const separator = day !== previousDay
        ? `<div class="conversation-date-separator" role="separator"><span>${escapeHtml(day)}</span></div>`
        : "";
      previousDay = day;
      const kind = conversationMessageKind(message);
      const delivery = message.delivery_status
        ? ` · <span class="conversation-delivery conversation-delivery-${escapeHtml(message.delivery_status)}">${escapeHtml(conversationDeliveryLabel(message.delivery_status))}</span>`
        : "";
      return `${separator}<div class="conversation-message conversation-message-${escapeHtml(message.direction)} conversation-message--${kind}"><span>${escapeHtml(message.body)}</span><small>${escapeHtml(conversationMessageLabel(message))} · ${escapeHtml(formatConversationMessageTime(message.created_at))}${delivery}</small></div>`;
    })
    .join("");
}

function conversationComposerModel(conversation) {
  const deliveryMode = conversation.delivery_mode || (
    conversation.integrated_delivery_available
      ? "integrated"
      : conversation.assisted_delivery_available ? "assisted" : "unavailable"
  );
  if (conversation.channel === "manual") {
    return { canCompose: true, canSend: true, assisted: false, notice: "La respuesta quedará registrada en el historial del negocio.", action: "Registrar respuesta" };
  }
  if (deliveryMode === "integrated") {
    const whatsapp = conversation.channel === "whatsapp";
    return { canCompose: true, canSend: true, assisted: whatsapp && conversation.assisted_delivery_available, notice: `Se enviará mediante ${conversationChannelLabel(conversation.channel)}.`, action: whatsapp ? "Enviar por WhatsApp" : "Enviar respuesta", assistedAction: "Abrir en WhatsApp" };
  }
  if (deliveryMode === "assisted" && conversation.channel === "whatsapp" && conversation.assisted_delivery_available) {
    const closedWindow = conversation.delivery_unavailable_reason === "whatsapp_template_required" || conversation.customer_service_window_open === false;
    return {
      canCompose: true,
      canSend: false,
      assisted: true,
      notice: closedWindow
        ? "La ventana de atención de 24 horas está cerrada. Para volver a escribir desde AutonoGrow necesitas una plantilla aprobada, o puedes continuar desde WhatsApp. AutonoGrow no marcará el mensaje como enviado."
        : "El envío integrado no está disponible. Continúa en WhatsApp; AutonoGrow no marcará el mensaje como enviado.",
      action: "Abrir en WhatsApp",
      assistedAction: "Abrir en WhatsApp"
    };
  }
  const reconnect = businessChannelHealth.find((item) => item.channel === conversation.channel)?.reconnection_required;
  return {
    canCompose: false,
    canSend: false,
    assisted: false,
    notice: reconnect
      ? "Este canal necesita reconectarse. Puedes consultar el historial mientras se recupera."
      : "Este canal no está disponible para responder. Puedes consultar el historial.",
    action: ""
  };
}

function resizeConversationReplyTextarea(textarea = document.getElementById("conversation-reply-body")) {
  if (!textarea) return;
  textarea.style.height = "auto";
  const maximumHeight = Number.parseFloat(window.getComputedStyle(textarea).maxHeight);
  const nextHeight = Number.isFinite(maximumHeight)
    ? Math.min(textarea.scrollHeight, maximumHeight)
    : textarea.scrollHeight;
  textarea.style.height = `${nextHeight}px`;
  textarea.style.overflowY = Number.isFinite(maximumHeight) && textarea.scrollHeight > maximumHeight ? "auto" : "hidden";
}

function renderConversationComposer(conversation) {
  const model = conversationComposerModel(conversation);
  if (!model.canCompose) {
    return `<div class="conversation-reply conversation-reply--unavailable" role="status"><strong>Respuesta no disponible</strong><p>${escapeHtml(model.notice)}</p><button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="navigate-section" data-section="channels">Revisar canal</button></div>`;
  }
  return `<div class="conversation-reply" role="group" aria-label="Responder a la conversación">
    <label class="ag-visually-hidden" for="conversation-reply-body">Respuesta</label>
    <div class="conversation-composer-shell">
      <textarea id="conversation-reply-body" rows="1" placeholder="Escribe una respuesta…" maxlength="4000" aria-describedby="conversation-reply-notice"></textarea>
      ${model.canSend ? `<button id="conversation-send-button" class="conversation-composer-send" type="button" data-admin-action="send-conversation-reply" aria-label="${escapeHtml(model.action)}" title="${escapeHtml(model.action)}"><span aria-hidden="true">➤</span><span class="ag-visually-hidden">${escapeHtml(model.action)}</span></button>` : ""}
      ${!model.canSend && model.assisted ? `<button id="conversation-whatsapp-button" class="conversation-composer-send conversation-composer-send--whatsapp" type="button" data-admin-action="open-conversation-whatsapp" aria-label="${escapeHtml(model.assistedAction || model.action)}" title="${escapeHtml(model.assistedAction || model.action)}"><span aria-hidden="true">↗</span><span class="ag-visually-hidden">${escapeHtml(model.assistedAction || model.action)}</span></button>` : ""}
    </div>
    <div class="conversation-composer-meta">
      <small id="conversation-reply-notice">${escapeHtml(model.notice)}</small>
      ${model.canSend && model.assisted ? `<button id="conversation-whatsapp-button" class="btn btn-whatsapp btn-small" type="button" data-admin-action="open-conversation-whatsapp">${escapeHtml(model.assistedAction || model.action)}</button>` : ""}
    </div>
  </div>`;
}

function renderConversationDetail(conversation, uiState = null) {
  const detail = document.getElementById("conversation-detail");
  const channelIdentity = conversationChannelIdentity(conversation);
  const messages = conversation.messages || [];
  const composer = conversationComposerModel(conversation);
  const quickReplies = conversationTemplates.filter((item) => item.active).map((template) => `
    <button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="fill-conversation-reply" data-id="${template.id}">${escapeHtml(template.name)}</button>
  `).join("");
  const pendingSuggestions = conversationSuggestions.filter((item) => item.status === "pending");
  const automation = conversation.automation || { mode: "automatic", is_active: true };
  const automationDuration = uiState?.automationDuration || "60";
  const automationReason = conversationAutomationReason(automation);
  const customerHeaderAction = !conversation.customer_id && !isBusinessStaff()
    ? `<button class="conversation-customer-open ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="open-conversation-customer-search" aria-controls="conversation-customer-panel" aria-expanded="${conversationCustomerPanelOpen}">Asociar cliente</button>`
    : "";
  const customerAssociationMarkup = conversation.customer_id
    ? `<button class="conversation-customer-open conversation-association-trigger" type="button" data-admin-action="open-conversation-customer-panel" aria-controls="conversation-customer-panel" aria-expanded="${conversationCustomerPanelOpen}">${escapeHtml(conversationAssociationLabel(conversation))}</button>`
    : `<span>${escapeHtml(conversationAssociationLabel(conversation))}</span>`;
  const suggestionsMarkup = pendingSuggestions.length || conversationSuggestionNotice ? `
    <div class="conversation-suggestions">
      ${conversationSuggestionNotice ? `<p class="conversation-automation-warning">${escapeHtml(conversationSuggestionNotice)}</p>` : ""}
      ${pendingSuggestions.map((suggestion) => `
        <article class="conversation-suggestion">
          <strong>Respuesta sugerida</strong>
          <span class="conversation-intent-badge">${escapeHtml(suggestion.intent_label)} · ${Number(suggestion.confidence)}%</span>
          <p>${escapeHtml(suggestion.body)}</p>
          <div class="conversation-suggestion-actions">
            ${composer.canSend ? `<button class="ag-button ag-button--primary ag-button--small" type="button" data-admin-action="send-conversation-suggestion" data-id="${Number(suggestion.id)}">Enviar sugerencia</button>` : ""}
            ${composer.canCompose ? `<button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="modify-conversation-suggestion" data-id="${Number(suggestion.id)}">Modificar</button>` : ""}
            <button class="ag-button ag-button--ghost ag-button--small" type="button" data-admin-action="dismiss-conversation-suggestion" data-id="${Number(suggestion.id)}">Descartar</button>
          </div>
        </article>
      `).join("")}
    </div>
  ` : "";
  detail.innerHTML = `
    <header class="conversation-detail-header">
      <div class="conversation-detail-header-copy">
        <div class="conversation-detail-heading-row">
          <h3 id="conversation-detail-title" tabindex="-1">${escapeHtml(conversationDisplayName(conversation))}</h3>
          <div class="conversation-detail-badges"><span class="conversation-channel">${escapeHtml(conversationChannelLabel(conversation.channel))}</span>${conversationProviderBadge(conversation)}${conversationIntentBadge(conversation)}${conversationAttentionBadges(conversation)}</div>
        </div>
      </div>
      <div class="conversation-detail-header-lower">
        <div class="conversation-detail-meta"><span>${escapeHtml(channelIdentity)}</span><span aria-hidden="true">·</span>${customerAssociationMarkup}</div>
        <div class="conversation-detail-actions">
          ${customerHeaderAction}
          <div class="conversation-operational-actions">
            ${conversation.status === "closed"
              ? `<button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="change-conversation-status" data-status="replied">Reabrir</button>`
              : `<button class="ag-button ag-button--ghost ag-button--small" type="button" data-admin-action="change-conversation-status" data-status="pending">Marcar pendiente</button><button class="ag-button ag-button--ghost ag-button--small" type="button" data-admin-action="change-conversation-status" data-status="closed">Cerrar</button>`}
          </div>
        </div>
      </div>
    </header>
    <div id="conversation-thread" class="conversation-thread" data-last-message-id="${messages.at(-1)?.id || ""}" data-message-count="${messages.length}">
      ${messages.length ? renderConversationMessages(messages) : `<div class="conversation-state conversation-state--compact"><p>Todavía no hay mensajes.</p></div>`}
      <button id="conversation-new-messages" class="ag-button ag-button--primary ag-button--small conversation-new-messages" type="button" data-admin-action="scroll-conversation-bottom" hidden>Hay mensajes nuevos</button>
    </div>
    <div class="conversation-footer">
      ${renderConversationComposer(conversation)}
      <div class="conversation-secondary-controls" role="group" aria-label="Controles secundarios de la conversación">
        <details id="conversation-templates-control" class="conversation-secondary-control"${uiState?.templatesOpen ? " open" : ""}>
          <summary><span>Plantillas</span><span class="conversation-secondary-chevron" aria-hidden="true">⌄</span></summary>
          <div class="conversation-secondary-panel">
            <div class="conversation-quick-replies">${quickReplies || `<small>No hay respuestas rápidas activas.</small>`}</div>
          </div>
        </details>
        <details id="conversation-automation-control" class="conversation-secondary-control"${uiState?.automationOpen ? " open" : ""}>
          <summary><span>Automatización · ${automation.is_active ? "Activa" : "Pausada"}</span><span class="conversation-secondary-chevron" aria-hidden="true">⌄</span></summary>
          <div class="conversation-secondary-panel conversation-automation-panel-inline">
            <div class="conversation-automation-controls">
              <div class="conversation-automation-state-copy"><span class="conversation-automation-state ${automation.is_active ? "is-active" : "is-paused"}">${escapeHtml(conversationAutomationLabel(automation))}</span>${automationReason ? `<small>${escapeHtml(automationReason)}</small>` : ""}</div>
              <select id="conversation-automation-duration" aria-label="Duración de la pausa"><option value="15" ${automationDuration === "15" ? "selected" : ""}>15 min</option><option value="60" ${automationDuration === "60" ? "selected" : ""}>1 h</option><option value="240" ${automationDuration === "240" ? "selected" : ""}>4 h</option><option value="-1" ${automationDuration === "-1" ? "selected" : ""}>Hasta reactivarla</option></select>
              <button id="conversation-automation-toggle" class="ag-button ag-button--small ${automation.is_active ? "ag-button--secondary" : "ag-button--primary"}" type="button" data-admin-action="toggle-conversation-automation" data-active="${automation.is_active ? "true" : "false"}">${automation.is_active ? "Pausar automatización" : "Activar automatización"}</button>
              <small class="conversation-automation-suggestion-note">Las sugerencias pueden seguir apareciendo durante la pausa.</small>
            </div>
            ${suggestionsMarkup}
          </div>
        </details>
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
  resizeConversationReplyTextarea(textarea);
  if (uiState?.automationControlFocusId) document.getElementById(uiState.automationControlFocusId)?.focus({ preventScroll: true });
  if (thread) {
    const lastMessageId = String(messages.at(-1)?.id || "");
    const hasNewMessages = Boolean(uiState && (messages.length > uiState.messageCount || (uiState.lastMessageId && lastMessageId !== uiState.lastMessageId)));
    if (!uiState || uiState.threadNearBottom) thread.scrollTop = thread.scrollHeight;
    else {
      thread.scrollTop = uiState.threadScrollTop;
      if (hasNewMessages || uiState.newMessagesVisible) document.getElementById("conversation-new-messages")?.removeAttribute("hidden");
    }
  }
}

function customerMemoryCategoryLabel(category) {
  return ({ preference: "Preferencia", service_interest: "Interés", availability_preference: "Horario", operational_note: "Nota", relationship: "Relación", other: "Otro" })[category] || category;
}

function customerMemoryKeyForCategory(category) {
  return ({ availability_preference: "preferred_time", service_interest: "service", preference: "preference", operational_note: "note" })[category] || "note";
}

function stopBookingCustomerMemoryTimer() {
  if (bookingCustomerMemoryTimer !== null) window.clearTimeout(bookingCustomerMemoryTimer);
  bookingCustomerMemoryTimer = null;
}

function refreshBookingCustomerMemoryPanel({ restoreToggleFocus = false } = {}) {
  const bookingId = Number(bookingCustomerMemoryPanelState.bookingId);
  if (!Number.isInteger(bookingId) || bookingId <= 0) return;
  const booking = allBookings.find((item) => Number(item.id) === bookingId);
  const current = document.querySelector(`[data-booking-customer-memory-panel="${bookingId}"]`);
  if (!booking || !current) return;
  current.outerHTML = renderBookingCustomerMemorySection(booking);
  if (restoreToggleFocus) {
    document.querySelector(`[data-booking-customer-memory-toggle="${bookingId}"]`)?.focus({ preventScroll: true });
  }
}

function resetBookingCustomerMemoryTimer() {
  stopBookingCustomerMemoryTimer();
  if (!bookingCustomerMemoryPanelState.open) return;
  bookingCustomerMemoryTimer = window.setTimeout(() => {
    bookingCustomerMemoryTimer = null;
    if (!bookingCustomerMemoryPanelState.open) return;
    const panel = document.querySelector(`[data-booking-customer-memory-panel="${Number(bookingCustomerMemoryPanelState.bookingId)}"]`);
    const textarea = panel?.querySelector("[data-booking-customer-memory-draft]");
    if (bookingCustomerMemoryPanelState.saving || (textarea && document.activeElement === textarea)) {
      resetBookingCustomerMemoryTimer();
      return;
    }
    const restoreToggleFocus = Boolean(panel?.contains(document.activeElement));
    bookingCustomerMemoryPanelState.open = false;
    refreshBookingCustomerMemoryPanel({ restoreToggleFocus });
  }, BOOKING_CUSTOMER_MEMORY_HIDE_MS);
}

function syncBookingCustomerMemorySelection(booking) {
  const bookingId = Number(booking?.id);
  const customerId = Number(booking?.customer_id);
  const normalizedBookingId = Number.isInteger(bookingId) && bookingId > 0 ? bookingId : null;
  const normalizedCustomerId = Number.isInteger(customerId) && customerId > 0 ? customerId : null;
  if (
    bookingCustomerMemoryPanelState.bookingId === normalizedBookingId
    && bookingCustomerMemoryPanelState.customerId === normalizedCustomerId
  ) return;
  stopBookingCustomerMemoryTimer();
  bookingCustomerMemoryPanelState = {
    bookingId: normalizedBookingId,
    customerId: normalizedCustomerId,
    open: false,
    formOpen: false,
    draft: normalizedBookingId ? (bookingCustomerMemoryDrafts.get(normalizedBookingId) || "") : "",
    saving: false,
    feedback: "",
    feedbackError: false
  };
}

function bookingCustomerMemoryItemMarkup(item) {
  const authorName = String(item.created_by_name || "").trim();
  const author = authorName
    ? `Autor: ${authorName}`
    : Number.isInteger(Number(item.created_by_user_id)) && Number(item.created_by_user_id) > 0
      ? `Autor: usuario #${Number(item.created_by_user_id)}`
      : "";
  const created = item.created_at ? formatConversationDate(item.created_at) : "";
  const metadata = [author, created].filter(Boolean).join(" · ");
  return `<article class="booking-customer-memory-item${item.is_sensitive ? " booking-customer-memory-item--sensitive" : ""}">
    <span>${escapeHtml(customerMemoryCategoryLabel(item.category))}${item.is_sensitive ? " · Sensible" : ""}</span>
    <p>${escapeHtml(item.value)}</p>
    ${metadata ? `<small>${escapeHtml(metadata)}</small>` : ""}
  </article>`;
}

function renderBookingCustomerMemorySection(booking) {
  if (!booking.customer_memory_eligible) return "";
  const bookingId = Number(booking.id);
  const customerId = Number(booking.customer_id);
  const hasCustomer = Number.isInteger(customerId) && customerId > 0;
  const selected = bookingCustomerMemoryPanelState.bookingId === bookingId
    && bookingCustomerMemoryPanelState.customerId === (hasCustomer ? customerId : null);
  const open = Boolean(selected && bookingCustomerMemoryPanelState.open);
  if (!hasCustomer) {
    return `<section class="booking-customer-memory" data-booking-customer-memory-panel="${bookingId}">
      <strong>Notas del cliente</strong>
      <p class="booking-customer-memory-help">Esta cita no tiene un cliente asociado.</p>
    </section>`;
  }
  const state = customerMemorySummaries.get(customerId);
  const memories = state?.status === "ready" ? (state.data.explicit || []) : [];
  const form = selected && bookingCustomerMemoryPanelState.formOpen ? `
    <form class="booking-customer-memory-form" data-booking-customer-memory-form data-booking-id="${bookingId}" data-customer-id="${customerId}">
      <label for="booking-customer-memory-value-${bookingId}">Nueva nota</label>
      <textarea id="booking-customer-memory-value-${bookingId}" class="ag-input" data-booking-customer-memory-draft maxlength="2000" rows="3" required>${escapeHtml(bookingCustomerMemoryPanelState.draft)}</textarea>
      <div class="booking-customer-memory-form__actions">
        <button class="ag-button ag-button--primary ag-button--small" type="submit" ${bookingCustomerMemoryPanelState.saving ? "disabled aria-busy=\"true\"" : ""}>${bookingCustomerMemoryPanelState.saving ? "Guardando…" : "Guardar nota"}</button>
        <button class="ag-button ag-button--ghost ag-button--small" type="button" data-admin-action="close-booking-customer-memory-form" data-id="${bookingId}">Cerrar formulario</button>
      </div>
    </form>` : "";
  let content = "";
  if (!state || state.status === "loading") {
    content = `<p class="booking-customer-memory-help" role="status">Cargando notas del cliente…</p>`;
  } else if (state.status === "error") {
    content = `<p class="booking-customer-memory-help" role="alert">No se pudieron cargar las notas.</p><button class="ag-button ag-button--ghost ag-button--small" type="button" data-admin-action="retry-booking-customer-memory" data-id="${bookingId}" data-customer-id="${customerId}">Reintentar</button>`;
  } else {
    content = memories.length
      ? `<div class="booking-customer-memory-list">${memories.map(bookingCustomerMemoryItemMarkup).join("")}</div>`
      : `<p class="booking-customer-memory-help">No hay notas guardadas sobre este cliente.</p>`;
    if (!(selected && bookingCustomerMemoryPanelState.formOpen)) {
      content += `<button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="add-booking-customer-memory" data-id="${bookingId}" data-customer-id="${customerId}">+ Añadir nota</button>`;
    }
  }
  const feedback = selected && bookingCustomerMemoryPanelState.feedback
    ? `<p class="inline-feedback ${bookingCustomerMemoryPanelState.feedbackError ? "error" : "success"}" role="status">${escapeHtml(bookingCustomerMemoryPanelState.feedback)}</p>`
    : "";
  return `<section class="booking-customer-memory" data-booking-customer-memory-panel="${bookingId}">
    <div class="booking-customer-memory-heading">
      <strong>Notas del cliente</strong>
      <button class="ag-button ag-button--ghost ag-button--small" type="button" data-admin-action="toggle-booking-customer-memory" data-id="${bookingId}" data-customer-id="${customerId}" data-booking-customer-memory-toggle="${bookingId}" aria-expanded="${open}">${open ? "Ocultar notas del cliente" : "Ver notas del cliente"}</button>
    </div>
    ${open ? `<div class="booking-customer-memory-content" aria-label="Notas persistentes del cliente">${content}${form}${feedback}</div>` : ""}
  </section>`;
}

function toggleBookingCustomerMemory(bookingId, customerId) {
  const booking = allBookings.find((item) => Number(item.id) === bookingId && Number(item.customer_id) === customerId);
  if (!booking) return;
  syncBookingCustomerMemorySelection(booking);
  bookingCustomerMemoryPanelState.open = !bookingCustomerMemoryPanelState.open;
  bookingCustomerMemoryPanelState.feedback = "";
  bookingCustomerMemoryPanelState.feedbackError = false;
  refreshBookingCustomerMemoryPanel();
  if (!bookingCustomerMemoryPanelState.open) {
    stopBookingCustomerMemoryTimer();
    return;
  }
  resetBookingCustomerMemoryTimer();
  if (!customerMemorySummaries.has(customerId)) void loadCustomerMemorySummary(customerId);
}

function openBookingCustomerMemoryForm(bookingId, customerId) {
  if (
    bookingCustomerMemoryPanelState.bookingId !== bookingId
    || bookingCustomerMemoryPanelState.customerId !== customerId
    || !bookingCustomerMemoryPanelState.open
  ) return;
  bookingCustomerMemoryPanelState.formOpen = true;
  bookingCustomerMemoryPanelState.feedback = "";
  refreshBookingCustomerMemoryPanel();
  resetBookingCustomerMemoryTimer();
  queueMicrotask(() => document.querySelector(`[data-booking-customer-memory-panel="${bookingId}"] [data-booking-customer-memory-draft]`)?.focus());
}

function closeBookingCustomerMemoryForm(bookingId) {
  if (bookingCustomerMemoryPanelState.bookingId !== bookingId) return;
  bookingCustomerMemoryPanelState.formOpen = false;
  bookingCustomerMemoryPanelState.feedback = bookingCustomerMemoryPanelState.draft.trim()
    ? "Borrador conservado mientras sigas en esta cita."
    : "";
  bookingCustomerMemoryPanelState.feedbackError = false;
  refreshBookingCustomerMemoryPanel();
  resetBookingCustomerMemoryTimer();
}

async function submitBookingCustomerMemoryForm(form) {
  const bookingId = Number(form.dataset.bookingId);
  const customerId = Number(form.dataset.customerId);
  if (
    bookingCustomerMemoryPanelState.bookingId !== bookingId
    || bookingCustomerMemoryPanelState.customerId !== customerId
    || bookingCustomerMemoryPanelState.saving
  ) return;
  const draft = String(form.querySelector("[data-booking-customer-memory-draft]")?.value || "").trim();
  bookingCustomerMemoryPanelState.draft = draft;
  if (!draft) {
    bookingCustomerMemoryPanelState.feedback = "Escribe una nota antes de guardarla.";
    bookingCustomerMemoryPanelState.feedbackError = true;
    refreshBookingCustomerMemoryPanel();
    queueMicrotask(() => document.querySelector(`[data-booking-customer-memory-panel="${bookingId}"] [data-booking-customer-memory-draft]`)?.focus());
    return;
  }
  bookingCustomerMemoryPanelState.saving = true;
  bookingCustomerMemoryPanelState.feedback = "";
  bookingCustomerMemoryDrafts.set(bookingId, draft);
  refreshBookingCustomerMemoryPanel();
  resetBookingCustomerMemoryTimer();
  try {
    const response = await customerMemoryRequest(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/customers/${customerId}/memory`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category: "operational_note", key: "note", value: draft, source_type: "manual" })
    });
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(body.detail || "No se pudo guardar la nota del cliente.");
    bookingCustomerMemoryDrafts.delete(bookingId);
    customerMemorySummaries.delete(customerId);
    if (bookingCustomerMemoryPanelState.bookingId === bookingId) {
      bookingCustomerMemoryPanelState.draft = "";
      bookingCustomerMemoryPanelState.formOpen = false;
      bookingCustomerMemoryPanelState.saving = false;
      bookingCustomerMemoryPanelState.feedback = "Nota añadida.";
      bookingCustomerMemoryPanelState.feedbackError = false;
    }
    await loadCustomerMemorySummary(customerId, { force: true });
    if (bookingCustomerMemoryPanelState.bookingId === bookingId) resetBookingCustomerMemoryTimer();
  } catch (error) {
    if (bookingCustomerMemoryPanelState.bookingId !== bookingId) return;
    bookingCustomerMemoryPanelState.saving = false;
    bookingCustomerMemoryPanelState.feedback = error.message || "No se pudo guardar la nota del cliente.";
    bookingCustomerMemoryPanelState.feedbackError = true;
    refreshBookingCustomerMemoryPanel();
    resetBookingCustomerMemoryTimer();
    queueMicrotask(() => document.querySelector(`[data-booking-customer-memory-panel="${bookingId}"] [data-booking-customer-memory-draft]`)?.focus());
  }
}

function handleBookingCustomerMemoryActivity(event) {
  if (!(event.target instanceof Element) || !event.target.closest("[data-booking-customer-memory-panel]")) return;
  if (event.target.matches("[data-booking-customer-memory-draft]")) {
    const bookingId = Number(bookingCustomerMemoryPanelState.bookingId);
    bookingCustomerMemoryPanelState.draft = event.target.value;
    if (event.target.value) bookingCustomerMemoryDrafts.set(bookingId, event.target.value);
    else bookingCustomerMemoryDrafts.delete(bookingId);
  }
  resetBookingCustomerMemoryTimer();
}

function customerMemoryDateValue(value) {
  const date = value ? new Date(value) : null;
  return date && !Number.isNaN(date.getTime()) ? date.toISOString().slice(0, 10) : "";
}

function renderCustomerMemoryForm(customerId, summary) {
  if (customerMemoryFormState?.customerId !== customerId) return "";
  const existing = summary?.explicit?.find((item) => item.id === customerMemoryFormState.memoryId);
  const category = existing?.category || "preference";
  const submitLabel = customerMemoryFormState.mode === "supersede" ? "Guardar sustitución" : (customerMemoryFormState.mode === "edit" ? "Guardar cambios" : "Añadir recuerdo");
  const options = [["preference", "Preferencia"], ["service_interest", "Interés"], ["availability_preference", "Horario"], ["operational_note", "Nota"]];
  return `<form id="customer-memory-form" class="customer-memory-form" data-customer-id="${customerId}" data-mode="${escapeHtml(customerMemoryFormState.mode)}" data-memory-id="${Number(existing?.id || 0)}">
    <label>Tipo<select id="customer-memory-category" class="ag-input" ${existing ? "disabled" : ""}>${options.map(([value, label]) => `<option value="${value}" ${category === value ? "selected" : ""}>${label}</option>`).join("")}</select></label>
    <label>Contenido<textarea id="customer-memory-value" class="ag-input" maxlength="2000" rows="3" required>${escapeHtml(existing?.value || "")}</textarea></label>
    <label>Caduca<input id="customer-memory-expires" class="ag-input" type="date" value="${escapeHtml(customerMemoryDateValue(existing?.expires_at))}" /></label>
    <label class="customer-memory-sensitive"><input id="customer-memory-sensitive" type="checkbox" ${existing?.is_sensitive ? "checked" : ""} /> Marcar como sensible</label>
    <p>No guardes contraseñas, tarjetas completas ni información clínica innecesaria.</p>
    <div class="customer-memory-form__actions"><button class="ag-button ag-button--primary ag-button--small" type="submit">${submitLabel}</button><button class="ag-button ag-button--ghost ag-button--small" type="button" data-admin-action="cancel-customer-memory-form">Cancelar</button></div>
    <p id="customer-memory-form-feedback" class="inline-feedback" role="status"></p>
  </form>`;
}

function renderCustomerMemorySection(customerId) {
  if (!customerId) return "";
  const state = customerMemorySummaries.get(customerId);
  if (!state || state.status === "loading") return `<section class="customer-memory" aria-busy="true"><div class="customer-memory-heading"><h4>Memoria</h4></div><div class="ag-skeleton ag-skeleton--card" aria-hidden="true"></div></section>`;
  if (state.status === "error") return `<section class="customer-memory"><div class="customer-memory-heading"><h4>Memoria</h4><button class="ag-button ag-button--ghost ag-button--small" type="button" data-admin-action="retry-customer-memory" data-id="${customerId}">Reintentar</button></div><p class="customer-memory-help">No se pudo cargar el contexto. Las reservas siguen disponibles.</p></section>`;
  const summary = state.data;
  const derived = summary.derived || {};
  const memories = summary.explicit || [];
  const cards = memories.map((item) => `<article class="customer-memory-item ${item.is_sensitive ? "customer-memory-item--sensitive" : ""}"><span>${escapeHtml(customerMemoryCategoryLabel(item.category))}${item.is_sensitive ? " · Sensible" : ""}</span><p>${escapeHtml(item.value)}</p>${item.expires_at ? `<small>Caduca: ${escapeHtml(formatConversationDate(item.expires_at))}</small>` : ""}<div><button class="ag-button ag-button--ghost ag-button--small" type="button" data-admin-action="edit-customer-memory" data-id="${item.id}" data-customer-id="${customerId}">Editar</button><button class="ag-button ag-button--ghost ag-button--small" type="button" data-admin-action="supersede-customer-memory" data-id="${item.id}" data-customer-id="${customerId}">Sustituir</button><button class="ag-button ag-button--ghost ag-button--small" type="button" data-admin-action="obsolete-customer-memory" data-id="${item.id}" data-customer-id="${customerId}">Obsoleta</button><button class="ag-button ag-button--ghost ag-button--small" type="button" data-admin-action="delete-customer-memory" data-id="${item.id}" data-customer-id="${customerId}">Eliminar</button></div></article>`).join("");
  const frequent = derived.most_frequent_service;
  return `<section class="customer-memory"><div class="customer-memory-heading"><div><h4>Memoria</h4><p>Contexto explícito del equipo</p></div><button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="add-customer-memory" data-id="${customerId}">+ Añadir</button></div>${cards || `<p class="customer-memory-help">Todavía no hay recuerdos activos.</p>`}${renderCustomerMemoryForm(customerId, summary)}</section>
    <section class="customer-memory customer-memory--activity"><div class="customer-memory-heading"><div><h4>Actividad</h4><p>Datos observados, no preferencias declaradas</p></div></div><dl class="conversation-customer-stats"><div><dt>Visitas completadas</dt><dd>${Number(derived.visit_count || 0)}</dd></div><div><dt>Última visita</dt><dd>${derived.last_visit_at ? escapeHtml(formatConversationDate(derived.last_visit_at)) : "Sin visitas"}</dd></div><div><dt>Servicio más frecuente</dt><dd>${escapeHtml(frequent?.name || "Sin evidencia")}</dd></div><div><dt>Comportamiento observado</dt><dd>${derived.observed_return_interval_days ? `~${Number(derived.observed_return_interval_days)} días` : "Evidencia insuficiente"}</dd></div></dl>${derived.configured_recurrence ? `<p class="customer-memory-help">La recurrencia configurada (${Number(derived.configured_recurrence.interval_days)} días) tiene prioridad sobre el intervalo observado.</p>` : ""}</section>`;
}

function renderConversationCustomerSearch() {
  if (!conversationCustomerSearchState.open || isBusinessStaff()) return "";
  const results = conversationCustomerSearchState.results.map((customer) => `
    <button class="conversation-customer-search-result" type="button" data-admin-action="associate-conversation-customer" data-id="${Number(customer.customer_id)}">
      <strong>${escapeHtml(customer.name)}</strong>
      <span>${escapeHtml(formatConversationPhone(customer.phone_normalized || customer.phone) || "Sin teléfono")}</span>
      <small>${customer.memory_eligible ? "Cliente registrado" : "Sin memoria persistente"}</small>
    </button>
  `).join("");
  return `<section class="conversation-customer-search" aria-busy="${conversationCustomerSearchState.loading}">
    <label for="conversation-customer-search-input">Buscar cliente</label>
    <div><input id="conversation-customer-search-input" class="ag-input" type="search" maxlength="200" value="${escapeHtml(conversationCustomerSearchState.query)}" placeholder="Nombre o teléfono" /><button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="search-conversation-customers">Buscar</button></div>
    ${conversationCustomerSearchState.loading ? `<p>Buscando clientes…</p>` : (results || `<p>No hay clientes que coincidan.</p>`)}
  </section>`;
}

async function searchConversationCustomers() {
  if (isBusinessStaff() || !selectedConversation) return;
  const input = document.getElementById("conversation-customer-search-input");
  const query = input?.value.trim() || conversationCustomerSearchState.query;
  conversationCustomerSearchState = { ...conversationCustomerSearchState, open: true, loading: true, query };
  renderConversationCustomerPanel(selectedConversation);
  try {
    const params = new URLSearchParams({ limit: "20" });
    if (query) params.set("q", query);
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/customers?${params.toString()}`);
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudieron buscar clientes."));
    conversationCustomerSearchState = { ...conversationCustomerSearchState, loading: false, results: Array.isArray(body) ? body : [] };
  } catch (error) {
    conversationCustomerSearchState = { ...conversationCustomerSearchState, loading: false, results: [] };
    showConversationFeedback(error.message, true);
  }
  if (selectedConversation) renderConversationCustomerPanel(selectedConversation);
}

function openConversationCustomerSearch() {
  if (isBusinessStaff()) return;
  openConversationCustomerPanel(document.activeElement);
  conversationCustomerSearchState = { open: true, loading: false, query: "", results: [] };
  if (selectedConversation) renderConversationCustomerPanel(selectedConversation);
  queueMicrotask(() => document.getElementById("conversation-customer-search-input")?.focus());
  void searchConversationCustomers();
}

async function updateConversationCustomer(customerId) {
  if (isBusinessStaff() || !selectedConversationId || conversationCustomerAssociationUpdating) return;
  if (customerId === null && !window.confirm("¿Desasociar este cliente de la conversación? La conversación y sus mensajes se conservarán.")) return;
  conversationCustomerAssociationUpdating = true;
  const uiState = captureConversationUiState(selectedConversationId);
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversations/${selectedConversationId}/customer`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ customer_id: customerId })
    });
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudo actualizar la asociación."));
    selectedConversation = body.conversation;
    conversations = conversations.map((item) => item.id === body.conversation.id ? body.conversation : item);
    conversationCustomerSearchState = { open: false, loading: false, query: "", results: [] };
    renderConversationList();
    renderConversationDetail(body.conversation, uiState);
    renderConversationCustomerPanel(body.conversation);
    showConversationFeedback(customerId === null ? "Cliente desasociado." : "Cliente asociado.");
  } catch (error) {
    showConversationFeedback(error.message, true);
  } finally {
    conversationCustomerAssociationUpdating = false;
  }
}

function renderConversationCustomerPanel(conversation) {
  const content = document.getElementById("conversation-customer-content");
  if (!content) return;
  if (!conversation) {
    content.innerHTML = `<div class="conversation-state conversation-state--compact"><p>Selecciona una conversación para ver la información disponible.</p></div>`;
    return;
  }
  const customer = conversation.customer || null;
  const customerId = Number(conversation.customer_id);
  const associated = Number.isInteger(customerId) && customerId > 0 && customer;
  const contact = associated
    ? [formatConversationPhone(customer.phone_normalized || customer.phone), customer.email].filter(Boolean)
    : [conversationChannelIdentity(conversation)].filter(Boolean);
  const controls = isBusinessStaff() ? "" : (associated
    ? `<div class="conversation-customer-actions"><button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="open-conversation-customer-search">Cambiar cliente</button><button class="ag-button ag-button--ghost ag-button--small" type="button" data-admin-action="detach-conversation-customer">Desasociar</button></div>`
    : `<button class="ag-button ag-button--primary ag-button--small" type="button" data-admin-action="open-conversation-customer-search">Asociar cliente</button>`);
  content.innerHTML = `
    <section class="conversation-customer-summary">
      <div class="conversation-customer-avatar" aria-hidden="true">${escapeHtml(conversationDisplayName(conversation).charAt(0).toUpperCase())}</div>
      <h4>${escapeHtml(conversationDisplayName(conversation))}</h4>
      <p>${escapeHtml(contact.join(" · ") || "Sin más datos de contacto")}</p>
      <span class="conversation-channel">${escapeHtml(conversationChannelLabel(conversation.channel))}</span>
      <strong class="conversation-association-status">${escapeHtml(conversationAssociationLabel(conversation))}</strong>
      ${controls}
    </section>
    <dl class="conversation-customer-stats">
      ${associated ? `<div><dt>Nombre</dt><dd>${escapeHtml(customer.name)}</dd></div><div><dt>Teléfono</dt><dd>${escapeHtml(formatConversationPhone(customer.phone_normalized || customer.phone) || "No disponible")}</dd></div><div><dt>Email</dt><dd>${escapeHtml(customer.email || "No disponible")}</dd></div>` : ""}
      <div><dt>Última actividad</dt><dd>${escapeHtml(formatConversationDate(conversation.last_message_at))}</dd></div>
    </dl>
    ${renderConversationCustomerSearch()}
    ${associated && conversation.customer_memory_eligible ? renderCustomerMemorySection(customerId) : ""}
  `;
  if (associated && conversation.customer_memory_eligible && !customerMemorySummaries.has(customerId)) void loadCustomerMemorySummary(customerId);
}

function openCustomerMemoryForm(mode, customerId, memoryId = null) {
  customerMemoryFormState = { mode, customerId, memoryId };
  if (selectedConversation) renderConversationCustomerPanel(selectedConversation);
  queueMicrotask(() => document.getElementById("customer-memory-value")?.focus());
}

async function mutateCustomerMemory(action, customerId, memoryId) {
  if (customerMemoryMutationIds.has(memoryId)) return;
  const message = action === "obsolete" ? "¿Marcar este recuerdo como obsoleto? Se conservará en el historial." : "¿Eliminar este recuerdo? Se conservará únicamente como registro histórico.";
  if (!window.confirm(message)) return;
  customerMemoryMutationIds.add(memoryId);
  try {
    const suffix = action === "obsolete" ? "/obsolete" : "";
    const response = await customerMemoryRequest(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/customer-memory/${memoryId}${suffix}`, { method: action === "delete" ? "DELETE" : "POST" });
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(body.detail || "No se pudo actualizar el recuerdo.");
    customerMemoryFormState = null;
    customerMemorySummaries.delete(customerId);
    await loadCustomerMemorySummary(customerId, { force: true });
  } catch (error) {
    window.alert(error.message || "No se pudo actualizar el recuerdo.");
  } finally {
    customerMemoryMutationIds.delete(memoryId);
  }
}

async function submitCustomerMemoryForm(form) {
  const customerId = Number(form.dataset.customerId);
  const memoryId = Number(form.dataset.memoryId);
  const mode = form.dataset.mode;
  const feedback = document.getElementById("customer-memory-form-feedback");
  const submit = form.querySelector("button[type='submit']");
  const category = document.getElementById("customer-memory-category").value;
  const expiration = document.getElementById("customer-memory-expires").value;
  const common = { value: document.getElementById("customer-memory-value").value.trim(), is_sensitive: document.getElementById("customer-memory-sensitive").checked, expires_at: expiration ? new Date(`${expiration}T23:59:59`).toISOString() : null };
  let endpoint = `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/customers/${customerId}/memory`;
  let method = "POST";
  let payload = { ...common, category, key: customerMemoryKeyForCategory(category), source_type: "manual" };
  if (mode === "edit") {
    endpoint = `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/customer-memory/${memoryId}`;
    method = "PATCH";
    payload = common;
  } else if (mode === "supersede") {
    endpoint = `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/customer-memory/${memoryId}/supersede`;
    payload = common;
  }
  submit.disabled = true;
  feedback.textContent = "Guardando…";
  try {
    const response = await customerMemoryRequest(endpoint, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(body.detail || "No se pudo guardar el recuerdo.");
    customerMemoryFormState = null;
    customerMemorySummaries.delete(customerId);
    await loadCustomerMemorySummary(customerId, { force: true });
  } catch (error) {
    feedback.textContent = error.message || "No se pudo guardar el recuerdo.";
    submit.disabled = false;
  }
}

function openConversationCustomerPanel(trigger) {
  conversationCustomerPanelOpen = true;
  conversationCustomerReturnFocus = trigger || document.activeElement;
  const panel = document.getElementById("conversation-customer-panel");
  const backdrop = document.getElementById("conversation-customer-backdrop");
  panel?.classList.add("is-open");
  panel?.setAttribute("aria-hidden", "false");
  document.querySelectorAll(".conversation-customer-open").forEach((button) => button.setAttribute("aria-expanded", "true"));
  if (window.matchMedia("(max-width: 1599px)").matches) {
    backdrop?.removeAttribute("hidden");
    document.body.classList.add("conversation-drawer-open");
  }
  const title = document.getElementById("conversation-customer-title");
  title?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  title?.focus?.({ preventScroll: true });
}

function closeConversationCustomerPanel({ restoreFocus = true } = {}) {
  conversationCustomerPanelOpen = false;
  document.getElementById("conversation-customer-panel")?.classList.remove("is-open");
  document.getElementById("conversation-customer-backdrop")?.setAttribute("hidden", "");
  document.body.classList.remove("conversation-drawer-open");
  document.querySelectorAll(".conversation-customer-open").forEach((button) => button.setAttribute("aria-expanded", "false"));
  syncConversationCustomerPanelMode();
  if (restoreFocus) conversationCustomerReturnFocus?.focus?.({ preventScroll: true });
  conversationCustomerReturnFocus = null;
}

function closeConversationMobileDetail() {
  closeConversationCustomerPanel({ restoreFocus: false });
  document.getElementById("conversation-center")?.classList.remove("conversation-mobile-detail-open");
  document.getElementById(`conversation-list-item-${selectedConversationId}`)?.focus({ preventScroll: true });
}

function resetConversationFilters() {
  document.getElementById("conversation-status-filter").value = "";
  document.getElementById("conversation-channel-filter").value = "";
  document.getElementById("conversation-search").value = "";
  updateConversationFilterSummary();
  loadConversations({ background: false });
}

function applyConversationQuickFilter(value) {
  document.getElementById("conversation-status-filter").value = value === "needs_reply" ? "needs_reply" : "";
  document.getElementById("conversation-channel-filter").value = ["whatsapp", "instagram"].includes(value) ? value : "";
  updateConversationFilterSummary();
  loadConversations({ background: false });
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
  resizeConversationReplyTextarea(textarea);
  document.getElementById("conversation-templates-control")?.removeAttribute("open");
  textarea.focus();
}

async function sendConversationReply() {
  if (!selectedConversationId || conversationReplySending) return;
  const textarea = document.getElementById("conversation-reply-body");
  const bodyText = textarea?.value.trim();
  if (!bodyText) return showConversationFeedback("Escribe un mensaje antes de enviarlo.", true);
  const button = document.getElementById("conversation-send-button");
  conversationReplySending = true;
  if (button) {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.setAttribute("aria-label", "Enviando…");
    button.setAttribute("title", "Enviando…");
    button.innerHTML = `<span aria-hidden="true">…</span><span class="ag-visually-hidden">Enviando…</span>`;
  }
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
    if (response.status === 429) throw new Error(adminRateLimitMessage(response));
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudo enviar el mensaje."));
    selectedConversationSuggestionId = null;
    if (textarea) {
      textarea.value = "";
      resizeConversationReplyTextarea(textarea);
    }
    showConversationFeedback(body.message?.delivery_status === "queued" ? "Respuesta en preparación." : "Respuesta registrada correctamente.");
    await requestAdminRefresh(["conversationList", "conversationThread", "operations"]);
  } catch (error) {
    showConversationFeedback(error.message, true);
    if (selectedConversationId) await requestAdminRefresh(["conversationList", "conversationThread"]);
  } finally {
    conversationReplySending = false;
    if (button?.isConnected) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      const action = selectedConversation ? conversationComposerModel(selectedConversation).action : "Enviar respuesta";
      button.setAttribute("aria-label", action);
      button.setAttribute("title", action);
      button.innerHTML = `<span aria-hidden="true">➤</span><span class="ag-visually-hidden">${escapeHtml(action)}</span>`;
    }
  }
}

function isSafeWhatsAppUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === "wa.me" && !url.username && !url.password;
  } catch (_error) {
    return false;
  }
}

async function openConversationWhatsApp() {
  if (!selectedConversationId || conversationAssistedOpening) return;
  const textarea = document.getElementById("conversation-reply-body");
  const bodyText = textarea?.value.trim();
  if (!bodyText) return showConversationFeedback("Escribe un mensaje antes de abrir WhatsApp.", true);
  const whatsappWindow = openBlankWhatsAppWindow();
  const button = document.getElementById("conversation-whatsapp-button");
  conversationAssistedOpening = true;
  if (button) {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
  }
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
    if (response.status === 429) throw new Error(adminRateLimitMessage(response));
    if (!response.ok || !isSafeWhatsAppUrl(body.whatsapp_url)) throw new Error(conversationErrorMessage(body, "No se pudo abrir WhatsApp de forma segura."));
    if (!whatsappWindow) throw new Error("El navegador bloqueó la nueva ventana de WhatsApp.");
    whatsappWindow.location.href = body.whatsapp_url;
    showConversationFeedback("WhatsApp abierto. El mensaje aún no se considera enviado.");
  } catch (error) {
    whatsappWindow?.close();
    showConversationFeedback(error.message, true);
  } finally {
    conversationAssistedOpening = false;
    if (button?.isConnected) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
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
  resizeConversationReplyTextarea(textarea);
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
  if (!selectedConversationId || conversationStatusUpdating) return;
  conversationStatusUpdating = true;
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
  } finally {
    conversationStatusUpdating = false;
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

const CONVERSATION_TEMPLATE_VARIABLES = new Set(["business_name", "business_slug", "public_booking_url", "business_phone", "business_address"]);

function showChannelAutomationFeedback(message, isError = false) {
  const summary = document.getElementById("channel-automations-errors");
  const status = document.getElementById("channel-automations-status");
  if (status) status.textContent = isError ? "Necesita revisión" : "Actualizado";
  if (!summary) return;
  summary.hidden = !message;
  summary.textContent = message || "";
  summary.classList.toggle("is-success", !isError);
  if (isError) summary.focus({ preventScroll: true });
}

async function customerMemoryRequest(input, options = {}) {
  return fetch(input, options);
}

function refreshCustomerMemoryConsumers(customerId) {
  if (selectedConversation && Number(selectedConversation.customer_id) === customerId) {
    renderConversationCustomerPanel(selectedConversation);
  }
  if (
    bookingCustomerMemoryPanelState.open
    && bookingCustomerMemoryPanelState.customerId === customerId
  ) refreshBookingCustomerMemoryPanel();
}

async function loadCustomerMemorySummary(customerId, { force = false } = {}) {
  if (!Number.isInteger(customerId) || customerId <= 0) return;
  if (!force && (customerMemoryLoadingIds.has(customerId) || customerMemorySummaries.has(customerId))) return;
  customerMemoryLoadingIds.add(customerId);
  customerMemorySummaries.set(customerId, { status: "loading" });
  refreshCustomerMemoryConsumers(customerId);
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/customers/${customerId}/memory-summary`);
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(body.detail || "No se pudo cargar la memoria del cliente.");
    customerMemorySummaries.set(customerId, { status: "ready", data: body });
  } catch (error) {
    console.error(error);
    customerMemorySummaries.set(customerId, { status: "error" });
  } finally {
    customerMemoryLoadingIds.delete(customerId);
    refreshCustomerMemoryConsumers(customerId);
  }
}

function templateValidation(name, body) {
  const errors = {};
  if (!name.trim()) errors.name = "Escribe un nombre.";
  else if (name.length > 160) errors.name = "El nombre no puede superar 160 caracteres.";
  if (!body.trim()) errors.body = "Escribe el contenido de la plantilla.";
  else if (body.length > 10000) errors.body = "El contenido no puede superar 10.000 caracteres.";
  else {
    const variables = [...body.matchAll(/\{([^{}]+)\}/g)].map((match) => match[1]);
    const unknown = variables.find((variable) => !CONVERSATION_TEMPLATE_VARIABLES.has(variable));
    const withoutVariables = body.replace(/\{[^{}]+\}/g, "");
    if (unknown) errors.body = `La variable {${unknown}} no está disponible.`;
    else if (/[{}]/.test(withoutVariables)) errors.body = "Hay una variable sin cerrar correctamente.";
  }
  return errors;
}

function templatePreviewText(body) {
  const values = {
    business_name: currentBusiness?.name || "Tu negocio",
    business_slug: currentBusiness?.slug || getBusinessSlug(),
    public_booking_url: currentBusiness?.public_booking_url || "Enlace público de reserva",
    business_phone: currentBusiness?.phone || "Teléfono del negocio",
    business_address: currentBusiness?.address || "Dirección del negocio"
  };
  return body.replace(/\{([^{}]+)\}/g, (match, variable) => Object.hasOwn(values, variable) ? values[variable] : match);
}

function renderNewTemplatePreview() {
  const body = document.getElementById("conversation-template-body")?.value || "";
  const preview = document.getElementById("conversation-template-preview");
  if (preview) preview.textContent = body.trim() ? templatePreviewText(body) : "Escribe un mensaje para ver una muestra.";
}

function canSaveChannelConfiguration(key) {
  const otherChanges = [...configurationDirtyKeys].filter((dirtyKey) => configurationCategoryForKey(dirtyKey) === "messages" && dirtyKey !== key);
  if (!otherChanges.length) return true;
  showChannelAutomationFeedback("Guarda o descarta los otros cambios pendientes antes de actualizar este bloque.", true);
  return false;
}

async function loadConversationTemplates({ background = false } = {}) {
  const requestVersion = ++conversationTemplatesLoadVersion;
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversation-templates`
    );
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudieron cargar las plantillas."));
    if (requestVersion !== conversationTemplatesLoadVersion) return;
    conversationTemplates = body.templates || [];
    channelHubLoadState.templates = "ready";
    if (!background || !configurationSectionHasDirty("messages")) renderConversationTemplates();
    if (!background && selectedConversationId) await selectConversation(selectedConversationId, false);
  } catch (error) {
    if (requestVersion !== conversationTemplatesLoadVersion) return;
    console.error(error);
    channelHubLoadState.templates = "error";
    if (!background && !conversationTemplates.length) renderConversationTemplates();
  }
}

function renderConversationTemplates() {
  const container = document.getElementById("conversation-template-list");
  if (!container || !canManageConversationTemplates()) return;
  container.setAttribute("aria-busy", "false");
  if (channelHubLoadState.templates === "error" && !conversationTemplates.length) {
    container.innerHTML = `<div class="channel-partial-error"><strong>No se pudieron cargar las plantillas.</strong><button class="ag-button ag-button--secondary" type="button" data-channel-retry="templates">Reintentar</button></div>`;
    return;
  }
  container.innerHTML = conversationTemplates.map((template) => `
    <article class="conversation-template-item" data-conversation-template-id="${template.id}" data-config-dirty-key="template-${template.id}">
      <div class="conversation-template-heading"><div><p>Plantilla</p><h4>${escapeHtml(template.name)}</h4></div><span>${template.active ? "Activa" : "Desactivada"}</span></div>
      <label class="ag-field">Nombre<input class="conversation-template-item-name" maxlength="160" value="${escapeHtml(template.name)}" /></label>
      <label class="ag-field">Contenido<textarea class="conversation-template-item-body" maxlength="10000" rows="4">${escapeHtml(template.body)}</textarea></label>
      <p><strong>Aplicación:</strong> canales con automatización autorizada.</p>
      <div class="template-preview"><strong>Vista previa</strong><p class="conversation-template-item-preview">${escapeHtml(templatePreviewText(template.body))}</p></div>
      <label class="active-setting"><input class="conversation-template-item-active" type="checkbox" ${template.active ? "checked" : ""} />Plantilla activa</label>
      <div class="settings-actions"><button class="btn btn-small btn-secondary" type="button" data-admin-action="save-conversation-template" data-id="${template.id}">Guardar</button><button class="btn btn-small btn-danger" type="button" data-admin-action="delete-conversation-template" data-id="${template.id}">Eliminar</button><span class="configuration-item-save-state">Sin cambios</span></div>
    </article>
  `).join("") || `<div class="empty-state"><strong>Aún no hay plantillas</strong><p>Crea la primera con las variables disponibles.</p></div>`;
  snapshotConfigurationForms("#conversation-templates-panel [data-config-dirty-key]");
  ensureConfigurationSnapshot("template-new");
  renderNewTemplatePreview();
}

async function createConversationTemplate() {
  const payload = {
    name: document.getElementById("conversation-template-name").value.trim(),
    body: document.getElementById("conversation-template-body").value.trim(),
    active: true
  };
  if (!canSaveChannelConfiguration("template-new")) return;
  const errors = templateValidation(payload.name, payload.body);
  document.getElementById("conversation-template-name-error").textContent = errors.name || "";
  document.getElementById("conversation-template-body-error").textContent = errors.body || "";
  if (Object.keys(errors).length) {
    showChannelAutomationFeedback("Revisa los campos indicados antes de crear la plantilla.", true);
    document.getElementById(errors.name ? "conversation-template-name" : "conversation-template-body").focus();
    return;
  }
  const saved = await mutateConversationTemplate(
    `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversation-templates`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }
  );
  if (!saved) return;
  document.getElementById("conversation-template-name").value = "";
  document.getElementById("conversation-template-body").value = "";
  renderNewTemplatePreview();
  snapshotConfigurationForm("template-new");
}

async function saveConversationTemplate(templateId) {
  const row = document.querySelector(`[data-conversation-template-id="${templateId}"]`);
  if (!row || !canSaveChannelConfiguration(`template-${templateId}`)) return;
  const name = row.querySelector(".conversation-template-item-name").value.trim();
  const body = row.querySelector(".conversation-template-item-body").value.trim();
  const errors = templateValidation(name, body);
  if (Object.keys(errors).length) return showChannelAutomationFeedback(Object.values(errors)[0], true);
  await mutateConversationTemplate(
    `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversation-templates/${templateId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        body,
        active: row.querySelector(".conversation-template-item-active").checked
      })
    }
  );
}

async function deleteConversationTemplate(templateId) {
  if (!canSaveChannelConfiguration(`template-${templateId}`)) return;
  if (!window.confirm("¿Eliminar esta plantilla?")) return;
  await mutateConversationTemplate(
    `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversation-templates/${templateId}`,
    { method: "DELETE" }
  );
}

async function mutateConversationTemplate(url, options) {
  const mutationKey = `template:${url}`;
  if (configurationMutationKeys.has(mutationKey)) return false;
  configurationMutationKeys.add(mutationKey);
  try {
    const response = await fetch(url, options);
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudo guardar la plantilla."));
    showChannelAutomationFeedback("Plantillas actualizadas.");
    await Promise.all([loadConversationTemplates(), loadConversationAutomation()]);
    if (selectedConversationId) await selectConversation(selectedConversationId, false);
    return true;
  } catch (error) {
    showChannelAutomationFeedback("No se pudo guardar la plantilla. Revisa los datos e inténtalo de nuevo.", true);
    return false;
  } finally {
    configurationMutationKeys.delete(mutationKey);
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
    const integrationBody = integrationResponse.ok ? await readAdminResponseBody(integrationResponse) : null;
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudo cargar la automatización."));
    if (requestVersion !== conversationAutomationLoadVersion) return;
    conversationAutomation = body;
    businessIntegrationStatus = integrationBody;
    channelHubLoadState.automation = "ready";
    if (!background || !configurationSectionHasDirty("messages")) renderConversationAutomation();
  } catch (error) {
    if (requestVersion !== conversationAutomationLoadVersion) return;
    console.error(error);
    channelHubLoadState.automation = "error";
    if (background) throw error;
    if (!conversationAutomation) {
      container.innerHTML = `<div class="channel-partial-error"><strong>No se pudieron cargar las respuestas automáticas.</strong><p>Los estados de Instagram y WhatsApp siguen disponibles.</p><button class="ag-button ag-button--secondary" type="button" data-channel-retry="automation">Reintentar</button></div>`;
      container.setAttribute("aria-busy", "false");
    }
  }
}

function automationAuthorizedChannels() {
  return ["instagram", "whatsapp"].filter((name) => {
    const channel = channelRecord(name);
    const health = channelHealthRecord(name);
    return channel?.status === "approved" && channel.automation_enabled && !health?.reconnection_required && !["revoked", "suspended", "action_required"].includes(health?.health_status);
  });
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
    ? `Inicio del periodo: ${formatDateTime(usage.period_start)} · Periodo activo hasta: ${formatDateTime(usage.period_end)} · ${usage.days_remaining} días restantes.`
    : usage.period_status === "suspended"
      ? `Periodo suspendido · Inicio: ${usage.period_start ? formatDateTime(usage.period_start) : "sin fecha"} · Vencimiento: ${usage.period_end ? formatDateTime(usage.period_end) : "sin fecha"}.`
      : `Periodo pendiente de renovación · Inicio anterior: ${usage.period_start ? formatDateTime(usage.period_start) : "sin fecha"} · Vencimiento anterior: ${usage.period_end ? formatDateTime(usage.period_end) : "sin fecha"}.`;
  const templates = conversationAutomation.templates || [];
  const templateOptions = (selectedId) => `
    <option value="">Plantilla recomendada</option>
    ${templates.map((template) => `
      <option value="${template.id}" ${template.id === selectedId ? "selected" : ""}>${escapeHtml(template.name)}${template.active ? "" : " (inactiva)"}</option>
    `).join("")}
  `;
  const authorizedChannels = automationAuthorizedChannels();
  const periodAvailable = usage.period_status === "active";
  const ownerAllowsAutomation = Boolean(settings.automation_feature_enabled);
  const canEnableAutomation = ownerAllowsAutomation && periodAvailable && authorizedChannels.length > 0;
  const automationBlockMessage = !ownerAllowsAutomation
    ? "AutonoGrow todavía no ha habilitado esta capacidad para el negocio."
    : !periodAvailable ? "El periodo de automatización no está activo."
      : !authorizedChannels.length ? "Ningún canal aprobado tiene las respuestas automáticas habilitadas y saludables." : "";
  container.innerHTML = `
    <div class="conversation-automation-settings" data-config-dirty-key="automation-settings">
      <div class="conversation-automation-heading"><div><p>Estado general</p><h3>${settings.automation_enabled ? "Respuestas automáticas activadas" : "Respuestas automáticas desactivadas"}</h3></div><span>${canEnableAutomation || settings.automation_enabled ? "Configurable" : "Bloqueada"}</span></div>
      ${automationBlockMessage ? `<div class="ag-alert ag-alert--warning"><div><strong>No se puede activar ahora</strong><p>${escapeHtml(automationBlockMessage)}</p></div></div>` : `<p class="channel-guidance">Canales autorizados: ${authorizedChannels.map((name) => name === "instagram" ? "Instagram" : "WhatsApp").join(" y ")}.</p>`}
      <label class="active-setting"><input id="conversation-automation-enabled" type="checkbox" ${settings.automation_enabled ? "checked" : ""} ${canEnableAutomation || settings.automation_enabled ? "" : "disabled"} />Activar respuestas automáticas</label>
      <label>Umbral automático (%)<input id="conversation-automation-threshold" type="number" min="0" max="100" value="${settings.auto_threshold}" /></label>
      <label>Al alcanzar el límite<select id="conversation-automation-limit-mode" ${allowedLimitBehaviors.length === 1 ? "disabled" : ""}>${allowedLimitBehaviors.map((value) => `<option value="${value}" ${settings.on_limit_reached === value ? "selected" : ""}>${limitBehaviorLabels[value]}</option>`).join("")}</select></label>
      <label>Pausa tras respuesta humana<select id="conversation-human-reply-pause"><option value="0" ${settings.human_reply_pause_minutes === 0 ? "selected" : ""}>No pausar</option><option value="15" ${settings.human_reply_pause_minutes === 15 ? "selected" : ""}>15 minutos</option><option value="60" ${settings.human_reply_pause_minutes === 60 ? "selected" : ""}>1 hora</option><option value="240" ${settings.human_reply_pause_minutes === 240 ? "selected" : ""}>4 horas</option><option value="-1" ${settings.human_reply_pause_minutes === -1 ? "selected" : ""}>Hasta reactivarla</option></select></label>
      <div class="settings-actions"><button class="btn btn-primary" type="button" data-admin-action="save-conversation-automation-settings">Guardar configuración</button><span class="configuration-item-save-state">Sin cambios</span></div>
    </div>
    <article class="conversation-automation-usage-card">
      <div><p>Créditos de automatización</p><strong>${usage.total_available} disponibles</strong><span class="conversation-automation-usage-state state-${escapeHtml(usage.status)}">${usageStatusLabels[usage.status] || "Estado no disponible"}</span></div>
      <div class="conversation-credit-breakdown"><span><strong>${usage.included_credits_remaining} de ${usage.included_credits_per_period}</strong>Incluidos disponibles</span><span><strong>${usage.additional_credits_balance}</strong>Créditos adicionales acumulados</span><span><strong>${usage.total_available}</strong>Total disponible</span></div>
      <div class="conversation-automation-quota-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${usage.percentage}"><span style="width:${usage.percentage}%"></span></div>
      <p>${usage.percentage}% utilizado · ${escapeHtml(periodSummary)}</p>
      <p>${usage.period_status === "pending_renewal" ? "El periodo de automatización está pendiente de renovación. El equipo de AutonoGrow gestionará la reactivación." : "El límite de mensajes forma parte de tu plan de AutonoGrow. Para modificarlo, contacta con el equipo de AutonoGrow."}</p>
      ${usage.included_credits_remaining === 0 && usage.additional_credits_balance > 0 ? "<p>Has utilizado los mensajes incluidos en tu plan. A partir de ahora se utilizarán tus créditos adicionales.</p>" : ""}
      ${usage.total_available === 0 ? "<p class=\"conversation-automation-warning\">No quedan créditos de automatización disponibles. El equipo de AutonoGrow gestionará la ampliación del servicio.</p>" : ""}
      ${settings.automation_feature_enabled ? "" : "<p class=\"conversation-automation-warning\">La automatización está pausada por AutonoGrow para este negocio.</p>"}
      <p><strong>Qué afectan:</strong> únicamente a respuestas generadas automáticamente. La salud del canal se comprueba por separado.</p>
    </article>
    ${usage.limit_reached ? `<p class="conversation-automation-warning">${settings.on_limit_reached === "semi_automatic" ? "Sin créditos disponibles. Las respuestas automáticas pasan a modo sugerencia." : "Sin créditos disponibles. No se enviarán más respuestas automáticas."}</p>` : ""}
    <div class="conversation-automation-rules">
      <h3>Modo por intención</h3>
      ${(conversationAutomation.rules || []).map((rule) => `
        <article class="conversation-automation-rule" data-automation-intent="${escapeHtml(rule.intent)}" data-config-dirty-key="automation-rule-${escapeHtml(rule.intent)}">
          <div><p>Regla</p><h4>${escapeHtml(rule.intent_label)}</h4><small>Se evalúa cuando el sistema reconoce esta intención en un canal autorizado.</small></div>
          <p><strong>Canal:</strong> ${authorizedChannels.length ? authorizedChannels.map((name) => name === "instagram" ? "Instagram" : "WhatsApp").join(" y ") : "Bloqueada por el canal"}</p>
          <select class="conversation-automation-rule-mode">
            <option value="disabled" ${rule.mode === "disabled" ? "selected" : ""}>Desactivado</option>
            <option value="semi_automatic" ${rule.mode === "semi_automatic" ? "selected" : ""}>Sugerir</option>
            <option value="automatic" ${rule.mode === "automatic" ? "selected" : ""} ${canEnableAutomation || rule.mode === "automatic" ? "" : "disabled"}>Automático seguro</option>
          </select>
          <select class="conversation-automation-rule-template">${templateOptions(rule.template_id)}</select>
          <label class="active-setting"><input class="conversation-automation-rule-active" type="checkbox" ${rule.active ? "checked" : ""} ${canEnableAutomation || rule.active ? "" : "disabled"} />Activa</label>
          <p class="automation-message-excerpt">${escapeHtml((templates.find((template) => template.id === rule.template_id)?.body || "Se usará la plantilla recomendada.").slice(0, 180))}</p>
          <div class="settings-actions"><button class="btn btn-small btn-secondary" type="button" data-admin-action="save-conversation-automation-rule" data-intent="${escapeHtml(rule.intent)}">Guardar</button><span class="configuration-item-save-state">Sin cambios</span></div>
        </article>
      `).join("")}
    </div>
  `;
  container.setAttribute("aria-busy", "false");
  document.getElementById("channel-automations-status").textContent = settings.automation_enabled ? "Activadas" : "Desactivadas";
  snapshotConfigurationForms("#conversation-automation-content [data-config-dirty-key]");
}

async function saveConversationAutomationSettings() {
  if (!canSaveChannelConfiguration("automation-settings")) return;
  const payload = {
    automation_enabled: document.getElementById("conversation-automation-enabled").checked,
    auto_threshold: Number(document.getElementById("conversation-automation-threshold").value),
    on_limit_reached: document.getElementById("conversation-automation-limit-mode").value,
    human_reply_pause_minutes: Number(document.getElementById("conversation-human-reply-pause").value)
  };
  if (payload.automation_enabled && !automationAuthorizedChannels().length) {
    showChannelAutomationFeedback("No puedes activar respuestas automáticas hasta que un canal aprobado tenga esta capacidad disponible.", true);
    return;
  }
  await mutateConversationAutomation(
    `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/conversation-automation/settings`,
    payload,
    "Configuración de automatización actualizada."
  );
}

async function saveConversationAutomationRule(intent) {
  const row = document.querySelector(`[data-automation-intent="${intent}"]`);
  if (!row || !canSaveChannelConfiguration(`automation-rule-${intent}`)) return;
  const templateValue = row.querySelector(".conversation-automation-rule-template").value;
  const payload = {
    mode: row.querySelector(".conversation-automation-rule-mode").value,
    template_id: templateValue ? Number(templateValue) : null,
    active: row.querySelector(".conversation-automation-rule-active").checked
  };
  const mutationKey = `automation-rule:${intent}`;
  if (configurationMutationKeys.has(mutationKey)) return;
  if ((payload.active || payload.mode === "automatic") && !automationAuthorizedChannels().length) {
    showChannelAutomationFeedback("Esta regla está bloqueada porque ningún canal autorizado puede automatizar respuestas.", true);
    return;
  }
  configurationMutationKeys.add(mutationKey);
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
    showChannelAutomationFeedback(`Regla de ${conversationIntentLabel(intent)} actualizada.`);
  } catch (_error) {
    showChannelAutomationFeedback("No se pudo guardar la regla. Revisa la configuración e inténtalo de nuevo.", true);
  } finally {
    configurationMutationKeys.delete(mutationKey);
  }
}

async function mutateConversationAutomation(url, payload, successMessage) {
  const mutationKey = `automation:${url}`;
  if (configurationMutationKeys.has(mutationKey)) return false;
  configurationMutationKeys.add(mutationKey);
  try {
    const response = await fetch(url, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const body = await readAdminResponseBody(response);
    if (!response.ok) throw new Error(conversationErrorMessage(body, "No se pudo guardar la automatización."));
    showChannelAutomationFeedback(successMessage);
    await loadConversationAutomation();
    await loadBusinessChannelOnboarding({ background: true });
    await requestAdminRefresh(["conversationList", "conversationThread", "operations"]);
    return true;
  } catch (_error) {
    showChannelAutomationFeedback("No se pudo guardar la automatización. Revisa los datos e inténtalo de nuevo.", true);
    return false;
  } finally {
    configurationMutationKeys.delete(mutationKey);
  }
}

async function loadMessageOutbox({ background = false } = {}) {
  const requestVersion = ++messageOutboxLoadVersion;
  const container = document.getElementById("message-outbox-list");
  if (!messageOutbox.length) growthLoadState.outbox = "loading";

  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/message-outbox`
    );

    if (!response.ok) {
      throw new Error("No se pudieron cargar los mensajes.");
    }

    const data = await response.json();
    if (requestVersion !== messageOutboxLoadVersion) return;
    const nextMessages = data.messages || [];
    const nextFingerprint = JSON.stringify(nextMessages);
    const changed = nextFingerprint !== messageOutboxFingerprint;
    messageOutbox = nextMessages;
    messageOutboxFingerprint = nextFingerprint;
    growthLoadState.outbox = "ready";
    if (!changed && background) {
      renderGrowth();
      renderDashboard();
      return;
    }
    renderMessageOutboxMetrics();
    renderMessageOutbox();
    renderGrowth();
    renderDashboard();
  } catch (error) {
    if (requestVersion !== messageOutboxLoadVersion) return;
    console.error(error);
    growthLoadState.outbox = "error";
    renderGrowth();
    renderDashboard();
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

function maskedOutboxPhone(value) {
  const digits = String(value || "").replace(/\D/g, "");
  return digits.length >= 4 ? `WhatsApp terminado en ${digits.slice(-4)}` : "Teléfono no disponible";
}

function renderMessageCards(messages, emptyMessage = "No hay mensajes para este filtro.") {
  if (!messages.length) {
    return `<p class="empty-state">${emptyMessage}</p>`;
  }

  return messages.map((message) => {
    const phoneIsValid = message.delivery_mode === "assisted" && isSafeWhatsAppUrl(message.whatsapp_url);
    const isClosed = ["sent", "skipped"].includes(message.status);
    return `
      <article class="message-outbox-item">
        <div class="message-outbox-header">
          <div>
            <span class="message-type">${getMessageTypeLabel(message.message_type)}</span>
            <h3>${escapeHtml(message.customer_name)}</h3>
            <p>${escapeHtml(maskedOutboxPhone(message.customer_phone))}</p>
          </div>
          <span class="status-pill ${getMessageStatusClass(message.status)}">${getMessageStatusLabel(message.status)}</span>
        </div>
        <p class="message-preview">${escapeHtml(message.message)}</p>
        ${phoneIsValid ? "" : `<p class="message-phone-warning">Este cliente no tiene un teléfono válido para WhatsApp.</p>`}
        <div class="message-actions">
          <button class="btn btn-small btn-whatsapp" type="button" data-admin-action="open-whatsapp-message" data-id="${message.id}" ${!phoneIsValid || isClosed ? "disabled" : ""}>
            Abrir en WhatsApp
          </button>
          <button class="btn btn-small btn-success" type="button" data-admin-action="update-outbox-status" data-id="${message.id}" data-status="sent" ${message.status === "sent" ? "disabled" : ""}>
            Marcar como enviado
          </button>
          <button class="btn btn-small btn-secondary" type="button" data-admin-action="update-outbox-status" data-id="${message.id}" data-status="skipped" ${message.status === "skipped" ? "disabled" : ""}>
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
  return labels[messageType] || "Mensaje";
}

function getMessageStatusLabel(status) {
  const labels = {
    pending: "Pendiente",
    opened: "Preparado",
    sent: "Enviado",
    skipped: "Omitido",
    failed: "Error"
  };
  return labels[status] || "Estado no disponible";
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
  if (!isSafeWhatsAppUrl(message?.whatsapp_url)) {
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

    if (response.status === 429) {
      throw new Error(adminRateLimitMessage(response));
    }
    if (!response.ok) {
      throw new Error(safeConfigurationError(result, "No se pudo preparar el mensaje."));
    }

    replaceOutboxMessage(result.message);
    requestAdminRefresh(["operations"]);
    if (!isSafeWhatsAppUrl(result.message?.whatsapp_url)) throw new Error("unsafe_whatsapp_url");
    whatsappWindow.location.href = result.message.whatsapp_url;
    return true;
  } catch (error) {
    whatsappWindow.close();
    console.error(error);
    alert(error.message?.startsWith("Hay demasiadas solicitudes")
      ? error.message
      : "No se pudo abrir WhatsApp de forma segura. Comprueba el teléfono e inténtalo de nuevo.");
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
      throw new Error(safeConfigurationError(result, "No se pudo actualizar el mensaje."));
    }

    replaceOutboxMessage(result.message);
    await requestAdminRefresh(["operations"]);
  } catch (error) {
    console.error(error);
    alert("No se pudo actualizar el mensaje. Inténtalo de nuevo.");
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
      const requests = [
        loadBookings({ background: true }),
        loadBookingCloseTasks({ background: true })
      ];
      requests.push(loadCustomerOpportunities({ background: true }), loadGrowthActionMetrics({ background: true }), loadBusinessGrowthSignals({ background: true }));
      if (!isBusinessStaff()) requests.push(loadMessageOutbox({ background: true }), loadReviewRequests({ background: true }));
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
    requests.push(loadConversationTemplates({ background: true }));
    requests.push(loadBusinessChannelOnboarding({ background: true }));
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
  const candidatesContainer = document.getElementById("review-candidates-list");
  if (!pendingContainer || !historyContainer || !candidatesContainer) return;
  const reviewRequests = Array.from(reviewRequestsByBooking.values());
  const pending = reviewRequests.filter((item) => ["pending", "copied"].includes(item.status));
  const history = reviewRequests.filter((item) => ["sent", "skipped"].includes(item.status));
  const candidates = getReviewCandidates();
  const reviewLink = getSafeReviewUrl();
  const errors = document.getElementById("growth-reviews-errors");
  const status = document.getElementById("growth-reviews-status");
  const linkCard = document.getElementById("growth-review-link-card");
  const loadFailed = growthLoadState.reviews === "error";
  errors.hidden = !loadFailed;
  errors.textContent = loadFailed ? "No se pudieron actualizar las solicitudes. Los clientes y estados ya cargados siguen disponibles." : "";
  status.textContent = loadFailed ? "Error parcial" : pending.length ? `${pending.length} pendientes` : "Sin pendientes";
  linkCard.setAttribute("aria-busy", "false");
  linkCard.innerHTML = reviewLink ? `<div><p>Configuración</p><h3 id="growth-review-link-title">Enlace de reseñas</h3><span class="growth-link-state growth-link-state--ready">Enlace configurado</span><small>Las nuevas solicitudes conservarán exactamente este destino.</small></div><a class="ag-button ag-button--secondary ag-button--small" href="${escapeHtml(reviewLink)}" target="_blank" rel="noopener noreferrer">Comprobar enlace</a>` : `<div><p>Configuración</p><h3 id="growth-review-link-title">Enlace de reseñas</h3><span class="growth-link-state growth-link-state--missing">${currentBusiness?.reviews_url?.trim() ? "Enlace no válido" : "Falta configurar"}</span><small>Añade el enlace donde quieres recibir las reseñas para poder preparar solicitudes.</small></div><button class="ag-button ag-button--primary ag-button--small" type="button" data-growth-action="configuration-reviews">Configurar enlace</button>`;
  candidatesContainer.setAttribute("aria-busy", "false");
  candidatesContainer.innerHTML = candidates.length ? candidates.map(renderReviewCandidateCard).join("") : `<div class="growth-empty-state"><strong>No hay clientes pendientes de solicitud</strong><p>Cuando completes nuevas citas, aparecerán aquí los clientes que todavía no tengan una solicitud.</p></div>`;
  pendingContainer.setAttribute("aria-busy", "false");
  pendingContainer.innerHTML = pending.length
    ? pending.map(renderReviewSummaryCard).join("")
    : `<div class="growth-empty-state"><strong>No hay solicitudes de reseña pendientes</strong><p>Las solicitudes preparadas o abiertas en WhatsApp aparecerán aquí.</p></div>`;
  historyContainer.setAttribute("aria-busy", "false");
  historyContainer.innerHTML = history.length
    ? history.map(renderReviewSummaryCard).join("")
    : `<div class="growth-empty-state"><strong>Aún no hay solicitudes cerradas</strong><p>Este historial distingue las marcadas como enviadas de las omitidas.</p></div>`;
}

function renderReviewCandidateCard(booking) {
  const reviewLink = getSafeReviewUrl();
  const hasPhone = hasUsableReviewPhone(booking);
  const state = !reviewLink ? "Falta enlace de reseñas" : hasPhone ? "Puede recibir una solicitud" : "Sin WhatsApp disponible";
  return `<article class="review-summary-card review-candidate-card"><div class="review-request-header"><div><h4>${escapeHtml(booking.customer_name || "Cliente sin nombre")}</h4><p>${escapeHtml(booking.service_name || "Servicio sin indicar")}</p></div><span class="review-status">${escapeHtml(state)}</span></div><dl class="review-useful-data"><div><dt>Fecha de la cita</dt><dd>${escapeHtml(formatBookingSlot(booking))}</dd></div><div><dt>Canal disponible</dt><dd>${hasPhone ? "WhatsApp asistido" : "Copia manual del mensaje"}</dd></div></dl><p class="review-delivery-note">${reviewLink ? (hasPhone ? "Prepararemos el mensaje y podrás abrir WhatsApp para enviarlo tú." : "Puedes preparar y copiar el mensaje, pero no abrir WhatsApp sin un teléfono válido.") : "Primero configura el destino de las reseñas."}</p><div class="review-actions">${reviewLink ? `<button class="ag-button ag-button--primary ag-button--small" type="button" data-review-create="${booking.id}">Preparar solicitud</button>` : `<button class="ag-button ag-button--primary ag-button--small" type="button" data-growth-action="configuration-reviews">Configurar enlace</button>`}<button class="ag-button ag-button--ghost ag-button--small" type="button" data-growth-action="booking" data-booking-id="${booking.id}">Ver reserva</button></div></article>`;
}

function reviewDeliveryState(reviewRequest) {
  const outbox = getReviewOutboxMessage(reviewRequest.booking_id);
  if (outbox?.status === "failed") return { label: "No se pudo preparar", detail: "Comprueba el canal. Este mensaje no dispone de un reintento automático seguro." };
  if (reviewRequest.status === "sent") return { label: "Marcada como enviada", detail: "Este estado lo confirmó una persona; no significa que la reseña se haya publicado." };
  if (reviewRequest.status === "skipped") return { label: "Omitida", detail: "La solicitud se cerró sin marcarla como enviada." };
  if (outbox?.status === "opened") return { label: "Abierta en WhatsApp", detail: "WhatsApp se abrió con el mensaje preparado; AutonoGrow no lo marcó como enviado." };
  if (reviewRequest.status === "copied") return { label: "Mensaje copiado", detail: "El texto se copió para un envío manual." };
  return { label: "Solicitud preparada", detail: "Todavía requiere que una persona copie el mensaje o abra WhatsApp." };
}

function renderReviewSummaryCard(reviewRequest) {
  const booking = allBookings.find((item) => item.id === reviewRequest.booking_id);
  const outbox = getReviewOutboxMessage(reviewRequest.booking_id);
  const delivery = reviewDeliveryState(reviewRequest);
  const openAvailable = !["sent", "skipped"].includes(reviewRequest.status) && ["pending", "opened"].includes(outbox?.status) && isSafeWhatsAppUrl(outbox?.whatsapp_url);
  const active = !["sent", "skipped"].includes(reviewRequest.status);
  const timestamp = reviewRequest.sent_at || reviewRequest.copied_at || outbox?.opened_at || reviewRequest.created_at;
  return `<article class="review-summary-card"><div class="review-request-header"><div><h4>${escapeHtml(reviewRequest.customer_name || "Cliente sin nombre")}</h4><p>${escapeHtml(booking?.service_name || "Servicio sin indicar")}${booking ? ` · ${escapeHtml(formatBookingSlot(booking))}` : ""}</p></div><span class="review-status review-status-${escapeHtml(reviewRequest.status)}">${escapeHtml(delivery.label)}</span></div><p class="review-delivery-note">${escapeHtml(delivery.detail)}</p><details class="review-message-details"><summary>Ver mensaje preparado</summary><p class="review-message">${escapeHtml(reviewRequest.message)}</p></details><textarea data-review-fallback="${reviewRequest.id}" class="review-copy-fallback" readonly>${escapeHtml(reviewRequest.message)}</textarea><p class="review-request-time">Actualizada: ${escapeHtml(formatConversationDate(timestamp))}</p><div class="review-actions">${openAvailable ? `<button class="btn btn-small btn-whatsapp" type="button" data-review-open="${reviewRequest.id}">${outbox?.status === "opened" ? "Abrir de nuevo en WhatsApp" : "Abrir en WhatsApp"}</button>` : ""}${active ? `<button class="ag-button ag-button--secondary ag-button--small" type="button" data-review-copy="${reviewRequest.id}">Copiar mensaje</button><button class="ag-button ag-button--secondary ag-button--small" type="button" data-review-status="sent" data-review-request="${reviewRequest.id}">Marcar como enviada</button><button class="ag-button ag-button--ghost ag-button--small" type="button" data-review-status="skipped" data-review-request="${reviewRequest.id}">Omitir</button>` : ""}${booking ? `<button class="ag-button ag-button--ghost ag-button--small" type="button" data-growth-action="booking" data-booking-id="${booking.id}">Ver reserva</button>` : ""}</div><p data-review-feedback="${reviewRequest.id}" class="inline-feedback" role="status"></p></article>`;
}

function getAgendaWeekStart(dateKey = agendaSelectedDate) {
  const date = new Date(`${dateKey}T12:00:00Z`);
  const weekday = date.getUTCDay();
  return addDaysToDateKey(dateKey, weekday === 0 ? -6 : 1 - weekday);
}

function getAgendaWeekDates(dateKey = agendaSelectedDate) {
  const start = getAgendaWeekStart(dateKey);
  return Array.from({ length: 7 }, (_, index) => addDaysToDateKey(start, index));
}

function formatAgendaDate(dateKey, options = {}) {
  if (!dateKey) return "Fecha sin indicar";
  return new Intl.DateTimeFormat("es-ES", { timeZone: "UTC", ...options })
    .format(new Date(`${dateKey}T12:00:00Z`));
}

function getBookingSortValue(booking) {
  const date = getBookingDateKey(booking) || "9999-12-31";
  const time = booking.start_datetime?.slice(11, 16) || booking.preferred_time || "23:59";
  return `${date}T${time}`;
}

function sortBookingsChronologically(bookings) {
  return [...bookings].sort((first, second) =>
    getBookingSortValue(first).localeCompare(getBookingSortValue(second)) ||
    String(first.created_at || "").localeCompare(String(second.created_at || ""))
  );
}

function filterAgendaBookings(bookings) {
  return bookings.filter((booking) => {
    if (selectedStaffFilter && String(booking.staff_business_user_id || "") !== selectedStaffFilter) return false;
    if (selectedBookingStatusFilter === "attention" && !["requested", "pending"].includes(booking.status)) return false;
    if (selectedBookingStatusFilter && selectedBookingStatusFilter !== "attention" && booking.status !== selectedBookingStatusFilter) return false;
    if (selectedBookingServiceFilter && String(booking.service_id || "") !== selectedBookingServiceFilter) return false;
    if (bookingCustomerSearch && !String(booking.customer_name || "").toLocaleLowerCase("es").includes(bookingCustomerSearch)) return false;
    return true;
  });
}

function getAgendaPeriodBookings(view = currentBookingView, { selectedDayOnly = true } = {}) {
  let bookings;
  if (view === "week") {
    const weekDates = getAgendaWeekDates();
    bookings = allBookings.filter((booking) => weekDates.includes(getBookingDateKey(booking)));
    if (selectedDayOnly) bookings = bookings.filter((booking) => getBookingDateKey(booking) === agendaSelectedDate);
  } else if (view === "month") {
    bookings = allBookings.filter((booking) => getBookingDateKey(booking)?.startsWith(agendaSelectedDate.slice(0, 7)));
  } else {
    bookings = allBookings.filter((booking) => getBookingDateKey(booking) === agendaSelectedDate);
  }
  return sortBookingsChronologically(filterAgendaBookings(bookings));
}

function getBookingsForView(view) {
  return getAgendaPeriodBookings(view);
}

function syncAgendaServiceFilter() {
  const filter = document.getElementById("agenda-service-filter");
  if (!filter) return;
  const services = new Map();
  adminServices.forEach((service) => services.set(String(service.id), service.name));
  allBookings.forEach((booking) => {
    if (booking.service_id && booking.service_name) services.set(String(booking.service_id), booking.service_name);
  });
  filter.innerHTML = `<option value="">Todos</option>` + Array.from(services.entries())
    .sort((first, second) => first[1].localeCompare(second[1], "es"))
    .map(([id, name]) => `<option value="${escapeHtml(id)}">${escapeHtml(name)}</option>`)
    .join("");
  filter.value = selectedBookingServiceFilter;
}

function renderAgendaHeaderAndSummary() {
  const dateLabel = document.getElementById("agenda-date-label");
  const context = document.getElementById("agenda-context-summary");
  const navigation = document.querySelector(".agenda-date-navigation");
  const weekDays = document.getElementById("agenda-week-days");
  const periodBookings = getAgendaPeriodBookings(currentBookingView, { selectedDayOnly: false });
  const pendingCount = periodBookings.filter((booking) => ["requested", "pending"].includes(booking.status)).length;
  const label = currentBookingView === "week"
      ? `${formatAgendaDate(getAgendaWeekDates()[0], { day: "numeric", month: "short" })} – ${formatAgendaDate(getAgendaWeekDates()[6], { day: "numeric", month: "short", year: "numeric" })}`
      : currentBookingView === "month"
        ? formatAgendaDate(`${agendaSelectedDate.slice(0, 7)}-01`, { month: "long", year: "numeric" })
      : formatAgendaDate(agendaSelectedDate, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  dateLabel.textContent = label;
  context.textContent = `${periodBookings.length} cita${periodBookings.length === 1 ? "" : "s"} · ${pendingCount} por confirmar`;
  navigation.hidden = false;
  weekDays.hidden = true;

  const totalPending = allBookings.filter((booking) => ["requested", "pending"].includes(booking.status)).length;
  const attention = document.getElementById("agenda-attention");
  attention.textContent = totalPending
    ? `${totalPending} solicitud${totalPending === 1 ? " espera" : "es esperan"} confirmación`
    : "Todo está revisado";
  attention.classList.toggle("agenda-attention--active", totalPending > 0);

  const metrics = {
    "agenda-stat-total": periodBookings.length,
    "agenda-stat-pending": pendingCount,
    "agenda-stat-confirmed": periodBookings.filter((booking) => booking.status === "confirmed").length,
    "agenda-stat-completed": periodBookings.filter((booking) => booking.status === "completed").length
  };
  Object.entries(metrics).forEach(([id, value]) => { document.getElementById(id).textContent = value; });
}

function renderAgendaFiltersSummary() {
  const labels = [];
  const staff = document.getElementById("booking-staff-filter");
  const status = document.getElementById("agenda-status-filter");
  const service = document.getElementById("agenda-service-filter");
  if (!isBusinessStaff() && selectedStaffFilter) labels.push(`Profesional: ${staff?.selectedOptions[0]?.textContent || "seleccionado"}`);
  if (selectedBookingStatusFilter) labels.push(`Estado: ${status?.selectedOptions[0]?.textContent || "seleccionado"}`);
  if (selectedBookingServiceFilter) labels.push(`Servicio: ${service?.selectedOptions[0]?.textContent || "seleccionado"}`);
  if (bookingCustomerSearch) labels.push("Búsqueda por cliente");
  document.getElementById("agenda-filter-count").textContent = `${labels.length} activo${labels.length === 1 ? "" : "s"}`;
  document.getElementById("agenda-active-filters").textContent = labels.length ? labels.join(" · ") : "Sin filtros adicionales.";
}

function renderAgendaWeekDays() {
  const container = document.getElementById("agenda-week-days");
  if (!container || currentBookingView !== "week") return;
  const filteredWeek = getAgendaPeriodBookings("week", { selectedDayOnly: false });
  container.innerHTML = getAgendaWeekDates().map((dateKey) => {
    const count = filteredWeek.filter((booking) => getBookingDateKey(booking) === dateKey).length;
    const active = dateKey === agendaSelectedDate;
    return `<button class="agenda-week-day${active ? " agenda-week-day--active" : ""}" type="button" data-agenda-date="${dateKey}" aria-pressed="${active}"><span>${escapeHtml(formatAgendaDate(dateKey, { weekday: "short" }))}</span><strong>${escapeHtml(formatAgendaDate(dateKey, { day: "numeric" }))}</strong><small>${count} cita${count === 1 ? "" : "s"}</small></button>`;
  }).join("");
}

function getBookingTimeRange(booking) {
  const start = booking.start_datetime?.slice(11, 16) || booking.preferred_time || "Hora pendiente";
  let end = booking.end_datetime?.slice(11, 16) || "";
  if (!end && /^\d{2}:\d{2}$/.test(start) && booking.duration_minutes) {
    const [hours, minutes] = start.split(":").map(Number);
    const endMinutes = hours * 60 + minutes + Number(booking.duration_minutes);
    end = `${String(Math.floor(endMinutes / 60) % 24).padStart(2, "0")}:${String(endMinutes % 60).padStart(2, "0")}`;
  }
  return end ? `${start}–${end}` : start;
}

function parseBusinessCivilDateTime(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/);
  if (!match) return Number.NaN;
  return Date.UTC(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
    Number(match[4]),
    Number(match[5]),
    Number(match[6] || 0)
  );
}

function getBusinessNowCivilTime() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: getBusinessTimeZone(),
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23"
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return Date.UTC(
    Number(values.year),
    Number(values.month) - 1,
    Number(values.day),
    Number(values.hour),
    Number(values.minute),
    Number(values.second)
  );
}

function bookingHasStarted(booking) {
  if (getBookingDateKey(booking) !== getMadridDateKey() || !booking.start_datetime) return false;
  const start = parseBusinessCivilDateTime(booking.start_datetime);
  const end = booking.end_datetime
    ? parseBusinessCivilDateTime(booking.end_datetime)
    : start + Number(booking.duration_minutes || 30) * 60000;
  const now = getBusinessNowCivilTime();
  return Number.isFinite(start) && Number.isFinite(end) && now >= start && now < end;
}

function formatRequestAge(createdAt) {
  if (!createdAt) return "";
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/.test(createdAt) ? createdAt : `${createdAt}Z`;
  const elapsedMinutes = Math.max(0, Math.floor((Date.now() - new Date(normalized).getTime()) / 60000));
  if (!Number.isFinite(elapsedMinutes)) return "";
  if (elapsedMinutes < 60) return `Hace ${elapsedMinutes} min`;
  if (elapsedMinutes < 1440) return `Hace ${Math.floor(elapsedMinutes / 60)} h`;
  return `Hace ${Math.floor(elapsedMinutes / 1440)} d`;
}

function renderAgendaEmptyState() {
  const hasFilters = Boolean(selectedStaffFilter || selectedBookingStatusFilter || selectedBookingServiceFilter || bookingCustomerSearch);
  if (hasFilters) {
    return `<div class="agenda-state"><strong>No hay citas con estos filtros.</strong><p>Prueba otra combinación o restablece los filtros.</p><button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="reset-agenda-filters">Restablecer filtros</button></div>`;
  }
  const changeDay = `<button class="ag-button ag-button--ghost ag-button--small" type="button" data-admin-action="navigate-agenda-date" data-direction="1">Ver día siguiente</button>`;
  const settings = isBusinessStaff() ? "" : `<button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="navigate-section" data-section="schedule">Revisar disponibilidad</button>`;
  return `<div class="agenda-state"><strong>${currentBookingView === "month" ? "No tienes citas este mes." : currentBookingView === "week" ? "No tienes citas esta semana." : "No tienes citas para este día."}</strong><p>La agenda está libre en el periodo seleccionado.</p><div class="agenda-state__actions">${changeDay}${settings}</div></div>`;
}

function navigateAgendaDate(days) {
  agendaSelectedDate = addDaysToDateKey(agendaSelectedDate, days);
  renderBookings();
}

function renderBookingCard(booking, nextBookingId) {
  const bookingId = Number(booking.id);
  if (!Number.isInteger(bookingId) || bookingId <= 0) return "";
  const isPending = ["requested", "pending"].includes(booking.status);
  const isExpiredRequest = isPending && booking.request_expired === true;
  const isStarted = bookingHasStarted(booking) && !["completed", "rejected", "cancelled", "no_show"].includes(booking.status);
  const isNext = bookingId === nextBookingId;
  const emphasis = isPending ? " booking-card--attention" : isStarted ? " booking-card--started" : isNext ? " booking-card--next" : "";
  const marker = isExpiredRequest ? "Solicitud vencida" : isPending ? "Requiere decisión" : isStarted ? "En curso" : isNext ? "Próxima cita" : "";
  const requestAge = currentBookingView === "pending" ? formatRequestAge(booking.created_at) : "";
  const duration = booking.duration_minutes ? `${Number(booking.duration_minutes)} min` : "Duración no indicada";
  const contact = booking.customer_phone ? `<p><span>Contacto</span><strong>${escapeHtml(booking.customer_phone)}</strong></p>` : "";
  return `
    <article class="booking-card agenda-booking-row${emphasis}" id="booking-${bookingId}" data-booking-id="${bookingId}">
      <div class="agenda-booking-time">
        <strong>${escapeHtml(getBookingTimeRange(booking))}</strong>
        <span>${escapeHtml(formatAgendaDate(getBookingDateKey(booking), { day: "numeric", month: "short" }))}</span>
      </div>
      <div class="agenda-booking-main">
        <div class="booking-top">
          <div class="booking-title">
            ${marker ? `<span class="agenda-booking-marker">${marker}</span>` : ""}
            <h3>${escapeHtml(booking.customer_name || "Cliente sin nombre")}</h3>
            <p>${escapeHtml(booking.service_name || "Servicio sin indicar")} · ${escapeHtml(duration)}</p>
            <p class="agenda-booking-staff">Con ${escapeHtml(booking.staff_display_name || "profesional sin asignar")}${requestAge ? ` · ${escapeHtml(requestAge)}` : ""}</p>
          </div>
          <span class="status-pill ${getStatusClass(booking.status)}">${escapeHtml(isExpiredRequest ? "Solicitud vencida" : getStatusLabel(booking.status))}</span>
        </div>
        ${renderCustomerComments(booking.notes)}
        ${renderBookingActions(booking)}
        <details class="agenda-booking-details">
          <summary>Contacto y notas</summary>
          <div class="agenda-booking-details__grid">
            ${contact}
            <p><span>Fecha y hora</span><strong>${escapeHtml(formatBookingSlot(booking))}</strong></p>
            <p><span>Profesional</span><strong>${escapeHtml(booking.staff_display_name || "Sin asignar")}</strong></p>
          </div>
          ${renderBookingCustomerMemorySection(booking)}
          <details class="booking-notes internal-notes-editor" data-internal-notes-details="${bookingId}">
            <summary>Nota interna de esta cita</summary>
            <div class="internal-notes-editor__body">
              <label>Contenido de la nota<textarea data-internal-notes="${bookingId}" rows="2">${escapeHtml(booking.internal_notes || "")}</textarea></label>
              <div class="internal-notes-editor__actions">
                <button class="btn btn-small btn-secondary" type="button" data-admin-action="save-internal-notes" data-internal-notes-action data-id="${bookingId}">Guardar nota de esta cita</button>
                ${booking.customer_memory_eligible ? `<button class="btn btn-small btn-secondary" type="button" data-admin-action="save-internal-notes-to-customer" data-internal-notes-action data-id="${bookingId}">Guardar también en notas del cliente</button>` : ""}
              </div>
            </div>
          </details>
          ${renderAttachments(booking.attachments || [])}
        </details>
        ${renderReviewRequest(booking)}
      </div>
    </article>`;
}

function bookingStartMinutes(booking) {
  const value = booking.start_datetime?.slice(11, 16) || booking.preferred_time || "";
  const match = value.match(/^(\d{2}):(\d{2})/);
  return match ? Number(match[1]) * 60 + Number(match[2]) : null;
}

function bookingVisualIcon(status) {
  if (["requested", "pending"].includes(status)) return "!";
  if (["confirmed", "completed"].includes(status)) return "✓";
  if (["cancelled", "rejected", "no_show"].includes(status)) return "×";
  return "○";
}

function agendaTimeRange(bookings) {
  const starts = bookings.map(bookingStartMinutes).filter(Number.isFinite);
  const ends = bookings.map((booking) => {
    const start = bookingStartMinutes(booking);
    return Number.isFinite(start) ? start + Number(booking.duration_minutes || 30) : null;
  }).filter(Number.isFinite);
  const startHour = starts.length ? Math.max(6, Math.min(9, Math.floor(Math.min(...starts) / 60))) : 8;
  const endHour = ends.length ? Math.min(24, Math.max(19, Math.ceil(Math.max(...ends) / 60))) : 20;
  return { startHour, endHour, rowHeight: 72 };
}

function renderAgendaTimeAxis(range) {
  return `<div class="agenda-time-axis" aria-hidden="true">${Array.from({ length: range.endHour - range.startHour + 1 }, (_item, index) => `<span style="top:${index * range.rowHeight}px">${String(range.startHour + index).padStart(2, "0")}:00</span>`).join("")}</div>`;
}

function renderAgendaBookingBlock(booking, range) {
  const start = bookingStartMinutes(booking);
  if (!Number.isFinite(start)) return "";
  const duration = Math.max(15, Number(booking.duration_minutes || 30));
  const top = Math.max(0, (start - range.startHour * 60) / 60 * range.rowHeight);
  const height = Math.max(38, duration / 60 * range.rowHeight - 3);
  const status = getStatusLabel(booking.status);
  return `<button class="agenda-time-block agenda-time-block--${escapeHtml(booking.status)}" type="button" data-agenda-booking-open="${Number(booking.id)}" style="--booking-top:${top}px;--booking-height:${height}px" aria-label="${escapeHtml(`${getBookingTimeRange(booking)}, ${booking.customer_name}, ${booking.service_name}, ${status}`)}"><span class="agenda-time-block__icon" aria-hidden="true">${bookingVisualIcon(booking.status)}</span><span class="agenda-time-block__content"><strong>${escapeHtml(booking.customer_name || "Cliente")}</strong><small>${escapeHtml(booking.service_name || "Servicio")} · ${escapeHtml(getBookingTimeRange(booking))}</small><small>${escapeHtml(booking.staff_display_name || "Sin asignar")} · ${escapeHtml(status)}</small></span></button>`;
}

function renderAgendaDayCalendar(bookings) {
  if (!bookings.length) return renderAgendaEmptyState();
  const range = agendaTimeRange(bookings);
  const laneHeight = (range.endHour - range.startHour) * range.rowHeight;
  const staff = new Map();
  bookings.forEach((booking) => {
    const key = String(booking.staff_business_user_id || "unassigned");
    if (!staff.has(key)) staff.set(key, booking.staff_display_name || "Sin asignar");
  });
  const lanes = Array.from(staff.entries());
  if (window.matchMedia("(max-width: 639px)").matches && lanes.length > 1) {
    return `<div class="agenda-mobile-staff-stack">${lanes.map(([staffId, name]) => `<section><h3>${escapeHtml(name)}</h3><div class="agenda-timeline agenda-timeline--mobile" style="--agenda-lane-height:${laneHeight}px"><div class="agenda-timeline-body">${renderAgendaTimeAxis(range)}<div class="agenda-staff-lanes"><section class="agenda-staff-lane">${Array.from({ length: range.endHour - range.startHour }, () => `<span class="agenda-hour-line"></span>`).join("")}${bookings.filter((booking) => String(booking.staff_business_user_id || "unassigned") === staffId).map((booking) => renderAgendaBookingBlock(booking, range)).join("")}</section></div></div></div></section>`).join("")}</div>`;
  }
  return `<div class="agenda-timeline agenda-timeline--day" style="--agenda-lane-height:${laneHeight}px"><div class="agenda-staff-headings" style="--agenda-staff-count:${lanes.length}">${lanes.map(([_id, name]) => `<strong>${escapeHtml(name)}</strong>`).join("")}</div><div class="agenda-timeline-body">${renderAgendaTimeAxis(range)}<div class="agenda-staff-lanes" style="--agenda-staff-count:${lanes.length}">${lanes.map(([staffId, name]) => `<section class="agenda-staff-lane" aria-label="Agenda de ${escapeHtml(name)}">${Array.from({ length: range.endHour - range.startHour }, () => `<span class="agenda-hour-line"></span>`).join("")}${bookings.filter((booking) => String(booking.staff_business_user_id || "unassigned") === staffId).map((booking) => renderAgendaBookingBlock(booking, range)).join("")}</section>`).join("")}</div></div></div>`;
}

function renderAgendaWeekCalendar(bookings) {
  if (!bookings.length) return renderAgendaEmptyState();
  const range = agendaTimeRange(bookings);
  const laneHeight = (range.endHour - range.startHour) * range.rowHeight;
  const days = getAgendaWeekDates();
  if (window.matchMedia("(max-width: 639px)").matches) {
    return `<div class="agenda-mobile-week">${days.map((dateKey) => { const items = bookings.filter((booking) => getBookingDateKey(booking) === dateKey); return `<section><button type="button" data-agenda-month-day="${dateKey}"><strong>${escapeHtml(formatAgendaDate(dateKey, { weekday: "long", day: "numeric", month: "short" }))}</strong><span>${items.length} cita${items.length === 1 ? "" : "s"}</span></button><div>${items.length ? items.map((booking) => renderAgendaBookingBlock(booking, range)).join("") : `<span class="agenda-calendar-gap">Sin citas</span>`}</div></section>`; }).join("")}</div>`;
  }
  return `<div class="agenda-timeline agenda-timeline--week" style="--agenda-lane-height:${laneHeight}px"><div class="agenda-week-headings">${days.map((dateKey) => `<button type="button" data-agenda-month-day="${dateKey}"><span>${escapeHtml(formatAgendaDate(dateKey, { weekday: "short" }))}</span><strong>${escapeHtml(formatAgendaDate(dateKey, { day: "numeric" }))}</strong></button>`).join("")}</div><div class="agenda-timeline-body">${renderAgendaTimeAxis(range)}<div class="agenda-week-lanes">${days.map((dateKey) => `<section class="agenda-week-lane" aria-label="${escapeHtml(formatAgendaDate(dateKey, { weekday: "long", day: "numeric", month: "long" }))}">${Array.from({ length: range.endHour - range.startHour }, () => `<span class="agenda-hour-line"></span>`).join("")}${bookings.filter((booking) => getBookingDateKey(booking) === dateKey).map((booking) => renderAgendaBookingBlock(booking, range)).join("")}</section>`).join("")}</div></div></div>`;
}

function renderAgendaMonthCalendar(bookings) {
  const month = agendaSelectedDate.slice(0, 7);
  const days = adminInstagramMonthGrid(agendaSelectedDate);
  const today = getMadridDateKey();
  const byDate = new Map(days.map((key) => [key, []]));
  bookings.forEach((booking) => { const key = getBookingDateKey(booking); if (byDate.has(key)) byDate.get(key).push(booking); });
  if (!bookings.length) return renderAgendaEmptyState();
  return `<div class="agenda-month-calendar"><div class="agenda-month-weekdays" aria-hidden="true">${["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"].map((day) => `<span>${day}</span>`).join("")}</div>${days.map((dateKey) => { const items = byDate.get(dateKey); const minutes = items.reduce((total, booking) => total + Number(booking.duration_minutes || 30), 0); const occupancy = Math.min(100, Math.round(minutes / 480 * 100)); const pending = items.filter((booking) => ["requested", "pending"].includes(booking.status)).length; return `<button class="agenda-month-day${dateKey.startsWith(month) ? "" : " agenda-month-day--outside"}${dateKey === today ? " agenda-month-day--today" : ""}" type="button" data-agenda-month-day="${dateKey}" aria-label="${escapeHtml(`${formatAgendaDate(dateKey, { day: "numeric", month: "long" })}: ${items.length} citas, ${occupancy}% de carga estimada${pending ? `, ${pending} pendientes` : ""}`)}"><span class="agenda-month-day__number">${escapeHtml(formatAgendaDate(dateKey, { day: "numeric" }))}</span><strong>${items.length}</strong><small>${items.length === 1 ? "cita" : "citas"}</small><span class="agenda-occupancy" aria-hidden="true"><i style="width:${occupancy}%"></i></span>${pending ? `<span class="agenda-month-attention">! ${pending}</span>` : ""}</button>`; }).join("")}</div>`;
}

function renderBookings() {
  const list = document.getElementById("bookings-list");
  if (!list) return;
  updateBookingViewTabs();
  renderAgendaHeaderAndSummary();
  renderAgendaFiltersSummary();
  renderAgendaWeekDays();
  const bookings = getAgendaPeriodBookings(currentBookingView, { selectedDayOnly: false });
  const businessNow = getBusinessNowCivilTime();
  const nextBooking = bookings.find((booking) => {
    if (!booking.start_datetime || ["completed", "rejected", "cancelled", "no_show"].includes(booking.status)) return false;
    return parseBusinessCivilDateTime(booking.start_datetime) > businessNow;
  });
  list.setAttribute("aria-busy", "false");
  const calendar = currentBookingView === "month"
    ? renderAgendaMonthCalendar(bookings)
    : currentBookingView === "week"
      ? renderAgendaWeekCalendar(bookings)
      : renderAgendaDayCalendar(bookings);
  const selected = allBookings.find((booking) => Number(booking.id) === agendaSelectedBookingId);
  syncBookingCustomerMemorySelection(selected || null);
  list.innerHTML = `${calendar}${selected ? `<section class="agenda-quick-detail" aria-label="Detalle de la cita">${renderBookingCard(selected, Number(nextBooking?.id))}</section>` : ""}`;
}

function getViewForBooking(booking) {
  return "day";
}

function goToBooking(bookingId, updateUrl = true) {
  // La ficha conserva esta navegación hasta que exista una acción backend
  // autorizada para cambiar el profesional de una reserva.
  const booking = allBookings.find((item) => item.id === bookingId);
  if (!booking) {
    alert("No se encontró la reserva solicitada.");
    return;
  }

  closeStaffRemovalModal();
  resetAgendaFilters({ render: false });
  agendaSelectedDate = getBookingDateKey(booking) || getMadridDateKey();
  currentBookingView = getViewForBooking(booking);
  agendaSelectedBookingId = bookingId;
  updateBookingViewTabs();
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

  if (!reviewRequest && !getSafeReviewUrl()) {
    return `
      <div class="review-request review-request-warning">
        <div class="review-request-header"><strong>Solicitud de reseña</strong><span class="review-status">Falta configuración</span></div>
        <p>Configura el enlace de reseñas antes de preparar una solicitud.</p>
        <button class="ag-button ag-button--secondary ag-button--small" type="button" data-growth-action="configuration-reviews">Configurar enlace</button>
      </div>
    `;
  }

  if (!reviewRequest) {
    return `
      <div class="review-request">
        <div class="review-request-header">
          <strong>Solicitud de reseña</strong>
          <span class="review-status">Puede recibir una solicitud</span>
        </div>
        <p>Prepararemos el mensaje; tú decidirás si lo copias o lo abres en WhatsApp.</p>
        <button class="ag-button ag-button--secondary ag-button--small" type="button" data-review-create="${booking.id}">
          Preparar solicitud
        </button>
      </div>
    `;
  }

  return `
    <div class="review-request">
      <div class="review-request-header">
        <strong>Solicitud de reseña</strong>
        <span class="review-status review-status-${escapeHtml(reviewRequest.status)}">
          ${escapeHtml(reviewDeliveryState(reviewRequest).label)}
        </span>
      </div>
      <p>${escapeHtml(reviewDeliveryState(reviewRequest).detail)}</p>
      <div class="review-actions">
        <button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="navigate-section" data-section="reviews">Gestionar en Crecimiento</button>
      </div>
      <p data-review-feedback="${reviewRequest.id}" class="inline-feedback"></p>
    </div>
  `;
}

function showGrowthReviewFeedback(message, isError = false, reviewRequestId = null) {
  const mainFeedback = document.getElementById("growth-reviews-feedback");
  if (mainFeedback) {
    mainFeedback.textContent = message || "";
    mainFeedback.className = `inline-feedback ${message ? (isError ? "error" : "success") : ""}`;
  }
  if (reviewRequestId) document.querySelectorAll(`[data-review-feedback="${reviewRequestId}"]`).forEach((feedback) => {
    feedback.textContent = message || "";
    feedback.className = `inline-feedback ${message ? (isError ? "error" : "success") : ""}`;
  });
}

async function createReviewRequest(bookingId) {
  const booking = allBookings.find((item) => item.id === bookingId);
  if (!booking || booking.status !== "completed") return showGrowthReviewFeedback("Esta reserva no está disponible para solicitar una reseña.", true);
  const reviewUrl = getSafeReviewUrl();
  if (!reviewUrl) return showGrowthReviewFeedback("Configura primero un enlace de reseñas válido.", true);
  const confirmed = window.confirm(`Preparar solicitud de reseña\n\nCliente: ${booking.customer_name || "Cliente sin nombre"}\nCanal: ${hasUsableReviewPhone(booking) ? "WhatsApp asistido" : "Copia manual"}\nEntrega: la enviarás tú; AutonoGrow no la marcará como enviada.\nDestino: ${reviewUrl}`);
  if (!confirmed) return;
  const mutationKey = `review-create:${bookingId}`;
  if (reviewMutationKeys.has(mutationKey) || reviewRequestsByBooking.has(bookingId)) return;
  reviewMutationKeys.add(mutationKey);
  document.querySelectorAll(`[data-review-create="${bookingId}"]`).forEach((button) => { button.disabled = true; });
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/bookings/${bookingId}/review-request`,
      { method: "POST" }
    );
    const result = await response.json().catch(() => null);

    if (response.status === 429) throw new Error(adminRateLimitMessage(response));
    if (!response.ok) {
      throw new Error("review_request_failed");
    }

    reviewRequestsByBooking.set(bookingId, result.review_request);
    replaceOutboxMessage(result.outbox_message);
    renderReviewStats();
    renderReviewRequests();
    renderBookings();
    renderGrowth();
    await requestAdminRefresh(["operations"]);
    showGrowthReviewFeedback("Solicitud preparada. Puedes copiar el mensaje o abrirlo en WhatsApp.");
  } catch (error) {
    console.error(error);
    showGrowthReviewFeedback(error.message?.startsWith("Hay demasiadas solicitudes")
      ? error.message
      : "No pudimos preparar la solicitud. Comprueba el enlace y vuelve a intentarlo.", true);
  } finally {
    reviewMutationKeys.delete(mutationKey);
    document.querySelectorAll(`[data-review-create="${bookingId}"]`).forEach((button) => { button.disabled = false; });
  }
}

async function openReviewWhatsApp(reviewRequestId) {
  const reviewRequest = Array.from(reviewRequestsByBooking.values())
    .find((item) => item.id === reviewRequestId);
  if (!reviewRequest) {
    return showGrowthReviewFeedback("No se encontró la solicitud de reseña.", true);
  }
  if (["sent", "skipped"].includes(reviewRequest.status)) return;
  const reviewUrl = isSafePublicUrl(reviewRequest.reviews_url) ? reviewRequest.reviews_url : "";
  const confirmed = window.confirm(`Abrir solicitud en WhatsApp\n\nCliente: ${reviewRequest.customer_name || "Cliente sin nombre"}\nCanal: WhatsApp asistido\nEntrega: se abrirá WhatsApp para que tú envíes el mensaje.\nDestino: ${reviewUrl || "Enlace guardado en la solicitud"}`);
  if (!confirmed) return;
  const mutationKey = `review-open:${reviewRequestId}`;
  if (reviewMutationKeys.has(mutationKey)) return;
  reviewMutationKeys.add(mutationKey);
  document.querySelectorAll(`[data-review-open="${reviewRequestId}"]`).forEach((button) => { button.disabled = true; });
  const whatsappWindow = openBlankWhatsAppWindow();

  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/bookings/${reviewRequest.booking_id}/review-request`,
      { method: "POST" }
    );
    const result = await response.json().catch(() => null);

    if (response.status === 429) throw new Error(adminRateLimitMessage(response));
    if (!response.ok) {
      throw new Error("review_request_open_failed");
    }

    reviewRequestsByBooking.set(reviewRequest.booking_id, result.review_request);
    replaceOutboxMessage(result.outbox_message);
    renderReviewStats();
    renderReviewRequests();
    renderBookings();
    renderGrowth();
    const opened = await openPreparedWhatsAppMessage(result.outbox_message, whatsappWindow);
    if (opened) showGrowthReviewFeedback("WhatsApp abierto. La solicitud todavía no está marcada como enviada.", false, reviewRequestId);
  } catch (error) {
    whatsappWindow?.close();
    console.error(error);
    showGrowthReviewFeedback(error.message?.startsWith("Hay demasiadas solicitudes")
      ? error.message
      : "No pudimos abrir WhatsApp. Comprueba el canal y vuelve a intentarlo.", true, reviewRequestId);
  } finally {
    reviewMutationKeys.delete(mutationKey);
    document.querySelectorAll(`[data-review-open="${reviewRequestId}"]`).forEach((button) => { button.disabled = false; });
  }
}

async function copyReviewMessage(reviewRequestId) {
  const reviewRequest = Array.from(reviewRequestsByBooking.values())
    .find((item) => item.id === reviewRequestId);

  if (!reviewRequest || ["sent", "skipped"].includes(reviewRequest.status)) return;
  const mutationKey = `review-copy:${reviewRequestId}`;
  if (reviewMutationKeys.has(mutationKey)) return;
  reviewMutationKeys.add(mutationKey);
  document.querySelectorAll(`[data-review-copy="${reviewRequestId}"]`).forEach((button) => { button.disabled = true; });
  let copied = false;

  try {
    await navigator.clipboard.writeText(reviewRequest.message);
    copied = true;
    const statusSaved = await updateReviewRequestStatus(reviewRequestId, "copied", false);
    if (!statusSaved) throw new Error("review_copy_status_failed");
    showGrowthReviewFeedback("Mensaje copiado. La solicitud todavía no está marcada como enviada.", false, reviewRequestId);
  } catch (error) {
    console.error(error);
    if (copied) {
      showGrowthReviewFeedback("El mensaje se copió, pero no pudimos guardar el estado. Actualiza y vuelve a intentarlo.", true, reviewRequestId);
    } else {
      const textareas = document.querySelectorAll(`[data-review-fallback="${reviewRequestId}"]`);
      textareas.forEach((textarea) => textarea.classList.add("visible"));
      const visibleTextarea = Array.from(textareas).find((textarea) => textarea.offsetParent !== null) || textareas[0];
      visibleTextarea?.focus();
      visibleTextarea?.select();
      showGrowthReviewFeedback("No se pudo copiar automáticamente. Selecciona el mensaje para copiarlo manualmente.", true, reviewRequestId);
    }
  } finally {
    reviewMutationKeys.delete(mutationKey);
    document.querySelectorAll(`[data-review-copy="${reviewRequestId}"]`).forEach((button) => { button.disabled = false; });
  }
}

async function updateReviewRequestStatus(reviewRequestId, status, showFeedback = true) {
  if (!["copied", "sent", "skipped"].includes(status)) return false;
  const reviewRequest = Array.from(reviewRequestsByBooking.values()).find((item) => item.id === reviewRequestId);
  if (!reviewRequest) return false;
  if (showFeedback && status === "sent" && !window.confirm("Marca esta solicitud como enviada solo si ya enviaste el mensaje. Esto no confirma que el cliente haya publicado una reseña.")) return false;
  if (showFeedback && status === "skipped" && !window.confirm("Omitir esta solicitud la cerrará sin marcarla como enviada. ¿Continuar?")) return false;
  const mutationKey = `review-status:${reviewRequestId}`;
  if (reviewMutationKeys.has(mutationKey)) return false;
  reviewMutationKeys.add(mutationKey);
  document.querySelectorAll(`[data-review-request="${reviewRequestId}"]`).forEach((button) => { button.disabled = true; });
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/review-requests/${reviewRequestId}/status`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status })
      }
    );
    const result = await response.json().catch(() => null);
    if (!response.ok || !result?.review_request) throw new Error("review_status_failed");
    reviewRequestsByBooking.set(result.review_request.booking_id, result.review_request);
    renderReviewStats();
    renderBookings();
    renderGrowth();
    renderDashboard();
    if (showFeedback) showGrowthReviewFeedback(status === "sent" ? "Solicitud marcada como enviada. Esto no confirma una reseña publicada." : "Solicitud omitida.", false, reviewRequestId);
    requestAdminRefresh(["operations"]);
    return true;
  } catch (error) {
    console.error(error);
    if (showFeedback) showGrowthReviewFeedback("No pudimos actualizar la solicitud. Inténtalo de nuevo.", true, reviewRequestId);
    return false;
  } finally {
    reviewMutationKeys.delete(mutationKey);
    document.querySelectorAll(`[data-review-request="${reviewRequestId}"]`).forEach((button) => { button.disabled = false; });
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

function renderCustomerComments(notes) {
  return `
    <section class="booking-customer-comments" aria-label="Comentarios del cliente">
      <strong>Comentarios del cliente:</strong>
      <p>${notes ? escapeHtml(notes) : "Sin comentarios."}</p>
    </section>`;
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
  const bookingId = Number(booking.id);
  const busy = bookingMutationIds.has(bookingId);
  const button = (label, action, className, description = "") => `
    <button class="ag-button ag-button--small ${className}" type="button" data-booking-action="${action}" data-booking-id="${bookingId}" data-action-allowed="true" ${busy ? "disabled aria-busy=\"true\"" : ""}${description ? ` title="${escapeHtml(description)}"` : ""}>${label}</button>`;
  let actions = [];

  if (["requested", "pending"].includes(booking.status)) {
    actions = [
      ...(booking.request_expired ? [] : [button("Confirmar", "confirmed", "ag-button--primary")]),
      ...(booking.service_id ? [button("Reagendar", "reschedule", "ag-button--secondary", "Muestra únicamente huecos disponibles")] : []),
      button("Rechazar", "rejected", "ag-button--danger-ghost")
    ];
  } else if (booking.status === "confirmed") {
    actions = [
      button("Completar", "completed", "ag-button--primary"),
      ...(booking.service_id ? [button("Reagendar", "reschedule", "ag-button--secondary", "Muestra únicamente huecos disponibles")] : []),
      button("Cancelar", "cancelled", "ag-button--danger-ghost"),
      button("No presentado", "no_show", "ag-button--ghost")
    ];
  }

  return actions.length ? `<div class="booking-actions" aria-label="Acciones de la reserva">${actions.join("")}</div>` : "";
}

function setBookingMutationBusy(bookingId, busy) {
  if (busy) bookingMutationIds.add(bookingId);
  else bookingMutationIds.delete(bookingId);
  document.querySelectorAll(`[data-booking-id="${bookingId}"][data-booking-action]`).forEach((button) => {
    button.disabled = busy || button.dataset.actionAllowed !== "true";
    button.toggleAttribute("aria-busy", busy);
  });
}

function setInternalNotesBusy(bookingId, busy) {
  document.querySelectorAll(`[data-internal-notes-action][data-id="${bookingId}"]`).forEach((button) => {
    button.disabled = busy;
    button.toggleAttribute("aria-busy", busy);
  });
}

async function saveInternalNotes(bookingId, { copyToCustomerMemory = false } = {}) {
  const field = document.querySelector(`[data-internal-notes="${bookingId}"]`);
  const booking = allBookings.find((item) => Number(item.id) === bookingId);
  if (!field || !booking) return alert("No se encontró la cita.");
  const note = field.value.trim();
  if (copyToCustomerMemory && (!booking.customer_memory_eligible || !Number(booking.customer_id))) {
    return alert("Esta cita no pertenece a un cliente registrado.");
  }
  if (copyToCustomerMemory && !note) {
    return alert("Escribe una nota antes de guardarla también en las notas del cliente.");
  }
  setInternalNotesBusy(bookingId, true);
  let bookingSaved = false;
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/bookings/${bookingId}/internal-notes`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ internal_notes: note || null })
    });
    const result = await response.json().catch(() => null);
    if (!response.ok) return alert(safeConfigurationError(result, "No se pudo guardar la nota interna de esta cita."));
    const index = allBookings.findIndex((item) => item.id === bookingId);
    if (index >= 0) allBookings[index] = { ...allBookings[index], ...result.booking };
    bookingSaved = true;
    if (!copyToCustomerMemory) {
      alert("Nota interna de esta cita guardada.");
      return;
    }
    const customerId = Number(booking.customer_id);
    const memoryResponse = await customerMemoryRequest(`${API_BASE_URL}/api/admin/businesses/${getBusinessSlug()}/customers/${customerId}/memory`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category: "operational_note", key: "note", value: note, source_type: "manual" })
    });
    const memoryResult = await readAdminResponseBody(memoryResponse);
    if (!memoryResponse.ok) {
      return alert(safeConfigurationError(memoryResult, "La nota interna se guardó en la cita, pero no se pudo copiar a las notas del cliente."));
    }
    customerMemorySummaries.delete(customerId);
    const conversationMemoryVisible = selectedConversation
      && Number(selectedConversation.customer_id) === customerId;
    if (
      (bookingCustomerMemoryPanelState.open && bookingCustomerMemoryPanelState.customerId === customerId)
      || conversationMemoryVisible
    ) {
      await loadCustomerMemorySummary(customerId, { force: true });
    }
    alert("Nota interna guardada en esta cita y también en las notas del cliente.");
  } catch (_error) {
    alert(bookingSaved
      ? "La nota interna se guardó en la cita, pero no se pudo copiar a las notas del cliente."
      : "No se pudo guardar la nota interna de esta cita.");
  } finally {
    setInternalNotesBusy(bookingId, false);
  }
}

function rescheduleBooking(bookingId) {
  if (bookingMutationIds.has(bookingId)) return;
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
  rescheduleReturnFocus = document.activeElement;
  rescheduleSubmitting = false;
  rescheduleSlotsLoadVersion += 1;

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
      <p><strong>Duración:</strong> ${booking.duration_minutes ? `${Number(booking.duration_minutes)} min` : "No indicada"}</p>
      <p><strong>Profesional:</strong> ${escapeHtml(booking.staff_display_name || "Sin asignar")}</p>
    </div>
    <div>
      <p class="calendar-title">1. Elige un día</p>
      <div id="reschedule-days" class="calendar-days"></div>
    </div>
    <div>
      <p class="calendar-title">2. Elige un hueco disponible</p>
      <div id="reschedule-slots" class="reschedule-slots" aria-live="polite" aria-busy="false">
        <p class="empty-state">Selecciona primero un día.</p>
      </div>
    </div>
    <div id="reschedule-selection-summary" class="reschedule-selection-summary" hidden></div>
    <p id="reschedule-feedback" class="inline-feedback" role="status" aria-live="polite"></p>
    <button id="confirm-reschedule-button" class="btn btn-primary btn-full" type="button" disabled>
      Confirmar cambio
    </button>
  `;

  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-scroll-locked");
  renderRescheduleDays();
  document.getElementById("confirm-reschedule-button").addEventListener("click", confirmSelectedReschedule);
  window.requestAnimationFrame(() => modal.querySelector(".ag-modal__close")?.focus());
}

function renderRescheduleDays() {
  const container = document.getElementById("reschedule-days");
  container.innerHTML = "";

  getNextDays(availabilitySettings?.max_days_ahead || 21).forEach((day) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "calendar-day";
    button.setAttribute("aria-pressed", "false");

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
      document.getElementById("reschedule-selection-summary").hidden = true;
      document.getElementById("reschedule-feedback").textContent = "";
      document.querySelectorAll("#reschedule-days .calendar-day").forEach((item) => {
        item.classList.remove("active");
        item.setAttribute("aria-pressed", "false");
      });
      button.classList.add("active");
      button.setAttribute("aria-pressed", "true");
      await loadRescheduleSlots();
    });

    container.appendChild(button);
  });
}

async function loadRescheduleSlots() {
  const container = document.getElementById("reschedule-slots");
  const booking = rescheduleState.booking;
  const requestedDate = rescheduleState.date;
  const loadVersion = ++rescheduleSlotsLoadVersion;
  container.setAttribute("aria-busy", "true");
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
    if (loadVersion !== rescheduleSlotsLoadVersion || requestedDate !== rescheduleState.date) return;
    container.setAttribute("aria-busy", "false");
    renderRescheduleSlots(data.slots || []);
  } catch (error) {
    if (loadVersion !== rescheduleSlotsLoadVersion) return;
    console.error(error);
    container.setAttribute("aria-busy", "false");
    container.innerHTML = `<div class="agenda-state agenda-state--error" role="alert"><strong>No pudimos cargar los huecos.</strong><p>Vuelve a intentarlo para consultar la disponibilidad real.</p><button class="ag-button ag-button--secondary ag-button--small" type="button" data-admin-action="retry-reschedule-slots">Reintentar</button></div>`;
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
    button.setAttribute("aria-pressed", "false");

    button.addEventListener("click", () => {
      rescheduleState.slot = slot;
      document.querySelectorAll("#reschedule-slots .time-slot").forEach((item) => {
        item.classList.remove("active");
        item.setAttribute("aria-pressed", "false");
      });
      button.classList.add("active");
      button.setAttribute("aria-pressed", "true");
      document.getElementById("confirm-reschedule-button").disabled = false;
      renderRescheduleSelectionSummary();
    });

    container.appendChild(button);
  });
}

function renderRescheduleSelectionSummary() {
  const summary = document.getElementById("reschedule-selection-summary");
  if (!summary || !rescheduleState.slot) return;
  summary.hidden = false;
  summary.innerHTML = `<strong>Revisa el cambio</strong><p>${escapeHtml(rescheduleState.dayLabel)} a las ${escapeHtml(rescheduleState.slot.label)}</p>`;
}

async function confirmSelectedReschedule() {
  const { booking, slot, dayLabel } = rescheduleState;

  if (rescheduleSubmitting) return;
  if (!booking || !slot) {
    alert("Selecciona un hueco disponible.");
    return;
  }

  const confirmed = window.confirm(`Confirmar cambio de horario\n\n${booking.customer_name} · ${booking.service_name}\n${dayLabel} a las ${slot.label}\n\nLa cita conservará su duración y el hueco anterior volverá a estar disponible.`);

  if (!confirmed) {
    return;
  }

  rescheduleSubmitting = true;
  setBookingMutationBusy(Number(booking.id), true);
  const confirmButton = document.getElementById("confirm-reschedule-button");
  const feedback = document.getElementById("reschedule-feedback");
  confirmButton.disabled = true;
  confirmButton.setAttribute("aria-busy", "true");
  confirmButton.textContent = "Guardando cambio...";
  feedback.textContent = "Guardando el nuevo horario...";
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
      feedback.className = "inline-feedback error";
      feedback.textContent = response.status === 409
        ? "Ese hueco acaba de dejar de estar disponible. Selecciona otro horario."
        : "No se pudo guardar el cambio. Revisa la disponibilidad y vuelve a intentarlo.";
      rescheduleState.slot = null;
      document.getElementById("reschedule-selection-summary").hidden = true;
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
    feedback.className = "inline-feedback error";
    feedback.textContent = "No se pudo guardar el cambio. Comprueba la conexión y vuelve a intentarlo.";
  } finally {
    rescheduleSubmitting = false;
    setBookingMutationBusy(Number(booking.id), false);
    if (confirmButton?.isConnected) {
      confirmButton.removeAttribute("aria-busy");
      confirmButton.textContent = "Confirmar cambio";
      confirmButton.disabled = !rescheduleState.slot;
    }
  }
}

function getNextDays(count) {
  const days = [];
  const today = getMadridDateKey();

  for (let index = 0; index < count; index += 1) {
    const date = addDaysToDateKey(today, index);
    days.push({
      date,
      day_label: formatAgendaDate(date, { weekday: "short", day: "2-digit", month: "short" }).replace(",", "")
    });
  }

  return days;
}

function closeRescheduleModal() {
  const modal = document.getElementById("reschedule-modal");
  if (!modal?.classList.contains("open")) return;
  rescheduleSlotsLoadVersion += 1;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
  document.body.classList.remove("modal-scroll-locked");
  const returnFocus = rescheduleReturnFocus;
  rescheduleReturnFocus = null;
  if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
}

function handleRescheduleModalKeydown(event) {
  const staffModal = document.getElementById("staff-removal-modal");
  if (staffModal?.classList.contains("open")) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeStaffRemovalModal();
      return;
    }
    if (event.key === "Tab") trapModalFocus(event, staffModal);
    return;
  }
  const modal = document.getElementById("reschedule-modal");
  if (!modal?.classList.contains("open")) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeRescheduleModal();
    return;
  }
  if (event.key !== "Tab") return;
  trapModalFocus(event, modal);
}

function trapModalFocus(event, modal) {
  const focusable = Array.from(modal.querySelectorAll("button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex='-1'])"))
    .filter((element) => !element.hidden && element.getClientRects().length > 0);
  if (!focusable.length) {
    event.preventDefault();
    modal.querySelector(".ag-modal")?.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

async function updateBookingStatus(bookingId, status) {
  if (bookingMutationIds.has(bookingId)) return;
  const slug = getBusinessSlug();
  const booking = allBookings.find((item) => item.id === bookingId)
    || bookingCloseTasks.find((item) => item.id === bookingId);
  if (!booking) return alert("No se encontró la reserva.");
  const bookingDescription = `${booking.customer_name} · ${booking.service_name}\n${formatBookingSlot(booking)}`;
  const confirmMessages = {
    confirmed: `Confirmar reserva\n\n${bookingDescription}\n\nSe preparará la confirmación para el cliente.`,
    rejected: `Rechazar reserva\n\n${bookingDescription}\n\nLa solicitud quedará rechazada y el hueco volverá a estar disponible.`,
    cancelled: `Cancelar cita\n\n${bookingDescription}\n\nLa cita quedará cancelada y el hueco volverá a estar disponible.`,
    completed: `Marcar como completada\n\n${bookingDescription}\n\nLa cita pasará al historial y podrá continuar el flujo de reseña.`,
    no_show: `Marcar como no presentado\n\n${bookingDescription}\n\nLa cita se cerrará como no presentada.`
  };
  const confirmed = window.confirm(confirmMessages[status] || `Cambiar estado de la reserva\n\n${bookingDescription}`);

  if (!confirmed) {
    return;
  }

  setBookingMutationBusy(bookingId, true);
  const shouldOpenWhatsApp = ["confirmed", "rejected", "completed"].includes(status);
  const whatsappWindow = shouldOpenWhatsApp ? openBlankWhatsAppWindow() : null;

  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/businesses/${slug}/bookings/${bookingId}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status })
    });

    const result = await response.json().catch(() => null);

    if (response.status === 429) throw new Error(adminRateLimitMessage(response));
    if (!response.ok) {
      throw new Error(safeConfigurationError(result, "No se pudo cambiar el estado de la cita."));
    }

    if (["completed", "no_show", "cancelled", "rejected"].includes(status)) {
      bookingCloseTasks = bookingCloseTasks.filter((item) => item.id !== bookingId);
      renderDashboard();
    }

    if (result?.already_in_status) {
      whatsappWindow?.close();
    } else if (shouldOpenWhatsApp) {
      if (result?.outbox_message) {
        await openPreparedWhatsAppMessage(result.outbox_message, whatsappWindow);
      } else {
        whatsappWindow?.close();
        alert(safeConfigurationError(
          { detail: result?.review_request_warning },
          "No se pudo preparar el mensaje de WhatsApp."
        ));
      }
    }

    await refreshOperationalData();
  } catch (error) {
    whatsappWindow?.close();
    console.error(error);
    alert(error.message || "No se pudo conectar con el backend.");
  } finally {
    setBookingMutationBusy(bookingId, false);
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
    requested: "Solicitud nueva",
    pending: "Por confirmar",
    confirmed: "Confirmada",
    completed: "Completada",
    rejected: "Rechazada",
    cancelled: "Cancelada",
    no_show: "No presentado"
  };

  return labels[status] || "Estado no disponible";
}

function formatDateTime(value) {
  if (!value) {
    return "No disponible";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "No disponible";
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

function syncConversationCustomerPanelMode() {
  const panel = document.getElementById("conversation-customer-panel");
  const backdrop = document.getElementById("conversation-customer-backdrop");
  if (!panel) return;
  const drawerMode = window.matchMedia("(max-width: 1599px)").matches;
  panel.setAttribute("aria-hidden", String(drawerMode && !conversationCustomerPanelOpen));
  if (!drawerMode) {
    backdrop?.setAttribute("hidden", "");
    document.body.classList.remove("conversation-drawer-open");
  } else if (conversationCustomerPanelOpen) {
    backdrop?.removeAttribute("hidden");
    document.body.classList.add("conversation-drawer-open");
  }
}

function setupConversationInterface() {
  const detail = document.getElementById("conversation-detail");
  document.querySelectorAll("[data-conversation-quick-filter]").forEach((button) => {
    button.addEventListener("click", () => applyConversationQuickFilter(button.dataset.conversationQuickFilter));
  });
  document.getElementById("conversation-reset-filters").addEventListener("click", resetConversationFilters);
  document.getElementById("conversation-customer-close").addEventListener("click", () => closeConversationCustomerPanel());
  document.getElementById("conversation-customer-backdrop").addEventListener("click", () => closeConversationCustomerPanel());
  document.addEventListener("submit", (event) => {
    if (event.target?.id !== "customer-memory-form") return;
    event.preventDefault();
    void submitCustomerMemoryForm(event.target);
  });
  detail.addEventListener("input", (event) => {
    if (event.target.id === "conversation-reply-body") resizeConversationReplyTextarea(event.target);
  });
  detail.addEventListener("scroll", (event) => {
    if (event.target.id !== "conversation-thread") return;
    const distanceFromBottom = event.target.scrollHeight - event.target.scrollTop - event.target.clientHeight;
    if (distanceFromBottom <= 80) document.getElementById("conversation-new-messages")?.setAttribute("hidden", "");
  }, true);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && conversationCustomerPanelOpen) {
      event.preventDefault();
      closeConversationCustomerPanel();
      return;
    }
    if (event.key !== "Tab" || !conversationCustomerPanelOpen || !window.matchMedia("(max-width: 1599px)").matches) return;
    const panel = document.getElementById("conversation-customer-panel");
    const focusable = [...panel.querySelectorAll("button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])")];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  window.addEventListener("resize", syncConversationCustomerPanelMode);
  syncConversationCustomerPanelMode();
}

function setupAdminDelegatedActions() {
  document.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) return;
    const button = event.target.closest("button[data-admin-action], button[data-booking-action]");
    if (!button || button.disabled) return;
    const bookingAction = button.dataset.bookingAction;
    if (bookingAction) {
      const bookingId = Number(button.dataset.bookingId);
      if (!Number.isInteger(bookingId)) return;
      if (bookingAction === "reschedule") rescheduleBooking(bookingId);
      else if (["confirmed", "rejected", "cancelled", "completed", "no_show"].includes(bookingAction)) {
        updateBookingStatus(bookingId, bookingAction);
      }
      return;
    }

    const action = button.dataset.adminAction;
    const id = Number(button.dataset.id);
    const index = Number(button.dataset.index);
    if (action === "navigate-section") showAdminSection(button.dataset.section);
    else if (action === "add-exception-window") addExceptionWindow();
    else if (action === "close-reschedule") closeRescheduleModal();
    else if (action === "close-staff-removal") closeStaffRemovalModal();
    else if (action === "retry-availability-settings") loadAvailabilitySettings();
    else if (action === "add-schedule-window") addScheduleWindow(button.dataset.day);
    else if (action === "remove-window-row") removeWindowRow(button);
    else if (action === "retry-availability-exceptions") loadAvailabilityExceptions();
    else if (action === "remove-exception-window" && Number.isInteger(index)) removeExceptionWindow(index);
    else if (action === "focus-control") document.getElementById(button.dataset.control)?.focus();
    else if (action === "delete-availability-exception" && Number.isInteger(id)) deleteAvailabilityException(id);
    else if (action === "retry-gallery") loadAdminGallery();
    else if (action === "retry-services") loadAdminServices();
    else if (action === "save-service" && Number.isInteger(id)) saveAdminService(id);
    else if (action === "retry-staff") loadStaffMembers();
    else if (action === "remove-staff" && Number.isInteger(id)) removeStaffMember(id);
    else if (action === "save-staff" && Number.isInteger(id)) saveStaffMember(id);
    else if (action === "edit-staff-schedule" && Number.isInteger(id)) editStaffSchedule(id);
    else if (action === "reactivate-staff" && Number.isInteger(id)) reactivateStaffMember(id);
    else if (action === "go-to-booking" && Number.isInteger(id)) goToBooking(id);
    else if (action === "retry-bookings") loadBookings();
    else if (action === "reset-conversation-filters") resetConversationFilters();
    else if (action === "retry-conversations") loadConversations();
    else if (action === "select-conversation" && Number.isInteger(id)) selectConversation(id);
    else if (action === "send-conversation-reply") sendConversationReply();
    else if (action === "open-conversation-whatsapp") openConversationWhatsApp();
    else if (action === "fill-conversation-reply" && Number.isInteger(id)) fillConversationReply(id);
    else if (action === "send-conversation-suggestion" && Number.isInteger(id)) sendConversationSuggestion(id);
    else if (action === "modify-conversation-suggestion" && Number.isInteger(id)) modifyConversationSuggestion(id);
    else if (action === "dismiss-conversation-suggestion" && Number.isInteger(id)) dismissConversationSuggestion(id);
    else if (action === "open-conversation-customer-panel") openConversationCustomerPanel(button);
    else if (action === "open-conversation-customer-search") openConversationCustomerSearch();
    else if (action === "search-conversation-customers") void searchConversationCustomers();
    else if (action === "associate-conversation-customer" && Number.isInteger(id)) void updateConversationCustomer(id);
    else if (action === "detach-conversation-customer") void updateConversationCustomer(null);
    else if (action === "add-customer-memory" && Number.isInteger(id)) openCustomerMemoryForm("create", id);
    else if (action === "retry-customer-memory" && Number.isInteger(id)) {
      customerMemorySummaries.delete(id);
      void loadCustomerMemorySummary(id, { force: true });
    }
    else if (action === "cancel-customer-memory-form") {
      customerMemoryFormState = null;
      if (selectedConversation) renderConversationCustomerPanel(selectedConversation);
    }
    else if (action === "edit-customer-memory" && Number.isInteger(id)) openCustomerMemoryForm("edit", Number(button.dataset.customerId), id);
    else if (action === "supersede-customer-memory" && Number.isInteger(id)) openCustomerMemoryForm("supersede", Number(button.dataset.customerId), id);
    else if (action === "obsolete-customer-memory" && Number.isInteger(id)) void mutateCustomerMemory("obsolete", Number(button.dataset.customerId), id);
    else if (action === "delete-customer-memory" && Number.isInteger(id)) void mutateCustomerMemory("delete", Number(button.dataset.customerId), id);
    else if (action === "change-conversation-status" && ["pending", "replied", "closed"].includes(button.dataset.status)) changeConversationStatus(button.dataset.status);
    else if (action === "toggle-conversation-automation") toggleConversationAutomation(button.dataset.active === "true");
    else if (action === "scroll-conversation-bottom") scrollConversationThreadToBottom();
    else if (action === "save-conversation-template" && Number.isInteger(id)) saveConversationTemplate(id);
    else if (action === "delete-conversation-template" && Number.isInteger(id)) deleteConversationTemplate(id);
    else if (action === "save-conversation-automation-settings") saveConversationAutomationSettings();
    else if (action === "save-conversation-automation-rule") saveConversationAutomationRule(button.dataset.intent);
    else if (action === "open-whatsapp-message" && Number.isInteger(id)) openWhatsAppMessage(id);
    else if (action === "update-outbox-status" && Number.isInteger(id) && ["sent", "skipped"].includes(button.dataset.status)) updateOutboxStatus(id, button.dataset.status);
    else if (action === "reset-agenda-filters") resetAgendaFilters();
    else if (action === "navigate-agenda-date") navigateAgendaDate(Number(button.dataset.direction));
    else if (action === "toggle-booking-customer-memory" && Number.isInteger(id)) toggleBookingCustomerMemory(id, Number(button.dataset.customerId));
    else if (action === "add-booking-customer-memory" && Number.isInteger(id)) openBookingCustomerMemoryForm(id, Number(button.dataset.customerId));
    else if (action === "close-booking-customer-memory-form" && Number.isInteger(id)) closeBookingCustomerMemoryForm(id);
    else if (action === "retry-booking-customer-memory" && Number.isInteger(id)) {
      const customerId = Number(button.dataset.customerId);
      customerMemorySummaries.delete(customerId);
      resetBookingCustomerMemoryTimer();
      void loadCustomerMemorySummary(customerId, { force: true });
    }
    else if (action === "save-internal-notes" && Number.isInteger(id)) saveInternalNotes(id);
    else if (action === "save-internal-notes-to-customer" && Number.isInteger(id)) saveInternalNotes(id, { copyToCustomerMemory: true });
    else if (action === "retry-reschedule-slots") loadRescheduleSlots();
  });

  document.addEventListener("change", (event) => {
    if (!(event.target instanceof HTMLInputElement)) return;
    const action = event.target.dataset.adminChange;
    const index = Number(event.target.dataset.index);
    const id = Number(event.target.dataset.id);
    if (action === "toggle-day-closed") toggleDayClosed(event.target.dataset.day, event.target.checked);
    else if (action === "update-exception-window" && Number.isInteger(index)) updateExceptionWindow(index, event.target.dataset.field, event.target.value);
    else if (action === "toggle-staff-services" && Number.isInteger(id)) toggleStaffServiceControls(id, event.target.checked);
  });
}

function adminInstagramApi() {
  return `${API_BASE_URL}/api/admin/businesses/${encodeURIComponent(getBusinessSlug())}/instagram-content`;
}

function socialContentProposalsApi() {
  return `${API_BASE_URL}/api/admin/businesses/${encodeURIComponent(getBusinessSlug())}/social-content-proposals`;
}

function socialContentLabel(kind, value) {
  const labels = {
    priority: { high: "Alta prioridad", normal: "Prioridad normal", low: "Prioridad baja" },
    objective: { increase_bookings: "aumentar reservas", reactivate_customers: "favorecer el retorno", promote_service: "dar visibilidad al servicio", seasonal_activation: "activar una ventana estacional", social_proof: "generar prueba social", educate: "educar", engagement: "generar interacción", fill_capacity: "llenar agenda" },
    format: { story: "Story", reel: "Reel", carousel: "Carrusel", static_post: "Post estático" },
    angle: { availability: "disponibilidad", before_after: "antes y después", process: "proceso", faq: "pregunta frecuente", benefit: "beneficio general", testimonial: "testimonio", seasonal: "estacional", limited_window: "ventana limitada", educational: "educativo", behind_the_scenes: "entre bastidores" },
    cta: { book_now: "Reservar", check_availability: "Consultar disponibilidad", contact_us: "Contactar", learn_more: "Saber más", discover_service: "Descubrir servicio", none: "Sin CTA" }
  };
  return labels[kind]?.[value] || value;
}

function renderSocialContentProposals() {
  const container = document.getElementById("social-content-ideas-list");
  if (!socialContentProposals.length) {
    container.innerHTML = `<div class="conversation-state conversation-state--compact"><strong>No hay decisiones pendientes</strong><p>Solo aparecerán aquí promociones u otras decisiones comerciales que necesiten tu respuesta.</p></div>`;
    return;
  }
  container.innerHTML = socialContentProposals.map((item) => {
    const busy = socialContentProposalMutationIds.has(item.id);
    const presentation = item.presentation || {};
    const title = presentation.title || item.service?.name || "Idea para tu negocio";
    const promotion = item.idea_review?.promotion;
    const promotionRevision = promotion?.revisions?.[promotion.revisions.length - 1];
    return `<article class="instagram-content-card" data-social-content-proposal="${item.id}"><header><div><h4>${escapeHtml(title)}</h4><p>Necesitamos tu aprobación para publicar estas condiciones económicas.</p></div><span class="ag-badge ag-badge--neutral">Promoción</span></header><div class="ag-alert ag-alert--info"><strong>Revisión ${promotionRevision.revision_number}</strong><p>${escapeHtml(promotionRevision.regular_price)} ${escapeHtml(promotionRevision.currency)} → ${escapeHtml(promotionRevision.promotional_price)} ${escapeHtml(promotionRevision.currency)}, del ${escapeHtml(promotionRevision.valid_from.slice(0, 10))} al ${escapeHtml(promotionRevision.valid_until.slice(0, 10))}. ${escapeHtml(promotionRevision.scope)}</p><div class="growth-action-card-actions"><button class="btn btn-primary" type="button" data-social-proposal-action="promotion-approve" data-revision-id="${promotionRevision.id}" ${busy ? "disabled" : ""}>Aprobar condiciones</button><button class="btn btn-secondary" type="button" data-social-proposal-action="promotion-modify" data-revision-id="${promotionRevision.id}" ${busy ? "disabled" : ""}>Pedir modificación</button><button class="btn btn-secondary" type="button" data-social-proposal-action="promotion-reject" data-revision-id="${promotionRevision.id}" ${busy ? "disabled" : ""}>Rechazar</button></div></div></article>`;
  }).join("");
}

async function loadSocialContentProposals() {
  const status = document.getElementById("social-content-ideas-status");
  status.textContent = "Cargando ideas recomendadas…";
  try {
    const [active, accepted] = await Promise.all([
      adminInstagramJson(`${socialContentProposalsApi()}?status=active`),
      adminInstagramJson(`${socialContentProposalsApi()}?status=accepted`)
    ]);
    socialContentProposals = [...(accepted.proposals || []), ...(active.proposals || [])].filter((item) => item.idea_review?.promotion?.revisions?.at(-1)?.status === "proposed");
    renderSocialContentProposals();
    status.textContent = `${socialContentProposals.length} decisión${socialContentProposals.length === 1 ? "" : "es"} pendiente${socialContentProposals.length === 1 ? "" : "s"}`;
  } catch (error) {
    socialContentProposals = [];
    renderSocialContentProposals();
    status.textContent = error.message;
  }
}

async function mutateSocialContentProposal(button) {
  const card = button.closest("[data-social-content-proposal]");
  const proposalId = Number(card?.dataset.socialContentProposal);
  const action = button.dataset.socialProposalAction;
  if (!Number.isInteger(proposalId) || !["promotion-approve", "promotion-modify", "promotion-reject"].includes(action) || socialContentProposalMutationIds.has(proposalId)) return;
  socialContentProposalMutationIds.add(proposalId);
  renderSocialContentProposals();
  try {
    const decision = action.replace("promotion-", "");
    const note = decision === "modify" ? window.prompt("Indica qué condiciones deben modificarse:") : decision === "reject" ? window.prompt("Motivo del rechazo (opcional):") : null;
    if (decision === "modify" && !String(note || "").trim()) return;
    const options = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ revision_id: Number(button.dataset.revisionId), decision, note: String(note || "").trim() || null }) };
    await adminInstagramJson(`${socialContentProposalsApi()}/${proposalId}/promotion/decision`, options);
    await loadSocialContentProposals();
  } catch (error) {
    document.getElementById("social-content-ideas-status").textContent = error.message;
  } finally {
    socialContentProposalMutationIds.delete(proposalId);
    renderSocialContentProposals();
  }
}

function adminInstagramStateLabel(status) {
  return ({ draft: "Borrador", ready_for_review: "Listo para revisión", changes_requested: "Cambios solicitados", validated: "Validado", scheduled: "Programado", published: "Publicado", cancelled: "Cancelado" })[status] || status;
}

function adminInstagramJobPanel(item) {
  const job = item.publish_jobs?.[0];
  if (!job) return `<p class="helper">Sin programación técnica.</p>`;
  const labels = { queued: "Programado", claimed: "En cola de ejecución", creating_container: "Preparando imagen", publishing: "Publicando en Instagram", simulating_publish: "Publicando (simulado)", published: "Publicado", retry_wait: "Reintento pendiente", failed: "Fallido", action_required: "Requiere revisión", cancelled: "Cancelado" };
  const when = job.scheduled_for ? new Intl.DateTimeFormat("es-ES", { dateStyle: "short", timeStyle: "short", timeZone: item.business_timezone }).format(new Date(job.scheduled_for)) : "Sin fecha";
  return `<section class="instagram-publish-job"><p><strong>${escapeHtml(labels[job.status] || job.status)}</strong> · ${escapeHtml(when)}</p><p>Intentos: ${job.attempt_count}/${job.max_attempts}</p>${job.provider_permalink ? `<p><a href="${escapeHtml(job.provider_permalink)}" target="_blank" rel="noopener noreferrer">Ver publicación en Instagram</a></p>` : ""}<details><summary>Resultado</summary><dl><dt>Versión aprobada</dt><dd>${job.content_version_id}</dd>${job.provider_media_id ? `<dt>Media ID</dt><dd>${escapeHtml(job.provider_media_id)}</dd>` : ""}${job.provider_error_code ? `<dt>Código</dt><dd>${escapeHtml(job.provider_error_code)}</dd>` : ""}${job.safe_error_message ? `<dt>Estado seguro</dt><dd>${escapeHtml(job.safe_error_message)}</dd>` : ""}</dl></details></section>`;
}

function adminInstagramLocalInput(isoValue, timeZone) {
  if (!isoValue) return "";
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(isoValue)).map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

function adminInstagramDateKey(item) {
  if (!item.planned_publish_at) return "";
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
    timeZone: item.business_timezone, year: "numeric", month: "2-digit", day: "2-digit"
  }).formatToParts(new Date(item.planned_publish_at)).map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function adminInstagramMonthGrid(dateKey) {
  const first = `${dateKey.slice(0, 7)}-01`;
  const start = getAgendaWeekStart(first);
  return Array.from({ length: 42 }, (_item, index) => addDaysToDateKey(start, index));
}

function adminInstagramNeedsAttention(item) {
  return item.status === "ready_for_review" || ["failed", "action_required"].includes(item.publish_jobs?.[0]?.status);
}

function adminInstagramFilteredContents() {
  return adminInstagramContents.filter((item) => {
    if (adminInstagramStateFilter === "attention" && !adminInstagramNeedsAttention(item)) return false;
    if (adminInstagramStateFilter && adminInstagramStateFilter !== "attention" && item.status !== adminInstagramStateFilter) return false;
    if (adminInstagramFormatFilter && item.current_version?.format !== adminInstagramFormatFilter) return false;
    return true;
  });
}

function adminInstagramPeriodKeys() {
  const cursor = adminInstagramCalendarDate || getMadridDateKey();
  if (adminInstagramCalendarView === "today") return [cursor];
  if (adminInstagramCalendarView === "week") {
    const start = getAgendaWeekStart(cursor);
    return Array.from({ length: 7 }, (_item, index) => addDaysToDateKey(start, index));
  }
  return adminInstagramMonthGrid(cursor);
}

function adminInstagramCalendarBlock(item) {
  const time = item.planned_publish_at
    ? new Intl.DateTimeFormat("es-ES", { timeStyle: "short", timeZone: item.business_timezone }).format(new Date(item.planned_publish_at))
    : "Sin hora";
  const format = item.current_version?.format === "carousel" ? "Carrusel" : "Imagen";
  const icon = adminInstagramNeedsAttention(item) ? "!" : item.status === "published" ? "✓" : ["validated", "scheduled"].includes(item.status) ? "●" : "○";
  const action = item.status === "ready_for_review" ? "Revisar" : item.status === "changes_requested" ? "Ver cambios" : "Ver";
  const tone = adminInstagramNeedsAttention(item) ? "attention" : item.status;
  return `<button class="instagram-calendar-item instagram-calendar-item--${escapeHtml(tone)}" type="button" data-admin-instagram-open="${item.id}" aria-label="${escapeHtml(`${item.title}, ${adminInstagramStateLabel(item.status)}, ${time}`)}"><span class="instagram-calendar-item__state" aria-hidden="true">${icon}</span><span class="instagram-calendar-item__body"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(time)} · ${escapeHtml(format)} · ${escapeHtml(adminInstagramStateLabel(item.status))}</small></span><span class="instagram-calendar-item__action">${action}</span></button>`;
}

function renderAdminInstagramCalendar() {
  const calendar = document.getElementById("admin-instagram-calendar");
  if (!calendar) return;
  adminInstagramCalendarDate ||= getMadridDateKey();
  const keys = adminInstagramPeriodKeys();
  const filtered = adminInstagramFilteredContents();
  const byDate = new Map(keys.map((key) => [key, []]));
  filtered.forEach((item) => { const key = adminInstagramDateKey(item); if (byDate.has(key)) byDate.get(key).push(item); });
  byDate.forEach((items) => items.sort((left, right) => String(left.planned_publish_at).localeCompare(String(right.planned_publish_at))));
  const dateLabel = (key, options) => new Intl.DateTimeFormat("es-ES", { timeZone: "UTC", ...options }).format(new Date(`${key}T12:00:00Z`));
  const today = getMadridDateKey();
  if (adminInstagramCalendarView === "today") {
    document.getElementById("admin-instagram-period-label").textContent = dateLabel(keys[0], { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    calendar.className = "instagram-calendar instagram-calendar--today";
    calendar.innerHTML = byDate.get(keys[0]).length ? byDate.get(keys[0]).map(adminInstagramCalendarBlock).join("") : `<div class="instagram-calendar-empty"><strong>No tienes publicaciones planificadas para hoy.</strong><p>Las nuevas ideas y el material siguen disponibles bajo el calendario.</p></div>`;
  } else if (adminInstagramCalendarView === "week") {
    document.getElementById("admin-instagram-period-label").textContent = `${dateLabel(keys[0], { day: "numeric", month: "short" })} – ${dateLabel(keys[6], { day: "numeric", month: "short", year: "numeric" })}`;
    calendar.className = "instagram-calendar instagram-calendar--week";
    const hasPlanned = keys.some((key) => byDate.get(key).length);
    calendar.innerHTML = `${hasPlanned ? "" : `<div class="instagram-calendar-empty"><strong>No tienes publicaciones planificadas esta semana.</strong><p>Puedes revisar ideas o subir material de origen.</p></div>`}${keys.map((key) => `<section class="instagram-calendar-day${key === today ? " instagram-calendar-day--today" : ""}" aria-label="${escapeHtml(dateLabel(key, { weekday: "long", day: "numeric", month: "long" }))}"><header><span>${escapeHtml(dateLabel(key, { weekday: "short" }))}</span><strong>${escapeHtml(dateLabel(key, { day: "numeric" }))}</strong></header><div>${byDate.get(key).length ? byDate.get(key).map(adminInstagramCalendarBlock).join("") : `<span class="instagram-calendar-gap">Hueco libre</span>`}</div></section>`).join("")}`;
  } else {
    const activeMonth = adminInstagramCalendarDate.slice(0, 7);
    document.getElementById("admin-instagram-period-label").textContent = dateLabel(`${activeMonth}-01`, { month: "long", year: "numeric" });
    calendar.className = "instagram-calendar instagram-calendar--month";
    calendar.innerHTML = `<div class="instagram-calendar-weekdays" aria-hidden="true">${["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"].map((day) => `<span>${day}</span>`).join("")}</div>${keys.map((key) => { const items = byDate.get(key); const shown = items.slice(0, 3); return `<section class="instagram-month-day${key.startsWith(activeMonth) ? "" : " instagram-month-day--outside"}${key === today ? " instagram-calendar-day--today" : ""}"><header><span>${escapeHtml(dateLabel(key, { day: "numeric" }))}</span><small>${items.length ? `${items.length} pub.` : ""}</small></header>${shown.map(adminInstagramCalendarBlock).join("")}${items.length > shown.length ? `<button type="button" class="instagram-calendar-more" data-admin-instagram-day="${key}">+${items.length - shown.length} más</button>` : ""}</section>`; }).join("")}`;
  }
  const unscheduled = filtered.filter((item) => !item.planned_publish_at && item.status !== "cancelled");
  document.getElementById("admin-instagram-unscheduled").innerHTML = unscheduled.length ? `<div><strong>Sin fecha</strong><span>${unscheduled.length} contenido${unscheduled.length === 1 ? "" : "s"} por colocar</span></div><div>${unscheduled.map(adminInstagramCalendarBlock).join("")}</div>` : "";
  document.querySelectorAll("[data-admin-instagram-view]").forEach((button) => button.setAttribute("aria-selected", String(button.dataset.adminInstagramView === adminInstagramCalendarView)));
}

function renderAdminInstagramPlanning() {
  const container = document.getElementById("admin-instagram-planning-summary");
  if (!container) return;
  const attention = adminInstagramContents.filter(adminInstagramNeedsAttention).length;
  const week = Array.from({ length: 7 }, (_item, index) => addDaysToDateKey(getAgendaWeekStart(getMadridDateKey()), index));
  const scheduled = adminInstagramContents.filter((item) => item.status === "scheduled" && week.includes(adminInstagramDateKey(item))).length;
  container.innerHTML = attention
    ? `<strong>${attention} publicación${attention === 1 ? "" : "es"} necesita${attention === 1 ? "" : "n"} tu atención</strong><span>${scheduled} programada${scheduled === 1 ? "" : "s"} esta semana</span>`
    : `<strong>Todo preparado para esta semana</strong><span>${scheduled} programada${scheduled === 1 ? "" : "s"}</span>`;
  container.classList.toggle("instagram-attention-summary--active", attention > 0);
  renderAdminInstagramCalendar();
}

async function adminInstagramJson(url, options = {}) {
  const response = await fetch(url, options);
  let body = {};
  try { body = await response.json(); } catch (_error) { body = {}; }
  if (!response.ok) {
    const detail = body?.detail;
    const message = typeof detail === "string"
      ? detail
      : typeof detail?.message === "string"
        ? detail.message
        : Array.isArray(detail)
          ? detail.map((item) => item?.msg).filter(Boolean).join(" ")
          : typeof body?.message === "string"
            ? body.message
            : "No se pudo completar la operación editorial.";
    throw new Error(message);
  }
  return body;
}

function renderAdminInstagramRaw(assets) {
  document.getElementById("admin-instagram-raw-list").innerHTML = assets.length
    ? assets.map((asset) => `<a class="instagram-asset-chip" href="${API_BASE_URL}${escapeHtml(asset.file_url)}" target="_blank" rel="noopener">${escapeHtml(asset.label || asset.original_filename)}</a>`).join("")
    : `<p class="helper">Todavía no hay material bruto.</p>`;
}

function generatedEditorialPreview(item) {
  const packageData = item.current_version.editorial_package;
  if (!packageData) return "";
  const format = packageData.editorial_format;
  const warnings = packageData.generation_context?.warnings || [];
  const missing = packageData.asset_plan?.missing || [];
  return `<details><summary>Paquete editorial · ${escapeHtml(socialContentLabel("format", format))}</summary>${warnings.length ? `<p class="helper">Aviso: las señales de origen han cambiado desde la aceptación.</p>` : ""}${missing.length ? `<p class="helper">Material pendiente: ${escapeHtml(missing.join(", "))}.</p>` : ""}<dl><dt>Hook</dt><dd>${escapeHtml(packageData.hook)}</dd><dt>Titular</dt><dd>${escapeHtml(packageData.headline)}</dd><dt>CTA</dt><dd>${escapeHtml(packageData.cta?.text || "Sin CTA")}</dd><dt>Dirección visual</dt><dd>${escapeHtml(packageData.visual_direction)}</dd></dl></details>`;
}

function renderAdminInstagramContents() {
  const container = document.getElementById("admin-instagram-content-list");
  renderAdminInstagramPlanning();
  const selected = adminInstagramContents.find((item) => item.id === adminInstagramSelectedContentId);
  document.getElementById("admin-instagram-detail-close").hidden = !selected;
  document.getElementById("admin-instagram-detail-title").textContent = selected ? selected.title : "Selecciona una publicación";
  if (!selected) {
    container.innerHTML = adminInstagramContents.length
      ? `<p class="helper">Pulsa una publicación del calendario para revisar sus datos y acciones.</p>`
      : `<p class="helper">El Owner todavía no ha preparado contenido final.</p>`;
    return;
  }
  container.innerHTML = [selected].map((item) => {
    const version = item.current_version;
    const assets = version.assets.map((asset) => `<a class="instagram-final-preview" href="${API_BASE_URL}${escapeHtml(asset.file_url)}" target="_blank" rel="noopener"><span>${asset.is_cover ? "Portada · " : ""}${escapeHtml(asset.original_filename)}</span></a>`).join("");
    const history = item.versions.map((candidate) => `<li>v${candidate.version_number} · ${escapeHtml(candidate.format)}${candidate.validation ? candidate.validation.invalidated_at ? " · aprobación invalidada" : ` · aprobada con assets ${candidate.validation.approved_asset_ids.join(", ")}` : ""}</li>`).join("");
    const events = (item.publication_events || []).map((event) => `<li>${escapeHtml(new Intl.DateTimeFormat("es-ES", { dateStyle: "short", timeStyle: "short", timeZone: item.business_timezone }).format(new Date(event.created_at)))} · ${escapeHtml(event.action)}${event.actor_user_id ? ` · usuario ${event.actor_user_id}` : " · worker"}</li>`).join("");
    const unsupported = adminInstagramSettings?.publishing_mode === "meta" && version.format !== "single_image" ? `<p class="inline-feedback">Formato preparado para futuro soporte: la publicación real V1 solo admite una imagen JPEG.</p>` : "";
    const editorial = version.editorial_review;
    const reviewBadge = editorial?.status === "approved" ? `<div class="ag-alert ag-alert--success"><strong>Visto bueno del negocio ✓</strong><p>Registrado para esta versión. No es un requisito para publicar contenido rutinario.</p></div>` : ["changes_requested", "rejected"].includes(editorial?.status) ? `<div class="ag-alert ag-alert--info"><strong>Esta versión está bloqueada</strong><p>${escapeHtml(editorial.note || "El negocio ha pedido cambios.")}</p></div>` : `<p class="helper">Si todo está bien, no necesitas hacer nada.</p>`;
    const review = ["ready_for_review", "validated", "scheduled"].includes(item.status) ? `<section data-admin-instagram-review>${reviewBadge}<div class="growth-action-card-actions"><form data-admin-instagram-business-review><input type="hidden" name="version_id" value="${version.id}"><input type="hidden" name="decision" value="approve"><button class="btn btn-secondary" type="submit">Dar visto bueno</button></form><button class="btn btn-secondary" type="button" data-admin-instagram-review-toggle="changes_requested">Solicitar cambios</button><button class="btn btn-secondary" type="button" data-admin-instagram-review-toggle="reject">Rechazar esta versión</button></div><form data-admin-instagram-business-review data-admin-instagram-review-panel="changes_requested" hidden><input type="hidden" name="version_id" value="${version.id}"><input type="hidden" name="decision" value="changes_requested"><label>¿Qué quieres que cambiemos?<textarea name="note" maxlength="4000" required rows="3"></textarea></label><button class="btn btn-primary" type="submit">Confirmar solicitud</button></form><form data-admin-instagram-business-review data-admin-instagram-review-panel="reject" hidden><input type="hidden" name="version_id" value="${version.id}"><input type="hidden" name="decision" value="reject"><label>Cuéntanos brevemente por qué<textarea name="note" maxlength="4000" required rows="3"></textarea></label><button class="btn btn-primary" type="submit">Confirmar rechazo</button></form></section>` : reviewBadge;
    const hold = item.publication_hold ? `<form data-admin-instagram-hold="release"><div class="ag-alert ag-alert--info"><strong>Publicación detenida</strong><p>${escapeHtml(item.publication_hold.reason)}</p></div><label>Nota al reanudar<textarea name="note" maxlength="4000" rows="2"></textarea></label><button class="btn btn-primary" type="submit">Reanudar publicación</button></form>` : ["cancelled", "published"].includes(item.status) ? "" : `<div><button class="btn btn-secondary" type="button" data-admin-instagram-hold-toggle>Detener publicación</button><form data-admin-instagram-hold="create" data-admin-instagram-hold-panel hidden><label>Motivo para detener esta publicación<textarea name="reason" maxlength="4000" required rows="3"></textarea></label><button class="btn btn-primary" type="submit">Confirmar detención</button></form></div>`;
    const rawHistory = (item.raw_asset_history || []).map((raw) => `<li><strong>${escapeHtml(raw.display_status)}</strong> · ${escapeHtml(raw.original_filename)} · versiones ${raw.version_numbers.join(", ")}${raw.preview_url ? ` · <a href="${API_BASE_URL}${escapeHtml(raw.preview_url)}" target="_blank" rel="noopener">Ver original</a>` : ""}</li>`).join("");
    return `<article class="instagram-content-card" data-admin-instagram-content="${item.id}"><header><div><h4>${escapeHtml(item.title)}</h4><p>${escapeHtml(adminInstagramStateLabel(item.status))} · versión ${version.version_number}</p></div><span class="ag-badge ag-badge--neutral">${item.planned_publish_at ? escapeHtml(new Intl.DateTimeFormat("es-ES", { dateStyle: "short", timeStyle: "short", timeZone: item.business_timezone }).format(new Date(item.planned_publish_at))) : "Sin fecha"}</span></header><p class="instagram-caption">${escapeHtml(version.caption) || "Sin caption"}</p>${unsupported}${generatedEditorialPreview(item)}<div class="instagram-final-assets">${assets || "<p class='helper'>Sin assets finales.</p>"}</div>${adminInstagramJobPanel(item)}<details><summary>Historial de versiones y decisiones</summary><ul>${history}</ul>${rawHistory ? `<h5>Material de origen</h5><ul>${rawHistory}</ul>` : ""}</details>${events ? `<details><summary>Historial de publicación</summary><ul>${events}</ul></details>` : ""}${item.comments.length ? `<ul class="instagram-comments">${item.comments.map((comment) => `<li><strong>${escapeHtml(comment.kind)}</strong><p>${escapeHtml(comment.body)}</p></li>`).join("")}</ul>` : ""}<button class="btn btn-ghost" type="button" data-admin-instagram-comment-toggle>Añadir comentario</button><form data-admin-instagram-comment data-admin-instagram-comment-panel hidden><input type="hidden" name="version_id" value="${version.id}"><label>Comentario<textarea name="body" maxlength="4000" required rows="3"></textarea></label><input type="hidden" name="kind" value="comment"><button class="btn btn-secondary" type="submit">Enviar comentario</button></form>${review}${hold}</article>`;
  }).join("");
}

function adminInstagramCalendarQuery() {
  adminInstagramCalendarDate ||= getMadridDateKey();
  const keys = adminInstagramPeriodKeys();
  return new URLSearchParams({
    from: `${addDaysToDateKey(keys[0], -1)}T00:00:00Z`,
    to: `${addDaysToDateKey(keys[keys.length - 1], 2)}T00:00:00Z`,
    include_unscheduled: "true"
  });
}

async function openAdminInstagramContent(contentId) {
  let content = adminInstagramContents.find((item) => item.id === contentId);
  if (!content) {
    try {
      content = await adminInstagramJson(`${adminInstagramApi()}/contents/${contentId}`);
      adminInstagramContents.unshift(content);
    } catch (error) {
      document.getElementById("admin-instagram-status").textContent = error.message;
      return;
    }
  } else if (!Array.isArray(content.versions)) {
    try {
      const detail = await adminInstagramJson(`${adminInstagramApi()}/contents/${contentId}`);
      adminInstagramContents[adminInstagramContents.indexOf(content)] = detail;
      content = detail;
    } catch (error) {
      document.getElementById("admin-instagram-status").textContent = error.message;
      return;
    }
  }
  adminInstagramSelectedContentId = contentId;
  renderAdminInstagramContents();
  const panel = document.getElementById("admin-instagram-detail");
  panel.tabIndex = -1;
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
  panel.focus({ preventScroll: true });
}

async function loadAdminInstagramCalendarPeriod() {
  if (isBusinessStaff()) return;
  try {
    const payload = await adminInstagramJson(`${adminInstagramApi()}/contents?${adminInstagramCalendarQuery().toString()}`);
    adminInstagramContents = payload.contents || [];
    if (!adminInstagramContents.some((item) => item.id === adminInstagramSelectedContentId)) adminInstagramSelectedContentId = null;
    renderAdminInstagramContents();
  } catch (error) {
    document.getElementById("admin-instagram-status").textContent = error.message;
  }
}

function shiftAdminInstagramCalendar(direction) {
  if (adminInstagramCalendarView === "month") {
    const value = new Date(`${adminInstagramCalendarDate.slice(0, 7)}-01T12:00:00Z`);
    value.setUTCMonth(value.getUTCMonth() + direction);
    adminInstagramCalendarDate = value.toISOString().slice(0, 10);
  } else {
    adminInstagramCalendarDate = addDaysToDateKey(adminInstagramCalendarDate, direction * (adminInstagramCalendarView === "week" ? 7 : 1));
  }
  loadAdminInstagramCalendarPeriod();
}

async function loadAdminInstagramPanel() {
  if (adminAuthUser?.is_owner) return;
  const status = document.getElementById("admin-instagram-status");
  if (isBusinessStaff()) {
    document.getElementById("admin-instagram-disabled").hidden = true;
    document.getElementById("admin-instagram-workspace").hidden = true;
    document.getElementById("social-content-ideas-list").innerHTML = `<p class="helper">Las decisiones de contenido están reservadas al responsable del negocio.</p>`;
    document.getElementById("social-content-ideas-status").textContent = "Acceso de consulta no disponible para este rol.";
    status.textContent = "Las decisiones editoriales están reservadas al responsable del negocio.";
    return;
  }
  const api = adminInstagramApi();
  status.textContent = "Cargando flujo editorial…";
  const proposalsPromise = loadSocialContentProposals();
  try {
    adminInstagramSettings = await adminInstagramJson(`${api}/settings`);
    const enabled = adminInstagramSettings.enabled;
    document.getElementById("admin-instagram-disabled").hidden = enabled;
    document.getElementById("admin-instagram-workspace").hidden = !enabled;
    if (!enabled) { status.textContent = "Servicio pendiente de activación por Owner."; await proposalsPromise; return; }
    const [raw, contentList, metrics] = await Promise.all([
      adminInstagramJson(`${api}/raw-assets`),
      adminInstagramJson(`${api}/contents?${adminInstagramCalendarQuery().toString()}`),
      adminInstagramJson(`${api}/publication-metrics`)
    ]);
    adminInstagramMetrics = metrics;
    adminInstagramContents = contentList.contents || [];
    renderAdminInstagramRaw(raw.assets);
    renderAdminInstagramPlanning();
    renderAdminInstagramContents();
    await proposalsPromise;
    status.textContent = `${adminInstagramContents.length} contenidos · ${raw.assets.length} materiales brutos · AutonoGrow gestiona la validación y publicación`;
  } catch (error) { status.textContent = error.message; }
}

async function uploadAdminInstagramRaw(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (form.dataset.busy === "true") return;
  const submit = form.querySelector('button[type="submit"]');
  const originalLabel = submit?.textContent || "Subir";
  form.dataset.busy = "true";
  form.setAttribute("aria-busy", "true");
  if (submit) {
    submit.disabled = true;
    submit.textContent = "Subiendo…";
  }
  try {
    await adminInstagramJson(`${adminInstagramApi()}/raw-assets`, { method: "POST", body: new FormData(form) });
    form.reset();
    await loadAdminInstagramPanel();
  } catch (error) {
    document.getElementById("admin-instagram-status").textContent = error.message;
  } finally {
    delete form.dataset.busy;
    form.removeAttribute("aria-busy");
    if (submit) {
      submit.disabled = false;
      submit.textContent = originalLabel;
    }
  }
}

async function submitAdminInstagramComment(event) {
  event.preventDefault();
  const form = event.target;
  const card = form.closest("[data-admin-instagram-content]");
  const data = new FormData(form);
  if (!card) return;
  try {
    await adminInstagramJson(`${adminInstagramApi()}/contents/${card.dataset.adminInstagramContent}/comments`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version_id: Number(data.get("version_id")), kind: data.get("kind"), body: data.get("body") }) });
    await loadAdminInstagramPanel();
  } catch (error) { document.getElementById("admin-instagram-status").textContent = error.message; }
}

async function submitAdminInstagramBusinessReview(event) {
  event.preventDefault();
  const form = event.target;
  const card = form.closest("[data-admin-instagram-content]");
  const data = new FormData(form);
  const decision = String(data.get("decision") || "");
  const note = String(data.get("note") || "").trim();
  if (!card || !["approve", "changes_requested", "reject"].includes(decision)) return;
  if (decision !== "approve" && !note) {
    document.getElementById("admin-instagram-status").textContent = "Añade una nota para solicitar cambios o rechazar esta versión.";
    return;
  }
  try {
    await adminInstagramJson(`${adminInstagramApi()}/contents/${card.dataset.adminInstagramContent}/editorial-review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version_id: Number(data.get("version_id")), decision, note: note || null }) });
    document.getElementById("admin-instagram-status").textContent = decision === "approve" ? "Visto bueno del negocio registrado." : "La decisión sobre esta versión ha sido registrada.";
    await loadAdminInstagramPanel();
  } catch (error) { document.getElementById("admin-instagram-status").textContent = error.message; }
}

async function submitAdminInstagramHold(event) {
  event.preventDefault();
  const form = event.target;
  const card = form.closest("[data-admin-instagram-content]");
  if (!card) return;
  const data = new FormData(form);
  const action = form.dataset.adminInstagramHold;
  try {
    const payload = action === "create" ? { reason: String(data.get("reason") || "").trim() } : { note: String(data.get("note") || "").trim() || null };
    const result = await adminInstagramJson(`${adminInstagramApi()}/contents/${card.dataset.adminInstagramContent}/publication-hold${action === "release" ? "/release" : ""}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    document.getElementById("admin-instagram-status").textContent = action === "release" ? "Publicación reanudada." : result.outcome_requires_review ? "La publicación ya estaba en curso. AutonoGrow revisará el resultado y no la reenviará." : "Publicación detenida.";
    await loadAdminInstagramPanel();
  } catch (error) { document.getElementById("admin-instagram-status").textContent = error.message; }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("admin-instagram-refresh").addEventListener("click", loadAdminInstagramPanel);
  document.getElementById("admin-instagram-raw-form").addEventListener("submit", uploadAdminInstagramRaw);
  document.getElementById("admin-instagram-content-list").addEventListener("submit", (event) => {
    if (event.target.matches("[data-admin-instagram-comment]")) submitAdminInstagramComment(event);
    if (event.target.matches("[data-admin-instagram-business-review]")) submitAdminInstagramBusinessReview(event);
    if (event.target.matches("[data-admin-instagram-hold]")) submitAdminInstagramHold(event);
  });
  document.getElementById("admin-instagram-workspace").addEventListener("click", (event) => {
    const commentToggle = event.target.closest("[data-admin-instagram-comment-toggle]");
    if (commentToggle) {
      const panel = commentToggle.parentElement.querySelector("[data-admin-instagram-comment-panel]");
      panel.hidden = !panel.hidden;
      if (!panel.hidden) panel.querySelector("textarea")?.focus();
      return;
    }
    const reviewToggle = event.target.closest("[data-admin-instagram-review-toggle]");
    if (reviewToggle) {
      const review = reviewToggle.closest("[data-admin-instagram-review]");
      const target = review.querySelector(`[data-admin-instagram-review-panel="${reviewToggle.dataset.adminInstagramReviewToggle}"]`);
      review.querySelectorAll("[data-admin-instagram-review-panel]").forEach((panel) => { panel.hidden = panel !== target || !target.hidden; });
      if (!target.hidden) target.querySelector("textarea")?.focus();
      return;
    }
    const holdToggle = event.target.closest("[data-admin-instagram-hold-toggle]");
    if (holdToggle) {
      const panel = holdToggle.parentElement.querySelector("[data-admin-instagram-hold-panel]");
      panel.hidden = !panel.hidden;
      if (!panel.hidden) panel.querySelector("textarea")?.focus();
      return;
    }
    const open = event.target.closest("[data-admin-instagram-open]");
    if (open) { openAdminInstagramContent(Number(open.dataset.adminInstagramOpen)); return; }
    const day = event.target.closest("[data-admin-instagram-day]");
    if (day) {
      adminInstagramCalendarDate = day.dataset.adminInstagramDay;
      adminInstagramCalendarView = "today";
      loadAdminInstagramCalendarPeriod();
    }
  });
  document.querySelectorAll("[data-admin-instagram-view]").forEach((button) => button.addEventListener("click", () => {
    adminInstagramCalendarView = button.dataset.adminInstagramView;
    loadAdminInstagramCalendarPeriod();
  }));
  document.querySelectorAll("[data-admin-instagram-nav]").forEach((button) => button.addEventListener("click", () => shiftAdminInstagramCalendar(Number(button.dataset.adminInstagramNav))));
  document.getElementById("admin-instagram-today").addEventListener("click", () => { adminInstagramCalendarDate = getMadridDateKey(); loadAdminInstagramCalendarPeriod(); });
  document.getElementById("admin-instagram-state-filter").addEventListener("change", (event) => { adminInstagramStateFilter = event.target.value; renderAdminInstagramContents(); });
  document.getElementById("admin-instagram-format-filter").addEventListener("change", (event) => { adminInstagramFormatFilter = event.target.value; renderAdminInstagramContents(); });
  document.getElementById("admin-instagram-detail-close").addEventListener("click", () => { adminInstagramSelectedContentId = null; renderAdminInstagramContents(); });
  document.getElementById("social-content-ideas-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-social-proposal-action]");
    if (button) mutateSocialContentProposal(button);
  });
  setupAdminDelegatedActions();
  setupBusinessConfiguration();
  setupChannelHub();
  setupGrowthHub();
  setupAdminNavigation();
  setupBookingViews();
  setupDashboardInteractions();
  setupConversationInterface();
  renderDashboard();
  document.getElementById("refresh-button").addEventListener("click", () => {
    refreshOperationalData({ includeAutomation: true });
  });
  document.addEventListener("visibilitychange", handleAdminVisibilityChange);
  document.getElementById("message-status-filter").addEventListener("change", renderMessageOutbox);
  document.getElementById("save-business-settings").addEventListener("click", () => saveBusinessSettings("business"));
  document.getElementById("save-public-page-settings").addEventListener("click", () => saveBusinessSettings("public-page"));
  document.getElementById("create-service").addEventListener("click", createAdminService);
  document.getElementById("create-staff-member").addEventListener("click", createStaffMember);
  document.getElementById("toggle-conversation-create").addEventListener("click", () => {
    const panel = document.getElementById("conversation-create-panel");
    panel.hidden = !panel.hidden;
    document.getElementById("toggle-conversation-create").setAttribute("aria-expanded", String(!panel.hidden));
  });
  document.getElementById("create-conversation").addEventListener("click", createConversation);
  document.getElementById("create-conversation-template").addEventListener("click", createConversationTemplate);
  document.getElementById("conversation-status-filter").addEventListener("change", () => {
    updateConversationFilterSummary();
    loadConversations({ background: false });
  });
  document.getElementById("conversation-channel-filter").addEventListener("change", () => {
    updateConversationFilterSummary();
    loadConversations({ background: false });
  });
  document.getElementById("conversation-search").addEventListener("input", () => {
    updateConversationFilterSummary();
    clearTimeout(conversationSearchTimer);
    conversationSearchTimer = setTimeout(
      () => loadConversations({ background: false }),
      350
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
      if (feedback) feedback.textContent = oauthResult === "pending_review" ? "Instagram conectado. La cuenta queda pendiente de revisión por AutonoGrow." : "No se pudo completar Instagram Login. Inicia un nuevo intento.";
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
