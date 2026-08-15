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
  return ({ draft: "Borrador", ready_for_review: "Listo para revisión", changes_requested: "Cambios solicitados", validated: "Validado", scheduled: "Programado", published: "Publicado", cancelled: "Cancelado" })[status] || status;
}

function ownerInstagramPublishingMode() {
  return ownerInstagramSettings?.publishing_mode === "meta" ? "real" : "simulado";
}

function ownerInstagramJobPanel(item) {
  const job = item.publish_jobs?.[0];
  if (!job) return item.status === "validated" ? `<div class="instagram-editorial-actions"><button class="button button-primary button-small" type="button" data-owner-instagram-action="publish-now" data-content-id="${item.id}">Publicar ahora (${ownerInstagramPublishingMode()})</button></div>` : `<p class="helper">Sin job de publicación.</p>`;
  const labels = { queued: "Programado", claimed: "En cola de ejecución", creating_container: "Creando contenedor", publishing: "Publicando en Instagram", simulating_publish: "Publicando (simulado)", published: "Publicado", retry_wait: "Reintento pendiente", failed: "Fallido", action_required: "Requiere acción", cancelled: "Cancelado" };
  const when = job.scheduled_for ? new Intl.DateTimeFormat("es-ES", { dateStyle: "short", timeStyle: "short", timeZone: item.business_timezone }).format(new Date(job.scheduled_for)) : "Sin fecha";
  const actions = ["validated", "scheduled"].includes(item.status) && !["published", "publishing", "creating_container", "simulating_publish", "claimed"].includes(job.status) ? `<button class="button button-primary button-small" type="button" data-owner-instagram-action="publish-now" data-content-id="${item.id}">Publicar ahora (${ownerInstagramPublishingMode()})</button>` : "";
  const cancel = ["queued", "retry_wait", "claimed"].includes(job.status) ? `<button class="button button-ghost button-small" type="button" data-owner-instagram-action="cancel-publish" data-content-id="${item.id}">Cancelar programación</button>` : "";
  const retry = ["failed", "action_required", "retry_wait"].includes(job.status) ? `<button class="button button-secondary button-small" type="button" data-owner-instagram-action="retry-publish" data-content-id="${item.id}">Reintentar</button>` : "";
  return `<section class="instagram-publish-job"><p><strong>${escapeHtml(labels[job.status] || job.status)}</strong> · ${escapeHtml(when)} · modo ${ownerInstagramPublishingMode()}</p><div class="instagram-editorial-actions">${actions}${cancel}${retry}</div>${job.provider_permalink ? `<p><a href="${escapeHtml(job.provider_permalink)}" target="_blank" rel="noopener noreferrer">Ver publicación en Instagram</a></p>` : ""}<details><summary>Detalle técnico</summary><dl><dt>Job</dt><dd>${job.id}</dd><dt>Versión</dt><dd>${job.content_version_id}</dd><dt>Intentos</dt><dd>${job.attempt_count}/${job.max_attempts}</dd>${job.provider_container_id ? `<dt>Contenedor</dt><dd>${escapeHtml(job.provider_container_id)}</dd>` : ""}${job.provider_media_id ? `<dt>Media ID</dt><dd>${escapeHtml(job.provider_media_id)}</dd>` : ""}${job.provider_error_code ? `<dt>Código</dt><dd>${escapeHtml(job.provider_error_code)}</dd>` : ""}${job.safe_error_message ? `<dt>Estado seguro</dt><dd>${escapeHtml(job.safe_error_message)}</dd>` : ""}</dl></details></section>`;
}

function ownerInstagramLocalInput(isoValue, timeZone) {
  if (!isoValue) return "";
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(isoValue)).map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

function renderOwnerInstagramRaw(assets) {
  byId("owner-instagram-raw-list").innerHTML = assets.length
    ? assets.map((asset) => `<a class="instagram-asset-chip" href="${API_BASE_URL}${escapeHtml(asset.file_url)}" target="_blank" rel="noopener">${escapeHtml(asset.label || asset.original_filename)}</a>`).join("")
    : `<p class="helper">Todavía no hay material bruto.</p>`;
}

