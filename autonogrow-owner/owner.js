const API_BASE_URL = AutonoGrowAuth.API_BASE_URL;
const browserFetch = window.fetch.bind(window);
const fetch = async (input, options = {}) => {
  const securedOptions = await AutonoGrowAuth.secureRequestOptions(options);
  const response = await browserFetch(input, securedOptions);
  if (response.status === 401) queueMicrotask(() => showOwnerLogin());
  if (response.status === 403) queueMicrotask(() => showOwnerLogin("No tienes permiso para acceder al panel interno.", true));
  return response;
};
let businesses = [];
let incidents = [];
let openIncidentCount = 0;
let ownerAuthUser = null;
let queueStatus = null;
let operationsStatus = null;
let ownerInstagramSettings = null;
let ownerInstagramContents = [];
let ownerInstagramRawAssets = [];
let ownerInstagramLoadPromise = null;
let ownerInstagramLoading = false;
let ownerInstagramRetryUntil = 0;
let ownerInstagramRetryTimer = null;
let ownerInstagramLifecycleTimer = null;
let ownerInstagramPreviewObjectUrl = null;
let ownerInstagramPreviewAssetId = null;
let ownerInstagramPreviewReturnFocus = null;
let ownerInstagramAssociationData = null;
let ownerInstagramAssociationReturnFocus = null;
let ownerInstagramAssociationBusy = false;
const ownerInstagramMutationKeys = new Set();
let ownerInstagramCalendarView = "week";
let ownerInstagramCalendarDate = "";
let ownerInstagramStateFilter = "";
let ownerInstagramFormatFilter = "";
let ownerInstagramComposerReturnFocus = null;
let ownerInstagramComposerSequence = 0;
let ownerInstagramComposerState = null;
const OWNER_CREDIT_PRESETS = [100, 200, 500];
const PALETTES = { slate_gold: ["#334155", "#0f172a", "#f59e0b", "#f8fafc"], rose_beauty: ["#be123c", "#831843", "#f9a8d4", "#fff1f2"], emerald_clean: ["#047857", "#064e3b", "#6ee7b7", "#ecfdf5"], blue_clinic: ["#2563eb", "#1e3a8a", "#93c5fd", "#eff6ff"], amber_barber: ["#92400e", "#451a03", "#fbbf24", "#fffbeb"], violet_modern: ["#7c3aed", "#4c1d95", "#c4b5fd", "#f5f3ff"] };
const TEMPLATE_DESCRIPTIONS = { classic: "Estructura equilibrada para cualquier negocio.", elegant: "Diseño más premium y visual.", beauty: "Pensada para estética, manicura y peluquería.", clinic: "Limpia y profesional para centros de salud o consulta.", urban: "Más impacto para barberías y negocios modernos.", minimal: "Directa y sencilla para servicios prácticos." };
const BUSINESS_TEMPLATES = {
  barberia: ["Barbería", "Cortes y barba con reserva rápida.", "Barbería profesional para un estilo cuidado.", "Lunes a sábado, 10:00 - 20:00", "barberia", "amber_barber", "urban", [["Corte de pelo",30],["Corte + barba",45],["Barba",20]]],
  manicura: ["Manicura", "Tus uñas, a tu estilo.", "Manicura, pedicura y diseños personalizados.", "Lunes a viernes, 10:00 - 20:00", "manicura", "rose_beauty", "beauty", [["Manicura semipermanente",60],["Pedicura",60],["Diseño personalizado",90]]],
  fisioterapia: ["Fisioterapia", "Recupera movilidad y bienestar.", "Tratamiento personalizado y valoración profesional.", "Lunes a viernes, 09:00 - 20:00", "fisioterapia", "blue_clinic", "clinic", [["Fisioterapia general",45],["Descarga muscular",30],["Primera valoración",60]]],
  taller: ["Taller mecánico", "Tu vehículo, en buenas manos.", "Diagnóstico y mantenimiento con cita previa.", "Lunes a viernes, 09:00 - 19:00", "taller", "slate_gold", "minimal", [["Diagnóstico básico",30],["Revisión general",60],["Cambio de aceite",45]]],
  peluqueria: ["Peluquería", "Un look que habla de ti.", "Corte, color y cuidado capilar.", "Martes a sábado, 10:00 - 20:00", "peluqueria", "violet_modern", "elegant", [["Corte",45],["Color",90],["Peinado",45]]],
  estetica: ["Estética", "Cuida tu piel y tu bienestar.", "Tratamientos estéticos personalizados.", "Lunes a viernes, 10:00 - 20:00", "estetica", "rose_beauty", "beauty", [["Limpieza facial",60],["Tratamiento hidratante",60],["Depilación",30]]],
  entrenamiento_personal: ["Entrenamiento personal", "Entrena con un plan hecho para ti.", "Sesiones individuales y seguimiento de objetivos.", "Lunes a sábado, 07:00 - 21:00", "entrenamiento_personal", "emerald_clean", "minimal", [["Sesión individual",60],["Valoración inicial",45],["Bono de seguimiento",30]]],
  psicologia: ["Psicología", "Un espacio seguro para avanzar.", "Acompañamiento psicológico presencial.", "Lunes a viernes, 09:00 - 20:00", "psicologia", "emerald_clean", "minimal", [["Primera consulta",60],["Sesión individual",50],["Seguimiento",50]]],
  clinica_dental: ["Clínica dental", "Tu sonrisa, cuidada con confianza.", "Odontología preventiva y tratamientos personalizados.", "Lunes a viernes, 09:00 - 20:00", "clinica_dental", "blue_clinic", "clinic", [["Primera revisión",30],["Limpieza dental",45],["Urgencia dental",30]]],
  masajes: ["Masajes", "Desconecta, recupera y respira.", "Masajes relajantes y terapéuticos.", "Lunes a sábado, 10:00 - 20:00", "masajes", "violet_modern", "elegant", [["Masaje relajante",60],["Masaje descontracturante",45],["Masaje de espalda",30]]]
};

const byId = (id) => document.getElementById(id);
const sum = (items, getter) => items.reduce((total, item) => total + getter(item), 0);

function resolveMediaUrl(url, cacheBust = false) {
  if (!url) return "";
  const resolved = /^https?:\/\//i.test(url) ? url : (url.startsWith("/uploads/") ? `${API_BASE_URL}${url}` : url);
  if (!cacheBust) return resolved;
  return `${resolved}${resolved.includes("?") ? "&" : "?"}v=${Date.now()}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

const OWNER_DASHBOARD_HEALTH_ATTENTION = new Set(["warning", "degraded", "action_required", "revoked", "suspended", "error"]);
const OWNER_DASHBOARD_SOURCE_NAMES = ["businesses", "channels", "incidents", "queue", "platform"];
const ownerDashboardState = Object.fromEntries(OWNER_DASHBOARD_SOURCE_NAMES.map((name) => [name, { status: "idle", data: null, errors: 0 }]));
const ownerDashboardSourceVersions = Object.fromEntries(OWNER_DASHBOARD_SOURCE_NAMES.map((name) => [name, 0]));
const ownerDashboardRetryInFlight = new Set();
let ownerDashboardLoadInFlight = null;
let ownerDashboardRerunRequested = false;
let ownerDashboardLastUpdated = null;

function formatOwnerDate(value, options = { dateStyle: "short", timeStyle: "short" }) {
  if (!value) return "Sin fecha";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Sin fecha";
  return new Intl.DateTimeFormat("es-ES", options).format(parsed);
}

function safeOwnerDashboardError() {
  return "No se pudo comprobar esta fuente. Los demás bloques siguen disponibles.";
}

function ownerDashboardBlock(id) {
  return byId(id);
}

function setOwnerDashboardBlock(id, html, state = "ready") {
  const block = ownerDashboardBlock(id);
  if (!block) return;
  block.dataset.state = state;
  block.setAttribute("aria-busy", state === "loading" ? "true" : "false");
  block.querySelector("[data-owner-dashboard-content]").innerHTML = html;
}

function ownerDashboardEmpty(title, description) {
  return `<div class="owner-dashboard-empty"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(description)}</span></div>`;
}

function ownerDashboardError() {
  return `<div class="owner-dashboard-error" role="group"><strong>Fuente no disponible</strong><span>${escapeHtml(safeOwnerDashboardError())}</span></div>`;
}

function ownerDashboardPartial(errors) {
  if (!errors) return "";
  return `<p class="owner-dashboard-partial">No se pudo comprobar ${errors} ${errors === 1 ? "negocio" : "negocios"}; el resumen conserva únicamente resultados confirmados.</p>`;
}

function ownerDashboardStale() {
  return '<p class="owner-dashboard-partial">No se pudo actualizar esta fuente; se conservan los últimos datos válidos.</p>';
}

function updateOwnerSyncStatus() {
  const failed = OWNER_DASHBOARD_SOURCE_NAMES.filter((name) => ownerDashboardState[name].status === "error").length;
  const partial = OWNER_DASHBOARD_SOURCE_NAMES.filter((name) => Number(ownerDashboardState[name].errors || 0) > 0).length;
  const unavailable = failed + partial;
  const prefix = unavailable ? `Actualización parcial · ${unavailable} ${unavailable === 1 ? "fuente incompleta" : "fuentes incompletas"}` : "Actualizado";
  byId("owner-sync-status").textContent = `${prefix} · ${formatOwnerDate((ownerDashboardLastUpdated || new Date()).toISOString())}`;
}

function dashboardSourceData(name, fallback) {
  return ownerDashboardState[name].data ?? fallback;
}

function pendingOwnerDecisions() {
  const snapshots = dashboardSourceData("channels", []);
  const decisions = [];
  snapshots.forEach((snapshot) => {
    const candidatesByChannel = {
      instagram: snapshot.instagramCandidates || [],
      whatsapp: snapshot.whatsappCandidates || [],
    };
    Object.entries(candidatesByChannel).forEach(([channel, candidates]) => {
      candidates.filter((candidate) => candidate.status === "candidate_ready").forEach((candidate) => decisions.push({
        business: snapshot.business,
        channel,
        kind: "candidate",
        requestedAt: candidate.created_at,
        purpose: candidate.purpose,
      }));
    });
    (snapshot.controls || []).forEach((control) => {
      if (control.status !== "pending_approval" || candidatesByChannel[control.channel]?.length) return;
      decisions.push({
        business: snapshot.business,
        channel: control.channel,
        kind: "connection",
        requestedAt: control.requested_at || control.updated_at,
        purpose: null,
      });
    });
  });
  return decisions.sort((left, right) => new Date(left.requestedAt || 0) - new Date(right.requestedAt || 0));
}

function integrationAttentionItems() {
  const items = [];
  dashboardSourceData("channels", []).forEach((snapshot) => {
    const healthChannels = snapshot.health || [];
    healthChannels.forEach((health) => {
      if (!OWNER_DASHBOARD_HEALTH_ATTENTION.has(health.health_status) && !health.reconnection_required) return;
      items.push({ business: snapshot.business, control: (snapshot.controls || []).find((item) => item.channel === health.channel), health });
    });
    (snapshot.controls || []).forEach((control) => {
      if (!["suspended", "revoked"].includes(control.status) || healthChannels.some((health) => health.channel === control.channel)) return;
      items.push({ business: snapshot.business, control, health: { channel: control.channel, health_status: control.status } });
    });
  });
  return items;
}

function ownerQueueIssueCount(queue) {
  if (!queue) return null;
  const failed = (queue.jobs || []).filter((item) => item.status === "failed").length;
  return Number(queue.retry_inbox || 0) + Number(queue.retry_outbox || 0) + Number(queue.dead_letter_inbox || 0) + Number(queue.dead_letter_outbox || 0) + Number(queue.blocked_outbox || 0) + failed;
}

function ownerBusinessIsPending(business) {
  return ["draft", "onboarding", "configuration_pending", "ready"].includes(business.status);
}

function renderOwnerMetrics() {
  const businessSource = ownerDashboardState.businesses;
  const channelSource = ownerDashboardState.channels;
  const incidentSource = ownerDashboardState.incidents;
  const queueSource = ownerDashboardState.queue;
  const businessData = dashboardSourceData("businesses", businesses);
  const incidentData = dashboardSourceData("incidents", {});
  const queueData = dashboardSourceData("queue", null);
  byId("owner-metric-active").textContent = businessSource.status === "error" ? "—" : businessData.filter((item) => item.status === "active").length;
  byId("owner-metric-pending-businesses").textContent = businessSource.status === "error" ? "—" : businessData.filter(ownerBusinessIsPending).length;
  byId("owner-metric-decisions").textContent = channelSource.status === "error" ? "—" : pendingOwnerDecisions().length;
  byId("owner-metric-integrations").textContent = channelSource.status === "error" ? "—" : integrationAttentionItems().length;
  byId("owner-metric-incidents").textContent = incidentSource.status === "error" ? "—" : Number(incidentData.open_count || 0);
  const queueIssues = ownerQueueIssueCount(queueData);
  byId("owner-metric-messages").textContent = queueSource.status === "error" || queueIssues === null ? "—" : queueIssues;
  byId("owner-dashboard-metrics").setAttribute("aria-busy", OWNER_DASHBOARD_SOURCE_NAMES.some((name) => ownerDashboardState[name].status === "loading") ? "true" : "false");
}

function ownerDecisionPurpose(value) {
  return value === "replacement" || value === "reconnection" ? "Reconexión solicitada" : "Nueva conexión solicitada";
}

function renderPendingDecisions() {
  const source = ownerDashboardState.channels;
  if (source.status === "error" && !source.data) { setOwnerDashboardBlock("owner-dashboard-decisions", ownerDashboardError(), "error"); return; }
  const decisions = pendingOwnerDecisions();
  if (!decisions.length) {
    const content = source.status === "error"
      ? ownerDashboardStale() + ownerDashboardEmpty("Última comprobación sin decisiones", "La fuente debe recuperarse antes de confirmar que no hay nuevas solicitudes.")
      : source.errors
      ? ownerDashboardPartial(source.errors) + ownerDashboardEmpty("Comprobación incompleta", "No hay decisiones confirmadas en las fuentes disponibles.")
      : ownerDashboardEmpty("No hay decisiones pendientes", "Las nuevas solicitudes de conexión o aprobación aparecerán aquí.");
    setOwnerDashboardBlock("owner-dashboard-decisions", content, source.status === "error" ? "error" : source.errors ? "partial" : "ready");
    return;
  }
  const html = (source.status === "error" ? ownerDashboardStale() : ownerDashboardPartial(source.errors)) + `<ul class="owner-dashboard-list">${decisions.slice(0, 8).map((item) => {
    const channel = item.channel === "instagram" ? "Instagram" : "WhatsApp";
    return `<li class="owner-dashboard-item"><div class="owner-dashboard-item__heading"><div><h3>${escapeHtml(item.business.name)}</h3><p>${escapeHtml(channel)} · ${escapeHtml(item.kind === "candidate" ? "Cuenta pendiente de revisión" : "Solicitud pendiente de revisión")}</p></div><span class="ag-badge ag-badge--warning">Pendiente</span></div><div class="owner-dashboard-item__meta"><span>Solicitada: ${escapeHtml(formatOwnerDate(item.requestedAt))}</span><span>${escapeHtml(ownerDecisionPurpose(item.purpose))}</span></div><button class="button button-secondary button-small owner-dashboard-item__action" type="button" data-owner-navigate="new-business" data-owner-business-id="${escapeHtml(item.business.id)}" data-owner-detail="${escapeHtml(item.channel)}">Revisar solicitud</button></li>`;
  }).join("")}</ul>`;
  setOwnerDashboardBlock("owner-dashboard-decisions", html, source.status === "loading" ? "loading" : source.status === "error" ? "error" : source.errors ? "partial" : "ready");
}

function ownerApprovalLabel(control) {
  if (!control) return "Sin control disponible";
  return ({ approved: "Aprobada", pending_approval: "Pendiente", available: "Disponible", suspended: "Suspendida", revoked: "Revocada", not_allowed: "No permitida" })[control.status] || "Sin comprobar";
}

function ownerCapabilityLabel(enabled) {
  return enabled ? "Activada" : "Desactivada";
}

function ownerHealthLabel(status) {
  return ({ warning: "Funciona con avisos", degraded: "Necesita revisión", action_required: "Requiere acción", revoked: "Acceso revocado", suspended: "Suspendida", error: "No está funcionando", healthy: "Operativa" })[status] || "No se pudo comprobar";
}

function renderIntegrationAttention() {
  const source = ownerDashboardState.channels;
  if (source.status === "error" && !source.data) { setOwnerDashboardBlock("owner-dashboard-integrations", ownerDashboardError(), "error"); return; }
  const attention = integrationAttentionItems();
  if (!attention.length) {
    const content = source.status === "error"
      ? ownerDashboardStale() + ownerDashboardEmpty("Última comprobación sin problemas", "La fuente debe recuperarse para confirmar el estado actual.")
      : source.errors
      ? ownerDashboardPartial(source.errors) + ownerDashboardEmpty("Comprobación incompleta", "No se confirmaron problemas en las fuentes disponibles.")
      : ownerDashboardEmpty("Sin integraciones problemáticas", "No hay integraciones que requieran atención.");
    setOwnerDashboardBlock("owner-dashboard-integrations", content, source.status === "error" ? "error" : source.errors ? "partial" : "ready");
    return;
  }
  const html = (source.status === "error" ? ownerDashboardStale() : ownerDashboardPartial(source.errors)) + `<ul class="owner-dashboard-list">${attention.slice(0, 6).map(({ business, control, health }) => {
    const channel = health.channel === "instagram" ? "Instagram" : "WhatsApp";
    const recommendation = health.reconnection_required ? "La cuenta debe volver a conectarse." : health.health_status === "warning" ? "Conviene comprobar el canal." : "Revisa el estado antes de reanudar capacidades.";
    return `<li class="owner-dashboard-item"><div class="owner-dashboard-item__heading"><div><h3>${escapeHtml(channel)} · ${escapeHtml(business.name)}</h3><p>${escapeHtml(ownerHealthLabel(health.health_status))}</p></div><span class="ag-badge ag-badge--danger">Atención</span></div><div class="owner-dashboard-item__layers"><span><strong>Aprobación</strong>${escapeHtml(ownerApprovalLabel(control))}</span><span><strong>Envío</strong>${escapeHtml(ownerCapabilityLabel(control?.integrated_delivery_enabled))}</span><span><strong>Automatización</strong>${escapeHtml(ownerCapabilityLabel(control?.automation_enabled))}</span></div><div class="owner-dashboard-item__meta"><span>Última comprobación: ${escapeHtml(formatOwnerDate(health.last_health_check_at))}</span><span>${escapeHtml(recommendation)}</span></div><button class="button button-secondary button-small owner-dashboard-item__action" type="button" data-owner-navigate="integrations" data-owner-business-id="${escapeHtml(business.id)}" data-owner-detail="${escapeHtml(health.channel)}">Revisar integración</button></li>`;
  }).join("")}</ul>`;
  setOwnerDashboardBlock("owner-dashboard-integrations", html, source.status === "loading" ? "loading" : source.status === "error" ? "error" : source.errors ? "partial" : "ready");
}

function safeIncidentTitle(incident) {
  const category = ({ integration_unavailable: "Canal no disponible", provider_authentication: "Autorización del canal caducada", instagram_authentication: "Instagram necesita reconexión", instagram_token_expired: "Instagram necesita reconexión", provider_send_failure: "No se pudo procesar un mensaje", queue_processing_failure: "Procesamiento de mensajes interrumpido", security_incident: "Incidencia de seguridad" })[incident.category];
  return category || (incident.channel ? `Incidencia en ${incident.channel === "instagram" ? "Instagram" : "WhatsApp"}` : "Incidencia operativa");
}

function renderIncidentSummary() {
  const source = ownerDashboardState.incidents;
  if (source.status === "error" && !source.data) { setOwnerDashboardBlock("owner-dashboard-incidents", ownerDashboardError(), "error"); return; }
  const open = (dashboardSourceData("incidents", {}).incidents || []).filter((item) => ["open", "acknowledged"].includes(item.status));
  if (!open.length) {
    const content = source.status === "error" ? ownerDashboardStale() + ownerDashboardEmpty("Última comprobación sin incidencias", "Reintenta para confirmar el estado actual.") : ownerDashboardEmpty("No hay incidencias abiertas", "Las incidencias nuevas aparecerán aquí.");
    setOwnerDashboardBlock("owner-dashboard-incidents", content, source.status === "loading" ? "loading" : source.status === "error" ? "error" : "ready");
    return;
  }
  const html = (source.status === "error" ? ownerDashboardStale() : "") + `<ul class="owner-dashboard-list">${open.slice(0, 5).map((incident) => `<li class="owner-dashboard-item"><div class="owner-dashboard-item__heading"><div><h3>${escapeHtml(safeIncidentTitle(incident))}</h3><p>${escapeHtml(incident.business_name || "Plataforma")}</p></div><span class="ag-badge ${["critical", "high"].includes(incident.severity) ? "ag-badge--danger" : "ag-badge--warning"}">${escapeHtml(({ critical: "Crítica", high: "Alta", medium: "Media", low: "Baja" })[incident.severity] || "Sin clasificar")}</span></div><div class="owner-dashboard-item__meta"><span>${escapeHtml(incident.status === "acknowledged" ? "Reconocida" : "Abierta")}</span><span>${escapeHtml(formatOwnerDate(incident.last_occurred_at))}</span></div><button class="button button-secondary button-small owner-dashboard-item__action" type="button" data-owner-navigate="incidents" data-owner-context-id="${escapeHtml(incident.id)}">Abrir incidencia</button></li>`).join("")}</ul>`;
  setOwnerDashboardBlock("owner-dashboard-incidents", html, source.status === "loading" ? "loading" : source.status === "error" ? "error" : "ready");
}

function renderOperationsSummary() {
  const source = ownerDashboardState.queue;
  if (source.status === "error" && !source.data) { setOwnerDashboardBlock("owner-dashboard-operations", ownerDashboardError(), "error"); return; }
  const queue = source.data;
  if (!queue) return;
  const issueCount = ownerQueueIssueCount(queue);
  const workerProblem = !queue.worker_active || Number(queue.stale_worker_count || 0) > 0;
  const pending = Number(queue.pending_inbox || 0) + Number(queue.pending_outbox || 0);
  if (!issueCount && !workerProblem) {
    const message = source.status === "error" ? "Reintenta para confirmar el estado actual." : pending ? `${pending} mensajes pendientes continúan en procesamiento.` : "El procesamiento no presenta problemas detectados.";
    const content = (source.status === "error" ? ownerDashboardStale() : "") + ownerDashboardEmpty(source.status === "error" ? "Última comprobación operativa" : "Procesamiento operativo", message);
    setOwnerDashboardBlock("owner-dashboard-operations", content, source.status === "loading" ? "loading" : source.status === "error" ? "error" : "ready");
    return;
  }
  const rows = [
    ["Mensajes pendientes", pending],
    ["Reintentos programados", Number(queue.retry_inbox || 0) + Number(queue.retry_outbox || 0)],
    ["Casos que necesitan revisión", Number(queue.dead_letter_inbox || 0) + Number(queue.dead_letter_outbox || 0) + Number(queue.blocked_outbox || 0) + (queue.jobs || []).filter((item) => item.status === "failed").length],
    ["Procesamiento", workerProblem ? "Necesita atención" : "Operativo"],
  ];
  const html = (source.status === "error" ? ownerDashboardStale() : "") + `<ul class="owner-dashboard-status-list">${rows.map(([label, value]) => `<li><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></li>`).join("")}</ul><button class="button button-secondary button-small owner-dashboard-item__action" type="button" data-owner-navigate="operations" data-owner-detail="messages">Revisar procesamiento</button>`;
  setOwnerDashboardBlock("owner-dashboard-operations", html, source.status === "loading" ? "loading" : source.status === "error" ? "error" : "ready");
}

function businessAttentionReasons(business) {
  const reasons = [];
  if (business.status !== "active") reasons.push(business.status === "suspended" ? "Negocio suspendido" : "Onboarding incompleto");
  if (!business.health?.has_basic_info) reasons.push("Información básica incompleta");
  if (!business.health?.has_active_services) reasons.push("Sin servicios activos");
  if (!business.health?.has_schedule) reasons.push("Sin horarios configurados");
  if (!business.health?.has_phone) reasons.push("Sin teléfono operativo");
  return reasons;
}

function renderBusinessesAttention() {
  const source = ownerDashboardState.businesses;
  if (source.status === "error" && !source.data) { setOwnerDashboardBlock("owner-dashboard-businesses", ownerDashboardError(), "error"); return; }
  const attention = dashboardSourceData("businesses", businesses).map((business) => ({ business, reasons: businessAttentionReasons(business) })).filter((item) => item.reasons.length);
  if (!attention.length) {
    const content = (source.status === "error" ? ownerDashboardStale() : "") + ownerDashboardEmpty(source.status === "error" ? "Última comprobación sin bloqueos" : "Sin bloqueos detectados", source.status === "error" ? "Reintenta para confirmar el estado actual." : "Los negocios cargados no presentan carencias operativas básicas.");
    setOwnerDashboardBlock("owner-dashboard-businesses", content, source.status === "loading" ? "loading" : source.status === "error" ? "error" : "ready");
    return;
  }
  const html = (source.status === "error" ? ownerDashboardStale() : "") + `<ul class="owner-dashboard-list">${attention.slice(0, 6).map(({ business, reasons }) => `<li class="owner-dashboard-item"><div class="owner-dashboard-item__heading"><h3>${escapeHtml(business.name)}</h3><span class="ag-badge ag-badge--warning">Revisar</span></div><p>${reasons.slice(0, 3).map(escapeHtml).join(" · ")}</p><button class="button button-secondary button-small owner-dashboard-item__action" type="button" data-owner-navigate="${business.status === "active" ? "businesses" : "new-business"}" data-owner-business-id="${escapeHtml(business.id)}"${business.status === "active" ? "" : ' data-owner-detail="onboarding"'}>${business.status === "active" ? "Abrir negocio" : "Continuar alta"}</button></li>`).join("")}</ul>`;
  setOwnerDashboardBlock("owner-dashboard-businesses", html, source.status === "loading" ? "loading" : source.status === "error" ? "error" : "ready");
}

function renderPlatformStatus() {
  const source = ownerDashboardState.platform;
  if (source.status === "error" && !source.data) { setOwnerDashboardBlock("owner-dashboard-platform", ownerDashboardError(), "error"); return; }
  const platform = source.data;
  if (!platform) return;
  const queue = dashboardSourceData("queue", null);
  const critical = (dashboardSourceData("incidents", {}).incidents || []).filter((item) => item.status !== "resolved" && item.status !== "ignored" && item.severity === "critical").length;
  const integrationIssues = integrationAttentionItems().length;
  const processing = !queue ? "No se pudo comprobar" : queue.worker_active && ownerQueueIssueCount(queue) === 0 ? "Operativo" : "Necesita atención";
  const rows = [
    ["API y datos", platform.database?.at_head === false ? "Necesita atención" : "Operativo"],
    ["Procesamiento de mensajes", processing],
    ["Trabajos de integración", integrationIssues ? "Necesita atención" : ownerDashboardState.channels.status === "error" ? "No se pudo comprobar" : "Operativos"],
    ["Incidencias críticas", critical],
    ["Última actualización", formatOwnerDate(platform.generated_at)],
  ];
  const html = (source.status === "error" ? ownerDashboardStale() : "") + `<ul class="owner-dashboard-status-list">${rows.map(([label, value]) => `<li><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></li>`).join("")}</ul><button class="button button-secondary button-small owner-dashboard-item__action" type="button" data-owner-navigate="operations">Abrir operaciones</button>`;
  setOwnerDashboardBlock("owner-dashboard-platform", html, source.status === "loading" ? "loading" : source.status === "error" ? "error" : "ready");
}

function ownerActivityItems() {
  const items = [];
  dashboardSourceData("businesses", businesses).forEach((business) => {
    if (business.created_at) items.push({ at: business.created_at, text: `${business.name}: negocio creado`, target: "businesses", businessId: business.id });
  });
  dashboardSourceData("channels", []).forEach((snapshot) => {
    [...(snapshot.instagramCandidates || []).map((item) => ({ ...item, channel: "Instagram" })), ...(snapshot.whatsappCandidates || []).map((item) => ({ ...item, channel: "WhatsApp" }))].forEach((candidate) => items.push({ at: candidate.created_at, text: `${snapshot.business.name}: candidatura ${candidate.channel} enviada`, target: "businesses", businessId: snapshot.business.id, detail: candidate.channel === "Instagram" ? "integration" : "channels" }));
    (snapshot.controls || []).forEach((control) => {
      const events = [[control.approved_at, `${control.channel === "instagram" ? "Instagram" : "WhatsApp"} aprobado`], [control.suspended_at, `${control.channel === "instagram" ? "Instagram" : "WhatsApp"} suspendido`], [control.revoked_at, `${control.channel === "instagram" ? "Instagram" : "WhatsApp"} revocado`]];
      events.filter(([at]) => at).forEach(([at, label]) => items.push({ at, text: `${snapshot.business.name}: ${label}`, target: "businesses", businessId: snapshot.business.id, detail: "channels" }));
    });
  });
  (dashboardSourceData("incidents", {}).incidents || []).forEach((incident) => items.push({ at: incident.resolved_at || incident.created_at, text: `${incident.business_name || "Plataforma"}: incidencia ${incident.resolved_at ? "resuelta" : "creada"}`, target: "incidents" }));
  return items.filter((item) => item.at).sort((left, right) => new Date(right.at) - new Date(left.at)).slice(0, 8);
}

function renderOwnerActivity() {
  const sourcesAvailable = ownerDashboardState.businesses.status !== "error" || ownerDashboardState.channels.status !== "error" || ownerDashboardState.incidents.status !== "error";
  if (!sourcesAvailable) { setOwnerDashboardBlock("owner-dashboard-activity", ownerDashboardError(), "error"); return; }
  const activity = ownerActivityItems();
  if (!activity.length) { setOwnerDashboardBlock("owner-dashboard-activity", ownerDashboardEmpty("Sin actividad reciente disponible", "La actividad aparecerá cuando existan eventos operativos confirmados."), "ready"); return; }
  const html = `<ul class="owner-dashboard-activity-list">${activity.map((item) => `<li><p>${escapeHtml(item.text)}</p><time datetime="${escapeHtml(item.at)}">${escapeHtml(formatOwnerDate(item.at))}</time><button class="owner-metric-link" type="button" data-owner-navigate="${escapeHtml(item.target)}"${item.businessId ? ` data-owner-business-id="${escapeHtml(item.businessId)}"` : ""}${item.detail ? ` data-owner-detail="${escapeHtml(item.detail)}"` : ""}>Abrir contexto</button></li>`).join("")}</ul>`;
  setOwnerDashboardBlock("owner-dashboard-activity", html, OWNER_DASHBOARD_SOURCE_NAMES.some((name) => ownerDashboardState[name].status === "loading") ? "loading" : "ready");
}

function renderOwnerDashboard() {
  byId("owner-dashboard-date").textContent = new Intl.DateTimeFormat("es-ES", { dateStyle: "full" }).format(new Date());
  renderOwnerMetrics();
  renderPendingDecisions();
  renderIntegrationAttention();
  renderIncidentSummary();
  renderOperationsSummary();
  renderBusinessesAttention();
  renderPlatformStatus();
  renderOwnerActivity();
}

function markOwnerDashboardSourceLoading(name) {
  ownerDashboardState[name].status = "loading";
  if (!ownerDashboardState[name].data) {
    const blockMap = { channels: ["owner-dashboard-decisions", "owner-dashboard-integrations"], incidents: ["owner-dashboard-incidents"], queue: ["owner-dashboard-operations"], businesses: ["owner-dashboard-businesses"], platform: ["owner-dashboard-platform"] };
    (blockMap[name] || []).forEach((id) => ownerDashboardBlock(id)?.setAttribute("aria-busy", "true"));
  }
}

async function fetchOwnerDashboardJson(path) {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) throw new Error(`Owner dashboard source failed (${response.status})`);
  return response.json();
}

async function loadOwnerDashboardBusinesses() {
  const version = ++ownerDashboardSourceVersions.businesses;
  markOwnerDashboardSourceLoading("businesses");
  renderOwnerDashboard();
  try {
    const data = await fetchOwnerDashboardJson("/api/owner/businesses");
    if (version !== ownerDashboardSourceVersions.businesses) return false;
    businesses = data;
    ownerDashboardState.businesses = { status: "ready", data, errors: 0 };
    renderSummary();
    if (document.querySelector('[data-panel="businesses"]').classList.contains("active")) renderBusinesses();
    renderOwnerDashboard();
    return true;
  } catch {
    if (version !== ownerDashboardSourceVersions.businesses) return false;
    ownerDashboardState.businesses.status = "error";
    renderOwnerDashboard();
    return false;
  }
}

async function loadBusinessChannelSnapshot(business) {
  const base = `/api/owner/businesses/${encodeURIComponent(business.id)}`;
  const results = await Promise.allSettled([
    fetchOwnerDashboardJson(`${base}/channel-controls`),
    fetchOwnerDashboardJson(`${base}/integrations/whatsapp/embedded-signup/candidates`),
    fetchOwnerDashboardJson(`${base}/channels/health`),
    fetchOwnerDashboardJson(`${base}/integrations/instagram/oauth/candidates`),
  ]);
  const value = (index, fallback) => results[index].status === "fulfilled" ? results[index].value : fallback;
  return {
    business: { id: business.id, name: business.name, slug: business.slug },
    controls: value(0, {}).channels || [],
    whatsappCandidates: value(1, []),
    health: value(2, {}).channels || [],
    instagramCandidates: value(3, []),
    errors: results.filter((result) => result.status === "rejected").length,
  };
}

async function loadOwnerDashboardChannels() {
  const version = ++ownerDashboardSourceVersions.channels;
  markOwnerDashboardSourceLoading("channels");
  renderOwnerDashboard();
  const snapshots = [];
  for (let index = 0; index < businesses.length; index += 4) {
    const batch = await Promise.all(businesses.slice(index, index + 4).map(loadBusinessChannelSnapshot));
    if (version !== ownerDashboardSourceVersions.channels) return;
    snapshots.push(...batch);
  }
  const errors = snapshots.filter((snapshot) => snapshot.errors === 4).length;
  ownerDashboardState.channels = { status: errors === businesses.length && businesses.length ? "error" : "ready", data: snapshots, errors: snapshots.filter((snapshot) => snapshot.errors > 0).length };
  renderOwnerDashboard();
}

async function loadOwnerDashboardIncidents() {
  const version = ++ownerDashboardSourceVersions.incidents;
  markOwnerDashboardSourceLoading("incidents");
  renderOwnerDashboard();
  try {
    const data = await fetchOwnerDashboardJson("/api/owner/incidents?limit=30");
    if (version !== ownerDashboardSourceVersions.incidents) return;
    ownerDashboardState.incidents = { status: "ready", data, errors: 0 };
    openIncidentCount = Number(data.open_count || 0);
    renderSummary();
  } catch {
    if (version !== ownerDashboardSourceVersions.incidents) return;
    ownerDashboardState.incidents.status = "error";
  }
  renderOwnerDashboard();
}

async function loadOwnerDashboardQueue() {
  const version = ++ownerDashboardSourceVersions.queue;
  markOwnerDashboardSourceLoading("queue");
  renderOwnerDashboard();
  try {
    const data = await fetchOwnerDashboardJson("/api/owner/system/queue-status");
    if (version !== ownerDashboardSourceVersions.queue) return;
    ownerDashboardState.queue = { status: "ready", data, errors: 0 };
  } catch {
    if (version !== ownerDashboardSourceVersions.queue) return;
    ownerDashboardState.queue.status = "error";
  }
  renderOwnerDashboard();
}

async function loadOwnerDashboardPlatform() {
  const version = ++ownerDashboardSourceVersions.platform;
  markOwnerDashboardSourceLoading("platform");
  renderOwnerDashboard();
  try {
    const data = await fetchOwnerDashboardJson("/api/owner/system/health");
    if (version !== ownerDashboardSourceVersions.platform) return;
    ownerDashboardState.platform = { status: "ready", data, errors: 0 };
  } catch {
    if (version !== ownerDashboardSourceVersions.platform) return;
    ownerDashboardState.platform.status = "error";
  }
  renderOwnerDashboard();
}

async function loadOwnerDashboard(options = {}) {
  if (ownerDashboardLoadInFlight) {
    ownerDashboardRerunRequested = true;
    return ownerDashboardLoadInFlight;
  }
  const announce = options.announce !== false;
  if (announce) byId("owner-sync-status").textContent = "Actualizando…";
  ownerDashboardLoadInFlight = (async () => {
    const businessesLoaded = await loadOwnerDashboardBusinesses();
    const sources = [loadOwnerDashboardIncidents(), loadOwnerDashboardQueue(), loadOwnerDashboardPlatform()];
    if (businessesLoaded) sources.push(loadOwnerDashboardChannels());
    else {
      ownerDashboardState.channels.status = "error";
      renderOwnerDashboard();
    }
    await Promise.allSettled(sources);
    ownerDashboardLastUpdated = new Date();
    updateOwnerSyncStatus();
    renderOwnerDashboard();
  })();
  try {
    await ownerDashboardLoadInFlight;
  } finally {
    ownerDashboardLoadInFlight = null;
    if (ownerDashboardRerunRequested) {
      ownerDashboardRerunRequested = false;
      return loadOwnerDashboard(options);
    }
  }
}

async function retryOwnerDashboardSource(source) {
  if (ownerDashboardRetryInFlight.has(source)) return;
  ownerDashboardRetryInFlight.add(source);
  try {
    if (source === "businesses") {
      const loaded = await loadOwnerDashboardBusinesses();
      if (loaded) await loadOwnerDashboardChannels();
    } else if (source === "channels") await loadOwnerDashboardChannels();
    else if (source === "incidents") await loadOwnerDashboardIncidents();
    else if (source === "queue") await loadOwnerDashboardQueue();
    else if (source === "platform") await loadOwnerDashboardPlatform();
    ownerDashboardLastUpdated = new Date();
    updateOwnerSyncStatus();
  } finally {
    ownerDashboardRetryInFlight.delete(source);
  }
}

function slugify(value) {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
    .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function setActiveTab(name) {
  const headings = {
    overview: ["Resumen operativo", "Supervisa negocios, aprobaciones, integraciones e incidencias de AutonoGrow."],
    businesses: ["Negocios", "Consulta y gestiona el contexto completo de cada cuenta."],
    "new-business": ["Altas y aprobaciones", "Continúa altas y toma decisiones pendientes con contexto seguro."],
    integrations: ["Integraciones", "Separa control comercial, conexión, capacidades, salud y recuperación."],
    "instagram-content": ["Contenido de Instagram", "Prepara material, versiones y fechas para el flujo de revisión."],
    incidents: ["Incidencias", "Revisa impacto, cronología y acciones operativas seguras."],
    operations: ["Operaciones", "Comprueba el estado técnico global y el mantenimiento."],
    audit: ["Auditoría operativa", "Consulta los hitos seguros disponibles sin exponer payloads ni datos internos."],
  };
  document.querySelectorAll("[data-tab]").forEach((tab) => {
    const active = tab.dataset.tab === name;
    tab.classList.toggle("active", active);
    if (active) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  });
  document.querySelectorAll("[data-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === name));
  byId("owner-page-title").textContent = headings[name]?.[0] || headings.overview[0];
  byId("owner-page-subtitle").textContent = headings[name]?.[1] || headings.overview[1];
  if (name !== "instagram-content") stopOwnerInstagramLifecyclePolling();
  if (name === "overview") renderOwnerDashboard();
  if (name === "businesses") renderBusinesses();
  if (name === "new-business" && typeof loadOwnerOnboardingHub === "function") loadOwnerOnboardingHub();
  if (name === "integrations" && typeof loadOwnerIntegrationsHub === "function") loadOwnerIntegrationsHub();
  if (name === "instagram-content") loadOwnerInstagramPanel();
  if (name === "incidents") loadIncidents();
  if (name === "queues") loadQueueStatus();
  if (name === "operations") {
    if (typeof loadOwnerOperationsHub === "function") loadOwnerOperationsHub();
    else loadOperationsStatus();
  }
  if (name === "audit" && typeof loadOwnerAuditHub === "function") loadOwnerAuditHub();
}

function navigateOwnerContext(target, businessId = null, detail = null, contextId = null) {
  const allowed = new Set(["overview", "businesses", "new-business", "integrations", "instagram-content", "incidents", "operations", "audit"]);
  if (!allowed.has(target)) return;
  setActiveTab(target);
  if (target === "new-business" && businessId && detail === "onboarding" && typeof openOwnerOnboarding === "function") {
    window.requestAnimationFrame(() => openOwnerOnboarding(businessId));
    return;
  }
  if (target === "new-business" && businessId && typeof openOwnerApprovalContext === "function") {
    window.requestAnimationFrame(() => openOwnerApprovalContext(businessId, detail));
    return;
  }
  if (target === "integrations" && businessId && typeof openOwnerIntegrationContext === "function") {
    window.requestAnimationFrame(() => openOwnerIntegrationContext(businessId, detail));
    return;
  }
  if (target === "incidents" && contextId && typeof openOwnerIncidentContext === "function") {
    window.requestAnimationFrame(() => openOwnerIncidentContext(contextId));
    return;
  }
  if (target === "operations" && detail && typeof setOwnerOperationsView === "function") {
    window.requestAnimationFrame(() => setOwnerOperationsView(detail));
    return;
  }
  if (target !== "businesses" || !businessId) return;
  window.requestAnimationFrame(() => {
    const card = document.querySelector(`[data-business-card-id="${CSS.escape(String(businessId))}"]`);
    if (!card) return;
    const selector = detail === "integration" ? "[data-owner-integration-id]" : detail === "channels" ? "[data-owner-channel-control-id]" : null;
    const details = selector ? card.querySelector(selector) : null;
    if (details) details.open = true;
    const focusTarget = details?.querySelector("summary") || card.querySelector("h3");
    focusTarget?.setAttribute("tabindex", "-1");
    focusTarget?.focus({ preventScroll: true });
    card.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  });
}

function renderOperationsStatus() {
  if (!operationsStatus) return;
  const items = [
    ["Release", operationsStatus.backend.release_id],
    ["PostgreSQL", operationsStatus.database.at_head ? "En head" : "Revisar migración"],
    ["Workers activos", operationsStatus.workers.active],
    ["Workers stale", operationsStatus.workers.stale],
    ["Disco libre", `${operationsStatus.storage.free_percent}%`],
    ["Último backup", operationsStatus.backups.last_status],
    ["Alertas abiertas", operationsStatus.alerts.open_incidents],
    ["Mantenimiento", operationsStatus.maintenance ? "Activo" : "Inactivo"],
  ];
  byId("operations-summary").innerHTML = items.map(([label, value]) => `<article class="summary-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></article>`).join("");
  byId("maintenance-toggle").textContent = operationsStatus.maintenance ? "Desactivar mantenimiento" : "Activar mantenimiento";
  byId("operations-details").textContent = "";
}