function renderOwnerInstagramContents() {
  const container = byId("owner-instagram-content-list");
  const finalAccept = ownerInstagramSettings?.publishing_mode === "meta" ? "image/jpeg" : "image/jpeg,image/png,image/webp";
  if (!ownerInstagramContents.length) {
    container.innerHTML = `<p class="helper">Todavía no hay contenido final.</p>`;
    return;
  }
  container.innerHTML = ownerInstagramContents.map((item) => {
    const version = item.current_version;
    const selected = new Set(version.assets.map((asset) => asset.id));
    const cover = version.assets.find((asset) => asset.is_cover)?.id;
    const assets = item.final_assets.map((asset) => `<label class="instagram-asset-choice"><input type="checkbox" data-instagram-asset-id="${asset.id}" ${selected.has(asset.id) ? "checked" : ""}><span>${escapeHtml(asset.original_filename)}</span><input type="radio" name="cover-${item.id}" data-instagram-cover-id="${asset.id}" ${cover === asset.id ? "checked" : ""} aria-label="Usar como portada"></label>`).join("");
    const actions = ["draft", "changes_requested"].includes(item.status) ? `<button class="button button-secondary button-small" type="button" data-owner-instagram-action="submit" data-content-id="${item.id}">Enviar a revisión</button>` : item.status === "ready_for_review" ? `<button class="button button-primary button-small" type="button" data-owner-instagram-action="validate" data-content-id="${item.id}" data-version-id="${version.id}">Validar técnicamente</button>` : item.status === "validated" ? `<button class="button button-primary button-small" type="button" data-owner-instagram-action="schedule" data-content-id="${item.id}">Marcar programado</button>` : "";
    return `<article class="instagram-content-card" data-owner-instagram-content="${item.id}"><header><div><h4>${escapeHtml(item.title)}</h4><p>Versión ${version.version_number} · ${escapeHtml(ownerInstagramStateLabel(item.status))}</p></div><span class="ag-badge ag-badge--neutral">${escapeHtml(version.format === "carousel" ? "Carrusel" : "Imagen")}</span></header>${ownerInstagramSettings?.publishing_mode === "meta" && version.format !== "single_image" ? `<p class="error-box">El modo real de este sprint solo publica una imagen JPEG.</p>` : ""}<label>Caption<textarea data-instagram-caption maxlength="2200" rows="4">${escapeHtml(version.caption)}</textarea></label><label>Formato<select data-instagram-format><option value="single_image" ${version.format === "single_image" ? "selected" : ""}>Imagen única</option><option value="carousel" ${version.format === "carousel" ? "selected" : ""}>Carrusel</option></select></label><label>Fecha prevista (${escapeHtml(item.business_timezone)})<input data-instagram-date type="datetime-local" value="${escapeHtml(ownerInstagramLocalInput(item.planned_publish_at, item.business_timezone))}"></label><form data-owner-final-upload><label>Subir asset final<input name="file" type="file" accept="${finalAccept}" required></label><button class="button button-secondary button-small" type="submit">Subir final</button></form><div class="instagram-asset-choices">${assets || "<p class='helper'>Sube al menos un asset final.</p>"}</div><div class="instagram-editorial-actions"><button class="button button-secondary button-small" type="button" data-owner-instagram-action="save-material" data-content-id="${item.id}">Guardar nueva versión</button><button class="button button-secondary button-small" type="button" data-owner-instagram-action="save-date" data-content-id="${item.id}">Guardar fecha</button>${actions}${item.status !== "cancelled" ? `<button class="button button-ghost button-small" type="button" data-owner-instagram-action="cancel" data-content-id="${item.id}">Cancelar</button>` : ""}</div>${ownerInstagramJobPanel(item)}${item.comments.length ? `<ul class="instagram-comments">${item.comments.map((comment) => `<li><strong>${escapeHtml(comment.kind)}</strong> · v${escapeHtml(item.versions.find((candidate) => candidate.id === comment.version_id)?.version_number || "?")}<p>${escapeHtml(comment.body)}</p></li>`).join("")}</ul>` : ""}</article>`;
  }).join("");
}

async function ownerInstagramJson(url, options = {}) {
  const response = await fetch(url, options);
  const body = await readResponseBody(response);
  if (!response.ok) throw new Error(body.detail || "No se pudo completar la operación editorial.");
  return body;
}

async function loadOwnerInstagramPanel() {
  const status = byId("owner-instagram-status");
  if (!businesses.length) await loadBusinesses();
  renderOwnerInstagramBusinessOptions();
  const api = ownerInstagramApi();
  byId("owner-instagram-workspace").hidden = !api;
  if (!api) { status.textContent = "Selecciona un negocio."; return; }
  status.textContent = "Cargando flujo editorial…";
  try {
    ownerInstagramSettings = await ownerInstagramJson(`${api}/settings`);
    byId("owner-instagram-enabled").checked = ownerInstagramSettings.enabled;
    byId("owner-instagram-enabled-area").hidden = !ownerInstagramSettings.enabled;
    if (!ownerInstagramSettings.enabled) { status.textContent = "Servicio desactivado."; return; }
    const [raw, contentList] = await Promise.all([
      ownerInstagramJson(`${api}/raw-assets`),
      ownerInstagramJson(`${api}/contents`)
    ]);
    ownerInstagramContents = await Promise.all(contentList.contents.map((item) => ownerInstagramJson(`${api}/contents/${item.id}`)));
    renderOwnerInstagramRaw(raw.assets);
    renderOwnerInstagramContents();
    status.textContent = `${ownerInstagramContents.length} contenidos · ${raw.assets.length} materiales brutos · publicación ${ownerInstagramPublishingMode()}`;
  } catch (error) {
    status.textContent = error.message;
  }
}