async function loadOperationsStatus() {
  byId("operations-status").textContent = "Comprobando...";
  const response = await fetch(`${API_BASE_URL}/api/owner/system/health`);
  const body = await readResponseBody(response);
  if (!response.ok) { byId("operations-status").textContent = body.detail || "No se pudo cargar el estado"; return; }
  operationsStatus = body;
  renderOperationsStatus();
  byId("operations-status").textContent = `Actualizado ${formatIncidentDate(body.generated_at)}`;
}

async function toggleMaintenance() {
  if (!operationsStatus) return;
  const action = operationsStatus.maintenance ? "disable" : "enable";
  const reason = window.prompt("Motivo operativo obligatorio:", "Ventana de mantenimiento planificada");
  if (!reason || reason.trim().length < 3) return;
  if (!window.confirm(`${action === "enable" ? "Activar" : "Desactivar"} el modo mantenimiento. ¿Continuar?`)) return;
  const response = await fetch(`${API_BASE_URL}/api/owner/system/maintenance/${action}?reason=${encodeURIComponent(reason.trim())}`, { method: "POST" });
  const body = await readResponseBody(response);
  if (!response.ok) throw new Error(body.detail || "No se pudo cambiar mantenimiento");
  await loadOperationsStatus();
}

function renderQueueStatus() {
  if (!queueStatus) return;
  const cards = [
    ["Worker", queueStatus.worker_active ? "Activo" : "Inactivo"],
    ["Heartbeat", formatIncidentDate(queueStatus.last_heartbeat)],
    ["Inbox pendientes", queueStatus.pending_inbox],
    ["Outbox pendientes", queueStatus.pending_outbox],
    ["Reintentos", queueStatus.retry_inbox + queueStatus.retry_outbox],
    ["Bloqueados", queueStatus.blocked_outbox],
    ["Dead letters", queueStatus.dead_letter_inbox + queueStatus.dead_letter_outbox],
    ["Más antiguo", formatIncidentDate(queueStatus.oldest_pending_at)],
  ];
  byId("queue-summary").innerHTML = cards.map(([label, value]) => `<article class="summary-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></article>`).join("");
  const filter = byId("queue-business-filter");
  const selected = filter.value;
  filter.innerHTML = '<option value="">Todos</option>' + businesses.map((item) => `<option value="${item.id}">${escapeHtml(item.name)}</option>`).join("");
  filter.value = selected;
  const jobs = (queueStatus.jobs || []).filter((job) => !selected || String(job.business_id) === selected);
  byId("queue-jobs").innerHTML = jobs.length ? jobs.map((job) => `<article class="incident-card"><div class="incident-heading"><div><h3>${escapeHtml(job.job_type)} #${escapeHtml(job.id)}</h3><p>Estado: ${escapeHtml(job.status)} · intentos ${escapeHtml(job.attempt_count)}/${escapeHtml(job.max_attempts)}</p></div></div><div class="incident-actions"><button class="button button-secondary button-small" data-queue-action="retry" data-job-type="${escapeHtml(job.job_type)}" data-job-id="${escapeHtml(job.id)}">Reintentar</button><button class="button button-danger button-small" data-queue-action="cancel" data-job-type="${escapeHtml(job.job_type)}" data-job-id="${escapeHtml(job.id)}">Cancelar</button></div></article>`).join("") : '<div class="empty-state">No hay trabajos accionables.</div>';
  byId("queue-incidents").innerHTML = (queueStatus.incidents || []).map(incidentCard).join("");
}

async function loadQueueStatus() {
  const response = await fetch(`${API_BASE_URL}/api/owner/system/queue-status`);
  const body = await readResponseBody(response);
  if (!response.ok) throw new Error(body.detail || "No se pudo consultar la cola");
  queueStatus = body;
  renderQueueStatus();
}

async function updateQueueJob(jobType, jobId, action) {
  const reason = window.prompt("Motivo obligatorio de la acción:");
  if (!reason || reason.trim().length < 3) return;
  const response = await fetch(`${API_BASE_URL}/api/owner/queue/${jobType}/${jobId}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: reason.trim() }) });
  const body = await readResponseBody(response);
  if (!response.ok) throw new Error(body.detail || "No se pudo actualizar el trabajo");
  await loadQueueStatus();
}

function renderSummary() {
  byId("total-businesses").textContent = businesses.length;
  byId("active-businesses").textContent = businesses.filter((item) => item.active).length;
  byId("pending-bookings").textContent = sum(businesses, (item) => item.metrics.pending_bookings);
  byId("pending-messages").textContent = sum(businesses, (item) => item.metrics.message_outbox_pending);
  byId("pending-reviews").textContent = sum(businesses, (item) => item.metrics.review_requests_pending);
  byId("open-incidents").textContent = openIncidentCount;
}

function formatIncidentDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("es-ES", { dateStyle: "short", timeStyle: "short" }).format(new Date(`${value}Z`));
}

function incidentCard(incident) {
  const actions = incident.status === "open"
    ? [["acknowledge", "Marcar reconocida"], ["resolve", "Resolver"], ["ignore", "Ignorar"]]
    : incident.status === "acknowledged"
      ? [["resolve", "Resolver"], ["ignore", "Ignorar"]]
      : [["reopen", "Reabrir"]];
  return `<article class="incident-card severity-${escapeHtml(incident.severity)}">
    <div class="incident-heading"><div><h3>${escapeHtml(incident.incident_id)}</h3><p>${escapeHtml(incident.category)} · ${escapeHtml(incident.operation)}</p></div><div class="incident-badges"><span class="incident-badge severity-${escapeHtml(incident.severity)}">${escapeHtml(incident.severity)}</span><span class="incident-badge">${escapeHtml(incident.status)}</span></div></div>
    <div class="incident-meta">
      <span><strong>Negocio</strong>${escapeHtml(incident.business_slug || incident.business_id || "Global")}</span>
      <span><strong>Canal / proveedor</strong>${escapeHtml(incident.channel || "—")} / ${escapeHtml(incident.provider || "—")}</span>
      <span><strong>Código</strong>${escapeHtml(incident.provider_error_code || "—")}</span>
      <span><strong>Ocurrencias</strong>${escapeHtml(incident.occurrence_count)}</span>
      <span><strong>Primera</strong>${escapeHtml(formatIncidentDate(incident.first_occurred_at))}</span>
      <span><strong>Última</strong>${escapeHtml(formatIncidentDate(incident.last_occurred_at))}</span>
      <span><strong>Último aviso</strong>${escapeHtml(formatIncidentDate(incident.notified_at))}</span>
      <span><strong>Conversación / mensaje</strong>${escapeHtml(incident.conversation_id || "—")} / ${escapeHtml(incident.message_id || "—")}</span>
    </div><div class="incident-actions">${actions.map(([action, label]) => `<button class="button ${action === "ignore" ? "button-danger" : "button-secondary"} button-small" type="button" data-incident-id="${incident.id}" data-incident-action="${action}">${label}</button>`).join("")}</div>
  </article>`;
}

function renderIncidents() {
  byId("incident-list").innerHTML = incidents.length ? incidents.map(incidentCard).join("") : '<div class="empty-state">No hay incidencias para estos filtros.</div>';
  byId("incidents-status").textContent = `${incidents.length} incidencia${incidents.length === 1 ? "" : "s"}`;
  const businessSelect = byId("incident-filters").elements.business_id;
  const selected = businessSelect.value;
  businessSelect.innerHTML = '<option value="">Todos</option>' + businesses.map((item) => `<option value="${item.id}">${escapeHtml(item.name)} (${escapeHtml(item.slug)})</option>`).join("");
  businessSelect.value = selected;
  renderSummary();
}

async function loadIncidents() {
  const form = byId("incident-filters");
  if (!form) return;
  byId("incidents-status").textContent = "Cargando…";
  const params = new URLSearchParams();
  if (form.elements.status.value === "active") params.set("open_only", "true");
  else if (form.elements.status.value) params.set("status", form.elements.status.value);
  if (form.elements.severity.value) params.set("severity", form.elements.severity.value);
  if (form.elements.business_id.value) params.set("business_id", form.elements.business_id.value);
  if (form.elements.channel.value) params.set("channel", form.elements.channel.value);
  try {
    const response = await fetch(`${API_BASE_URL}/api/owner/incidents?${params}`);
    const body = await readResponseBody(response);
    if (!response.ok) throw new Error(body.detail || "No se pudieron cargar las incidencias");
    incidents = body.incidents || [];
    openIncidentCount = Number(body.open_count || 0);
    renderIncidents();
  } catch (error) {
    byId("incidents-status").textContent = "No disponible";
    byId("incident-list").innerHTML = `<div class="error-box">${escapeHtml(error.message)}</div>`;
  }
}

async function updateIncident(incidentId, action, button) {
  button.disabled = true;
  const response = await fetch(`${API_BASE_URL}/api/owner/incidents/${incidentId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }) });
  const body = await readResponseBody(response);
  if (!response.ok) { button.disabled = false; throw new Error(body.detail || "No se pudo actualizar la incidencia"); }
  await loadIncidents();
}

function healthBadge(label, healthy) {
  return `<span class="health-badge ag-badge ${healthy ? "healthy ag-badge--success" : "missing ag-badge--warning"}">${label}${healthy ? "" : " pendiente"}</span>`;
}

function businessCard(business) {
  const slug = encodeURIComponent(business.slug);
  const health = business.health;
  const metrics = business.metrics;
  return `
    <article class="business-card" data-business-card-id="${escapeHtml(business.id)}">
      <div class="business-card-header">
        <div class="owner-brand-title">${business.logo_url ? `<img src="${escapeHtml(resolveMediaUrl(business.logo_url, true))}" alt="${escapeHtml(business.logo_alt || business.name)}">` : `<span>${escapeHtml((business.name || "?").slice(0,2).toUpperCase())}</span>`}<div><p class="business-category">${escapeHtml(business.category || "Sin categoría")}</p><h3>${escapeHtml(business.name)}</h3><p>${escapeHtml(business.city || "Sin ciudad")} · <code>${escapeHtml(business.slug)}</code></p></div></div>
        <span class="state-badge ag-badge ${business.active ? "active ag-badge--success" : "inactive ag-badge--neutral"}">${business.active ? "Activo" : "Inactivo"}</span>
      </div>
      <div class="health-row">
        ${healthBadge("Datos", health.has_basic_info)}
        ${healthBadge("Servicios", health.has_active_services)}
        ${healthBadge("Horarios", health.has_schedule)}
        ${healthBadge("Reseñas", health.has_reviews_url)}
        ${healthBadge("WhatsApp", health.has_phone)}
        ${healthBadge("Logo", health.has_logo)}
        ${healthBadge("Fotos", health.has_gallery)}
        ${healthBadge("Colores", health.has_colors)}
      </div>
      <div class="metrics-grid">
        <span><strong>${metrics.pending_bookings}</strong>Pendientes</span>
        <span><strong>${metrics.today_bookings}</strong>Hoy</span>
        <span><strong>${metrics.upcoming_bookings}</strong>Próximos</span>
        <span><strong>${metrics.message_outbox_pending}</strong>Mensajes</span>
        <span><strong>${metrics.review_requests_pending}</strong>Reseñas</span>
      </div>
      <div class="card-actions">
        <a class="button button-secondary button-small" href="../autonogrow-landing/index.html?b=${slug}" target="_blank" rel="noopener">Abrir landing</a>
        <a class="button button-secondary button-small" href="../autonogrow-admin/index.html?b=${slug}" target="_blank" rel="noopener">Abrir admin</a>
        <a class="button button-ghost button-small" href="../autonogrow-admin/index.html?b=${slug}#business" target="_blank" rel="noopener">Editar rápido</a>
        <button class="button ${business.active ? "button-danger" : "button-primary"} button-small" type="button" data-business-state-id="${business.id}" data-business-status="${escapeHtml(business.status || (business.active ? "active" : "configuration_pending"))}">${business.active ? "Suspender" : business.status === "suspended" ? "Reactivar" : "Continuar onboarding"}</button>
      </div>
      <details class="owner-brand-editor" data-owner-editor="${escapeHtml(business.slug)}"><summary>Marca y apariencia · ${escapeHtml(business.theme_key === "custom" ? "Personalizado" : (business.theme_key || "Sin paleta"))} · ${escapeHtml(business.template_key || "classic")}</summary>
        <div class="owner-brand-grid"><label>Paleta<select data-owner-theme>${paletteOptions(business.theme_key)}</select></label><label>Plantilla<select data-owner-template>${templateOptions(business.template_key)}</select></label><p class="wide helper" data-owner-template-description>${escapeHtml(templateDescription(business.template_key))}</p>${["primary","secondary","accent","background"].map((name, index) => `<label>${name}<span class="owner-color"><input type="color" data-owner-color="${name}" value="${escapeHtml(business[`${name}_color`] || PALETTES.slate_gold[index])}"><input data-owner-hex="${name}" aria-label="Código hexadecimal: ${name}" value="${escapeHtml(business[`${name}_color`] || PALETTES.slate_gold[index])}"></span></label>`).join("")}<label>Alt logo<input data-owner-logo-alt value="${escapeHtml(business.logo_alt || "")}"></label></div>
        <div class="owner-upload-row"><input id="owner-logo-input-${escapeHtml(business.slug)}" type="file" accept="image/jpeg,image/png,image/webp" hidden data-owner-media-input="logo" data-slug="${escapeHtml(business.slug)}"><button type="button" class="button button-secondary button-small" data-action="select-logo">Subir logo</button><button type="button" class="button button-danger button-small" data-action="delete-logo">Eliminar logo</button></div>
        <div class="owner-upload-row"><input id="owner-gallery-input-${escapeHtml(business.slug)}" type="file" accept="image/jpeg,image/png,image/webp" hidden data-owner-media-input="gallery" data-slug="${escapeHtml(business.slug)}"><input data-owner-gallery-alt placeholder="Texto alternativo" aria-label="Texto alternativo de la nueva foto"><button type="button" class="button button-secondary button-small" data-action="select-gallery">Subir foto</button></div>
        <div class="owner-gallery" data-owner-gallery></div><button type="button" class="button button-primary button-small" data-owner-brand-save>Guardar apariencia</button><span data-owner-feedback></span>
      </details>
      <details class="owner-users-editor" data-owner-users="${escapeHtml(business.slug)}"><summary>Usuarios del negocio</summary>
        <div class="owner-user-form"><input data-owner-user-email type="email" placeholder="persona@negocio.com" aria-label="Email del usuario"><select data-owner-user-role aria-label="Rol a asignar"><option value="business_admin">Administrador</option><option value="business_staff">Personal</option></select><button type="button" class="button button-primary button-small" data-owner-user-action="add">Añadir usuario</button></div>
        <div data-owner-users-list class="owner-users-list"><p>Cargando usuarios...</p></div><p data-owner-users-feedback class="status-text"></p>
      </details>
      <details class="owner-channel-control-editor" data-owner-channel-control-id="${business.id}"><summary>Control y onboarding de canales</summary><div data-owner-channel-control-content><p>Cargando permisos...</p></div></details>
      <details class="owner-integration-editor" data-owner-integration-id="${business.id}" data-owner-integration-name="${escapeHtml(business.name)}"><summary>Integraciones</summary><div data-owner-integration-content><p>Cargando Instagram...</p></div></details>
      <details class="owner-automation-editor" data-owner-automation-id="${business.id}" data-owner-automation-name="${escapeHtml(business.name)}"><summary>Plan, automatización y cuota</summary><div data-owner-automation-content><p>Cargando configuración...</p></div></details>
    </article>`;
}