async function updateOwnerInstagramService() {
  const api = ownerInstagramApi();
  if (!api) return;
  const enabled = byId("owner-instagram-enabled").checked;
  try {
    await ownerInstagramJson(`${api}/settings`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }) });
    await loadOwnerInstagramPanel();
  } catch (error) {
    byId("owner-instagram-enabled").checked = !enabled;
    byId("owner-instagram-status").textContent = error.message;
  }
}

async function uploadOwnerInstagramRaw(event) {
  event.preventDefault();
  const api = ownerInstagramApi();
  if (!api) return;
  try {
    await ownerInstagramJson(`${api}/raw-assets`, { method: "POST", body: new FormData(event.currentTarget) });
    event.currentTarget.reset();
    await loadOwnerInstagramPanel();
  } catch (error) { byId("owner-instagram-status").textContent = error.message; }
}

async function createOwnerInstagramContent(event) {
  event.preventDefault();
  const api = ownerInstagramApi();
  const data = new FormData(event.currentTarget);
  if (!api) return;
  try {
    await ownerInstagramJson(`${api}/contents`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: data.get("title"), caption: data.get("caption"), format: data.get("format"), planned_publish_at: data.get("planned_publish_at") || null }) });
    event.currentTarget.reset();
    await loadOwnerInstagramPanel();
  } catch (error) { byId("owner-instagram-status").textContent = error.message; }
}

async function handleOwnerInstagramAction(button) {
  const api = ownerInstagramApi();
  const contentId = Number(button.dataset.contentId);
  const card = button.closest("[data-owner-instagram-content]");
  if (!api || !contentId || !card) return;
  const action = button.dataset.ownerInstagramAction;
  let url = `${api}/contents/${contentId}/${action}`;
  let options = { method: "POST" };
  if (action === "save-material") {
    const assetIds = [...card.querySelectorAll("[data-instagram-asset-id]:checked")].map((input) => Number(input.dataset.instagramAssetId));
    const cover = card.querySelector("[data-instagram-cover-id]:checked");
    url = `${api}/contents/${contentId}/material`;
    options = { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ caption: card.querySelector("[data-instagram-caption]").value, format: card.querySelector("[data-instagram-format]").value, asset_ids: assetIds, cover_asset_id: cover ? Number(cover.dataset.instagramCoverId) : null }) };
  } else if (action === "save-date") {
    const value = card.querySelector("[data-instagram-date]").value;
    url = `${api}/contents/${contentId}/planned-date`;
    options = { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ planned_publish_at: value || null }) };
  } else if (action === "submit") url = `${api}/contents/${contentId}/submit-for-review`;
  else if (action === "publish-now") url = `${api}/contents/${contentId}/publish-now`;
  else if (action === "cancel-publish") url = `${api}/contents/${contentId}/publish-job/cancel`;
  else if (action === "retry-publish") url = `${api}/contents/${contentId}/publish-job/retry`;
  else if (action === "validate") options = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version_id: Number(button.dataset.versionId) }) };
  try {
    button.disabled = true;
    await ownerInstagramJson(url, options);
    await loadOwnerInstagramPanel();
  } catch (error) { byId("owner-instagram-status").textContent = error.message; }
  finally { button.disabled = false; }
}

async function uploadOwnerInstagramFinal(event) {
  event.preventDefault();
  const api = ownerInstagramApi();
  const card = event.currentTarget.closest("[data-owner-instagram-content]");
  if (!api || !card) return;
  try {
    await ownerInstagramJson(`${api}/contents/${card.dataset.ownerInstagramContent}/final-assets`, { method: "POST", body: new FormData(event.currentTarget) });
    await loadOwnerInstagramPanel();
  } catch (error) { byId("owner-instagram-status").textContent = error.message; }
}

let onboardingReadiness = null;

document.querySelectorAll("[data-tab]").forEach((tab) => tab.addEventListener("click", () => setActiveTab(tab.dataset.tab)));
byId("owner-instagram-business").addEventListener("change", loadOwnerInstagramPanel);
byId("owner-instagram-refresh").addEventListener("click", loadOwnerInstagramPanel);
byId("owner-instagram-enabled").addEventListener("change", updateOwnerInstagramService);
byId("owner-instagram-raw-form").addEventListener("submit", uploadOwnerInstagramRaw);
byId("owner-instagram-create-form").addEventListener("submit", createOwnerInstagramContent);
byId("owner-instagram-content-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-owner-instagram-action]");
  if (button) handleOwnerInstagramAction(button);
});
byId("owner-instagram-content-list").addEventListener("submit", (event) => {
  if (event.target.matches("[data-owner-final-upload]")) uploadOwnerInstagramFinal(event);
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