function paletteOptions(selected) { return [...Object.keys(PALETTES), "custom"].map((key) => `<option value="${key}" ${key === selected ? "selected" : ""}>${key === "custom" ? "Personalizado" : key}</option>`).join(""); }
function templateOptions(selected) { return ["classic","elegant","beauty","clinic","urban","minimal"].map((key) => `<option value="${key}" ${key === selected ? "selected" : ""}>${key}</option>`).join(""); }
function templateDescription(key) { return TEMPLATE_DESCRIPTIONS[key] || TEMPLATE_DESCRIPTIONS.classic; }

function renderBusinesses() {
  renderSummary();
  byId("business-list").innerHTML = businesses.length
    ? businesses.map(businessCard).join("")
    : '<div class="empty-state">Todavía no hay negocios.</div>';
  byId("list-status").textContent = `${businesses.length} negocio${businesses.length === 1 ? "" : "s"}`;
  document.querySelectorAll("[data-owner-editor]").forEach(loadOwnerGallery);
  document.querySelectorAll("[data-owner-users]").forEach(loadOwnerUsers);
  document.querySelectorAll("[data-owner-channel-control-id]").forEach(loadOwnerChannelControls);
  document.querySelectorAll("[data-owner-integration-id]").forEach(loadOwnerIntegration);
  document.querySelectorAll("[data-owner-automation-id]").forEach(loadOwnerAutomation);
  restoreOwnerMediaStatus();
}

function ownerChannelControlStatusLabel(status) {
  return ({ not_allowed: "No permitido", available: "Disponible", pending_approval: "Pendiente de aprobación", approved: "Aprobado", suspended: "Suspendido", revoked: "Revocado" })[status] || "Estado no disponible";
}

function ownerIntegrationHealthLabel(kind, status) {
  const labels = {
    health: { unknown: "Aún no comprobado", healthy: "Correcta", warning: "Revisar", degraded: "Con problemas", action_required: "Requiere acción", revoked: "Revocada", suspended: "Suspendida", error: "No comprobada" },
    token: { unknown: "No comprobado", valid: "Válido", expires_soon: "Caduca pronto", critical: "Caducidad inminente", expired: "Caducado", revoked: "Revocado" },
    subscription: { unknown: "No comprobada", active: "Activa", subscribed: "Activa", missing: "No configurada", failed: "Fallida", error: "No comprobada" },
    asset: { unknown: "No comprobado", active: "Activo", registered: "Registrado", inaccessible: "Sin acceso", invalid: "No válido", failed: "Fallido" }
  };
  return labels[kind]?.[status] || "Estado no disponible";
}

function ownerIntegrationHealthTone(status) {
  if (status === "healthy") return "healthy";
  if (["warning", "degraded"].includes(status)) return "warning";
  if (["action_required", "revoked", "suspended", "error"].includes(status)) return "danger";
  return "unknown";
}

function ownerWhatsAppCandidate(candidate) {
  const setupReady = candidate.app_subscription_status === "subscribed" && candidate.phone_registration_status === "registered";
  return `<section class="owner-integration-warning"><h5>Cuenta de WhatsApp pendiente de revisión</h5><p><strong>${escapeHtml(candidate.candidate_verified_name || "WhatsApp Business")}</strong> · ${escapeHtml(candidate.candidate_display_phone_number_redacted || "número verificado")}</p><p>Finalidad: ${escapeHtml(candidate.purpose || "No indicada")} · Expira: ${escapeHtml(formatAutomationDate(candidate.expires_at))}</p><p>Suscripción: ${escapeHtml(ownerIntegrationHealthLabel("subscription", candidate.app_subscription_status))} · Registro: ${escapeHtml(ownerIntegrationHealthLabel("asset", candidate.phone_registration_status))}</p>${candidate.safe_error_message ? `<p>${escapeHtml(candidate.safe_error_message)}</p>` : ""}<div class="owner-integration-actions"><button class="button button-secondary button-small" type="button" data-owner-channel-action="whatsapp-retry" data-channel="whatsapp" data-attempt-id="${candidate.id}">Reintentar verificación</button><button class="button button-primary button-small" type="button" data-owner-channel-action="whatsapp-approve" data-channel="whatsapp" data-attempt-id="${candidate.id}" ${setupReady ? "" : "disabled"}>Aprobar cuenta</button><button class="button button-danger button-small" type="button" data-owner-channel-action="whatsapp-reject" data-channel="whatsapp" data-attempt-id="${candidate.id}">Rechazar cuenta</button></div></section>`;
}

function renderOwnerChannelControls(panel, data) {
  const names = { instagram: "Instagram", whatsapp: "WhatsApp" };
  const healthByChannel = Object.fromEntries((data.health_channels || []).map((item) => [item.channel, item]));
  panel.querySelector("[data-owner-channel-control-content]").innerHTML = `<p class="helper">Instagram y WhatsApp usan los flujos oficiales de Meta. Aprobar una cuenta no activa por sí solo el envío ni la automatización.</p><div class="owner-channel-control-grid">${data.channels.map((channel) => {
    const health = healthByChannel[channel.channel];
    const policy = `<select data-owner-channel-policy="${escapeHtml(channel.channel)}"><option value="business_admin" ${channel.connector_policy === "business_admin" ? "selected" : ""}>Administrador del negocio</option><option value="owner_only" ${channel.connector_policy === "owner_only" ? "selected" : ""}>Solo Owner</option></select>`;
    let actions = `<label>Quién puede solicitar${policy}</label><button class="button button-primary button-small" type="button" data-owner-channel-action="grant" data-channel="${escapeHtml(channel.channel)}">${channel.status === "not_allowed" ? "Conceder permiso" : "Guardar permiso"}</button>`;
    if (channel.status === "available" && channel.connector_policy === "owner_only") actions += channel.channel === "instagram" ? `<button class="button button-primary button-small" type="button" data-owner-channel-action="oauth-start" data-channel="instagram">Conectar con Instagram</button>` : `<button class="button button-secondary button-small" type="button" data-owner-channel-action="request" data-channel="${escapeHtml(channel.channel)}">Iniciar conexión controlada</button>`;
    if (channel.status === "pending_approval" && channel.connection_mode === "simulated" && channel.channel !== "instagram") actions += `<button class="button button-primary button-small" type="button" data-owner-channel-action="approve" data-channel="${escapeHtml(channel.channel)}">Aprobar uso</button>`;
    if (channel.status === "approved") actions += `<label class="checkbox-row"><input type="checkbox" data-owner-channel-delivery="${escapeHtml(channel.channel)}" ${channel.integrated_delivery_enabled ? "checked" : ""}> Envío integrado</label><label class="checkbox-row"><input type="checkbox" data-owner-channel-automation="${escapeHtml(channel.channel)}" ${channel.automation_enabled ? "checked" : ""}> Automatización</label><button class="button button-primary button-small" type="button" data-owner-channel-action="capabilities" data-channel="${escapeHtml(channel.channel)}">Guardar activaciones</button>`;
    if (!["not_allowed", "revoked"].includes(channel.status)) actions += `<button class="button button-danger button-small" type="button" data-owner-channel-action="suspend" data-channel="${escapeHtml(channel.channel)}">Suspender</button><button class="button button-danger button-small" type="button" data-owner-channel-action="revoke" data-channel="${escapeHtml(channel.channel)}">Revocar</button>`;
    if (health) actions += `<button class="button button-secondary button-small" type="button" data-owner-channel-action="health-check" data-channel="${escapeHtml(channel.channel)}">Comprobar ahora</button>${health.subscription_status === "missing" ? `<button class="button button-secondary button-small" type="button" data-owner-channel-action="retry-subscription" data-channel="${escapeHtml(channel.channel)}">Reintentar suscripción</button>` : ""}${health.reconnection_required && channel.channel === "instagram" ? `<button class="button button-primary button-small" type="button" data-owner-channel-action="health-reconnect" data-channel="instagram">Reconectar</button>` : ""}${health.reconnection_required && channel.channel === "whatsapp" ? `<a class="button button-primary button-small" href="../autonogrow-admin/index.html?b=${escapeHtml(data.business.slug)}#channels">Abrir onboarding</a>` : ""}`;
    const candidates = channel.channel === "whatsapp" ? (data.whatsapp_candidates || []).map(ownerWhatsAppCandidate).join("") : "";
    const healthPanel = health ? `<div class="owner-integration-health state-${ownerIntegrationHealthTone(health.health_status)}"><p><strong>Salud: ${escapeHtml(ownerIntegrationHealthLabel("health", health.health_status))}</strong></p><p>Última: ${escapeHtml(formatAutomationDate(health.last_health_check_at))} · Próxima: ${escapeHtml(formatAutomationDate(health.next_health_check_at))}</p><p>Token: ${escapeHtml(ownerIntegrationHealthLabel("token", health.token_expiry_status))} · Suscripción: ${escapeHtml(ownerIntegrationHealthLabel("subscription", health.subscription_status))} · Activo: ${escapeHtml(ownerIntegrationHealthLabel("asset", health.asset_status))}</p><p>Fallos consecutivos: ${Number(health.consecutive_health_failures || 0)}</p>${health.safe_error_message ? `<p>${escapeHtml(health.safe_error_message)}</p>` : ""}</div>` : `<p class="helper">Sin integración operativa.</p>`;
    return `<article class="owner-channel-control-card"><div class="owner-integration-heading"><h4>${escapeHtml(names[channel.channel])}</h4><span class="state-badge ag-badge ${channel.status === "approved" ? "active ag-badge--success" : "inactive ag-badge--neutral"}">${escapeHtml(ownerChannelControlStatusLabel(channel.status))}</span></div>${healthPanel}${candidates}<div class="owner-channel-control-actions">${actions}</div></article>`;
  }).join("")}</div><p data-owner-channel-feedback class="status-text"></p>`;
}

async function loadOwnerChannelControls(panel) {
  const businessId = panel.dataset.ownerChannelControlId;
  const [response, candidateResponse, healthResponse] = await Promise.all([
    fetch(`${API_BASE_URL}/api/owner/businesses/${businessId}/channel-controls`),
    fetch(`${API_BASE_URL}/api/owner/businesses/${businessId}/integrations/whatsapp/embedded-signup/candidates`),
    fetch(`${API_BASE_URL}/api/owner/businesses/${businessId}/channels/health`)
  ]);
  const body = await readResponseBody(response);
  if (!response.ok) {
    panel.querySelector("[data-owner-channel-control-content]").innerHTML = `<p class="error-box">${escapeHtml(body.detail || "No se pudieron cargar los controles")}</p>`;
    return;
  }
  body.whatsapp_candidates = candidateResponse.ok ? await candidateResponse.json() : [];
  body.health_channels = healthResponse.ok ? (await healthResponse.json()).channels : [];
  renderOwnerChannelControls(panel, body);
}

async function handleOwnerChannelControlAction(button) {
  const panel = button.closest("[data-owner-channel-control-id]");
  const channel = button.dataset.channel;
  const action = button.dataset.ownerChannelAction;
  const base = `${API_BASE_URL}/api/owner/businesses/${panel.dataset.ownerChannelControlId}/channel-controls/${encodeURIComponent(channel)}`;
  let url = `${base}/${action}`;
  let method = "POST";
  let payload = {};
  if (["health-check", "retry-subscription", "health-reconnect"].includes(action)) {
    const healthBase = `${API_BASE_URL}/api/owner/businesses/${panel.dataset.ownerChannelControlId}/channels/${encodeURIComponent(channel)}`;
    url = `${healthBase}/${action === "health-reconnect" ? "request-reconnection" : action}`;
  } else if (["whatsapp-approve", "whatsapp-reject", "whatsapp-retry"].includes(action)) {
    const signupBase = `${API_BASE_URL}/api/owner/businesses/${panel.dataset.ownerChannelControlId}/integrations/whatsapp/embedded-signup/candidates/${encodeURIComponent(button.dataset.attemptId)}`;
    if (action === "whatsapp-retry") {
      url = `${signupBase}/setup/retry`;
    } else {
      const reason = window.prompt("Motivo obligatorio de la decisión Owner:");
      if (!reason || reason.trim().length < 3) return;
      url = `${signupBase}/${action === "whatsapp-approve" ? "approve" : "reject"}`;
      payload = { reason: reason.trim() };
    }
  } else if (action === "oauth-start") {
    url = `${API_BASE_URL}/api/owner/businesses/${panel.dataset.ownerChannelControlId}/integrations/instagram/oauth/start`;
    payload = { purpose: null };
  } else if (action === "request") {
    payload = { confirm_meta_authority: true };
  } else {
    const reason = window.prompt("Motivo obligatorio de la acción:");
    if (!reason || reason.trim().length < 3) return;
    payload.reason = reason.trim();
    if (action === "grant") {
      url = `${base}/access`;
      method = "PUT";
      payload.connector_policy = panel.querySelector(`[data-owner-channel-policy="${channel}"]`).value;
    } else if (action === "capabilities") {
      payload.integrated_delivery_enabled = panel.querySelector(`[data-owner-channel-delivery="${channel}"]`).checked;
      payload.automation_enabled = panel.querySelector(`[data-owner-channel-automation="${channel}"]`).checked;
      method = "PATCH";
    }
  }
  button.disabled = true;
  const response = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  const body = await readResponseBody(response);
  if (!response.ok) { button.disabled = false; throw new Error(body.detail || "No se pudo actualizar el canal"); }
  if (action === "oauth-start") {
    if (!String(body.authorization_url || "").startsWith("https://www.instagram.com/oauth/authorize?")) throw new Error("Meta devolvió una URL de autorización no válida.");
    window.location.assign(body.authorization_url);
    return;
  }
  if (action === "health-reconnect" && channel === "instagram") {
    if (!String(body.authorization_url || "").startsWith("https://www.instagram.com/oauth/authorize?")) throw new Error("Meta devolvió una URL de autorización no válida.");
    window.location.assign(body.authorization_url);
    return;
  }
  await loadOwnerChannelControls(panel);
  panel.querySelector("[data-owner-channel-feedback]").textContent = "Control de canal actualizado y auditado.";
}

function ownerAutomationStatusLabel(status) {
  return ({ available: "Activo", near_limit: "Activo · cerca del límite", limit_reached: "Límite alcanzado", automation_paused: "Activo · automatización pausada", pending_renewal: "Pendiente de renovación", suspended: "Suspendido" })[status] || "Estado no disponible";
}

function formatAutomationDate(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return new Intl.DateTimeFormat("es-ES", { dateStyle: "short", timeStyle: "short" }).format(parsed);
}

function ownerIntegrationStatusLabel(status) {
  return ({ pending: "Pendiente", connected: "Conectado", degraded: "Necesita revisión", expired: "Caducado", disconnected: "Desconectado", revoked: "Revocado", error: "Error" })[status] || "Estado no disponible";
}

function ownerInstagramCredentialForm(mode) {
  return `<div class="owner-integration-form" data-owner-integration-form="${mode}">
    <label>Instagram Business Account ID<input data-integration-account-id maxlength="255" autocomplete="off" required></label>
    <label>Token de acceso<input data-integration-token type="password" maxlength="4096" autocomplete="new-password" required></label>
    <label>Caducidad opcional<input data-integration-expiration type="datetime-local"></label>
    <label>Motivo<input data-integration-reason maxlength="500" required></label>
    <p class="wide helper">Vía administrativa avanzada de compatibilidad. El token se envía una sola vez, se cifra y no se mostrará de nuevo.</p>
    <button class="button button-primary button-small" type="button" data-owner-integration-action="${mode}">${mode === "connect" ? "Conectar" : "Reconectar"}</button>
  </div>`;
}

function ownerInstagramCandidate(candidate) {
  const webhookRetry = candidate.webhook_subscription_status === "failed" ? `<button class="button button-secondary button-small" type="button" data-owner-integration-action="candidate-retry-webhook" data-attempt-id="${candidate.id}">Reintentar webhook</button>` : "";
  return `<section class="owner-integration-warning"><h5>Cuenta pendiente de revisión</h5><p><strong>${escapeHtml(candidate.candidate_external_account_name || "Cuenta profesional sin nombre público")}</strong> · ${escapeHtml(candidate.candidate_account_type || "Profesional")} · ${escapeHtml(candidate.purpose)}</p><p>Autorizada: ${escapeHtml(formatAutomationDate(candidate.created_at))} · Expira: ${escapeHtml(formatAutomationDate(candidate.candidate_token_expires_at))}</p><p>Webhook: ${escapeHtml(candidate.webhook_subscription_status || "pendiente")} · Permisos técnicos validados por el servidor</p>${candidate.safe_error_message ? `<p>${escapeHtml(candidate.safe_error_message)}</p>` : ""}<div class="owner-integration-actions">${webhookRetry}<button class="button button-primary button-small" type="button" data-owner-integration-action="candidate-approve" data-attempt-id="${candidate.id}" ${candidate.webhook_subscription_status !== "subscribed" ? "disabled" : ""}>Aprobar cuenta</button><button class="button button-danger button-small" type="button" data-owner-integration-action="candidate-reject" data-attempt-id="${candidate.id}">Rechazar cuenta</button></div></section>`;
}

function renderOwnerIntegration(panel, integration, candidates = []) {
  const content = panel.querySelector("[data-owner-integration-content]");
  const candidateHtml = candidates.map(ownerInstagramCandidate).join("");
  if (!integration) {
    content.innerHTML = `<article class="owner-integration-card"><h4>Instagram</h4><p>No conectado.</p>${candidateHtml}<button class="button button-primary button-small" type="button" data-owner-integration-action="oauth-start" data-oauth-purpose="initial_connection">Conectar con Instagram</button><p class="helper">La conexión segura continúa en Instagram; este panel no solicita credenciales.</p><p data-owner-integration-feedback class="status-text"></p></article>`;
    return;
  }
  content.innerHTML = `<article class="owner-integration-card">
    <div class="owner-integration-heading"><h4>Instagram</h4><span class="state-badge ag-badge ${integration.integration_status === "connected" ? "active ag-badge--success" : "inactive ag-badge--neutral"}">${escapeHtml(ownerIntegrationStatusLabel(integration.integration_status))}</span></div>${candidateHtml}
    <div class="owner-integration-summary"><span><strong>${escapeHtml(integration.external_account_name || "Nombre público no disponible")}</strong>Cuenta pública</span><span><strong>${escapeHtml(formatAutomationDate(integration.connected_at))}</strong>Conectado desde</span><span><strong>${escapeHtml(formatAutomationDate(integration.last_verified_at))}</strong>Última verificación</span><span><strong>${escapeHtml(formatAutomationDate(integration.last_success_at))}</strong>Último éxito</span><span><strong>${escapeHtml(formatAutomationDate(integration.token_expires_at))}</strong>Caducidad</span></div>
    ${integration.expires_soon ? `<p class="owner-integration-warning">El token caduca próximamente (${integration.days_remaining} días).</p>` : ""}
    ${integration.safe_error_message ? `<p class="owner-integration-warning">${escapeHtml(integration.safe_error_message)}</p>` : ""}
    ${integration.has_open_incident ? `<p class="owner-integration-warning">Existe una incidencia abierta para esta integración.</p>` : ""}
    <p>Los permisos técnicos se validan en el servidor y no se muestran en este panel.</p>
    <div class="owner-integration-actions"><button class="button button-primary button-small" type="button" data-owner-integration-action="oauth-start" data-oauth-purpose="replacement">Conectar o reemplazar con Instagram</button><button class="button button-secondary button-small" type="button" data-owner-integration-action="verify">Verificar conexión</button><button class="button button-danger button-small" type="button" data-owner-integration-action="disconnect">Desconectar</button><button class="button button-danger button-small" type="button" data-owner-integration-action="delete-credentials">Eliminar credenciales</button><button class="button button-secondary button-small" type="button" data-owner-integration-action="incidents">Ver incidencias</button></div>
    <div data-owner-integration-reconnect></div><p data-owner-integration-feedback class="status-text"></p>
  </article>`;
}

async function loadOwnerIntegration(panel) {
  const base = `${API_BASE_URL}/api/owner/businesses/${panel.dataset.ownerIntegrationId}/integrations/instagram`;
  const [response, candidateResponse] = await Promise.all([fetch(base), fetch(`${base}/oauth/candidates`)]);
  const candidates = candidateResponse.ok ? await candidateResponse.json() : [];
  if (response.status === 404) { renderOwnerIntegration(panel, null, candidates); return; }
  const body = await readResponseBody(response);
  if (!response.ok) { panel.querySelector("[data-owner-integration-content]").innerHTML = `<p class="error-box">${escapeHtml(body.detail || "No se pudo cargar Instagram")}</p>`; return; }
  renderOwnerIntegration(panel, body, candidates);
}

async function handleOwnerIntegrationAction(button) {
  const panel = button.closest("[data-owner-integration-id]");
  const action = button.dataset.ownerIntegrationAction;
  const feedback = panel.querySelector("[data-owner-integration-feedback]");
  const base = `${API_BASE_URL}/api/owner/businesses/${panel.dataset.ownerIntegrationId}/integrations/instagram`;
  if (action === "show-reconnect") {
    panel.querySelector("[data-owner-integration-reconnect]").innerHTML = ownerInstagramCredentialForm("reconnect");
    return;
  }
  if (action === "oauth-start") {
    const response = await fetch(`${base}/oauth/start`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ purpose: button.dataset.oauthPurpose || null }) });
    const body = await readResponseBody(response);
    if (!response.ok) throw new Error(body.detail || "No se pudo iniciar Instagram Login");
    if (!String(body.authorization_url || "").startsWith("https://www.instagram.com/oauth/authorize?")) throw new Error("Meta devolvió una URL de autorización no válida.");
    window.location.assign(body.authorization_url);
    return;
  }
  if (action === "candidate-approve" || action === "candidate-reject") {
    const reason = window.prompt("Motivo obligatorio de la decisión Owner:");
    if (!reason || reason.trim().length < 3) return;
    const decision = action === "candidate-approve" ? "approve" : "reject";
    const response = await fetch(`${base}/oauth/candidates/${encodeURIComponent(button.dataset.attemptId)}/${decision}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: reason.trim() }) });
    const body = await readResponseBody(response);
    if (!response.ok) throw new Error(body.detail || "No se pudo revisar la cuenta candidata");
    const businessCard = panel.closest(".business-card");
    const controlPanel = businessCard?.querySelector("[data-owner-channel-control-id]");
    await loadOwnerIntegration(panel);
    if (controlPanel) await loadOwnerChannelControls(controlPanel);
    return;
  }
  if (action === "candidate-retry-webhook") {
    const response = await fetch(`${base}/oauth/candidates/${encodeURIComponent(button.dataset.attemptId)}/webhook/retry`, { method: "POST" });
    const body = await readResponseBody(response);
    if (!response.ok) throw new Error(body.detail || "No se pudo reintentar el webhook");
    await loadOwnerIntegration(panel);
    return;
  }
  if (action === "incidents") { setActiveTab("incidents"); await loadIncidents(); return; }
  let response;
  if (action === "connect" || action === "reconnect") {
    const form = button.closest("[data-owner-integration-form]");
    const tokenInput = form.querySelector("[data-integration-token]");
    const accountId = form.querySelector("[data-integration-account-id]").value.trim();
    const accessToken = tokenInput.value;
    const expiration = form.querySelector("[data-integration-expiration]").value;
    const reason = form.querySelector("[data-integration-reason]").value.trim();
    if (!accountId || !accessToken || !reason) throw new Error("Cuenta, token y motivo son obligatorios.");
    if (!window.confirm(`${action === "connect" ? "Conectar" : "Reconectar"} Instagram para ${panel.dataset.ownerIntegrationName}. ¿Continuar?`)) { tokenInput.value = ""; return; }
    const payload = { external_account_id: accountId, access_token: accessToken, token_expires_at: expiration ? new Date(expiration).toISOString() : null, reason };
    tokenInput.value = "";
    response = await fetch(action === "connect" ? base : `${base}/reconnect`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    payload.access_token = "";
  } else if (action === "verify") {
    response = await fetch(`${base}/verify`, { method: "POST" });
  } else if (action === "disconnect" || action === "delete-credentials") {
    const reason = window.prompt(`Motivo obligatorio para ${action === "disconnect" ? "desconectar" : "eliminar las credenciales"}:`);
    if (!reason?.trim()) return;
    if (!window.confirm(action === "delete-credentials" ? "Las credenciales cifradas se eliminarán definitivamente. ¿Continuar?" : "Se impedirán nuevos envíos. ¿Continuar?")) return;
    response = await fetch(action === "disconnect" ? `${base}/disconnect` : `${base}/credentials`, { method: action === "disconnect" ? "POST" : "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: reason.trim() }) });
  }
  const body = await readResponseBody(response);
  if (!response.ok) throw new Error(body.detail || "No se pudo actualizar la integración");
  if (feedback) feedback.textContent = "Integración actualizada.";
  await loadOwnerIntegration(panel);
}

function renderOwnerAutomation(panel, data) {
  const settings = data.settings;
  const usage = data.usage;
  const credits = data.credits;
  const allowed = settings.allowed_limit_behaviors || ["disabled"];
  const lastIncident = data.last_incident;
  panel.dataset.ownerPeriodStatus = usage.period_status || "pending_renewal";
  panel.dataset.ownerPeriodDays = String(usage.days_remaining || 0);
  panel.dataset.ownerPeriodStart = usage.period_start || "";
  panel.dataset.ownerPeriodEnd = usage.period_end || "";
  panel.dataset.ownerPlan = settings.plan || "—";
  panel.dataset.ownerLimit = String(usage.limit);
  panel.dataset.ownerUsage = String(usage.used);
  panel.querySelector("[data-owner-automation-content]").innerHTML = `
    <div class="owner-automation-summary">
      <span><strong>${usage.used} / ${usage.limit}</strong>Mensajes del periodo</span><span><strong>${usage.percentage}%</strong>Consumido</span><span><strong>${escapeHtml(ownerAutomationStatusLabel(usage.status))}</strong>Estado</span><span><strong>${escapeHtml(formatAutomationDate(usage.period_start))}</strong>Inicio</span><span><strong>${escapeHtml(formatAutomationDate(usage.period_end))}</strong>Vencimiento</span><span><strong>${usage.days_remaining}</strong>Días restantes</span>
    </div>
    <div class="owner-automation-progress"><span style="width:${usage.percentage}%"></span></div>
    <section class="owner-credit-wallet">
      <h4>Créditos de automatización</h4>
      <div class="owner-automation-summary"><span><strong>${credits.included_credits_remaining} / ${credits.included_credits_per_period}</strong>Incluidos disponibles</span><span><strong>${credits.included_credits_used}</strong>Incluidos utilizados</span><span><strong>${credits.additional_credits_balance}</strong>Adicionales acumulados</span><span><strong>${credits.total_available}</strong>Total disponible</span></div>
      <div class="owner-automation-actions">${OWNER_CREDIT_PRESETS.map((amount) => `<button class="button button-secondary button-small" type="button" data-owner-automation-action="purchase-credit" data-credit-amount="${amount}">+${amount} créditos</button>`).join("")}<button class="button button-primary button-small" type="button" data-owner-automation-action="purchase-credit">Añadir créditos adicionales</button><button class="button button-secondary button-small" type="button" data-owner-automation-action="adjust-credits">Ajustar saldo</button><button class="button button-secondary button-small" type="button" data-owner-automation-action="credit-history">Ver historial</button></div>
      <div data-owner-credit-history class="owner-credit-history">${(data.credit_transactions || []).map((item) => `<p><strong>${escapeHtml(item.transaction_type)}</strong> · ${item.included_delta >= 0 ? "+" : ""}${item.included_delta} incluidos · ${item.additional_delta >= 0 ? "+" : ""}${item.additional_delta} adicionales · saldo ${item.total_balance_after} · ${escapeHtml(formatAutomationDate(item.created_at))}</p>`).join("") || "<p>Sin movimientos.</p>"}</div>
    </section>
    <div class="owner-automation-grid">
      <label>Plan<input data-owner-automation-plan maxlength="60" value="${escapeHtml(settings.plan || "")}" placeholder="standard"></label>
      <label>Límite por periodo<input data-owner-automation-limit type="number" min="0" max="${data.limit_max}" value="${settings.auto_limit_per_period}"></label>
      <label>Al alcanzar el límite<select data-owner-automation-limit-mode><option value="semi_automatic" ${settings.on_limit_reached === "semi_automatic" ? "selected" : ""}>Pasar a sugerencias</option><option value="disabled" ${settings.on_limit_reached === "disabled" ? "selected" : ""}>No responder</option></select></label>
      <label class="checkbox-row"><input data-owner-automation-instagram type="checkbox" ${settings.instagram_channel_enabled ? "checked" : ""}> Instagram habilitado</label>
      <label class="checkbox-row"><input data-owner-automation-whatsapp type="checkbox" ${settings.whatsapp_channel_enabled ? "checked" : ""}> WhatsApp habilitado</label>
      <fieldset class="owner-limit-behaviors"><legend>Opciones disponibles para el admin</legend><label class="checkbox-row"><input data-owner-limit-behavior="semi_automatic" type="checkbox" ${allowed.includes("semi_automatic") ? "checked" : ""}> Pasar a sugerencias</label><label class="checkbox-row"><input data-owner-limit-behavior="disabled" type="checkbox" ${allowed.includes("disabled") ? "checked" : ""}> No responder</label></fieldset>
    </div>
    <p class="owner-automation-feature-state">Último pago confirmado: <strong>${escapeHtml(formatAutomationDate(usage.payment_confirmed_at))}</strong> · Automatización comercial: <strong>${settings.automation_feature_enabled ? "habilitada" : "suspendida"}</strong> · Estado operativo: <strong>${settings.automation_enabled ? "activo" : "pausado"}</strong></p>
    <p>Canales habilitados: <strong>${[settings.instagram_channel_enabled ? "Instagram" : null, settings.whatsapp_channel_enabled ? "WhatsApp" : null].filter(Boolean).join(" · ") || "ninguno"}</strong></p>
    <p>Última incidencia: ${lastIncident ? `<strong>${escapeHtml(lastIncident.incident_id)}</strong> · ${escapeHtml(lastIncident.status)} · ${escapeHtml(lastIncident.category)}` : "ninguna"}</p>
    <div class="owner-automation-actions"><button class="button button-primary button-small" type="button" data-owner-automation-action="renew">Confirmar pago y renovar 30 días</button><button class="button button-secondary button-small" type="button" data-owner-automation-action="adjust-period">Corrección administrativa del periodo</button><button class="button button-secondary button-small" type="button" data-owner-automation-action="save">Guardar plan y créditos incluidos</button><button class="button ${settings.automation_feature_enabled ? "button-danger" : "button-primary"} button-small" type="button" data-owner-automation-action="feature" data-next-enabled="${!settings.automation_feature_enabled}">${settings.automation_feature_enabled ? "Suspender automatización" : "Reactivar automatización"}</button></div>
    <p data-owner-automation-feedback class="status-text"></p>`;
}

async function loadOwnerAutomation(panel) {
  const content = panel.querySelector("[data-owner-automation-content]");
  try {
    const response = await fetch(`${API_BASE_URL}/api/owner/businesses/${panel.dataset.ownerAutomationId}/automation-settings`);
    const body = await readResponseBody(response);
    if (!response.ok) throw new Error(body.detail || "No se pudo cargar la automatización");
    renderOwnerAutomation(panel, body);
  } catch (error) {
    content.innerHTML = `<p class="error-box">${escapeHtml(error.message)}</p>`;
  }
}

async function ownerAutomationRequest(panel, path, options) {
  const feedback = panel.querySelector("[data-owner-automation-feedback]");
  if (feedback) feedback.textContent = "Guardando...";
  const response = await fetch(`${API_BASE_URL}/api/owner/businesses/${panel.dataset.ownerAutomationId}/${path}`, options);
  const body = await readResponseBody(response);
  if (!response.ok) throw new Error(body.detail || "No se pudo actualizar la automatización");
  await loadOwnerAutomation(panel);
}

async function handleOwnerAutomationAction(button) {
  const panel = button.closest("[data-owner-automation-id]");
  const businessName = panel.dataset.ownerAutomationName;
  const action = button.dataset.ownerAutomationAction;
  if (action === "purchase-credit") {
    const preset = Number(button.dataset.creditAmount || 0);
    const rawCredits = preset || Number(window.prompt(`Créditos adicionales para ${businessName}:`));
    if (!Number.isInteger(rawCredits) || rawCredits <= 0) throw new Error("Los créditos deben ser un entero positivo.");
    const amountText = window.prompt("Importe pagado (opcional):", "") ?? "";
    const paymentAmount = amountText.trim() ? Number(amountText) : null;
    if (paymentAmount !== null && (!Number.isFinite(paymentAmount) || paymentAmount <= 0)) throw new Error("El importe debe ser positivo.");
    const paymentMethod = (window.prompt("Método de pago opcional (bank_transfer, cash, card u other):", "") ?? "").trim() || null;
    const externalReference = (window.prompt("Referencia externa opcional:", "") ?? "").trim() || null;
    const reason = window.prompt(`Motivo obligatorio para añadir ${rawCredits} créditos a ${businessName}:`);
    if (!reason?.trim()) throw new Error("El motivo es obligatorio.");
    if (!window.confirm(`Añadir ${rawCredits} créditos adicionales a ${businessName}. No se modificará el periodo ni el plan. ¿Confirmar?`)) return;
    const idempotencyKey = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    await ownerAutomationRequest(panel, "automation-credits/purchase", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ credits: rawCredits, payment_amount: paymentAmount, payment_method: paymentMethod, external_reference: externalReference, reason: reason.trim(), idempotency_key: idempotencyKey }) });
  } else if (action === "adjust-credits") {
    const includedDelta = Number(window.prompt("Variación de créditos incluidos disponibles (puede ser negativa):", "0"));
    const additionalDelta = Number(window.prompt("Variación de créditos adicionales (puede ser negativa):", "0"));
    if (!Number.isInteger(includedDelta) || !Number.isInteger(additionalDelta) || (includedDelta === 0 && additionalDelta === 0)) throw new Error("Introduce al menos una variación entera distinta de cero.");
    const reason = window.prompt(`Motivo obligatorio del ajuste de saldo para ${businessName}:`);
    if (!reason?.trim()) throw new Error("El motivo es obligatorio.");
    const warning = includedDelta < 0 || additionalDelta < 0 ? " ADVERTENCIA: este ajuste reducirá el saldo disponible." : "";
    if (!window.confirm(`Ajustar saldo de ${businessName}: incluidos ${includedDelta >= 0 ? "+" : ""}${includedDelta}, adicionales ${additionalDelta >= 0 ? "+" : ""}${additionalDelta}.${warning} ¿Confirmar?`)) return;
    const idempotencyKey = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    await ownerAutomationRequest(panel, "automation-credits/adjustment", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ included_delta: includedDelta, additional_delta: additionalDelta, reason: reason.trim(), idempotency_key: idempotencyKey }) });
  } else if (action === "credit-history") {
    const response = await fetch(`${API_BASE_URL}/api/owner/businesses/${panel.dataset.ownerAutomationId}/automation-credits/transactions?limit=100`);
    const body = await readResponseBody(response);
    if (!response.ok) throw new Error(body.detail || "No se pudo cargar el historial de créditos");
    panel.querySelector("[data-owner-credit-history]").innerHTML = body.map((item) => `<p><strong>${escapeHtml(item.transaction_type)}</strong> · ${item.included_delta >= 0 ? "+" : ""}${item.included_delta} incluidos · ${item.additional_delta >= 0 ? "+" : ""}${item.additional_delta} adicionales · saldo ${item.total_balance_after} · ${escapeHtml(formatAutomationDate(item.created_at))} · ${escapeHtml(item.reason)}</p>`).join("") || "<p>Sin movimientos.</p>";
  } else if (action === "save") {
    const allowed = Array.from(panel.querySelectorAll("[data-owner-limit-behavior]:checked"), (item) => item.dataset.ownerLimitBehavior);
    if (!allowed.length) throw new Error("Selecciona al menos una opción permitida para el admin.");
    const behavior = panel.querySelector("[data-owner-automation-limit-mode]").value;
    if (!allowed.includes(behavior)) throw new Error("El comportamiento seleccionado debe estar entre las opciones permitidas.");
    if (!window.confirm(`Vas a modificar el plan y la cuota de ${businessName}. ¿Continuar?`)) return;
    const reason = window.prompt(`Motivo opcional del cambio para ${businessName}:`, "") ?? "";
    const payload = { plan: panel.querySelector("[data-owner-automation-plan]").value.trim() || null, auto_limit_per_period: Number(panel.querySelector("[data-owner-automation-limit]").value), on_limit_reached: behavior, allowed_limit_behaviors: allowed, instagram_channel_enabled: panel.querySelector("[data-owner-automation-instagram]").checked, whatsapp_channel_enabled: panel.querySelector("[data-owner-automation-whatsapp]").checked, reason };
    await ownerAutomationRequest(panel, "automation-settings", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  } else if (action === "renew") {
    const now = new Date();
    const expectedEnd = new Date(now.getTime() + (30 * 24 * 60 * 60 * 1000));
    const activeWarning = panel.dataset.ownerPeriodStatus === "active"
      ? `\n\nADVERTENCIA: todavía quedan ${panel.dataset.ownerPeriodDays} días activos. La renovación sustituirá el periodo actual y comenzará hoy.`
      : "";
    const confirmation = `Confirmar pago de ${businessName}\n\nPlan: ${panel.dataset.ownerPlan}\nLímite: ${panel.dataset.ownerLimit}\nConsumo actual: ${panel.dataset.ownerUsage}\nInicio previsto: ${formatAutomationDate(now.toISOString())}\nVencimiento previsto: ${formatAutomationDate(expectedEnd.toISOString())}\n\nEl consumo pasará a cero.${activeWarning}`;
    if (!window.confirm(confirmation)) return;
    const reason = window.prompt(`Motivo o referencia del pago para ${businessName} (obligatorio):`);
    if (!reason?.trim()) throw new Error("El motivo es obligatorio.");
    const amountText = window.prompt("Importe recibido (opcional, usa punto decimal):", "") ?? "";
    const amount = amountText.trim() ? Number(amountText) : null;
    if (amount !== null && (!Number.isFinite(amount) || amount < 0)) throw new Error("El importe no es válido.");
    const paymentMethod = (window.prompt("Método de pago opcional (bank_transfer, cash, card u other):", "") ?? "").trim() || null;
    const externalReference = (window.prompt("Referencia externa opcional:", "") ?? "").trim() || null;
    const idempotencyKey = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    button.disabled = true;
    try {
      await ownerAutomationRequest(panel, "automation-period-renewal", { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey }, body: JSON.stringify({ reason: reason.trim(), amount, payment_method: paymentMethod, external_reference: externalReference, confirm_active_period: panel.dataset.ownerPeriodStatus === "active" }) });
    } finally {
      button.disabled = false;
    }
  } else if (action === "adjust-period") {
    const startText = window.prompt("Inicio corregido en UTC (formato ISO, termina en Z):", panel.dataset.ownerPeriodStart || new Date().toISOString());
    if (startText === null) return;
    const endText = window.prompt("Vencimiento corregido en UTC (formato ISO, termina en Z):", panel.dataset.ownerPeriodEnd || new Date(Date.now() + (30 * 86400000)).toISOString());
    if (endText === null) return;
    const start = new Date(startText);
    const end = new Date(endText);
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end <= start) throw new Error("Las fechas corregidas no son válidas.");
    const reason = window.prompt(`Motivo obligatorio de la corrección administrativa para ${businessName}:`);
    if (!reason?.trim()) throw new Error("El motivo es obligatorio.");
    if (!window.confirm(`Esta corrección modifica las fechas de ${businessName}, no confirma ningún pago y no reinicia el consumo. ¿Continuar?`)) return;
    await ownerAutomationRequest(panel, "automation-period-adjustment", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: reason.trim(), period_started_at: start.toISOString(), period_ends_at: end.toISOString(), period_status: end > new Date() ? "active" : "pending_renewal", confirm_no_payment: true }) });
  } else if (action === "feature") {
    const enabled = button.dataset.nextEnabled === "true";
    if (!window.confirm(`${enabled ? "Reactivar" : "Suspender"} la automatización de ${businessName}. ¿Confirmar?`)) return;
    const reason = window.prompt(`Motivo opcional para ${businessName}:`, "") ?? "";
    await ownerAutomationRequest(panel, "automation-settings", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ automation_feature_enabled: enabled, reason }) });
  }
}

function restoreOwnerMediaStatus() {
  const raw = sessionStorage.getItem("ownerMediaPending");
  if (!raw) return;
  try {
    const pending = JSON.parse(raw);
    const editor = Array.from(document.querySelectorAll("[data-owner-editor]")).find((item) => item.dataset.ownerEditor === pending.slug);
    if (!editor) return;
    editor.open = true;
    const message = pending.kind === "logo" ? "Logo actualizado." : "Foto añadida a la galería.";
    editor.querySelector("[data-owner-feedback]").textContent = message;
    byId("list-status").textContent = message;
    sessionStorage.removeItem("ownerMediaPending");
  } catch {
    sessionStorage.removeItem("ownerMediaPending");
  }
}

async function loadBusinesses() {
  byId("list-status").textContent = "Cargando…";
  try {
    const response = await fetch(`${API_BASE_URL}/api/owner/businesses`);
    if (!response.ok) throw new Error("No se pudo cargar la lista");
    businesses = await response.json();
    ownerDashboardState.businesses = { status: "ready", data: businesses, errors: 0 };
    renderBusinesses();
    renderOwnerDashboard();
  } catch (error) {
    byId("list-status").textContent = "Backend no disponible";
    byId("business-list").innerHTML = `<div class="error-box">${escapeHtml(error.message)}. Comprueba que el backend esté en ${API_BASE_URL}.</div>`;
  }
}

let changeBusinessState = null;

function addServiceRow(service = {}) {
  const row = document.createElement("div");
  row.className = "service-row";
  row.innerHTML = `
    <label>Nombre <input data-service="name" required maxlength="200" /></label>
    <label>Precio <input data-service="price_text" maxlength="80" placeholder="25 €" /></label>
    <label>Duración (min) <input data-service="duration_minutes" type="number" min="1" max="1440" value="30" required /></label>
    <label class="service-description">Descripción <input data-service="description" /></label>
    <label class="service-active"><input data-service="active" type="checkbox" checked /> Activo</label>
    <button class="remove-service" type="button" aria-label="Eliminar servicio">×</button>`;
  row.querySelector(".remove-service").addEventListener("click", () => row.remove());
  byId("service-list").appendChild(row);
  row.querySelector('[data-service="name"]').value = service.name || "";
  row.querySelector('[data-service="duration_minutes"]').value = service.duration || 30;
}

function collectServices() {
  return Array.from(document.querySelectorAll(".service-row")).map((row) => ({
    name: row.querySelector('[data-service="name"]').value.trim(),
    price_text: row.querySelector('[data-service="price_text"]').value.trim() || null,
    duration_minutes: Number(row.querySelector('[data-service="duration_minutes"]').value),
    description: row.querySelector('[data-service="description"]').value.trim() || null,
    active: row.querySelector('[data-service="active"]').checked
  }));
}

async function createBusiness(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const payload = Object.fromEntries(data.entries());
  payload.active = form.elements.active.checked;
  payload.services = collectServices();
  Object.keys(payload).forEach((key) => { if (payload[key] === "") payload[key] = null; });

  const button = byId("submit-button");
  const status = byId("form-status");
  button.disabled = true;
  status.textContent = "Creando…";
  try {
    const response = await fetch(`${API_BASE_URL}/api/owner/businesses`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Revisa los datos del formulario");
    const business = result.business;
    const slug = encodeURIComponent(business.slug);
    byId("creation-result").hidden = false;
    byId("creation-result").innerHTML = `
      <p class="success-label">Negocio creado</p><h3>${escapeHtml(business.name)}</h3>
      <p>Slug: <code>${escapeHtml(business.slug)}</code></p>
      <div class="card-actions">
        <a class="button button-secondary" href="../autonogrow-landing/index.html?b=${slug}" target="_blank" rel="noopener">Ver landing</a>
        <a class="button button-primary" href="../autonogrow-admin/index.html?b=${slug}" target="_blank" rel="noopener">Abrir admin del negocio</a>
      </div>`;
    form.reset();
    byId("owner-create-template-description").textContent = TEMPLATE_DESCRIPTIONS.classic;
    form.elements.active.checked = true;
    form.elements.slug.dataset.manuallyEdited = "";
    form.elements.slug.placeholder = "Se genera automáticamente";
    byId("service-list").innerHTML = "";
    status.textContent = "Creado correctamente";
    await loadBusinesses();
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function loadOwnerGallery(editor) {
  const slug = editor.dataset.ownerEditor;
  const response = await fetch(`${API_BASE_URL}/api/owner/businesses/${encodeURIComponent(slug)}/media/gallery`);
  if (!response.ok) return;
  const images = (await response.json()).images || [];
  editor.querySelector("[data-owner-gallery]").innerHTML = images.map((image) => `<article><img src="${escapeHtml(resolveMediaUrl(image.url, true))}" alt="${escapeHtml(image.alt_text || "Foto")}"><input data-image-alt="${image.id}" value="${escapeHtml(image.alt_text || "")}" placeholder="Texto alternativo"><input data-image-position="${image.id}" type="number" min="0" value="${image.position}"><button type="button" class="button button-secondary button-small" data-owner-image-toggle="${image.id}" data-active="${!image.active}">${image.active ? "Desactivar" : "Activar"}</button><button type="button" class="button button-secondary button-small" data-owner-image-save="${image.id}">Guardar</button><button type="button" class="button button-danger button-small" data-owner-image-delete="${image.id}">Eliminar</button></article>`).join("") || "<p>Sin fotos todavía.</p>";
}

async function loadOwnerUsers(panel) {
  const slug = panel.dataset.ownerUsers;
  const response = await fetch(`${API_BASE_URL}/api/owner/businesses/${encodeURIComponent(slug)}/users`);
  const body = await readResponseBody(response);
  if (!response.ok) {
    panel.querySelector("[data-owner-users-feedback]").textContent = `Error ${response.status}: ${body.detail || "No se pudieron cargar los usuarios"}`;
    return;
  }
  panel.querySelector("[data-owner-users-list]").innerHTML = (body.users || []).map((item) => `<article data-business-user-id="${item.id}"><div><strong>${escapeHtml(item.name || item.email)}</strong><span>${escapeHtml(item.email)} · ${item.pending ? "Pendiente de vincular Google" : "Cuenta vinculada"}</span></div><select data-membership-role><option value="business_admin" ${item.role === "business_admin" ? "selected" : ""}>Administrador</option><option value="business_staff" ${item.role === "business_staff" ? "selected" : ""}>Personal</option></select><button type="button" class="button button-secondary button-small" data-owner-user-action="save">${item.active ? "Guardar" : "Reactivar"}</button><button type="button" class="button button-danger button-small" data-owner-user-action="deactivate" ${item.active ? "" : "disabled"}>Desactivar</button></article>`).join("") || "<p>No hay usuarios asignados.</p>";
}

async function handleOwnerUserAction(button) {
  const panel = button.closest("[data-owner-users]");
  const slug = panel.dataset.ownerUsers;
  const feedback = panel.querySelector("[data-owner-users-feedback]");
  let url = `${API_BASE_URL}/api/owner/businesses/${encodeURIComponent(slug)}/users`;
  let options;
  if (button.dataset.ownerUserAction === "add") {
    const email = panel.querySelector("[data-owner-user-email]").value.trim();
    const role = panel.querySelector("[data-owner-user-role]").value;
    if (!email) { feedback.textContent = "Introduce un email."; return; }
    options = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, role }) };
  } else {
    const row = button.closest("[data-business-user-id]");
    url += `/${row.dataset.businessUserId}`;
    options = button.dataset.ownerUserAction === "deactivate"
      ? { method: "DELETE" }
      : { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role: row.querySelector("[data-membership-role]").value, active: true }) };
  }
  feedback.textContent = "Guardando...";
  const response = await fetch(url, options);
  const body = await readResponseBody(response);
  if (!response.ok) { feedback.textContent = `Error ${response.status}: ${body.detail || "No se pudo guardar"}`; return; }
  feedback.textContent = "Usuarios actualizados.";
  await loadOwnerUsers(panel);
}

async function readResponseBody(response) {
  const text = await response.text();
  if (!text) return {};
  try { return JSON.parse(text); } catch { return { detail: text }; }
}

function mediaErrorMessage(action, response, body) {
  const detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail || body || {});
  console.error("Error de media", { action, url: response.url, status: response.status, body });
  return `No se pudo ${action}. Error ${response.status}: ${detail || response.statusText}`;
}

async function refreshOwnerMedia(slug, message) {
  await loadBusinesses();
  byId("list-status").textContent = message;
  const editor = Array.from(document.querySelectorAll("[data-owner-editor]")).find((item) => item.dataset.ownerEditor === slug);
  if (!editor) return;
  editor.open = true;
  await loadOwnerGallery(editor);
  editor.querySelector("[data-owner-feedback]").textContent = message;
}

async function uploadOwnerMedia(input) {
  const editor = input.closest("[data-owner-editor]");
  const kind = input.dataset.ownerMediaInput;
  const slug = input.dataset.slug;
  const file = input.files?.[0];
  const feedback = editor.querySelector("[data-owner-feedback]");
  if (!file) {
    feedback.textContent = "Selecciona una imagen JPG, PNG o WEBP.";
    return;
  }

  const action = kind === "logo" ? "subir el logo" : "subir la foto";
  const url = `${API_BASE_URL}/api/owner/businesses/${encodeURIComponent(slug)}/media/${kind}`;
  const data = new FormData();
  data.append("file", file);
  if (kind === "gallery") data.append("alt_text", editor.querySelector("[data-owner-gallery-alt]").value.trim());
  feedback.textContent = "Subiendo imagen...";
  sessionStorage.setItem("ownerMediaPending", JSON.stringify({ slug, kind }));

  try {
    const response = await fetch(url, { method: "POST", body: data });
    const body = await readResponseBody(response);
    if (!response.ok) throw new Error(mediaErrorMessage(action, response, body));
    input.value = "";
    sessionStorage.removeItem("ownerMediaPending");
    await refreshOwnerMedia(slug, kind === "logo" ? "Logo actualizado." : "Foto añadida a la galería.");
  } catch (error) {
    sessionStorage.removeItem("ownerMediaPending");
    console.error("Fallo de subida en Owner", { action, url, error });
    feedback.textContent = error.message || `No se pudo ${action}.`;
  }
}

async function handleOwnerBrandClick(event) {
  const editor = event.target.closest("[data-owner-editor]");
  if (!editor) return;
  const feedback = editor.querySelector("[data-owner-feedback]");
  let response;
  const actionButton = event.target.closest("[data-action]");
  if (actionButton?.dataset.action === "select-logo") {
    editor.querySelector('[data-owner-media-input="logo"]').click();
    return;
  }
  if (actionButton?.dataset.action === "select-gallery") {
    editor.querySelector('[data-owner-media-input="gallery"]').click();
    return;
  }
  if (event.target.closest("[data-owner-brand-save]")) {
    const payload = { theme_key: editor.querySelector("[data-owner-theme]").value, template_key: editor.querySelector("[data-owner-template]").value, logo_alt: editor.querySelector("[data-owner-logo-alt]").value.trim() };
    ["primary","secondary","accent","background"].forEach((name) => payload[`${name}_color`] = editor.querySelector(`[data-owner-hex="${name}"]`).value.trim());
    response = await fetch(`${API_BASE_URL}/api/owner/businesses/${encodeURIComponent(editor.dataset.ownerEditor)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  } else if (actionButton?.dataset.action === "delete-logo") {
    const url = `${API_BASE_URL}/api/owner/businesses/${encodeURIComponent(editor.dataset.ownerEditor)}/media/logo`;
    response = await fetch(url, { method: "DELETE" });
  }
  else {
    const button = event.target.closest("[data-owner-image-toggle],[data-owner-image-save],[data-owner-image-delete]");
    if (!button) return;
    const id = button.dataset.ownerImageToggle || button.dataset.ownerImageSave || button.dataset.ownerImageDelete;
    const url = `${API_BASE_URL}/api/owner/businesses/${encodeURIComponent(editor.dataset.ownerEditor)}/media/gallery/${id}`;
    if (button.dataset.ownerImageDelete) response = await fetch(url, { method: "DELETE" });
    else response = await fetch(url, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ active: button.dataset.active === undefined ? undefined : button.dataset.active === "true", alt_text: editor.querySelector(`[data-image-alt="${id}"]`).value, position: Number(editor.querySelector(`[data-image-position="${id}"]`).value) }) });
  }
  if (!response) return;
  const result = await readResponseBody(response);
  if (!response.ok) {
    feedback.textContent = mediaErrorMessage("guardar los cambios", response, result);
    return;
  }
  await refreshOwnerMedia(editor.dataset.ownerEditor, actionButton?.dataset.action === "delete-logo" ? "Logo eliminado." : "Cambios guardados.");
}

function applyCreationPalette(theme) {
  const colors = PALETTES[theme]; if (!colors) return;
  ["primary","secondary","accent","background"].forEach((name, index) => byId("business-form").elements[`${name}_color`].value = colors[index]);
}

function applyBusinessTemplate(key) {
  const item = BUSINESS_TEMPLATES[key]; if (!item) return;
  const form = byId("business-form");
  [["category",0],["headline",1],["description",2],["schedule",3],["schedule_template",4],["theme_key",5],["template_key",6]].forEach(([name,index]) => form.elements[name].value = item[index]);
  byId("owner-create-template-description").textContent = templateDescription(item[6]);
  applyCreationPalette(item[5]);
  byId("service-list").innerHTML = "";
  item[7].forEach(([name, duration]) => addServiceRow({ name, duration }));
}

let onboardingData = null;
let onboardingStepIndex = 0;
function ownerInstagramBusinessId() {
  return Number(byId("owner-instagram-business").value) || null;
}

function ownerInstagramApi() {
  const businessId = ownerInstagramBusinessId();
  return businessId ? `${API_BASE_URL}/api/owner/businesses/${businessId}/instagram-content` : null;
}

function renderOwnerInstagramBusinessOptions() {
  const select = byId("owner-instagram-business");
  const previous = select.value;
  select.innerHTML = `<option value="">Selecciona un negocio</option>${businesses.map((business) => `<option value="${business.id}">${escapeHtml(business.name)}</option>`).join("")}`;
  if (businesses.some((business) => String(business.id) === previous)) select.value = previous;
  else if (businesses.length === 1) select.value = String(businesses[0].id);
}

function ownerInstagramStateLabel(status) {
  return ({
    draft: "Borrador",
    ready_for_review: "Listo para revisión",
    changes_requested: "Cambios solicitados",
    validated: "Validado",
    scheduled: "Programado",
    published: "Publicado",
    cancelled: "Cancelado",
  })[status] || status;
}

const OWNER_INSTAGRAM_ACTIVE_JOB_STATUSES = new Set([
  "queued",
  "claimed",
  "creating_container",
  "publishing",
  "simulating_publish",
  "retry_wait",
]);

function ownerInstagramPublicationUxState(item) {
  const job = item?.publish_jobs?.[0] || null;
  const status = job?.status;
  const carousel = item?.current_version?.format === "carousel";
  if (status === "published" || item?.status === "published") {
    return { key: "published", label: "Publicado", detail: "La publicación está disponible en Instagram.", tone: "published", icon: "✓", transient: false, actionLocked: true };
  }
  if (status === "queued") {
    const dueSoon = !job.scheduled_for || new Date(job.scheduled_for).getTime() <= Date.now() + 60_000;
    return dueSoon
      ? { key: "preparing", label: "Preparando publicación", detail: carousel ? "Preparando el carrusel antes de enviarlo a Instagram." : "La publicación está en cola y comenzará en breve.", tone: "scheduled", icon: "…", transient: true, actionLocked: true }
      : { key: "scheduled", label: "Programado", detail: `Se publicará ${formatOwnerDate(job.scheduled_for)}.`, tone: "scheduled", icon: "●", transient: false, actionLocked: false };
  }
  if (["claimed", "creating_container"].includes(status)) {
    return { key: "preparing", label: "Preparando publicación", detail: carousel ? "Instagram está preparando los elementos del carrusel." : "Instagram está preparando el contenido.", tone: "scheduled", icon: "…", transient: true, actionLocked: true };
  }
  if (["publishing", "simulating_publish"].includes(status)) {
    return { key: "publishing", label: "Publicando en Instagram", detail: "El envío está en curso. No es necesario volver a pulsar Publicar.", tone: "scheduled", icon: "…", transient: true, actionLocked: true };
  }
  if (status === "retry_wait") {
    const exhausted = Number(job.attempt_count || 0) >= Number(job.max_attempts || 0);
    if (!exhausted) {
      return { key: "processing", label: "Procesando en Instagram", detail: carousel ? "Instagram sigue procesando el carrusel; se comprobará de nuevo automáticamente." : "Instagram sigue procesando el contenido; se reintentará automáticamente.", tone: "scheduled", icon: "…", transient: true, actionLocked: true };
    }
  }
  if (status === "action_required") {
    const code = String(job.provider_error_code || "");
    const uncertain = ["outcome_requires_review", "unknown_after_claim_expiry", "publish_result_unknown"].includes(job.provider_status) || code.includes("unknown");
    if (uncertain) return { key: "verify", label: "Verificar publicación", detail: "El resultado no es concluyente. Comprueba Instagram antes de intentar otra acción.", tone: "attention", icon: "!", transient: false, actionLocked: true };
    if (code.includes("authentication") || code.includes("token") || code.includes("permission")) return { key: "reconnect", label: "Reconectar Instagram", detail: "La conexión o los permisos de Instagram requieren atención.", tone: "attention", icon: "!", transient: false, actionLocked: true };
    return { key: "attention", label: "Necesita atención", detail: job.safe_error_message || "Revisa el detalle técnico antes de continuar.", tone: "attention", icon: "!", transient: false, actionLocked: true };
  }
  if (status === "failed" || status === "retry_wait") {
    return { key: "failed", label: "Publicación fallida", detail: job?.safe_error_message || "No se pudo completar la publicación.", tone: "attention", icon: "!", transient: false, actionLocked: true };
  }
  const attention = ["ready_for_review", "changes_requested"].includes(item?.status);
  return { key: item?.status || "draft", label: ownerInstagramStateLabel(item?.status), detail: "", tone: attention ? "attention" : item?.status || "draft", icon: attention ? "!" : ["validated", "scheduled"].includes(item?.status) ? "●" : "○", transient: false, actionLocked: false };
}

function ownerInstagramFormatLabel(format) {
  return ({
    single_image: "Imagen",
    carousel: "Carrusel",
    reel: "Reel",
    story: "Historia",
  })[format] || "Imagen";
}

function ownerInstagramPublishingMode() {
  return ownerInstagramSettings?.publishing_mode === "meta" ? "real" : "simulado";
}

function renderOwnerInstagramModeCopy() {
  const isMeta = ownerInstagramSettings?.publishing_mode === "meta";
  byId("owner-instagram-mode-label").textContent = isMeta ? "Publicación en Instagram" : "Entorno de simulación";
  byId("owner-instagram-mode-copy").textContent = isMeta
    ? "Prepara versiones, programa y supervisa las publicaciones de cada negocio en Instagram."
    : "Prepara versiones y comprueba el flujo editorial sin enviar publicaciones a Instagram.";
}

function ownerInstagramLocalInput(isoValue, timeZone) {
  if (!isoValue) return "";
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(isoValue)).map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

function ownerInstagramCalendarTimezone() {
  return ownerInstagramContents[0]?.business_timezone || "Europe/Madrid";
}

function instagramCivilDateKey(value = new Date(), timeZone = ownerInstagramCalendarTimezone()) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
    timeZone, year: "numeric", month: "2-digit", day: "2-digit"
  }).formatToParts(value).map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function instagramAddDays(dateKey, amount) {
  const value = new Date(`${dateKey}T12:00:00Z`);
  value.setUTCDate(value.getUTCDate() + amount);
  return value.toISOString().slice(0, 10);
}

function instagramWeekStart(dateKey) {
  const value = new Date(`${dateKey}T12:00:00Z`);
  const offset = (value.getUTCDay() + 6) % 7;
  return instagramAddDays(dateKey, -offset);
}

function instagramMonthGrid(dateKey) {
  const monthStart = `${dateKey.slice(0, 7)}-01`;
  const start = instagramWeekStart(monthStart);
  return Array.from({ length: 42 }, (_item, index) => instagramAddDays(start, index));
}

function ownerInstagramContentDateKey(item) {
  return item.planned_publish_at
    ? instagramCivilDateKey(new Date(item.planned_publish_at), item.business_timezone)
    : "";
}

function ownerInstagramNeedsAttention(item) {
  return ownerInstagramPublicationUxState(item).tone === "attention";
}

function ownerInstagramStatusIcon(item) {
  return ownerInstagramPublicationUxState(item).icon;
}

function ownerInstagramQuickAction(item) {
  const ux = ownerInstagramPublicationUxState(item);
  if (ux.transient) return "En proceso";
  if (["failed", "attention", "reconnect", "verify"].includes(ux.key)) return "Revisar";
  return ({ draft: "Continuar", changes_requested: "Corregir", ready_for_review: "Revisar", validated: "Programar", scheduled: "Reprogramar", published: "Ver publicación", cancelled: "Ver" })[item.status] || "Ver";
}

function ownerInstagramFilteredContents() {
  return ownerInstagramContents.filter((item) => {
    if (ownerInstagramStateFilter === "attention" && !ownerInstagramNeedsAttention(item)) return false;
    if (ownerInstagramStateFilter && ownerInstagramStateFilter !== "attention" && item.status !== ownerInstagramStateFilter) return false;
    if (ownerInstagramFormatFilter && item.current_version?.format !== ownerInstagramFormatFilter) return false;
    return true;
  });
}

function ownerInstagramCalendarBlock(item) {
  const local = ownerInstagramLocalInput(item.planned_publish_at, item.business_timezone);
  const time = local ? local.slice(11, 16) : "Sin hora";
  const format = ownerInstagramFormatLabel(item.current_version?.format);
  const ux = ownerInstagramPublicationUxState(item);
  return `<button class="instagram-calendar-item instagram-calendar-item--${escapeHtml(ux.tone)}" type="button" data-owner-instagram-open="${item.id}" aria-label="${escapeHtml(`${item.title}, ${ux.label}, ${time}. ${ux.detail}`)}" title="${escapeHtml(ux.detail)}"><span class="instagram-calendar-item__state" aria-hidden="true">${ownerInstagramStatusIcon(item)}</span><span class="instagram-calendar-item__body"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(time)} · ${escapeHtml(format)} · ${escapeHtml(ux.label)}</small></span><span class="instagram-calendar-item__action">${escapeHtml(ownerInstagramQuickAction(item))}</span></button>`;
}

function ownerInstagramPeriodKeys() {
  const cursor = ownerInstagramCalendarDate || instagramCivilDateKey();
  if (ownerInstagramCalendarView === "today") return [cursor];
  if (ownerInstagramCalendarView === "week") {
    const start = instagramWeekStart(cursor);
    return Array.from({ length: 7 }, (_item, index) => instagramAddDays(start, index));
  }
  return instagramMonthGrid(cursor);
}

function renderOwnerInstagramCalendar() {
  const calendar = byId("owner-instagram-calendar");
  if (!calendar) return;
  const cursor = ownerInstagramCalendarDate || instagramCivilDateKey();
  ownerInstagramCalendarDate = cursor;
  const keys = ownerInstagramPeriodKeys();
  const filtered = ownerInstagramFilteredContents();
  const byDate = new Map(keys.map((key) => [key, []]));
  filtered.forEach((item) => {
    const key = ownerInstagramContentDateKey(item);
    if (byDate.has(key)) byDate.get(key).push(item);
  });
  byDate.forEach((items) => items.sort((left, right) => String(left.planned_publish_at).localeCompare(String(right.planned_publish_at))));
  const longDate = (key, options) => new Intl.DateTimeFormat("es-ES", { timeZone: "UTC", ...options }).format(new Date(`${key}T12:00:00Z`));
  const today = instagramCivilDateKey();
  if (ownerInstagramCalendarView === "today") {
    byId("owner-instagram-period-label").textContent = longDate(cursor, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    const items = byDate.get(cursor) || [];
    calendar.className = "instagram-calendar instagram-calendar--today";
    calendar.innerHTML = `${items.length ? items.map(ownerInstagramCalendarBlock).join("") : `<div class="instagram-calendar-empty"><strong>No tienes publicaciones planificadas para hoy.</strong><p>Puedes preparar una directamente para este día.</p></div>`}<button class="instagram-calendar-gap" type="button" data-owner-instagram-create-date="${cursor}">+ Crear para este día</button>`;
  } else if (ownerInstagramCalendarView === "week") {
    byId("owner-instagram-period-label").textContent = `${longDate(keys[0], { day: "numeric", month: "short" })} – ${longDate(keys[6], { day: "numeric", month: "short", year: "numeric" })}`;
    calendar.className = "instagram-calendar instagram-calendar--week";
    const hasPlanned = keys.some((key) => byDate.get(key).length);
    calendar.innerHTML = `${hasPlanned ? "" : `<div class="instagram-calendar-empty"><strong>No tienes publicaciones planificadas esta semana.</strong><p>Puedes crear contenido directamente desde el día que prefieras.</p></div>`}${keys.map((key) => `<section class="instagram-calendar-day${key === today ? " instagram-calendar-day--today" : ""}" aria-label="${escapeHtml(longDate(key, { weekday: "long", day: "numeric", month: "long" }))}"><header><span>${escapeHtml(longDate(key, { weekday: "short" }))}</span><strong>${escapeHtml(longDate(key, { day: "numeric" }))}</strong></header><div>${byDate.get(key).map(ownerInstagramCalendarBlock).join("")}<button class="instagram-calendar-gap" type="button" data-owner-instagram-create-date="${key}">${byDate.get(key).length ? "+ Crear" : "Hueco libre · Crear"}</button></div></section>`).join("")}`;
  } else {
    byId("owner-instagram-period-label").textContent = longDate(`${cursor.slice(0, 7)}-01`, { month: "long", year: "numeric" });
    calendar.className = "instagram-calendar instagram-calendar--month";
    const activeMonth = cursor.slice(0, 7);
    calendar.innerHTML = `<div class="instagram-calendar-weekdays" aria-hidden="true">${["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"].map((day) => `<span>${day}</span>`).join("")}</div>${keys.map((key) => { const items = byDate.get(key); const shown = items.slice(0, 3); return `<section class="instagram-month-day${key.startsWith(activeMonth) ? "" : " instagram-month-day--outside"}${key === today ? " instagram-calendar-day--today" : ""}"><header><span>${escapeHtml(longDate(key, { day: "numeric" }))}</span><button class="instagram-calendar-day-create" type="button" data-owner-instagram-create-date="${key}" aria-label="Crear publicación para el ${escapeHtml(longDate(key, { day: "numeric", month: "long" }))}">+</button></header>${shown.map(ownerInstagramCalendarBlock).join("")}${items.length > shown.length ? `<button type="button" class="instagram-calendar-more" data-owner-instagram-day="${key}">+${items.length - shown.length} más</button>` : ""}</section>`; }).join("")}`;
  }
  const attention = filtered.filter(ownerInstagramNeedsAttention).length;
  const weekKeys = Array.from({ length: 7 }, (_item, index) => instagramAddDays(instagramWeekStart(today), index));
  const scheduled = filtered.filter((item) => item.status === "scheduled" && weekKeys.includes(ownerInstagramContentDateKey(item))).length;
  const filledDays = new Set(filtered.map(ownerInstagramContentDateKey).filter((key) => weekKeys.includes(key))).size;
  const attentionSummary = byId("owner-instagram-attention");
  attentionSummary.innerHTML = attention
    ? `<strong>${attention} publicación${attention === 1 ? "" : "es"} necesita${attention === 1 ? "" : "n"} tu atención</strong><span>${scheduled} programada${scheduled === 1 ? "" : "s"} esta semana · ${7 - filledDays} hueco${7 - filledDays === 1 ? "" : "s"} sin contenido</span>`
    : `<strong>Todo preparado para esta semana</strong><span>${scheduled} programada${scheduled === 1 ? "" : "s"} · ${7 - filledDays} hueco${7 - filledDays === 1 ? "" : "s"} sin contenido</span>`;
  attentionSummary.classList.toggle("instagram-attention-summary--active", attention > 0);
  const unscheduled = filtered.filter((item) => !item.planned_publish_at && item.status !== "cancelled");
  byId("owner-instagram-unscheduled").innerHTML = unscheduled.length ? `<div><strong>Sin fecha</strong><span>${unscheduled.length} contenido${unscheduled.length === 1 ? "" : "s"} por colocar</span></div><div>${unscheduled.map(ownerInstagramCalendarBlock).join("")}</div>` : "";
  document.querySelectorAll("[data-owner-instagram-view]").forEach((button) => button.setAttribute("aria-selected", String(button.dataset.ownerInstagramView === ownerInstagramCalendarView)));
}

async function openOwnerInstagramContentDetail(contentId, options = {}) {
  return openOwnerInstagramComposer({ contentId, trigger: options.trigger || document.activeElement });
}

function renderOwnerInstagramRaw(assets) {
  const eligibleContents = ownerInstagramContents.filter((item) => ["draft", "changes_requested"].includes(item.status));
  byId("owner-instagram-raw-list").innerHTML = assets.length
    ? assets.map((asset) => {
      const associations = asset.associations?.length
        ? `<ul class="instagram-comments">${asset.associations.map((association) => `<li>${escapeHtml(association.content_title)} · ${escapeHtml(ownerInstagramStateLabel(association.content_status))}${association.content_archived ? " · Archivado" : ""}</li>`).join("")}</ul>`
        : `<p class="helper">Sin contenidos asociados.</p>`;
      const options = eligibleContents.map((content) => `<option value="${content.id}">${escapeHtml(content.title)}</option>`).join("");
      const previewAction = asset.media_type?.startsWith("image/")
        ? `<button class="button button-secondary button-small" type="button" data-owner-instagram-raw-action="preview" data-raw-asset-id="${asset.id}">Previsualizar</button>`
        : "";
      return `<article class="instagram-raw-card" data-owner-instagram-raw="${asset.id}"><header><div><strong>${escapeHtml(asset.label || asset.original_filename)}</strong><p class="helper">${escapeHtml(asset.original_filename)} · ${escapeHtml(asset.media_type)}</p></div><span class="ag-badge ag-badge--neutral">Origen</span></header>${associations}<label>Contenido destino<select class="instagram-raw-target" data-owner-instagram-raw-target ${options ? "" : "disabled"}><option value="">Selecciona un contenido</option>${options}</select></label><div class="instagram-raw-actions">${previewAction}<button class="button button-secondary button-small" type="button" data-owner-instagram-raw-action="download" data-raw-asset-id="${asset.id}">Descargar</button><button class="button button-secondary button-small" type="button" data-owner-instagram-raw-action="associations" data-raw-asset-id="${asset.id}">Asociaciones</button><button class="button button-secondary button-small" type="button" data-owner-instagram-raw-action="associate" data-raw-asset-id="${asset.id}" ${options ? "" : "disabled"}>Usar en contenido</button><button class="button button-secondary button-small" type="button" data-owner-instagram-raw-action="create-content" data-raw-asset-id="${asset.id}">Crear contenido con este material</button><button class="button button-primary button-small" type="button" data-owner-instagram-raw-action="use-final" data-raw-asset-id="${asset.id}" ${options ? "" : "disabled"}>Usar como final</button><button class="button button-ghost button-small" type="button" data-owner-instagram-raw-delete="${asset.id}">Eliminar</button></div></article>`;
    }).join("")
    : `<p class="helper">Todavía no hay material bruto.</p>`;
}

function ownerInstagramRemovalConfirmation(item) {
  if (item.status === "ready_for_review") return "Este contenido está en revisión. Se cancelará la revisión y se eliminará. ¿Quieres continuar?";
  if (item.status === "validated") return "Este contenido ya está validado técnicamente. ¿Quieres eliminarlo?";
  if (item.status === "scheduled") return "Este contenido está programado. Se cancelará la publicación programada antes de retirarlo. ¿Quieres continuar?";
  if (item.status === "published") return "Este contenido ya está publicado. Se archivará en el Owner y se conservará su historial. ¿Quieres continuar?";
  return "¿Eliminar este contenido?";
}

function renderOwnerInstagramContents() {
  renderOwnerInstagramCalendar();
}

const OWNER_INSTAGRAM_COMPOSER_FORMATS = {
  single_image: { label: "Publicación", accept: "image/jpeg", help: "Añade una imagen JPEG.", add: "+ Añadir foto", min: 1, max: 1 },
  carousel: { label: "Carrusel", accept: "image/jpeg", help: "Añade entre 2 y 10 imágenes JPEG y ordénalas como quieras.", add: "+ Añadir fotos", min: 2, max: 10 },
  reel: { label: "Reel", accept: "video/mp4", help: "Añade un vídeo MP4.", add: "+ Añadir vídeo", min: 1, max: 1 },
  story: { label: "Historia", accept: "image/jpeg,image/png,image/webp,video/mp4", help: "Sube una foto para adaptarla a 9:16 o mantén el flujo MP4 actual.", add: "+ Subir foto o vídeo", min: 1, max: 1 },
};

const OWNER_INSTAGRAM_STORY_TRANSFORM_DEFAULT = Object.freeze({ mode: "fill", zoom: 1, position_x: 0.5, position_y: 0.5, background: "dark" });
let ownerInstagramLibraryState = null;

function ownerInstagramComposerBusiness() {
  return businesses.find((business) => business.id === ownerInstagramBusinessId()) || null;
}

function ownerInstagramComposerMediaType(item) {
  return item.mediaType || item.file?.type || "";
}

function ownerInstagramComposerRevoke(item) {
  if (item?.objectUrl && item.url) URL.revokeObjectURL(item.url);
}

function ownerInstagramComposerClearMedia() {
  ownerInstagramComposerState?.media.forEach(ownerInstagramComposerRevoke);
  if (ownerInstagramComposerState) ownerInstagramComposerState.media = [];
}

function ownerInstagramComposerFormatAccepts(format, mediaType) {
  if (["single_image", "carousel"].includes(format)) return mediaType === "image/jpeg";
  if (format === "reel") return mediaType === "video/mp4";
  return ["image/jpeg", "image/png", "image/webp", "video/mp4"].includes(mediaType);
}

function ownerInstagramComposerTitle(state) {
  const firstLine = state.caption.split(/\r?\n/).map((part) => part.trim()).find(Boolean);
  if (firstLine) return firstLine.slice(0, 200);
  const date = state.date ? new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeZone: "UTC" }).format(new Date(`${state.date}T12:00:00Z`)) : "sin fecha";
  return `${OWNER_INSTAGRAM_COMPOSER_FORMATS[state.format].label} · ${date}`.slice(0, 200);
}

function ownerInstagramComposerItem(content, date = "") {
  const business = ownerInstagramComposerBusiness();
  const version = content?.current_version;
  const local = content?.planned_publish_at ? ownerInstagramLocalInput(content.planned_publish_at, content.business_timezone) : "";
  return {
    generation: ++ownerInstagramComposerSequence,
    contentId: content?.id || null,
    content,
    format: version?.format || "single_image",
    caption: version?.caption || "",
    media: (version?.assets || []).map((asset) => ({
      uid: `asset-${asset.id}`,
      id: asset.id,
      name: asset.original_filename,
      mediaType: asset.media_type,
      fileUrl: asset.file_url,
      file: null,
      sourceRawAssetId: asset.source_raw_asset_id || null,
      remoteMediaId: null,
      url: "",
      objectUrl: false,
      loading: true,
    })),
    previewIndex: 0,
    publication: "schedule",
    date: date || local.slice(0, 10),
    time: local.slice(11, 16),
    timezone: content?.business_timezone || business?.timezone || ownerInstagramCalendarTimezone(),
    business,
    dirty: false,
    busy: false,
    storyTransform: { ...OWNER_INSTAGRAM_STORY_TRANSFORM_DEFAULT, ...(version?.story_transform || {}) },
    storyTransformDirty: false,
  };
}

async function ownerInstagramLoadComposerMedia(state) {
  for (const media of state.media) {
    if (!media.fileUrl || state.generation !== ownerInstagramComposerState?.generation) return;
    try {
      const response = await ownerInstagramFileResponse(`${API_BASE_URL}${media.fileUrl}`);
      const blob = await response.blob();
      if (state.generation !== ownerInstagramComposerState?.generation) return;
      media.url = URL.createObjectURL(blob);
      media.objectUrl = true;
      media.loading = false;
    } catch (error) {
      media.loading = false;
      media.error = true;
      byId("owner-instagram-composer-error").textContent = error.message;
    }
    renderOwnerInstagramComposer();
  }
}

async function openOwnerInstagramComposer({ contentId = null, date = "", trigger = null } = {}) {
  const api = ownerInstagramApi();
  if (!api) {
    byId("owner-instagram-status").textContent = "Selecciona primero un negocio.";
    byId("owner-instagram-business").focus();
    return;
  }
  let content = contentId ? ownerInstagramContents.find((item) => item.id === contentId) : null;
  try {
    if (contentId && !Array.isArray(content?.versions)) {
      content = await ownerInstagramJson(`${api}/contents/${contentId}`);
      upsertOwnerInstagramContent(content);
    }
  } catch (error) {
    showOwnerInstagramError(error);
    return;
  }
  if (ownerInstagramComposerState) ownerInstagramComposerClearMedia();
  ownerInstagramComposerState = ownerInstagramComposerItem(content, date);
  ownerInstagramComposerReturnFocus = trigger || document.activeElement;
  const dialog = byId("owner-instagram-composer");
  dialog.hidden = false;
  document.body.classList.add("owner-dialog-open");
  byId("owner-instagram-composer-advanced").open = false;
  byId("owner-instagram-composer-error").textContent = "";
  renderOwnerInstagramComposer();
  byId("owner-instagram-composer-close").focus();
  if (content) ownerInstagramLoadComposerMedia(ownerInstagramComposerState);
}

function closeOwnerInstagramComposer({ force = false } = {}) {
  const state = ownerInstagramComposerState;
  if (!state || (state.busy && !force)) return;
  if (!force && state.dirty && !window.confirm("Hay cambios sin guardar. ¿Cerrar el Composer?")) return;
  ownerInstagramComposerClearMedia();
  ownerInstagramComposerState = null;
  byId("owner-instagram-composer").hidden = true;
  document.body.classList.remove("owner-dialog-open");
  ownerInstagramComposerReturnFocus?.focus?.();
  ownerInstagramComposerReturnFocus = null;
}

function ownerInstagramComposerAdvanced(content) {
  if (!content) return `<p class="helper">Al guardar se conservarán internamente versiones, validaciones, jobs y auditoría.</p>`;
  const version = content.current_version;
  const job = content.publish_jobs?.[0];
  const rows = [
    ["Estado", ownerInstagramPublicationUxState(content).label],
    ["Versión", version?.version_number],
    ["Formato interno", version?.format],
    ["Contenido", content.id],
  ];
  if (job) rows.push(["Job", job.id], ["Estado del job", job.status], ["Intentos", `${job.attempt_count}/${job.max_attempts}`]);
  if (job?.provider_status) rows.push(["Estado del proveedor", job.provider_status]);
  if (job?.next_attempt_at) rows.push(["Próxima comprobación", formatOwnerDate(job.next_attempt_at)]);
  if (job?.provider_container_id) rows.push(["Contenedor", job.provider_container_id]);
  if (job?.provider_media_id) rows.push(["Media ID", job.provider_media_id]);
  if (job?.provider_error_code) rows.push(["Código seguro", job.provider_error_code]);
  if (job?.safe_error_message) rows.push(["Error seguro", job.safe_error_message]);
  if (content.instagram_remote?.remote_status === "unavailable") rows.push(["Instagram", "No disponible actualmente"]);
  if (content.source_instagram_media) rows.push(["Origen de la Historia", content.source_instagram_media.origin === "autonogrow" ? "Publicación de AutonoGrow" : "Publicación de Instagram"]);
  const diagnostics = job?.provider_metadata?.last_provider_error;
  if (diagnostics) {
    if (diagnostics.operation) rows.push(["Operación de Meta", diagnostics.operation]);
    if (diagnostics.http_status) rows.push(["HTTP de Meta", diagnostics.http_status]);
    if (diagnostics.error_code) rows.push(["Código de Meta", diagnostics.error_code]);
    if (diagnostics.error_subcode) rows.push(["Subcódigo de Meta", diagnostics.error_subcode]);
    if (typeof diagnostics.is_transient === "boolean") rows.push(["Error transitorio", diagnostics.is_transient ? "Sí" : "No"]);
    if (diagnostics.container_status) rows.push(["Procesamiento del contenedor", diagnostics.container_status]);
    if (diagnostics.carousel_position !== undefined) rows.push(["Elemento del carrusel", Number(diagnostics.carousel_position) + 1]);
  }
  const childCount = job?.provider_metadata?.carousel_child_container_ids?.filter(Boolean).length;
  if (childCount) rows.push(["Elementos de carrusel preparados", childCount]);
  const permalink = job?.provider_permalink && content.instagram_remote?.remote_status !== "unavailable" ? `<p><a href="${escapeHtml(job.provider_permalink)}" target="_blank" rel="noopener noreferrer">Ver publicación en Instagram</a></p>` : "";
  return `<dl>${rows.map(([term, value]) => `<dt>${escapeHtml(term)}</dt><dd>${escapeHtml(value ?? "—")}</dd>`).join("")}</dl>${permalink}<p class="helper">${content.publication_events?.length || 0} eventos de publicación conservados.</p>`;
}

function ownerInstagramComposerMediaMarkup(media, index, state) {
  const isVideo = ownerInstagramComposerMediaType(media) === "video/mp4";
  const controlsLocked = state.busy || ownerInstagramPublicationUxState(state.content).actionLocked;
  const disabled = controlsLocked ? "disabled" : "";
  const visual = media.loading
    ? `<div class="instagram-phone__empty"><p>Cargando…</p></div>`
    : media.error
      ? `<div class="instagram-phone__empty"><p>No disponible</p></div>`
      : isVideo
        ? `<video src="${escapeHtml(media.url)}" muted playsinline preload="metadata"></video>`
        : `<img src="${escapeHtml(media.url)}" alt="${escapeHtml(media.name)}">`;
  const controls = state.format === "carousel" ? `<div class="instagram-composer-media__controls"><button type="button" data-owner-composer-move="-1" data-media-uid="${escapeHtml(media.uid)}" aria-label="Mover ${escapeHtml(media.name)} a la izquierda" ${disabled || (index === 0 ? "disabled" : "")}>←</button><button class="instagram-composer-media__drag" type="button" draggable="true" data-media-uid="${escapeHtml(media.uid)}" aria-label="Arrastrar ${escapeHtml(media.name)} para reordenar" ${disabled}>↕</button><button type="button" data-owner-composer-move="1" data-media-uid="${escapeHtml(media.uid)}" aria-label="Mover ${escapeHtml(media.name)} a la derecha" ${disabled || (index === state.media.length - 1 ? "disabled" : "")}>→</button></div>` : "";
  return `<article class="instagram-composer-media" data-media-uid="${escapeHtml(media.uid)}"><div class="instagram-composer-media__visual">${visual}<span class="instagram-composer-media__position">${index + 1}</span><button class="instagram-composer-media__remove" type="button" data-owner-composer-remove="${escapeHtml(media.uid)}" aria-label="Eliminar ${escapeHtml(media.name)}" ${disabled}>×</button></div><div class="instagram-composer-media__meta"><strong>${escapeHtml(media.name)}</strong></div>${controls}</article>`;
}

function ownerInstagramStoryGeometry(sourceWidth, sourceHeight, canvasWidth, canvasHeight, transform) {
  const widthScale = canvasWidth / sourceWidth;
  const heightScale = canvasHeight / sourceHeight;
  const baseScale = transform.mode === "fill" ? Math.max(widthScale, heightScale) : Math.min(widthScale, heightScale);
  const scale = baseScale * transform.zoom;
  const width = Math.max(1, Math.floor(sourceWidth * scale + 0.5));
  const height = Math.max(1, Math.floor(sourceHeight * scale + 0.5));
  const left = width <= canvasWidth ? Math.floor((canvasWidth - width) * transform.position_x + 0.5) : -Math.floor((width - canvasWidth) * transform.position_x + 0.5);
  const top = height <= canvasHeight ? Math.floor((canvasHeight - height) * transform.position_y + 0.5) : -Math.floor((height - canvasHeight) * transform.position_y + 0.5);
  return { width, height, left, top };
}

function ownerInstagramApplyStoryPreview() {
  const state = ownerInstagramComposerState;
  const stage = byId("owner-instagram-preview-stage");
  const image = stage.querySelector("[data-story-preview]");
  if (!state || state.format !== "story" || !image?.naturalWidth) return;
  const transform = state.storyTransform;
  const geometry = ownerInstagramStoryGeometry(image.naturalWidth, image.naturalHeight, stage.clientWidth, stage.clientHeight, transform);
  stage.style.background = transform.background === "light" ? "rgb(248, 250, 252)" : "rgb(17, 24, 39)";
  Object.assign(image.style, {
    position: "absolute",
    width: `${geometry.width}px`,
    height: `${geometry.height}px`,
    maxWidth: "none",
    left: `${geometry.left}px`,
    top: `${geometry.top}px`,
    objectFit: "fill",
    touchAction: "none",
    cursor: "grab",
  });
  image.onpointerdown = (event) => {
    if (ownerInstagramPublicationUxState(state.content).actionLocked || state.busy) return;
    event.preventDefault();
    image.setPointerCapture(event.pointerId);
    image.style.cursor = "grabbing";
    const initial = { x: event.clientX, y: event.clientY, positionX: transform.position_x, positionY: transform.position_y };
    image.onpointermove = (moveEvent) => {
      if (!image.hasPointerCapture(moveEvent.pointerId)) return;
      const dx = moveEvent.clientX - initial.x;
      const dy = moveEvent.clientY - initial.y;
      const xRange = Math.abs(geometry.width - stage.clientWidth);
      const yRange = Math.abs(geometry.height - stage.clientHeight);
      transform.position_x = Math.min(1, Math.max(0, initial.positionX + (geometry.width > stage.clientWidth ? -dx : dx) / Math.max(1, xRange)));
      transform.position_y = Math.min(1, Math.max(0, initial.positionY + (geometry.height > stage.clientHeight ? -dy : dy) / Math.max(1, yRange)));
      state.storyTransformDirty = true;
      state.dirty = true;
      byId("owner-instagram-story-x").value = String(transform.position_x);
      byId("owner-instagram-story-y").value = String(transform.position_y);
      ownerInstagramApplyStoryPreview();
    };
    image.onpointerup = () => {
      image.style.cursor = "grab";
      image.onpointermove = null;
      image.onpointerup = null;
    };
  };
}

function renderOwnerInstagramComposerPreview(state) {
  const config = OWNER_INSTAGRAM_COMPOSER_FORMATS[state.format];
  const phone = byId("owner-instagram-phone");
  const vertical = ["reel", "story"].includes(state.format);
  phone.className = `instagram-phone ${vertical ? "instagram-phone--vertical" : "instagram-phone--feed"}${state.format === "story" ? " instagram-phone--story" : ""}`;
  byId("owner-instagram-preview-heading").textContent = config.label;
  const businessName = state.business?.name || "Mi negocio";
  ["owner-instagram-preview-business", "owner-instagram-preview-business-copy", "owner-instagram-preview-story-business"].forEach((id) => { byId(id).textContent = businessName; });
  const avatar = byId("owner-instagram-preview-avatar");
  avatar.innerHTML = state.business?.logo_url ? `<img src="${escapeHtml(resolveMediaUrl(state.business.logo_url))}" alt="">` : escapeHtml(businessName.slice(0, 2).toUpperCase());
  const storyTop = byId("owner-instagram-preview-story-top");
  storyTop.hidden = state.format !== "story";
  storyTop.style.display = state.format === "story" ? "grid" : "none";
  const feedCopy = byId("owner-instagram-preview-feed-copy");
  feedCopy.hidden = state.format === "story";
  byId("owner-instagram-preview-caption").textContent = state.caption.trim() || "Tu texto aparecerá aquí.";
  state.previewIndex = Math.min(Math.max(0, state.previewIndex), Math.max(0, state.media.length - 1));
  const media = state.media[state.previewIndex];
  const stage = byId("owner-instagram-preview-stage");
  if (!media || media.loading) stage.innerHTML = `<div class="instagram-phone__empty"><span aria-hidden="true">${media ? "◌" : "▧"}</span><p>${media ? "Cargando vista previa…" : "Añade contenido para verlo aquí"}</p></div>`;
  else if (media.error) stage.innerHTML = `<div class="instagram-phone__empty"><p>No se pudo abrir este archivo.</p></div>`;
  else if (ownerInstagramComposerMediaType(media) === "video/mp4") stage.innerHTML = `<video src="${escapeHtml(media.url)}" controls muted playsinline preload="metadata" aria-label="Vista previa de ${escapeHtml(media.name)}"></video>`;
  else if (state.format === "story") {
    stage.innerHTML = `<img data-story-preview src="${escapeHtml(media.url)}" alt="Vista previa de ${escapeHtml(media.name)}">`;
    const image = stage.querySelector("[data-story-preview]");
    image.addEventListener("load", ownerInstagramApplyStoryPreview, { once: true });
    if (image.complete) ownerInstagramApplyStoryPreview();
  } else stage.innerHTML = `<img src="${escapeHtml(media.url)}" alt="Vista previa de ${escapeHtml(media.name)}">`;
  const carousel = byId("owner-instagram-preview-carousel");
  carousel.hidden = state.format !== "carousel" || state.media.length < 2;
  carousel.style.display = carousel.hidden ? "none" : "flex";
  byId("owner-instagram-preview-position").textContent = `${state.previewIndex + 1}/${Math.max(1, state.media.length)}`;
  byId("owner-instagram-preview-dots").innerHTML = state.format === "carousel" ? state.media.map((_item, index) => `<span class="${index === state.previewIndex ? "active" : ""}"></span>`).join("") : "";
}

function renderOwnerInstagramComposer() {
  const state = ownerInstagramComposerState;
  if (!state) return;
  const config = OWNER_INSTAGRAM_COMPOSER_FORMATS[state.format];
  const terminal = ["published", "cancelled"].includes(state.content?.status);
  const lifecycle = ownerInstagramPublicationUxState(state.content);
  const lifecycleLocked = Boolean(state.content && lifecycle.actionLocked);
  const locked = terminal || lifecycleLocked;
  byId("owner-instagram-composer-title").textContent = lifecycleLocked && !terminal ? "Supervisar publicación" : state.content ? "Editar publicación" : "Crear publicación";
  byId("owner-instagram-composer-kicker").textContent = state.content ? `${lifecycle.label} · Instagram` : "Nueva publicación · Instagram";
  document.querySelectorAll('[name="composer_format"]').forEach((input) => { input.checked = input.value === state.format; input.disabled = locked || state.busy; });
  document.querySelectorAll('[name="composer_publication"]').forEach((input) => { input.checked = input.value === state.publication; input.disabled = locked || state.busy; });
  const fileInput = byId("owner-instagram-composer-file");
  fileInput.accept = config.accept;
  fileInput.multiple = state.format === "carousel";
  fileInput.disabled = locked || state.busy;
  byId("owner-instagram-composer-add").textContent = state.media.length ? (state.format === "carousel" ? "+ Añadir más" : "Cambiar archivo") : config.add;
  byId("owner-instagram-composer-add").disabled = locked || state.busy || (state.format === "carousel" && state.media.length >= config.max);
  const reuseButton = byId("owner-instagram-composer-reuse");
  reuseButton.hidden = state.format !== "story";
  reuseButton.disabled = locked || state.busy;
  byId("owner-instagram-media-help").textContent = config.help;
  byId("owner-instagram-media-count").textContent = state.format === "carousel" ? `${state.media.length}/10` : String(state.media.length);
  const mediaList = byId("owner-instagram-composer-media");
  mediaList.innerHTML = state.media.map((media, index) => ownerInstagramComposerMediaMarkup(media, index, state)).join("");
  mediaList.querySelectorAll("[data-owner-composer-move]").forEach((button) => {
    button.addEventListener("click", () => window.setTimeout(() => ownerInstagramComposerMove(button.dataset.mediaUid, Number(button.dataset.ownerComposerMove)), 0));
  });
  mediaList.querySelectorAll("[data-owner-composer-remove]").forEach((button) => { button.addEventListener("click", () => window.setTimeout(() => {
    const index = ownerInstagramComposerState?.media.findIndex((item) => item.uid === button.dataset.ownerComposerRemove) ?? -1;
    if (index < 0) return;
    ownerInstagramComposerRevoke(ownerInstagramComposerState.media[index]);
    ownerInstagramComposerState.media.splice(index, 1);
    ownerInstagramComposerState.previewIndex = Math.max(0, Math.min(ownerInstagramComposerState.previewIndex, ownerInstagramComposerState.media.length - 1));
    ownerInstagramComposerState.dirty = true;
    renderOwnerInstagramComposer();
  }, 0)); });
  const storyMedia = state.media[0];
  const storyImage = state.format === "story" && storyMedia && ownerInstagramComposerMediaType(storyMedia).startsWith("image/");
  const storyEditor = byId("owner-instagram-story-editor");
  storyEditor.hidden = !storyImage;
  if (storyImage) {
    const transform = state.storyTransform;
    document.querySelectorAll('[name="story_mode"]').forEach((input) => { input.checked = input.value === transform.mode; });
    document.querySelectorAll('[name="story_background"]').forEach((input) => { input.checked = input.value === transform.background; });
    byId("owner-instagram-story-zoom").value = String(transform.zoom);
    byId("owner-instagram-story-zoom-output").value = `${Number(transform.zoom).toFixed(2)}×`;
    byId("owner-instagram-story-x").value = String(transform.position_x);
    byId("owner-instagram-story-y").value = String(transform.position_y);
    const canRender = Boolean(storyMedia.file || storyMedia.remoteMediaId || storyMedia.sourceRawAssetId);
    storyEditor.querySelectorAll("input,button").forEach((control) => { control.disabled = locked || state.busy || !canRender; });
    byId("owner-instagram-story-editor-help").textContent = canRender ? "La vista previa y el JPEG final utilizan el mismo encuadre." : "Esta imagen anterior no conserva una fuente editable. Sustitúyela para ajustar el encuadre.";
  }
  const captionField = byId("owner-instagram-caption-field");
  captionField.hidden = state.format === "story";
  const caption = byId("owner-instagram-composer-caption");
  if (caption.value !== state.caption) caption.value = state.caption;
  caption.disabled = locked || state.busy;
  byId("owner-instagram-caption-count").textContent = String(state.caption.length);
  byId("owner-instagram-schedule-fields").hidden = state.publication !== "schedule";
  byId("owner-instagram-composer-date").value = state.date;
  byId("owner-instagram-composer-time").value = state.time;
  byId("owner-instagram-composer-date").disabled = locked || state.busy;
  byId("owner-instagram-composer-time").disabled = locked || state.busy;
  byId("owner-instagram-composer-timezone").textContent = state.timezone;
  byId("owner-instagram-composer-advanced-content").innerHTML = ownerInstagramComposerAdvanced(state.content);
  byId("owner-instagram-composer-save").disabled = locked || state.busy;
  byId("owner-instagram-composer-primary").disabled = locked || state.busy;
  byId("owner-instagram-composer-primary").textContent = lifecycleLocked && !terminal ? lifecycle.label : state.publication === "now" ? "Publicar ahora" : state.content?.status === "scheduled" ? "Reprogramar" : "Programar";
  byId("owner-instagram-composer-cancel-content").hidden = !state.content || locked;
  byId("owner-instagram-composer-close").disabled = state.busy;
  byId("owner-instagram-composer").querySelector(".instagram-composer").setAttribute("aria-busy", String(state.busy));
  renderOwnerInstagramComposerPreview(state);
}

function ownerInstagramLibraryStatusText(sync) {
  if (!sync) return "La biblioteca se actualiza de forma conservadora en segundo plano.";
  if (["queued", "running"].includes(sync.status)) return "Actualizando publicaciones de Instagram… Puedes seguir trabajando.";
  if (sync.status === "failed") return sync.safe_error_message || "No se pudo actualizar Instagram. Se mantiene la última información disponible.";
  if (sync.last_success_at) return `Última sincronización: ${formatOwnerDate(sync.last_success_at)}.`;
  return "Todavía no se ha completado la primera sincronización.";
}

function ownerInstagramLibraryCard(item) {
  const type = item.media_type === "CAROUSEL_ALBUM" ? `Carrusel · ${item.child_count} elementos` : item.media_product_type === "REELS" ? "Reel" : "Foto";
  const origin = item.origin === "autonogrow" ? "AutonoGrow" : "Instagram";
  const date = item.published_at ? formatOwnerDate(item.published_at) : "Fecha no disponible";
  const unsupported = item.media_type === "VIDEO";
  return `<article class="instagram-library-card"><div class="instagram-library-card__visual"><img src="${escapeHtml(`${API_BASE_URL}${item.preview_url}`)}" alt="" loading="lazy"></div><div><strong>${escapeHtml(type)}</strong><p>${escapeHtml(date)} · ${escapeHtml(origin)}</p></div><button class="button button-primary button-small" type="button" data-instagram-library-use="${item.id}" ${unsupported ? "disabled" : ""}>${unsupported ? "Reel no compatible en P1" : item.media_type === "CAROUSEL_ALBUM" ? "Elegir imagen" : "Usar en Story"}</button></article>`;
}

function renderOwnerInstagramLibrary() {
  const state = ownerInstagramLibraryState;
  if (!state) return;
  document.querySelectorAll("[data-instagram-library-filter]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.instagramLibraryFilter === state.filter)));
  byId("owner-instagram-library-sync").disabled = state.loading || ["queued", "running"].includes(state.sync?.status);
  byId("owner-instagram-library-status").textContent = ownerInstagramLibraryStatusText(state.sync);
  byId("owner-instagram-library-error").textContent = state.error || "";
  const grid = byId("owner-instagram-library-grid");
  const back = byId("owner-instagram-library-back");
  if (state.parent) {
    back.hidden = false;
    grid.innerHTML = `<div class="instagram-library__child-heading"><strong>¿Qué imagen quieres usar?</strong><p>Una Historia utilizará un solo elemento del carrusel.</p></div>${state.parent.children.map((child) => `<article class="instagram-library-card"><div class="instagram-library-card__visual"><img src="${escapeHtml(`${API_BASE_URL}${child.preview_url}`)}" alt="Elemento ${Number(child.position) + 1}" loading="lazy"></div><strong>Imagen ${Number(child.position) + 1}</strong><button class="button button-primary button-small" type="button" data-instagram-library-child="${child.id}">Usar en Story</button></article>`).join("")}`;
  } else {
    back.hidden = true;
    grid.innerHTML = state.loading && !state.items.length
      ? `<div class="instagram-library__empty"><strong>Cargando contenido de Instagram…</strong></div>`
      : state.items.length
        ? state.items.map(ownerInstagramLibraryCard).join("")
        : `<div class="instagram-library__empty"><strong>${state.error ? "No se pudo actualizar Instagram." : "No hay publicaciones disponibles para reutilizar."}</strong><p>${state.error ? "Se conserva la última información conocida." : "Cuando Instagram exponga contenido compatible aparecerá aquí."}</p></div>`;
  }
}

async function ownerInstagramLoadLibrary({ preserve = true } = {}) {
  const state = ownerInstagramLibraryState;
  if (!state) return;
  state.loading = true;
  state.error = "";
  if (!preserve) state.items = [];
  renderOwnerInstagramLibrary();
  try {
    const [library, sync] = await Promise.all([
      ownerInstagramJson(`${ownerInstagramApi()}/instagram-media?filter=${encodeURIComponent(state.filter)}&limit=60`),
      ownerInstagramJson(`${ownerInstagramApi()}/instagram-media/sync`),
    ]);
    if (state !== ownerInstagramLibraryState) return;
    state.items = library.items || [];
    state.sync = sync;
  } catch (error) {
    if (state !== ownerInstagramLibraryState) return;
    state.error = error.message || "No se pudo cargar Instagram.";
  } finally {
    if (state === ownerInstagramLibraryState) {
      state.loading = false;
      renderOwnerInstagramLibrary();
    }
  }
}

async function openOwnerInstagramLibrary() {
  const composer = ownerInstagramComposerState;
  if (!composer || composer.format !== "story" || composer.busy) return;
  ownerInstagramLibraryState = { filter: "recent", items: [], sync: null, parent: null, loading: false, error: "" };
  byId("owner-instagram-library-dialog").hidden = false;
  byId("owner-instagram-library-close").focus();
  await ownerInstagramLoadLibrary({ preserve: false });
}

function closeOwnerInstagramLibrary() {
  ownerInstagramLibraryState = null;
  byId("owner-instagram-library-dialog").hidden = true;
  byId("owner-instagram-composer-reuse").focus();
}

async function ownerInstagramRefreshLibrary() {
  const state = ownerInstagramLibraryState;
  if (!state || state.loading) return;
  state.loading = true;
  state.error = "";
  state.sync = { status: "queued" };
  renderOwnerInstagramLibrary();
  try {
    await ownerInstagramJson(`${ownerInstagramApi()}/instagram-media/sync`, { method: "POST" });
    for (let attempt = 0; attempt < 15 && state === ownerInstagramLibraryState; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1200));
      const sync = await ownerInstagramJson(`${ownerInstagramApi()}/instagram-media/sync`);
      state.sync = sync;
      renderOwnerInstagramLibrary();
      if (!["queued", "running"].includes(sync.status)) break;
    }
    if (state === ownerInstagramLibraryState) await ownerInstagramLoadLibrary({ preserve: true });
  } catch (error) {
    if (state === ownerInstagramLibraryState) {
      state.loading = false;
      state.error = error.message || "No se pudo actualizar Instagram. Se mantiene la última información disponible.";
      renderOwnerInstagramLibrary();
    }
  }
}

async function ownerInstagramUseRemoteMedia(mediaId) {
  const library = ownerInstagramLibraryState;
  const composer = ownerInstagramComposerState;
  if (!library || !composer) return;
  const item = library.parent?.children.find((child) => child.id === mediaId) || library.items.find((candidate) => candidate.id === mediaId);
  if (!item) return;
  library.loading = true;
  renderOwnerInstagramLibrary();
  try {
    const response = await ownerInstagramFileResponse(`${API_BASE_URL}${item.preview_url}`);
    const blob = await response.blob();
    composer.media.forEach(ownerInstagramComposerRevoke);
    composer.media = [{
      uid: `instagram-${item.id}`,
      id: null,
      name: "Contenido de Instagram",
      mediaType: blob.type || "image/jpeg",
      file: null,
      sourceRawAssetId: null,
      remoteMediaId: item.id,
      url: URL.createObjectURL(blob),
      objectUrl: true,
      loading: false,
    }];
    composer.previewIndex = 0;
    composer.storyTransform = { ...OWNER_INSTAGRAM_STORY_TRANSFORM_DEFAULT };
    composer.storyTransformDirty = true;
    composer.dirty = true;
    closeOwnerInstagramLibrary();
    renderOwnerInstagramComposer();
  } catch (error) {
    library.loading = false;
    library.error = error.message || "No se pudo preparar esta imagen.";
    renderOwnerInstagramLibrary();
  }
}

function ownerInstagramComposerChangeFormat(format) {
  const state = ownerInstagramComposerState;
  if (!state || !OWNER_INSTAGRAM_COMPOSER_FORMATS[format] || state.format === format) return;
  const compatible = state.media.filter((item) => ownerInstagramComposerFormatAccepts(format, ownerInstagramComposerMediaType(item)));
  const max = OWNER_INSTAGRAM_COMPOSER_FORMATS[format].max;
  state.media.filter((item) => !compatible.slice(0, max).includes(item)).forEach(ownerInstagramComposerRevoke);
  state.media = compatible.slice(0, max);
  state.format = format;
  state.previewIndex = 0;
  state.dirty = true;
  byId("owner-instagram-composer-error").textContent = compatible.length ? "" : "Añade contenido compatible con el formato elegido.";
  renderOwnerInstagramComposer();
}

function ownerInstagramComposerAddFiles(fileList) {
  const state = ownerInstagramComposerState;
  if (!state) return;
  const config = OWNER_INSTAGRAM_COMPOSER_FORMATS[state.format];
  const files = Array.from(fileList);
  const invalid = files.find((file) => !ownerInstagramComposerFormatAccepts(state.format, file.type));
  if (invalid) {
    byId("owner-instagram-composer-error").textContent = state.format === "story" ? "La Historia admite imágenes JPEG, PNG o WebP y mantiene el flujo MP4 actual." : `${config.label} solo admite ${config.accept === "image/jpeg" ? "JPEG" : "MP4"}.`;
    return;
  }
  const nextCount = state.format === "carousel" ? state.media.length + files.length : files.length;
  if (nextCount > config.max) {
    byId("owner-instagram-composer-error").textContent = "Un carrusel admite como máximo 10 imágenes.";
    return;
  }
  const additions = files.map((file) => ({ uid: `local-${++ownerInstagramComposerSequence}`, id: null, name: file.name, mediaType: file.type, file, sourceRawAssetId: null, remoteMediaId: null, url: URL.createObjectURL(file), objectUrl: true, loading: false }));
  if (state.format === "carousel") state.media.push(...additions);
  else {
    state.media.forEach(ownerInstagramComposerRevoke);
    state.media = additions.slice(0, 1);
  }
  state.previewIndex = state.format === "carousel" ? Math.max(0, state.media.length - additions.length) : 0;
  if (state.format === "story" && additions[0]?.mediaType.startsWith("image/")) {
    state.storyTransform = { ...OWNER_INSTAGRAM_STORY_TRANSFORM_DEFAULT };
    state.storyTransformDirty = true;
  }
  state.dirty = true;
  byId("owner-instagram-composer-error").textContent = "";
  renderOwnerInstagramComposer();
}

function ownerInstagramComposerMove(uid, direction) {
  const state = ownerInstagramComposerState;
  const index = state?.media.findIndex((item) => item.uid === uid) ?? -1;
  const target = index + direction;
  if (!state || index < 0 || target < 0 || target >= state.media.length) return;
  const [item] = state.media.splice(index, 1);
  state.media.splice(target, 0, item);
  state.previewIndex = target;
  state.dirty = true;
  renderOwnerInstagramComposer();
}

function ownerInstagramComposerDrop(sourceUid, targetUid) {
  const state = ownerInstagramComposerState;
  if (!state || sourceUid === targetUid) return;
  const source = state.media.findIndex((item) => item.uid === sourceUid);
  const target = state.media.findIndex((item) => item.uid === targetUid);
  if (source < 0 || target < 0) return;
  const [item] = state.media.splice(source, 1);
  state.media.splice(target, 0, item);
  state.previewIndex = target;
  state.dirty = true;
  renderOwnerInstagramComposer();
}

function ownerInstagramComposerValidate({ requirePublication = false } = {}) {
  const state = ownerInstagramComposerState;
  if (!state) return false;
  const config = OWNER_INSTAGRAM_COMPOSER_FORMATS[state.format];
  if (state.format === "carousel" && state.media.length === 1) {
    byId("owner-instagram-composer-error").textContent = "Añade al menos 2 imágenes para guardar el carrusel.";
    return false;
  }
  if (requirePublication && (state.media.length < config.min || state.media.length > config.max)) {
    byId("owner-instagram-composer-error").textContent = state.format === "carousel" ? "Selecciona entre 2 y 10 imágenes para el carrusel." : `Añade el contenido de la ${config.label.toLowerCase()}.`;
    return false;
  }
  if (state.media.some((item) => !ownerInstagramComposerFormatAccepts(state.format, ownerInstagramComposerMediaType(item)))) {
    byId("owner-instagram-composer-error").textContent = "Hay un archivo que no es compatible con el formato elegido.";
    return false;
  }
  if (requirePublication && state.publication === "schedule" && (!state.date || !state.time)) {
    byId("owner-instagram-composer-error").textContent = "Elige la fecha y la hora para programar.";
    (!state.date ? byId("owner-instagram-composer-date") : byId("owner-instagram-composer-time")).focus();
    return false;
  }
  byId("owner-instagram-composer-error").textContent = "";
  return true;
}

function ownerInstagramComposerPlannedValue(state = ownerInstagramComposerState) {
  return state?.date && state?.time ? `${state.date}T${state.time}` : null;
}

function setOwnerInstagramComposerBusy(busy, message = "") {
  const state = ownerInstagramComposerState;
  if (!state) return;
  state.busy = busy;
  if (message) byId("owner-instagram-composer-error").textContent = message;
  renderOwnerInstagramComposer();
}

async function ownerInstagramComposerUploadLocalMedia(contentId) {
  const state = ownerInstagramComposerState;
  const api = ownerInstagramApi();
  for (let index = 0; index < state.media.length; index += 1) {
    const media = state.media[index];
    const storyImage = state.format === "story" && ownerInstagramComposerMediaType(media).startsWith("image/");
    if (storyImage && (media.file || media.remoteMediaId || state.storyTransformDirty)) {
      byId("owner-instagram-composer-error").textContent = "Generando JPEG 9:16…";
      const data = new FormData();
      data.append("transform", JSON.stringify(state.storyTransform));
      if (media.file) data.append("file", media.file, media.name);
      else if (media.remoteMediaId) data.append("remote_media_id", String(media.remoteMediaId));
      else if (media.sourceRawAssetId) data.append("source_raw_asset_id", String(media.sourceRawAssetId));
      else throw new Error("Sustituye la imagen para poder regenerar su encuadre.");
      const result = await ownerInstagramJson(`${api}/contents/${contentId}/story-image`, { method: "POST", body: data });
      media.id = result.asset.id;
      media.mediaType = result.asset.media_type;
      media.fileUrl = result.asset.file_url;
      media.sourceRawAssetId = result.asset.source_raw_asset_id;
      media.remoteMediaId = null;
      media.file = null;
      media.uid = `asset-${result.asset.id}`;
      state.content = result.content;
      state.storyTransformDirty = false;
      continue;
    }
    if (!media.file) continue;
    byId("owner-instagram-composer-error").textContent = `Subiendo ${index + 1} de ${state.media.length}…`;
    const data = new FormData();
    data.append("file", media.file, media.name);
    const asset = await ownerInstagramJson(`${api}/contents/${contentId}/final-assets`, { method: "POST", body: data });
    media.id = asset.id;
    media.mediaType = asset.media_type;
    media.fileUrl = asset.file_url;
    media.file = null;
    media.uid = `asset-${asset.id}`;
  }
}

async function ownerInstagramComposerPatchDate(content, value) {
  const state = ownerInstagramComposerState;
  const local = content.planned_publish_at ? ownerInstagramLocalInput(content.planned_publish_at, content.business_timezone) : "";
  if ((value || "") === local) return content;
  return ownerInstagramJson(`${ownerInstagramApi()}/contents/${content.id}/planned-date`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ planned_publish_at: value }),
  });
}

async function ownerInstagramComposerSave({ persistDate = true } = {}) {
  const state = ownerInstagramComposerState;
  const api = ownerInstagramApi();
  let content = state.content;
  if (!content) {
    content = await ownerInstagramJson(`${api}/contents`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: ownerInstagramComposerTitle(state),
        caption: state.format === "story" ? "" : state.caption,
        format: state.format,
        planned_publish_at: null,
      }),
    });
    state.contentId = content.id;
    state.content = content;
    upsertOwnerInstagramContent(content);
  }
  await ownerInstagramComposerUploadLocalMedia(content.id);
  content = await ownerInstagramJson(`${api}/contents/${content.id}/material`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      caption: state.format === "story" ? "" : state.caption,
      format: state.format,
      asset_ids: state.media.map((item) => item.id),
      cover_asset_id: state.media[0]?.id || null,
    }),
  });
  if (persistDate) content = await ownerInstagramComposerPatchDate(content, ownerInstagramComposerPlannedValue(state));
  state.content = content;
  state.contentId = content.id;
  state.dirty = false;
  upsertOwnerInstagramContent(content);
  return content;
}

async function ownerInstagramComposerClearPlannedDate(content) {
  return content.planned_publish_at ? ownerInstagramComposerPatchDate(content, null) : content;
}

async function ownerInstagramComposerEnsureValidated(content) {
  const api = ownerInstagramApi();
  let current = content;
  if (["draft", "changes_requested", "ready_for_review"].includes(current.status)) {
    current = await ownerInstagramComposerClearPlannedDate(current);
  }
  if (["draft", "changes_requested"].includes(current.status)) {
    current = await ownerInstagramJson(`${api}/contents/${current.id}/submit-for-review`, { method: "POST" });
  }
  if (current.status === "ready_for_review") {
    current = await ownerInstagramJson(`${api}/contents/${current.id}/validate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version_id: current.current_version.id }),
    });
  }
  if (!["validated", "scheduled"].includes(current.status)) throw new Error("La publicación no ha podido quedar preparada.");
  return current;
}

async function saveOwnerInstagramComposerDraft() {
  const state = ownerInstagramComposerState;
  if (!state || state.busy || !ownerInstagramComposerValidate()) return;
  const mutationKey = state.contentId ? `content:${state.contentId}` : "content-create";
  if (!beginOwnerInstagramMutation(mutationKey)) return;
  setOwnerInstagramComposerBusy(true, "Guardando borrador…");
  try {
    const content = await ownerInstagramComposerSave({ persistDate: true });
    byId("owner-instagram-status").textContent = "Borrador guardado.";
    state.dirty = false;
    closeOwnerInstagramComposer({ force: true });
    if (content.planned_publish_at) ownerInstagramCalendarDate = ownerInstagramContentDateKey(content);
    renderOwnerInstagramContents();
  } catch (error) {
    byId("owner-instagram-composer-error").textContent = error.message;
    if (state.contentId) await reconcileOwnerInstagramContent(ownerInstagramApi(), state.contentId);
  } finally {
    endOwnerInstagramMutation(mutationKey);
    if (ownerInstagramComposerState) setOwnerInstagramComposerBusy(false);
  }
}

async function publishOwnerInstagramComposer() {
  const state = ownerInstagramComposerState;
  if (!state || state.busy) return;
  const lifecycle = ownerInstagramPublicationUxState(state.content);
  if (state.content && lifecycle.actionLocked) {
    byId("owner-instagram-composer-error").textContent = lifecycle.detail;
    renderOwnerInstagramComposer();
    return;
  }
  if (!ownerInstagramComposerValidate({ requirePublication: true })) return;
  const mutationKey = state.contentId ? `content:${state.contentId}` : "content-create";
  if (!beginOwnerInstagramMutation(mutationKey)) return;
  setOwnerInstagramComposerBusy(true, state.publication === "now" ? "Preparando la publicación…" : "Preparando la programación…");
  try {
    const desired = ownerInstagramComposerPlannedValue(state);
    let content = await ownerInstagramComposerSave({ persistDate: false });
    const wasScheduled = content.status === "scheduled";
    if (!wasScheduled) content = await ownerInstagramComposerEnsureValidated(content);
    if (state.publication === "now") {
      content = await ownerInstagramComposerClearPlannedDate(content);
      await ownerInstagramJson(`${ownerInstagramApi()}/contents/${content.id}/publish-now`, { method: "POST" });
      content = await ownerInstagramJson(`${ownerInstagramApi()}/contents/${content.id}`);
      byId("owner-instagram-status").textContent = `Publicación enviada a la cola (${ownerInstagramPublishingMode()}).`;
    } else if (wasScheduled) {
      content = await ownerInstagramComposerPatchDate(content, desired);
      byId("owner-instagram-status").textContent = "Publicación reprogramada.";
    } else {
      content = await ownerInstagramComposerPatchDate(content, desired);
      if (content.status === "validated") content = await ownerInstagramJson(`${ownerInstagramApi()}/contents/${content.id}/schedule`, { method: "POST" });
      byId("owner-instagram-status").textContent = "Publicación programada.";
    }
    upsertOwnerInstagramContent(content);
    state.dirty = false;
    closeOwnerInstagramComposer({ force: true });
    if (content.planned_publish_at) ownerInstagramCalendarDate = ownerInstagramContentDateKey(content);
    renderOwnerInstagramContents();
  } catch (error) {
    byId("owner-instagram-composer-error").textContent = error.message;
    if (state.contentId) {
      try {
        const content = await ownerInstagramJson(`${ownerInstagramApi()}/contents/${state.contentId}`);
        state.content = content;
        upsertOwnerInstagramContent(content);
      } catch (_reconcileError) { /* El error original es el que debe mostrarse. */ }
    }
  } finally {
    endOwnerInstagramMutation(mutationKey);
    if (ownerInstagramComposerState) setOwnerInstagramComposerBusy(false);
  }
}

async function cancelOwnerInstagramComposerContent() {
  const state = ownerInstagramComposerState;
  if (!state?.contentId || state.busy || !window.confirm(ownerInstagramRemovalConfirmation(state.content))) return;
  const mutationKey = `content:${state.contentId}`;
  if (!beginOwnerInstagramMutation(mutationKey)) return;
  setOwnerInstagramComposerBusy(true, "Cancelando publicación…");
  try {
    const content = await ownerInstagramJson(`${ownerInstagramApi()}/contents/${state.contentId}/cancel`, { method: "POST" });
    upsertOwnerInstagramContent(content);
    state.dirty = false;
    closeOwnerInstagramComposer({ force: true });
    byId("owner-instagram-status").textContent = "Publicación cancelada.";
  } catch (error) {
    byId("owner-instagram-composer-error").textContent = error.message;
  } finally {
    endOwnerInstagramMutation(mutationKey);
    if (ownerInstagramComposerState) setOwnerInstagramComposerBusy(false);
  }
}

function ownerInstagramRetryAfterSeconds(response) {
  const value = response.headers.get("Retry-After");
  if (!value) return 60;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.max(1, Math.ceil(seconds));
  const retryAt = Date.parse(value);
  return Number.isNaN(retryAt) ? 60 : Math.max(1, Math.ceil((retryAt - Date.now()) / 1000));
}

function ownerInstagramCooldownSeconds() {
  return Math.max(0, Math.ceil((ownerInstagramRetryUntil - Date.now()) / 1000));
}

function ownerInstagramRateLimitError(seconds = ownerInstagramCooldownSeconds()) {
  const wait = Math.max(1, seconds);
  const error = new Error(`Se han realizado demasiadas solicitudes. Vuelve a intentarlo en ${wait} s.`);
  error.status = 429;
  error.ownerInstagramRateLimited = true;
  return error;
}

function updateOwnerInstagramRefreshState() {
  const button = byId("owner-instagram-refresh");
  const coolingDown = ownerInstagramCooldownSeconds() > 0;
  const mutating = ownerInstagramMutationKeys.size > 0;
  button.disabled = ownerInstagramLoading || coolingDown || mutating;
  byId("owner-instagram-business").disabled = ownerInstagramLoading || mutating;
  byId("owner-instagram-enabled").disabled = ownerInstagramLoading || mutating;
  button.textContent = ownerInstagramLoading ? "Actualizando…" : "Actualizar";
  if (ownerInstagramLoading) button.setAttribute("aria-busy", "true");
  else button.removeAttribute("aria-busy");
}

function startOwnerInstagramCooldown(seconds) {
  ownerInstagramRetryUntil = Math.max(ownerInstagramRetryUntil, Date.now() + seconds * 1000);
  if (ownerInstagramRetryTimer) window.clearTimeout(ownerInstagramRetryTimer);
  updateOwnerInstagramRefreshState();
  ownerInstagramRetryTimer = window.setTimeout(() => {
    ownerInstagramRetryTimer = null;
    ownerInstagramRetryUntil = 0;
    updateOwnerInstagramRefreshState();
    const status = byId("owner-instagram-status");
    if (status.dataset.rateLimited === "true") {
      delete status.dataset.rateLimited;
      status.textContent = "Ya puedes volver a actualizar el contenido.";
    }
  }, Math.max(1, ownerInstagramCooldownSeconds()) * 1000);
}

function showOwnerInstagramError(error) {
  const status = byId("owner-instagram-status");
  status.textContent = error.message || "No se pudo completar la operación editorial.";
  if (error.ownerInstagramRateLimited) {
    status.dataset.rateLimited = "true";
    byId("owner-instagram-workspace").hidden = true;
  } else delete status.dataset.rateLimited;
}

async function ownerInstagramJson(url, options = {}) {
  const cooldown = ownerInstagramCooldownSeconds();
  if (cooldown > 0) throw ownerInstagramRateLimitError(cooldown);
  const response = await fetch(url, options);
  const body = await readResponseBody(response);
  if (response.status === 429) {
    const retryAfter = ownerInstagramRetryAfterSeconds(response);
    startOwnerInstagramCooldown(retryAfter);
    throw ownerInstagramRateLimitError(retryAfter);
  }
  if (!response.ok) {
    const detail = body.detail;
    const error = new Error(typeof detail === "string" ? detail : detail?.message || "No se pudo completar la operación editorial.");
    error.status = response.status;
    error.detail = detail;
    error.code = typeof detail === "object" ? detail?.code : null;
    throw error;
  }
  return body;
}

async function ownerInstagramFileResponse(url) {
  const cooldown = ownerInstagramCooldownSeconds();
  if (cooldown > 0) throw ownerInstagramRateLimitError(cooldown);
  const response = await fetch(url);
  if (response.status === 429) {
    const retryAfter = ownerInstagramRetryAfterSeconds(response);
    startOwnerInstagramCooldown(retryAfter);
    throw ownerInstagramRateLimitError(retryAfter);
  }
  if (!response.ok) {
    const body = await readResponseBody(response);
    const error = new Error(body.detail || "No se pudo abrir el material de origen.");
    error.status = response.status;
    throw error;
  }
  return response;
}

function ownerInstagramDownloadFilename(response, fallback) {
  const disposition = response.headers.get("Content-Disposition") || "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const plain = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  if (encoded) {
    try { return decodeURIComponent(encoded); } catch (_error) { return fallback; }
  }
  return plain || fallback;
}

async function downloadOwnerInstagramRawAsset(asset, trigger = null) {
  const response = await ownerInstagramFileResponse(`${API_BASE_URL}${asset.download_url}`);
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = ownerInstagramDownloadFilename(response, asset.original_filename);
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
  if (trigger) trigger.focus();
}

function closeOwnerInstagramPreview() {
  const dialog = byId("owner-instagram-preview-dialog");
  dialog.hidden = true;
  document.body.classList.remove("owner-dialog-open");
  byId("owner-instagram-preview-image").removeAttribute("src");
  if (ownerInstagramPreviewObjectUrl) URL.revokeObjectURL(ownerInstagramPreviewObjectUrl);
  ownerInstagramPreviewObjectUrl = null;
  ownerInstagramPreviewAssetId = null;
  ownerInstagramPreviewReturnFocus?.focus();
  ownerInstagramPreviewReturnFocus = null;
}

async function openOwnerInstagramPreview(asset, trigger) {
  const response = await ownerInstagramFileResponse(`${API_BASE_URL}${asset.preview_url}`);
  const blob = await response.blob();
  if (!blob.type.startsWith("image/")) throw new Error("Este formato no admite previsualización.");
  if (ownerInstagramPreviewObjectUrl) URL.revokeObjectURL(ownerInstagramPreviewObjectUrl);
  ownerInstagramPreviewObjectUrl = URL.createObjectURL(blob);
  ownerInstagramPreviewAssetId = asset.id;
  ownerInstagramPreviewReturnFocus = trigger;
  byId("owner-instagram-preview-title").textContent = asset.label || asset.original_filename;
  const image = byId("owner-instagram-preview-image");
  image.src = ownerInstagramPreviewObjectUrl;
  image.alt = `Previsualización de ${asset.label || asset.original_filename}`;
  byId("owner-instagram-preview-dialog").hidden = false;
  document.body.classList.add("owner-dialog-open");
  byId("owner-instagram-preview-close").focus();
}

function ownerInstagramAssociationUsage(association) {
  const uses = [];
  if (association.is_source_material) uses.push("Material de origen");
  if (association.has_final_derivative) uses.push("Origen de material final");
  if (association.has_historical_reference) uses.push("Historial editorial");
  return uses.join(" + ") || "Dependencia editorial";
}

function renderOwnerInstagramAssociationManager() {
  const data = ownerInstagramAssociationData;
  if (!data) return;
  const count = data.association_count || 0;
  byId("owner-instagram-associations-title").textContent = data.raw_asset.label || data.raw_asset.original_filename;
  byId("owner-instagram-associations-filename").textContent = data.raw_asset.original_filename;
  byId("owner-instagram-associations-count").textContent = String(count);
  byId("owner-instagram-associations-description").textContent = count
    ? "Este material está siendo utilizado y no puede eliminarse todavía."
    : "Este material no tiene asociaciones y ya puede eliminarse de forma segura.";
  byId("owner-instagram-associations-remove-all").hidden = data.modifiable_count < 2;
  byId("owner-instagram-associations-delete").hidden = count !== 0;
  byId("owner-instagram-associations-list").innerHTML = count
    ? data.associations.map((association) => `<article class="instagram-association-row" data-owner-instagram-association="${association.content_id}"><header><div><h3>${escapeHtml(association.content_title)}</h3><p>${escapeHtml(ownerInstagramStateLabel(association.content_status))}${association.content_archived ? " · Archivado" : ""}</p></div><span class="ag-badge ag-badge--neutral">${escapeHtml(ownerInstagramAssociationUsage(association))}</span></header><dl><div><dt>Uso</dt><dd>${escapeHtml(ownerInstagramAssociationUsage(association))}</dd></div><div><dt>Modificable</dt><dd>${association.modifiable ? "Sí" : "No"}</dd></div></dl>${association.protected_reason ? `<p class="instagram-association-protection">${escapeHtml(association.protected_reason)}</p>` : ""}<div class="instagram-editorial-actions"><button class="button button-secondary button-small" type="button" data-owner-instagram-association-open="${association.content_id}">Abrir contenido</button>${association.modifiable ? `<button class="button button-ghost button-small" type="button" data-owner-instagram-association-remove="${association.content_id}" data-owner-instagram-association-mutation>Desasociar</button>` : ""}</div></article>`).join("")
    : `<p class="instagram-associations-empty">Este archivo no se utiliza en ningún contenido.</p>`;
}

function showOwnerInstagramAssociationManager(data, trigger) {
  const wasHidden = byId("owner-instagram-associations-dialog").hidden;
  ownerInstagramAssociationData = data;
  if (wasHidden) ownerInstagramAssociationReturnFocus = trigger || null;
  byId("owner-instagram-associations-error").textContent = "";
  renderOwnerInstagramAssociationManager();
  byId("owner-instagram-associations-dialog").hidden = false;
  document.body.classList.add("owner-dialog-open");
  document.querySelector("main").inert = true;
  byId("owner-instagram-associations-close").focus();
}

async function openOwnerInstagramAssociationManager(assetId, trigger, initialData = null) {
  if (initialData) {
    showOwnerInstagramAssociationManager(initialData, trigger);
    return;
  }
  const api = ownerInstagramApi();
  if (!api || !assetId) return;
  trigger.disabled = true;
  trigger.setAttribute("aria-busy", "true");
  try {
    const data = await ownerInstagramJson(`${api}/raw-assets/${assetId}/associations`);
    showOwnerInstagramAssociationManager(data, trigger);
  } catch (error) {
    showOwnerInstagramError(error);
  } finally {
    if (trigger.isConnected) {
      trigger.disabled = false;
      trigger.removeAttribute("aria-busy");
    }
  }
}

function closeOwnerInstagramAssociationManager(restoreFocus = true) {
  if (ownerInstagramAssociationBusy) return;
  byId("owner-instagram-associations-dialog").hidden = true;
  document.body.classList.remove("owner-dialog-open");
  document.querySelector("main").inert = false;
  if (restoreFocus) ownerInstagramAssociationReturnFocus?.focus();
  ownerInstagramAssociationData = null;
  ownerInstagramAssociationReturnFocus = null;
  byId("owner-instagram-associations-error").textContent = "";
}

function setOwnerInstagramAssociationBusy(busy, trigger = null, label = "Procesando…") {
  ownerInstagramAssociationBusy = busy;
  const dialog = byId("owner-instagram-associations-dialog");
  const panel = dialog.querySelector("[role='dialog']");
  if (busy) panel.setAttribute("aria-busy", "true");
  else panel.removeAttribute("aria-busy");
  dialog.querySelectorAll("[data-owner-instagram-association-mutation], #owner-instagram-associations-close, #owner-instagram-associations-done").forEach((control) => { control.disabled = busy; });
  if (!trigger) return;
  if (busy) {
    trigger.dataset.ownerInstagramLabel = trigger.textContent;
    trigger.textContent = label;
  } else if (trigger.dataset.ownerInstagramLabel) {
    trigger.textContent = trigger.dataset.ownerInstagramLabel;
    delete trigger.dataset.ownerInstagramLabel;
  }
}

async function refreshOwnerInstagramAssociationManager(api, assetId) {
  const data = await ownerInstagramJson(`${api}/raw-assets/${assetId}/associations`);
  if (ownerInstagramAssociationData?.raw_asset.id === assetId) {
    ownerInstagramAssociationData = data;
    renderOwnerInstagramAssociationManager();
  }
  return data;
}

async function disassociateOwnerInstagramAssociation(button) {
  const api = ownerInstagramApi();
  const assetId = ownerInstagramAssociationData?.raw_asset.id;
  const contentId = Number(button.dataset.ownerInstagramAssociationRemove);
  const keys = [`raw:${assetId}`, `content:${contentId}`];
  if (!api || !assetId || !contentId || !beginOwnerInstagramMutationGroup(keys)) return;
  setOwnerInstagramAssociationBusy(true, button, "Desasociando…");
  byId("owner-instagram-associations-error").textContent = "";
  try {
    const payload = await ownerInstagramJson(`${api}/raw-assets/${assetId}/associations/${contentId}`, { method: "DELETE" });
    applyOwnerInstagramRawContentPayload(payload);
    ownerInstagramAssociationData.associations = ownerInstagramAssociationData.associations.filter((association) => association.content_id !== contentId);
    ownerInstagramAssociationData.association_count = ownerInstagramAssociationData.associations.length;
    ownerInstagramAssociationData.modifiable_count = ownerInstagramAssociationData.associations.filter((association) => association.modifiable).length;
    renderOwnerInstagramAssociationManager();
    await refreshOwnerInstagramAssociationManager(api, assetId);
    byId("owner-instagram-status").textContent = "Material desasociado.";
  } catch (error) {
    if ([404, 409].includes(error.status)) {
      try {
        await refreshOwnerInstagramAssociationManager(api, assetId);
      } catch (refreshError) {
        byId("owner-instagram-associations-error").textContent = refreshError.message;
      }
    }
    if (error.status !== 404) byId("owner-instagram-associations-error").textContent = error.message;
    if (error.status === 429) showOwnerInstagramError(error);
  } finally {
    setOwnerInstagramAssociationBusy(false, button);
    endOwnerInstagramMutationGroup(keys);
  }
}

async function disassociateAllOwnerInstagramAssociations(button) {
  const api = ownerInstagramApi();
  const assetId = ownerInstagramAssociationData?.raw_asset.id;
  const key = `raw:${assetId}`;
  if (!api || !assetId || !beginOwnerInstagramMutation(key)) return;
  setOwnerInstagramAssociationBusy(true, button, "Desasociando…");
  byId("owner-instagram-associations-error").textContent = "";
  try {
    const payload = await ownerInstagramJson(`${api}/raw-assets/${assetId}/associations`, { method: "DELETE" });
    upsertOwnerInstagramRawAsset(payload.raw_asset);
    payload.contents.forEach((content) => {
      const index = ownerInstagramContents.findIndex((item) => item.id === content.id);
      if (index === -1) ownerInstagramContents.unshift(content);
      else ownerInstagramContents[index] = content;
    });
    renderOwnerInstagramRaw(ownerInstagramRawAssets);
    renderOwnerInstagramContents();
    ownerInstagramAssociationData = payload.association_manager;
    renderOwnerInstagramAssociationManager();
    byId("owner-instagram-status").textContent = "Asociaciones permitidas eliminadas.";
  } catch (error) {
    byId("owner-instagram-associations-error").textContent = error.message;
    if ([404, 409].includes(error.status)) {
      try {
        await refreshOwnerInstagramAssociationManager(api, assetId);
      } catch (refreshError) {
        byId("owner-instagram-associations-error").textContent = refreshError.message;
      }
    }
    if (error.status === 429) showOwnerInstagramError(error);
  } finally {
    setOwnerInstagramAssociationBusy(false, button);
    endOwnerInstagramMutation(key);
  }
}

async function openOwnerInstagramAssociatedContent(contentId) {
  if (!ownerInstagramContents.some((item) => item.id === contentId)) {
    byId("owner-instagram-associations-error").textContent = "Este contenido no está disponible en el workspace activo.";
    return;
  }
  closeOwnerInstagramAssociationManager(false);
  await openOwnerInstagramContentDetail(contentId);
}

function beginOwnerInstagramMutation(key) {
  return beginOwnerInstagramMutationGroup([key]);
}

function beginOwnerInstagramMutationGroup(keys) {
  if (ownerInstagramMutationKeys.has("settings") || (keys.includes("settings") && ownerInstagramMutationKeys.size > 0)) return false;
  if (keys.some((key) => ownerInstagramMutationKeys.has(key))) return false;
  keys.forEach((key) => ownerInstagramMutationKeys.add(key));
  updateOwnerInstagramRefreshState();
  return true;
}

function endOwnerInstagramMutation(key) {
  endOwnerInstagramMutationGroup([key]);
}

function endOwnerInstagramMutationGroup(keys) {
  keys.forEach((key) => ownerInstagramMutationKeys.delete(key));
  updateOwnerInstagramRefreshState();
}

function upsertOwnerInstagramRawAsset(asset) {
  const index = ownerInstagramRawAssets.findIndex((item) => item.id === asset.id);
  if (index === -1) ownerInstagramRawAssets.unshift(asset);
  else ownerInstagramRawAssets[index] = asset;
}

function applyOwnerInstagramRawContentPayload(payload) {
  upsertOwnerInstagramRawAsset(payload.raw_asset);
  upsertOwnerInstagramContent(payload.content);
}

function stopOwnerInstagramLifecyclePolling() {
  if (ownerInstagramLifecycleTimer) window.clearTimeout(ownerInstagramLifecycleTimer);
  ownerInstagramLifecycleTimer = null;
}

function ownerInstagramHasTransientPublications() {
  return ownerInstagramContents.some((item) => {
    const jobStatus = item.publish_jobs?.[0]?.status;
    return OWNER_INSTAGRAM_ACTIVE_JOB_STATUSES.has(jobStatus)
      && ownerInstagramPublicationUxState(item).transient;
  });
}

function ownerInstagramLifecyclePanelIsActive() {
  return document.querySelector('[data-panel="instagram-content"]')?.classList.contains("active")
    && Boolean(ownerInstagramApi())
    && ownerInstagramSettings?.enabled;
}

function scheduleOwnerInstagramLifecyclePolling() {
  if (ownerInstagramLifecycleTimer || !ownerInstagramLifecyclePanelIsActive() || !ownerInstagramHasTransientPublications()) {
    if (!ownerInstagramHasTransientPublications()) stopOwnerInstagramLifecyclePolling();
    return;
  }
  ownerInstagramLifecycleTimer = window.setTimeout(async () => {
    ownerInstagramLifecycleTimer = null;
    if (!ownerInstagramLifecyclePanelIsActive() || !ownerInstagramHasTransientPublications()) return;
    if (document.hidden || ownerInstagramLoading || ownerInstagramMutationKeys.size > 0) {
      scheduleOwnerInstagramLifecyclePolling();
      return;
    }
    await loadOwnerInstagramCalendarPeriod();
  }, 10_000);
}

function syncOwnerInstagramComposerLifecycle(content) {
  const state = ownerInstagramComposerState;
  if (!state || state.contentId !== content.id) return;
  state.content = {
    ...state.content,
    ...content,
    versions: content.versions || state.content?.versions,
    publication_events: content.publication_events || state.content?.publication_events,
  };
  renderOwnerInstagramComposer();
}

function upsertOwnerInstagramContent(content) {
  const index = ownerInstagramContents.findIndex((item) => item.id === content.id);
  if (index === -1) ownerInstagramContents.unshift(content);
  else ownerInstagramContents[index] = content;
  syncOwnerInstagramComposerLifecycle(content);
  renderOwnerInstagramContents();
  renderOwnerInstagramRaw(ownerInstagramRawAssets);
  scheduleOwnerInstagramLifecyclePolling();
}

async function loadOwnerInstagramWorkspace(api) {
  ownerInstagramCalendarDate ||= instagramCivilDateKey();
  const keys = ownerInstagramPeriodKeys();
  const range = new URLSearchParams({
    from: `${instagramAddDays(keys[0], -1)}T00:00:00Z`,
    to: `${instagramAddDays(keys[keys.length - 1], 2)}T00:00:00Z`,
    include_unscheduled: "true"
  });
  const [raw, contentList] = await Promise.all([
    ownerInstagramJson(`${api}/raw-assets`),
    ownerInstagramJson(`${api}/contents?${range.toString()}`)
  ]);
  ownerInstagramRawAssets = raw.assets;
  ownerInstagramContents = contentList.contents;
  const openContent = ownerInstagramContents.find((item) => item.id === ownerInstagramComposerState?.contentId);
  if (openContent) syncOwnerInstagramComposerLifecycle(openContent);
  renderOwnerInstagramRaw(ownerInstagramRawAssets);
  renderOwnerInstagramContents();
  scheduleOwnerInstagramLifecyclePolling();
}

async function loadOwnerInstagramCalendarPeriod() {
  const api = ownerInstagramApi();
  if (!api || ownerInstagramLoading) return;
  const keys = ownerInstagramPeriodKeys();
  const range = new URLSearchParams({
    from: `${instagramAddDays(keys[0], -1)}T00:00:00Z`,
    to: `${instagramAddDays(keys[keys.length - 1], 2)}T00:00:00Z`,
    include_unscheduled: "true"
  });
  ownerInstagramLoading = true;
  updateOwnerInstagramRefreshState();
  try {
    const payload = await ownerInstagramJson(`${api}/contents?${range.toString()}`);
    ownerInstagramContents = payload.contents;
    const openContent = ownerInstagramContents.find((item) => item.id === ownerInstagramComposerState?.contentId);
    if (openContent) syncOwnerInstagramComposerLifecycle(openContent);
    renderOwnerInstagramRaw(ownerInstagramRawAssets);
    renderOwnerInstagramContents();
  } catch (error) {
    showOwnerInstagramError(error);
  } finally {
    ownerInstagramLoading = false;
    updateOwnerInstagramRefreshState();
    scheduleOwnerInstagramLifecyclePolling();
  }
}

function shiftOwnerInstagramCalendar(direction) {
  const cursor = ownerInstagramCalendarDate || instagramCivilDateKey();
  if (ownerInstagramCalendarView === "month") {
    const value = new Date(`${cursor.slice(0, 7)}-01T12:00:00Z`);
    value.setUTCMonth(value.getUTCMonth() + direction);
    ownerInstagramCalendarDate = value.toISOString().slice(0, 10);
  } else {
    ownerInstagramCalendarDate = instagramAddDays(cursor, direction * (ownerInstagramCalendarView === "week" ? 7 : 1));
  }
  loadOwnerInstagramCalendarPeriod();
}

async function refreshOwnerInstagramContent(api, contentId) {
  const content = await ownerInstagramJson(`${api}/contents/${contentId}`);
  upsertOwnerInstagramContent(content);
}

async function reconcileOwnerInstagramContent(api, contentId) {
  try {
    await refreshOwnerInstagramContent(api, contentId);
  } catch (error) {
    if (error.ownerInstagramRateLimited) showOwnerInstagramError(error);
    if (error.status !== 404) return;
    ownerInstagramContents = ownerInstagramContents.filter((item) => item.id !== contentId);
    renderOwnerInstagramContents();
  }
}

function setOwnerInstagramFormBusy(form, busy, busyLabel = "Guardando…") {
  const submit = form.querySelector('button[type="submit"], input[type="submit"]');
  if (busy) {
    form.dataset.ownerInstagramSubmitting = "true";
    form.setAttribute("aria-busy", "true");
    if (submit) {
      submit.dataset.ownerInstagramLabel = submit.textContent;
      submit.textContent = busyLabel;
    }
  } else {
    delete form.dataset.ownerInstagramSubmitting;
    form.removeAttribute("aria-busy");
    if (submit?.dataset.ownerInstagramLabel) {
      submit.textContent = submit.dataset.ownerInstagramLabel;
      delete submit.dataset.ownerInstagramLabel;
    }
  }
  form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach((control) => { control.disabled = busy; });
}

function setOwnerInstagramScopeBusy(scope, busy, trigger = null, busyLabel = "Guardando…") {
  if (busy) scope.setAttribute("aria-busy", "true");
  else scope.removeAttribute("aria-busy");
  scope.querySelectorAll("button, input, select, textarea").forEach((control) => {
    if (busy) {
      control.dataset.ownerInstagramWasDisabled = control.disabled ? "true" : "false";
      control.disabled = true;
    } else {
      control.disabled = control.dataset.ownerInstagramWasDisabled === "true";
      delete control.dataset.ownerInstagramWasDisabled;
    }
  });
  if (!trigger) return;
  if (busy) {
    trigger.dataset.ownerInstagramLabel = trigger.textContent;
    trigger.textContent = busyLabel;
  } else if (trigger.dataset.ownerInstagramLabel) {
    trigger.textContent = trigger.dataset.ownerInstagramLabel;
    delete trigger.dataset.ownerInstagramLabel;
  }
}

function loadOwnerInstagramPanel() {
  if (ownerInstagramLoadPromise) return ownerInstagramLoadPromise;
  if (ownerInstagramMutationKeys.size > 0) return Promise.resolve(null);
  const status = byId("owner-instagram-status");
  const cooldown = ownerInstagramCooldownSeconds();
  if (cooldown > 0) {
    showOwnerInstagramError(ownerInstagramRateLimitError(cooldown));
    updateOwnerInstagramRefreshState();
    return Promise.resolve(null);
  }
  ownerInstagramLoading = true;
  updateOwnerInstagramRefreshState();
  status.textContent = "Actualizando…";
  const task = (async () => {
    try {
      if (!businesses.length) await loadBusinesses();
      renderOwnerInstagramBusinessOptions();
      const api = ownerInstagramApi();
      byId("owner-instagram-workspace").hidden = !api;
      if (!api) { status.textContent = "Selecciona un negocio."; return; }
      ownerInstagramSettings = await ownerInstagramJson(`${api}/settings`);
      renderOwnerInstagramModeCopy();
      byId("owner-instagram-enabled").checked = ownerInstagramSettings.enabled;
      byId("owner-instagram-enabled-area").hidden = !ownerInstagramSettings.enabled;
      if (!ownerInstagramSettings.enabled) { status.textContent = "Servicio desactivado."; return; }
      await loadOwnerInstagramWorkspace(api);
      status.textContent = `${ownerInstagramContents.length} contenidos · ${ownerInstagramRawAssets.length} materiales brutos · publicación ${ownerInstagramPublishingMode()}`;
    } catch (error) {
      showOwnerInstagramError(error);
    }
  })();
  ownerInstagramLoadPromise = task.finally(() => {
    ownerInstagramLoadPromise = null;
    ownerInstagramLoading = false;
    updateOwnerInstagramRefreshState();
  });
  return ownerInstagramLoadPromise;
}

async function updateOwnerInstagramService() {
  const api = ownerInstagramApi();
  if (!api) return;
  const input = byId("owner-instagram-enabled");
  const enabled = input.checked;
  const mutationKey = "settings";
  if (!beginOwnerInstagramMutation(mutationKey)) return;
  input.disabled = true;
  try {
    ownerInstagramSettings = await ownerInstagramJson(`${api}/settings`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }) });
    renderOwnerInstagramModeCopy();
    byId("owner-instagram-enabled-area").hidden = !ownerInstagramSettings.enabled;
    if (ownerInstagramSettings.enabled) {
      await loadOwnerInstagramWorkspace(api);
      byId("owner-instagram-status").textContent = `${ownerInstagramContents.length} contenidos · ${ownerInstagramRawAssets.length} materiales brutos · publicación ${ownerInstagramPublishingMode()}`;
    } else {
      byId("owner-instagram-status").textContent = "Servicio desactivado.";
    }
  } catch (error) {
    input.checked = !enabled;
    showOwnerInstagramError(error);
  } finally {
    endOwnerInstagramMutation(mutationKey);
    input.disabled = false;
  }
}

async function uploadOwnerInstagramRaw(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const api = ownerInstagramApi();
  if (!api || form.dataset.ownerInstagramSubmitting === "true") return;
  const mutationKey = "raw-upload";
  if (!beginOwnerInstagramMutation(mutationKey)) return;
  setOwnerInstagramFormBusy(form, true, "Subiendo…");
  try {
    const asset = await ownerInstagramJson(`${api}/raw-assets`, { method: "POST", body: new FormData(form) });
    ownerInstagramRawAssets = [asset, ...ownerInstagramRawAssets.filter((item) => item.id !== asset.id)];
    form.reset();
    renderOwnerInstagramRaw(ownerInstagramRawAssets);
    byId("owner-instagram-status").textContent = "Material bruto añadido.";
  } catch (error) { showOwnerInstagramError(error); }
  finally {
    setOwnerInstagramFormBusy(form, false);
    endOwnerInstagramMutation(mutationKey);
  }
}

async function deleteOwnerInstagramRaw(button) {
  const api = ownerInstagramApi();
  const assetId = Number(button.dataset.ownerInstagramRawDelete || ownerInstagramAssociationData?.raw_asset.id);
  const scope = button.closest("[data-owner-instagram-raw]");
  const mutationKey = `raw:${assetId}`;
  const fromManager = button.id === "owner-instagram-associations-delete";
  if (!api || !assetId || !window.confirm("¿Eliminar este material bruto?")) return;
  if (!beginOwnerInstagramMutation(mutationKey)) return;
  if (fromManager) setOwnerInstagramAssociationBusy(true, button, "Eliminando…");
  else if (scope) setOwnerInstagramScopeBusy(scope, true, button, "Eliminando…");
  try {
    await ownerInstagramJson(`${api}/raw-assets/${assetId}`, { method: "DELETE" });
    ownerInstagramRawAssets = ownerInstagramRawAssets.filter((item) => item.id !== assetId);
    renderOwnerInstagramRaw(ownerInstagramRawAssets);
    if (fromManager) {
      setOwnerInstagramAssociationBusy(false, button);
      closeOwnerInstagramAssociationManager(false);
    }
    byId("owner-instagram-status").textContent = "Material bruto eliminado.";
  } catch (error) {
    if (error.status === 409 && error.code === "raw_asset_in_use") {
      showOwnerInstagramAssociationManager(error.detail, button);
    } else {
      showOwnerInstagramError(error);
      if (fromManager) byId("owner-instagram-associations-error").textContent = error.message;
    }
  } finally {
    if (scope?.isConnected) setOwnerInstagramScopeBusy(scope, false, button);
    if (fromManager && ownerInstagramAssociationBusy) setOwnerInstagramAssociationBusy(false, button);
    endOwnerInstagramMutation(mutationKey);
  }
}

async function handleOwnerInstagramRawAction(button) {
  const api = ownerInstagramApi();
  const assetId = Number(button.dataset.rawAssetId);
  const asset = ownerInstagramRawAssets.find((item) => item.id === assetId);
  const action = button.dataset.ownerInstagramRawAction;
  const rawCard = button.closest("[data-owner-instagram-raw]");
  const contentCard = button.closest("[data-owner-instagram-content]");
  const target = rawCard?.querySelector("[data-owner-instagram-raw-target]");
  const contentId = Number(button.dataset.contentId || target?.value) || null;
  if (!api || !asset || !action) return;
  if (action === "associations") {
    await openOwnerInstagramAssociationManager(assetId, button);
    return;
  }
  if (["associate", "use-final"].includes(action) && !contentId) {
    byId("owner-instagram-status").textContent = "Selecciona primero un contenido destino.";
    target?.focus();
    return;
  }
  const mutationKeys = [`raw:${assetId}`];
  if (contentId) mutationKeys.push(`content:${contentId}`);
  if (!beginOwnerInstagramMutationGroup(mutationKeys)) return;
  const scope = contentCard || rawCard;
  const busyLabels = { preview: "Abriendo…", download: "Descargando…", associate: "Asociando…", disassociate: "Desasociando…", "create-content": "Preparando contenido…", "use-final": "Usando como final…" };
  if (scope) setOwnerInstagramScopeBusy(scope, true, button, busyLabels[action] || "Procesando…");
  try {
    if (action === "preview") {
      await openOwnerInstagramPreview(asset, button);
      byId("owner-instagram-status").textContent = "Previsualización abierta.";
    } else if (action === "download") {
      await downloadOwnerInstagramRawAsset(asset, button);
      byId("owner-instagram-status").textContent = "Descarga iniciada por el navegador.";
    } else {
      let url = `${api}/raw-assets/${assetId}/associations`;
      let options = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content_id: contentId }) };
      if (action === "disassociate") {
        url = `${api}/raw-assets/${assetId}/associations/${contentId}`;
        options = { method: "DELETE" };
      } else if (action === "create-content") {
        url = `${api}/raw-assets/${assetId}/create-content`;
        options = { method: "POST" };
      } else if (action === "use-final") {
        url = `${api}/raw-assets/${assetId}/use-as-final`;
      }
      const payload = await ownerInstagramJson(url, options);
      applyOwnerInstagramRawContentPayload(payload);
      const successMessages = { associate: "Material asociado al contenido.", disassociate: "Material desasociado.", "create-content": "Borrador preparado con el material de origen.", "use-final": "Asset final creado desde el material de origen." };
      byId("owner-instagram-status").textContent = successMessages[action] || "Material actualizado.";
    }
  } catch (error) {
    showOwnerInstagramError(error);
    if (error.status === 409 && contentId) await reconcileOwnerInstagramContent(api, contentId);
  } finally {
    if (scope?.isConnected) setOwnerInstagramScopeBusy(scope, false, button);
    endOwnerInstagramMutationGroup(mutationKeys);
  }
}

async function downloadOwnerInstagramPreviewAsset() {
  const asset = ownerInstagramRawAssets.find((item) => item.id === ownerInstagramPreviewAssetId);
  const button = byId("owner-instagram-preview-download");
  if (!asset || !beginOwnerInstagramMutation(`raw:${asset.id}`)) return;
  const original = button.textContent;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = "Descargando…";
  try {
    await downloadOwnerInstagramRawAsset(asset, button);
    byId("owner-instagram-status").textContent = "Descarga iniciada por el navegador.";
  } catch (error) {
    showOwnerInstagramError(error);
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = original;
    endOwnerInstagramMutation(`raw:${asset.id}`);
  }
}

let onboardingReadiness = null;

document.querySelectorAll("[data-tab]").forEach((tab) => tab.addEventListener("click", () => setActiveTab(tab.dataset.tab)));
byId("owner-instagram-business").addEventListener("change", () => {
  stopOwnerInstagramLifecyclePolling();
  if (ownerInstagramComposerState) closeOwnerInstagramComposer({ force: true });
  if (!byId("owner-instagram-library-dialog").hidden) closeOwnerInstagramLibrary();
  if (!byId("owner-instagram-associations-dialog").hidden) closeOwnerInstagramAssociationManager(false);
  ownerInstagramCalendarDate = instagramCivilDateKey();
  loadOwnerInstagramPanel();
});
byId("owner-instagram-refresh").addEventListener("click", loadOwnerInstagramPanel);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) scheduleOwnerInstagramLifecyclePolling();
});
byId("owner-instagram-enabled").addEventListener("change", updateOwnerInstagramService);
byId("owner-instagram-raw-form").addEventListener("submit", uploadOwnerInstagramRaw);
byId("owner-instagram-raw-list").addEventListener("click", (event) => {
  const actionButton = event.target.closest("[data-owner-instagram-raw-action]");
  if (actionButton) { handleOwnerInstagramRawAction(actionButton); return; }
  const button = event.target.closest("[data-owner-instagram-raw-delete]");
  if (button) deleteOwnerInstagramRaw(button);
});
byId("owner-instagram-create").addEventListener("click", (event) => openOwnerInstagramComposer({ trigger: event.currentTarget }));
byId("owner-instagram-enabled-area").addEventListener("click", (event) => {
  const create = event.target.closest("[data-owner-instagram-create-date]");
  if (create) {
    openOwnerInstagramComposer({ date: create.dataset.ownerInstagramCreateDate, trigger: create });
    return;
  }
  const open = event.target.closest("[data-owner-instagram-open]");
  if (open) {
    openOwnerInstagramContentDetail(Number(open.dataset.ownerInstagramOpen), { trigger: open });
    return;
  }
  const day = event.target.closest("[data-owner-instagram-day]");
  if (day) {
    ownerInstagramCalendarDate = day.dataset.ownerInstagramDay;
    ownerInstagramCalendarView = "today";
    loadOwnerInstagramCalendarPeriod();
  }
});
document.querySelectorAll("[data-owner-instagram-view]").forEach((button) => button.addEventListener("click", () => {
  ownerInstagramCalendarView = button.dataset.ownerInstagramView;
  loadOwnerInstagramCalendarPeriod();
}));
document.querySelectorAll("[data-owner-instagram-nav]").forEach((button) => button.addEventListener("click", () => shiftOwnerInstagramCalendar(Number(button.dataset.ownerInstagramNav))));
byId("owner-instagram-today").addEventListener("click", () => { ownerInstagramCalendarDate = instagramCivilDateKey(); loadOwnerInstagramCalendarPeriod(); });
byId("owner-instagram-state-filter").addEventListener("change", (event) => { ownerInstagramStateFilter = event.target.value; renderOwnerInstagramContents(); });
byId("owner-instagram-format-filter").addEventListener("change", (event) => { ownerInstagramFormatFilter = event.target.value; renderOwnerInstagramContents(); });
byId("owner-instagram-composer-close").addEventListener("click", () => closeOwnerInstagramComposer());
byId("owner-instagram-composer-add").addEventListener("click", () => byId("owner-instagram-composer-file").click());
byId("owner-instagram-composer-reuse").addEventListener("click", openOwnerInstagramLibrary);
byId("owner-instagram-composer-file").addEventListener("change", (event) => { ownerInstagramComposerAddFiles(event.target.files); event.target.value = ""; });
byId("owner-instagram-composer-form").addEventListener("change", (event) => {
  const state = ownerInstagramComposerState;
  if (!state) return;
  if (event.target.name === "composer_format") { ownerInstagramComposerChangeFormat(event.target.value); return; }
  if (event.target.name === "composer_publication") state.publication = event.target.value;
  if (event.target.id === "owner-instagram-composer-date") state.date = event.target.value;
  if (event.target.id === "owner-instagram-composer-time") state.time = event.target.value;
  state.dirty = true;
  renderOwnerInstagramComposer();
});
byId("owner-instagram-composer-caption").addEventListener("input", (event) => {
  if (!ownerInstagramComposerState) return;
  ownerInstagramComposerState.caption = event.target.value;
  ownerInstagramComposerState.dirty = true;
  byId("owner-instagram-caption-count").textContent = String(event.target.value.length);
  byId("owner-instagram-preview-caption").textContent = event.target.value.trim() || "Tu texto aparecerá aquí.";
});
byId("owner-instagram-story-editor").addEventListener("input", (event) => {
  const state = ownerInstagramComposerState;
  if (!state) return;
  if (event.target.name === "story_mode") state.storyTransform.mode = event.target.value;
  if (event.target.name === "story_background") state.storyTransform.background = event.target.value;
  if (event.target.id === "owner-instagram-story-zoom") state.storyTransform.zoom = Number(event.target.value);
  if (event.target.id === "owner-instagram-story-x") state.storyTransform.position_x = Number(event.target.value);
  if (event.target.id === "owner-instagram-story-y") state.storyTransform.position_y = Number(event.target.value);
  state.storyTransformDirty = true;
  state.dirty = true;
  renderOwnerInstagramComposer();
});
byId("owner-instagram-story-center").addEventListener("click", () => {
  const state = ownerInstagramComposerState;
  if (!state) return;
  state.storyTransform.position_x = 0.5;
  state.storyTransform.position_y = 0.5;
  state.storyTransformDirty = true;
  state.dirty = true;
  renderOwnerInstagramComposer();
});
byId("owner-instagram-story-reset").addEventListener("click", () => {
  const state = ownerInstagramComposerState;
  if (!state) return;
  state.storyTransform = { ...OWNER_INSTAGRAM_STORY_TRANSFORM_DEFAULT };
  state.storyTransformDirty = true;
  state.dirty = true;
  renderOwnerInstagramComposer();
});
byId("owner-instagram-composer-media").addEventListener("dragstart", (event) => {
  const card = event.target.closest("[data-media-uid]");
  if (!event.target.matches(".instagram-composer-media__drag") || event.target.disabled || !card || ownerInstagramComposerState?.format !== "carousel") return;
  event.dataTransfer.setData("text/plain", card.dataset.mediaUid);
  event.dataTransfer.effectAllowed = "move";
  card.classList.add("instagram-composer-media--dragging");
});
byId("owner-instagram-composer-media").addEventListener("dragend", (event) => event.target.closest("[data-media-uid]")?.classList.remove("instagram-composer-media--dragging"));
byId("owner-instagram-composer-media").addEventListener("dragover", (event) => { if (event.target.closest("[data-media-uid]")) event.preventDefault(); });
byId("owner-instagram-composer-media").addEventListener("drop", (event) => {
  const target = event.target.closest("[data-media-uid]");
  if (!target) return;
  event.preventDefault();
  ownerInstagramComposerDrop(event.dataTransfer.getData("text/plain"), target.dataset.mediaUid);
});
byId("owner-instagram-preview-carousel").addEventListener("click", (event) => {
  const button = event.target.closest("[data-owner-composer-preview]");
  const state = ownerInstagramComposerState;
  if (!button || !state?.media.length) return;
  const direction = button.dataset.ownerComposerPreview === "next" ? 1 : -1;
  state.previewIndex = (state.previewIndex + direction + state.media.length) % state.media.length;
  renderOwnerInstagramComposerPreview(state);
});
byId("owner-instagram-composer-save").addEventListener("click", saveOwnerInstagramComposerDraft);
byId("owner-instagram-composer-primary").addEventListener("click", publishOwnerInstagramComposer);
byId("owner-instagram-composer-cancel-content").addEventListener("click", cancelOwnerInstagramComposerContent);
byId("owner-instagram-composer").addEventListener("click", (event) => { if (event.target === event.currentTarget) closeOwnerInstagramComposer(); });
byId("owner-instagram-library-close").addEventListener("click", closeOwnerInstagramLibrary);
byId("owner-instagram-library-done").addEventListener("click", closeOwnerInstagramLibrary);
byId("owner-instagram-library-sync").addEventListener("click", ownerInstagramRefreshLibrary);
byId("owner-instagram-library-back").addEventListener("click", () => {
  if (!ownerInstagramLibraryState) return;
  ownerInstagramLibraryState.parent = null;
  renderOwnerInstagramLibrary();
});
byId("owner-instagram-library-dialog").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) { closeOwnerInstagramLibrary(); return; }
  const filter = event.target.closest("[data-instagram-library-filter]");
  if (filter && ownerInstagramLibraryState && !ownerInstagramLibraryState.loading) {
    ownerInstagramLibraryState.filter = filter.dataset.instagramLibraryFilter;
    ownerInstagramLibraryState.parent = null;
    ownerInstagramLoadLibrary({ preserve: false });
    return;
  }
  const use = event.target.closest("[data-instagram-library-use]");
  if (use && ownerInstagramLibraryState) {
    const item = ownerInstagramLibraryState.items.find((candidate) => candidate.id === Number(use.dataset.instagramLibraryUse));
    if (item?.media_type === "CAROUSEL_ALBUM") {
      ownerInstagramLibraryState.parent = item;
      renderOwnerInstagramLibrary();
    } else if (item) ownerInstagramUseRemoteMedia(item.id);
    return;
  }
  const child = event.target.closest("[data-instagram-library-child]");
  if (child) ownerInstagramUseRemoteMedia(Number(child.dataset.instagramLibraryChild));
});
byId("owner-instagram-preview-close").addEventListener("click", closeOwnerInstagramPreview);
byId("owner-instagram-preview-done").addEventListener("click", closeOwnerInstagramPreview);
byId("owner-instagram-preview-download").addEventListener("click", downloadOwnerInstagramPreviewAsset);
byId("owner-instagram-preview-dialog").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) closeOwnerInstagramPreview();
});
byId("owner-instagram-associations-close").addEventListener("click", () => closeOwnerInstagramAssociationManager());
byId("owner-instagram-associations-done").addEventListener("click", () => closeOwnerInstagramAssociationManager());
byId("owner-instagram-associations-delete").addEventListener("click", (event) => deleteOwnerInstagramRaw(event.currentTarget));
byId("owner-instagram-associations-remove-all").addEventListener("click", (event) => disassociateAllOwnerInstagramAssociations(event.currentTarget));
byId("owner-instagram-associations-list").addEventListener("click", (event) => {
  const remove = event.target.closest("[data-owner-instagram-association-remove]");
  if (remove) { disassociateOwnerInstagramAssociation(remove); return; }
  const open = event.target.closest("[data-owner-instagram-association-open]");
  if (open) openOwnerInstagramAssociatedContent(Number(open.dataset.ownerInstagramAssociationOpen));
});
document.addEventListener("keydown", (event) => {
  const libraryDialog = byId("owner-instagram-library-dialog");
  if (!libraryDialog.hidden) {
    if (event.key === "Escape" && !ownerInstagramLibraryState?.loading) closeOwnerInstagramLibrary();
    if (event.key === "Tab") {
      const focusable = Array.from(libraryDialog.querySelectorAll("button:not([disabled]):not([hidden]), [href], input:not([disabled]), [tabindex]:not([tabindex='-1'])")).filter((item) => item.offsetParent !== null);
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    return;
  }
  const composer = byId("owner-instagram-composer");
  if (!composer.hidden) {
    if (event.key === "Escape" && !ownerInstagramComposerState?.busy) closeOwnerInstagramComposer();
    if (event.key === "Tab") {
      const focusable = Array.from(composer.querySelectorAll("button:not([disabled]):not([hidden]), [href], input:not([disabled]):not([type='hidden']), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])")).filter((item) => item.offsetParent !== null);
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    return;
  }
  const associationDialog = byId("owner-instagram-associations-dialog");
  if (!associationDialog.hidden) {
    if (event.key === "Escape" && !ownerInstagramAssociationBusy) closeOwnerInstagramAssociationManager();
    if (event.key === "Tab") {
      const focusable = Array.from(associationDialog.querySelectorAll("button:not([disabled]):not([hidden]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])"));
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    return;
  }
  if (event.key === "Escape" && !byId("owner-instagram-preview-dialog").hidden) closeOwnerInstagramPreview();
});
byId("refresh-button").addEventListener("click", async () => {
  const button = byId("refresh-button");
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  try {
    await loadOwnerDashboard();
    const activeTab = document.querySelector("[data-tab].active")?.dataset.tab;
    if (activeTab === "businesses" && typeof loadOwnerBusinessAccessIndex === "function") await loadOwnerBusinessAccessIndex(true);
    if (activeTab === "new-business" && typeof loadOwnerOnboardingHub === "function") await loadOwnerOnboardingHub(true);
    if (activeTab === "integrations" && typeof loadOwnerIntegrationsHub === "function") await loadOwnerIntegrationsHub(true);
    if (activeTab === "instagram-content") await loadOwnerInstagramPanel();
    if (activeTab === "incidents") await loadIncidents();
    if (activeTab === "queues") await loadQueueStatus();
    if (activeTab === "operations" && typeof loadOwnerOperationsHub === "function") await loadOwnerOperationsHub(true);
    else if (activeTab === "operations") await loadOperationsStatus();
    if (activeTab === "audit" && typeof loadOwnerAuditHub === "function") await loadOwnerAuditHub(true);
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
});
byId("owner-overview").addEventListener("click", (event) => {
  const retry = event.target.closest("[data-owner-retry]");
  if (retry) {
    retry.disabled = true;
    retryOwnerDashboardSource(retry.dataset.ownerRetry).finally(() => { retry.disabled = false; });
    return;
  }
  const focus = event.target.closest("[data-owner-focus-block]");
  if (focus) {
    const block = byId(focus.dataset.ownerFocusBlock);
    block?.focus();
    block?.scrollIntoView({ block: "start" });
    return;
  }
  const navigation = event.target.closest("[data-owner-navigate]");
  if (navigation) navigateOwnerContext(navigation.dataset.ownerNavigate, navigation.dataset.ownerBusinessId, navigation.dataset.ownerDetail, navigation.dataset.ownerContextId);
});
byId("queue-refresh").addEventListener("click", loadQueueStatus);
byId("operations-refresh").addEventListener("click", () => {
  if (typeof loadOwnerOperationsHub === "function") loadOwnerOperationsHub(true);
  else loadOperationsStatus();
});
byId("maintenance-toggle").addEventListener("click", () => toggleMaintenance().catch((error) => { byId("operations-status").textContent = error.message; }));
byId("queue-business-filter").addEventListener("change", renderQueueStatus);
byId("queue-jobs").addEventListener("click", (event) => { const button = event.target.closest("[data-queue-action]"); if (button) updateQueueJob(button.dataset.jobType, button.dataset.jobId, button.dataset.queueAction).catch((error) => window.alert(error.message)); });
byId("incident-filters").addEventListener("submit", (event) => { event.preventDefault(); loadIncidents(); });
byId("incident-list").addEventListener("click", (event) => { const button = event.target.closest("[data-incident-action]"); if (button) updateIncident(button.dataset.incidentId, button.dataset.incidentAction, button).catch((error) => { byId("incidents-status").textContent = error.message; }); });
byId("add-service").addEventListener("click", addServiceRow);
byId("business-form").addEventListener("submit", createBusiness);
byId("businesses-section").addEventListener("click", (event) => {
  const button = event.target.closest("[data-business-state-id]");
  if (button) changeBusinessState(button.dataset.businessStateId, button.dataset.businessStatus, button);
  else if (event.target.closest("[data-owner-user-action]")) handleOwnerUserAction(event.target.closest("[data-owner-user-action]")).catch((error) => console.error("Business user action failed", error));
  else if (event.target.closest("[data-owner-channel-action]")) handleOwnerChannelControlAction(event.target.closest("[data-owner-channel-action]")).catch((error) => { const feedback = event.target.closest("[data-owner-channel-control-id]")?.querySelector("[data-owner-channel-feedback]"); if (feedback) feedback.textContent = error.message; });
  else if (event.target.closest("[data-owner-integration-action]")) handleOwnerIntegrationAction(event.target.closest("[data-owner-integration-action]")).catch((error) => { const feedback = event.target.closest("[data-owner-integration-id]")?.querySelector("[data-owner-integration-feedback]"); if (feedback) feedback.textContent = error.message; });
  else if (event.target.closest("[data-owner-automation-action]")) handleOwnerAutomationAction(event.target.closest("[data-owner-automation-action]")).catch((error) => { const feedback = event.target.closest("[data-owner-automation-id]")?.querySelector("[data-owner-automation-feedback]"); if (feedback) feedback.textContent = error.message; });
  else handleOwnerBrandClick(event).catch((error) => {
    console.error("Fallo gestionando marca en Owner", error);
    const feedback = event.target.closest("[data-owner-editor]")?.querySelector("[data-owner-feedback]");
    if (feedback) feedback.textContent = error.message || "No se pudo completar la acción.";
  });
});
byId("businesses-section").addEventListener("change", async (event) => {
  if (event.target.matches("[data-owner-media-input]")) {
    await uploadOwnerMedia(event.target);
    return;
  }
  const editor = event.target.closest("[data-owner-editor]"); if (!editor) return;
  if (event.target.matches("[data-owner-theme]")) { const colors = PALETTES[event.target.value]; if (colors) ["primary","secondary","accent","background"].forEach((name,index) => { editor.querySelector(`[data-owner-color="${name}"]`).value = colors[index]; editor.querySelector(`[data-owner-hex="${name}"]`).value = colors[index]; }); }
  if (event.target.matches("[data-owner-template]")) editor.querySelector("[data-owner-template-description]").textContent = templateDescription(event.target.value);
  if (event.target.matches("[data-owner-color]")) { const name = event.target.dataset.ownerColor; editor.querySelector(`[data-owner-hex="${name}"]`).value = event.target.value; editor.querySelector("[data-owner-theme]").value = "custom"; }
});
byId("businesses-section").addEventListener("input", (event) => {
  const editor = event.target.closest("[data-owner-editor]"); if (!editor) return;
  if (event.target.matches("[data-owner-color]")) { const name = event.target.dataset.ownerColor; editor.querySelector(`[data-owner-hex="${name}"]`).value = event.target.value; editor.querySelector("[data-owner-theme]").value = "custom"; }
  if (event.target.matches("[data-owner-hex]")) { const name = event.target.dataset.ownerHex; if (/^#[0-9a-f]{6}$/i.test(event.target.value)) editor.querySelector(`[data-owner-color="${name}"]`).value = event.target.value; editor.querySelector("[data-owner-theme]").value = "custom"; }
});
byId("business-type-template").addEventListener("change", (event) => applyBusinessTemplate(event.target.value));
byId("business-form").elements.template_key.addEventListener("change", (event) => { byId("owner-create-template-description").textContent = templateDescription(event.target.value); });
byId("owner-create-theme").addEventListener("change", (event) => applyCreationPalette(event.target.value));
byId("business-form").querySelectorAll('input[type="color"]').forEach((input) => input.addEventListener("input", () => { byId("owner-create-theme").value = "custom"; }));
byId("business-form").elements.name.addEventListener("input", (event) => {
  const slugInput = byId("business-form").elements.slug;
  if (!slugInput.dataset.manuallyEdited) slugInput.placeholder = slugify(event.target.value) || "Se genera automáticamente";
});
byId("business-form").elements.slug.addEventListener("input", (event) => { event.target.dataset.manuallyEdited = event.target.value ? "true" : ""; });

async function showOwnerLogin(message = "Inicia sesión con una cuenta autorizada.", denied = false) {
  byId("owner-app").hidden = true;
  byId("owner-auth-gate").hidden = false;
  byId("owner-auth-message").textContent = message;
  byId("owner-gate-logout").hidden = !denied;
  if (!denied) {
    await AutonoGrowAuth.renderGoogleButton(byId("owner-google-button"), bootstrapOwnerAuth, (error) => {
      byId("owner-auth-message").textContent = error.message;
    });
  } else {
    byId("owner-google-button").innerHTML = "";
  }
}

async function bootstrapOwnerAuth() {
  try {
    ownerAuthUser = await AutonoGrowAuth.getMe();
    if (!ownerAuthUser) return showOwnerLogin();
    if (!ownerAuthUser.is_owner) return showOwnerLogin("No tienes permiso para acceder al panel interno.", true);
    byId("owner-auth-gate").hidden = true;
    byId("owner-app").hidden = false;
    byId("owner-auth-user").textContent = ownerAuthUser.name || ownerAuthUser.email;
    renderOwnerDashboard();
    await loadOwnerDashboard({ announce: false });
    const oauthResult = new URLSearchParams(window.location.search).get("instagram_oauth");
    if (oauthResult) {
      byId("owner-sync-status").textContent = oauthResult === "pending_review" ? "Instagram autorizado; hay una candidatura pendiente de revisión." : "Instagram Login no se completó.";
      if (oauthResult === "pending_review") setActiveTab("overview");
    }
    if (typeof window.loadOwnerOnboardingTemplates === "function") await window.loadOwnerOnboardingTemplates();
  } catch (error) {
    console.error("Owner authentication failed", error);
    await showOwnerLogin(error.message);
  }
}

async function ownerLogout() {
  await AutonoGrowAuth.logout();
  ownerAuthUser = null;
  await showOwnerLogin();
}

byId("owner-logout").addEventListener("click", ownerLogout);
byId("owner-gate-logout").addEventListener("click", ownerLogout);
bootstrapOwnerAuth();
