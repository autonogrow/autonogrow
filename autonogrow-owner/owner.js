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

function slugify(value) {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
    .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function setActiveTab(name) {
  document.querySelectorAll("[data-tab]").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  document.querySelectorAll("[data-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === name));
  if (name === "incidents") loadIncidents();
  if (name === "queues") loadQueueStatus();
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
  return `<span class="health-badge ${healthy ? "healthy" : "missing"}">${label}${healthy ? "" : " pendiente"}</span>`;
}

function businessCard(business) {
  const slug = encodeURIComponent(business.slug);
  const health = business.health;
  const metrics = business.metrics;
  return `
    <article class="business-card">
      <div class="business-card-header">
        <div class="owner-brand-title">${business.logo_url ? `<img src="${escapeHtml(resolveMediaUrl(business.logo_url, true))}" alt="${escapeHtml(business.logo_alt || business.name)}">` : `<span>${escapeHtml((business.name || "?").slice(0,2).toUpperCase())}</span>`}<div><p class="business-category">${escapeHtml(business.category || "Sin categoría")}</p><h3>${escapeHtml(business.name)}</h3><p>${escapeHtml(business.city || "Sin ciudad")} · <code>${escapeHtml(business.slug)}</code></p></div></div>
        <span class="state-badge ${business.active ? "active" : "inactive"}">${business.active ? "Activo" : "Inactivo"}</span>
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
        <button class="button ${business.active ? "button-danger" : "button-primary"} button-small" type="button" data-toggle-slug="${escapeHtml(business.slug)}" data-next-active="${!business.active}">${business.active ? "Desactivar" : "Activar"}</button>
      </div>
      <details class="owner-brand-editor" data-owner-editor="${escapeHtml(business.slug)}"><summary>Marca y apariencia · ${escapeHtml(business.theme_key === "custom" ? "Personalizado" : (business.theme_key || "Sin paleta"))} · ${escapeHtml(business.template_key || "classic")}</summary>
        <div class="owner-brand-grid"><label>Paleta<select data-owner-theme>${paletteOptions(business.theme_key)}</select></label><label>Plantilla<select data-owner-template>${templateOptions(business.template_key)}</select></label><p class="wide helper" data-owner-template-description>${escapeHtml(templateDescription(business.template_key))}</p>${["primary","secondary","accent","background"].map((name, index) => `<label>${name}<span class="owner-color"><input type="color" data-owner-color="${name}" value="${escapeHtml(business[`${name}_color`] || PALETTES.slate_gold[index])}"><input data-owner-hex="${name}" value="${escapeHtml(business[`${name}_color`] || PALETTES.slate_gold[index])}"></span></label>`).join("")}<label>Alt logo<input data-owner-logo-alt value="${escapeHtml(business.logo_alt || "")}"></label></div>
        <div class="owner-upload-row"><input id="owner-logo-input-${escapeHtml(business.slug)}" type="file" accept="image/jpeg,image/png,image/webp" hidden data-owner-media-input="logo" data-slug="${escapeHtml(business.slug)}"><button type="button" class="button button-secondary button-small" data-action="select-logo">Subir logo</button><button type="button" class="button button-danger button-small" data-action="delete-logo">Eliminar logo</button></div>
        <div class="owner-upload-row"><input id="owner-gallery-input-${escapeHtml(business.slug)}" type="file" accept="image/jpeg,image/png,image/webp" hidden data-owner-media-input="gallery" data-slug="${escapeHtml(business.slug)}"><input data-owner-gallery-alt placeholder="Texto alternativo"><button type="button" class="button button-secondary button-small" data-action="select-gallery">Subir foto</button></div>
        <div class="owner-gallery" data-owner-gallery></div><button type="button" class="button button-primary button-small" data-owner-brand-save>Guardar apariencia</button><span data-owner-feedback></span>
      </details>
      <details class="owner-users-editor" data-owner-users="${escapeHtml(business.slug)}"><summary>Usuarios del negocio</summary>
        <div class="owner-user-form"><input data-owner-user-email type="email" placeholder="persona@negocio.com"><select data-owner-user-role><option value="business_admin">Administrador</option><option value="business_staff">Personal</option></select><button type="button" class="button button-primary button-small" data-owner-user-action="add">Añadir usuario</button></div>
        <div data-owner-users-list class="owner-users-list"><p>Cargando usuarios...</p></div><p data-owner-users-feedback class="status-text"></p>
      </details>
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
  document.querySelectorAll("[data-owner-integration-id]").forEach(loadOwnerIntegration);
  document.querySelectorAll("[data-owner-automation-id]").forEach(loadOwnerAutomation);
  restoreOwnerMediaStatus();
}

function ownerAutomationStatusLabel(status) {
  return ({ available: "Activo", near_limit: "Activo · cerca del límite", limit_reached: "Límite alcanzado", automation_paused: "Activo · automatización pausada", pending_renewal: "Pendiente de renovación", suspended: "Suspendido" })[status] || status;
}

function formatAutomationDate(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return new Intl.DateTimeFormat("es-ES", { dateStyle: "short", timeStyle: "short" }).format(parsed);
}

function ownerIntegrationStatusLabel(status) {
  return ({ pending: "Pendiente", connected: "Conectado", degraded: "Necesita revisión", expired: "Caducado", disconnected: "Desconectado", revoked: "Revocado", error: "Error" })[status] || status;
}

function ownerInstagramCredentialForm(mode) {
  return `<div class="owner-integration-form" data-owner-integration-form="${mode}">
    <label>Instagram Business Account ID<input data-integration-account-id maxlength="255" autocomplete="off" required></label>
    <label>Token de acceso<input data-integration-token type="password" maxlength="4096" autocomplete="new-password" required></label>
    <label>Caducidad opcional<input data-integration-expiration type="datetime-local"></label>
    <label>Motivo<input data-integration-reason maxlength="500" required></label>
    <p class="wide helper">El token se envía una sola vez y se almacena cifrado. No se mostrará de nuevo.</p>
    <button class="button button-primary button-small" type="button" data-owner-integration-action="${mode}">${mode === "connect" ? "Conectar" : "Reconectar"}</button>
  </div>`;
}

function renderOwnerIntegration(panel, integration) {
  const content = panel.querySelector("[data-owner-integration-content]");
  if (!integration) {
    content.innerHTML = `<article class="owner-integration-card"><h4>Instagram</h4><p>No conectado.</p>${ownerInstagramCredentialForm("connect")}<p data-owner-integration-feedback class="status-text"></p></article>`;
    return;
  }
  content.innerHTML = `<article class="owner-integration-card">
    <div class="owner-integration-heading"><h4>Instagram</h4><span class="state-badge ${integration.integration_status === "connected" ? "active" : "inactive"}">${escapeHtml(ownerIntegrationStatusLabel(integration.integration_status))}</span></div>
    <div class="owner-integration-summary"><span><strong>${escapeHtml(integration.external_account_id_masked || "—")}</strong>Cuenta</span><span><strong>${escapeHtml(integration.external_account_name || "—")}</strong>Nombre</span><span><strong>${escapeHtml(formatAutomationDate(integration.connected_at))}</strong>Conectado desde</span><span><strong>${escapeHtml(formatAutomationDate(integration.last_verified_at))}</strong>Última verificación</span><span><strong>${escapeHtml(formatAutomationDate(integration.last_success_at))}</strong>Último éxito</span><span><strong>${escapeHtml(formatAutomationDate(integration.token_expires_at))}</strong>Caducidad</span></div>
    ${integration.expires_soon ? `<p class="owner-integration-warning">El token caduca próximamente (${integration.days_remaining} días).</p>` : ""}
    ${integration.safe_error_message ? `<p class="owner-integration-warning">${escapeHtml(integration.safe_error_message)}</p>` : ""}
    ${integration.has_open_incident ? `<p class="owner-integration-warning">Existe una incidencia abierta para esta integración.</p>` : ""}
    <p>Scopes: <strong>${(integration.granted_scopes || []).map(escapeHtml).join(" · ") || "No disponibles"}</strong></p>
    <div class="owner-integration-actions"><button class="button button-secondary button-small" type="button" data-owner-integration-action="verify">Verificar conexión</button><button class="button button-secondary button-small" type="button" data-owner-integration-action="show-reconnect">Reconectar</button><button class="button button-danger button-small" type="button" data-owner-integration-action="disconnect">Desconectar</button><button class="button button-danger button-small" type="button" data-owner-integration-action="delete-credentials">Eliminar credenciales</button><button class="button button-secondary button-small" type="button" data-owner-integration-action="incidents">Ver incidencias</button></div>
    <div data-owner-integration-reconnect></div><p data-owner-integration-feedback class="status-text"></p>
  </article>`;
}

async function loadOwnerIntegration(panel) {
  const response = await fetch(`${API_BASE_URL}/api/owner/businesses/${panel.dataset.ownerIntegrationId}/integrations/instagram`);
  if (response.status === 404) { renderOwnerIntegration(panel, null); return; }
  const body = await readResponseBody(response);
  if (!response.ok) { panel.querySelector("[data-owner-integration-content]").innerHTML = `<p class="error-box">${escapeHtml(body.detail || "No se pudo cargar Instagram")}</p>`; return; }
  renderOwnerIntegration(panel, body);
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
    renderBusinesses();
  } catch (error) {
    byId("list-status").textContent = "Backend no disponible";
    byId("business-list").innerHTML = `<div class="error-box">${escapeHtml(error.message)}. Comprueba que el backend esté en ${API_BASE_URL}.</div>`;
  }
}

async function toggleBusiness(slug, active, button) {
  button.disabled = true;
  try {
    const response = await fetch(`${API_BASE_URL}/api/owner/businesses/${encodeURIComponent(slug)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ active })
    });
    if (!response.ok) throw new Error("No se pudo cambiar el estado");
    await loadBusinesses();
  } catch (error) {
    window.alert(error.message);
    button.disabled = false;
  }
}

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

document.querySelectorAll("[data-tab]").forEach((tab) => tab.addEventListener("click", () => setActiveTab(tab.dataset.tab)));
byId("refresh-button").addEventListener("click", async () => { await loadBusinesses(); await loadIncidents(); if (queueStatus) await loadQueueStatus(); });
byId("queue-refresh").addEventListener("click", loadQueueStatus);
byId("queue-business-filter").addEventListener("change", renderQueueStatus);
byId("queue-jobs").addEventListener("click", (event) => { const button = event.target.closest("[data-queue-action]"); if (button) updateQueueJob(button.dataset.jobType, button.dataset.jobId, button.dataset.queueAction).catch((error) => window.alert(error.message)); });
byId("incident-filters").addEventListener("submit", (event) => { event.preventDefault(); loadIncidents(); });
byId("incident-list").addEventListener("click", (event) => { const button = event.target.closest("[data-incident-action]"); if (button) updateIncident(button.dataset.incidentId, button.dataset.incidentAction, button).catch((error) => { byId("incidents-status").textContent = error.message; }); });
byId("add-service").addEventListener("click", addServiceRow);
byId("business-form").addEventListener("submit", createBusiness);
byId("business-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-toggle-slug]");
  if (button) toggleBusiness(button.dataset.toggleSlug, button.dataset.nextActive === "true", button);
  else if (event.target.closest("[data-owner-user-action]")) handleOwnerUserAction(event.target.closest("[data-owner-user-action]")).catch((error) => console.error("Business user action failed", error));
  else if (event.target.closest("[data-owner-integration-action]")) handleOwnerIntegrationAction(event.target.closest("[data-owner-integration-action]")).catch((error) => { const feedback = event.target.closest("[data-owner-integration-id]")?.querySelector("[data-owner-integration-feedback]"); if (feedback) feedback.textContent = error.message; });
  else if (event.target.closest("[data-owner-automation-action]")) handleOwnerAutomationAction(event.target.closest("[data-owner-automation-action]")).catch((error) => { const feedback = event.target.closest("[data-owner-automation-id]")?.querySelector("[data-owner-automation-feedback]"); if (feedback) feedback.textContent = error.message; });
  else handleOwnerBrandClick(event).catch((error) => {
    console.error("Fallo gestionando marca en Owner", error);
    const feedback = event.target.closest("[data-owner-editor]")?.querySelector("[data-owner-feedback]");
    if (feedback) feedback.textContent = error.message || "No se pudo completar la acción.";
  });
});
byId("business-list").addEventListener("change", async (event) => {
  if (event.target.matches("[data-owner-media-input]")) {
    await uploadOwnerMedia(event.target);
    return;
  }
  const editor = event.target.closest("[data-owner-editor]"); if (!editor) return;
  if (event.target.matches("[data-owner-theme]")) { const colors = PALETTES[event.target.value]; if (colors) ["primary","secondary","accent","background"].forEach((name,index) => { editor.querySelector(`[data-owner-color="${name}"]`).value = colors[index]; editor.querySelector(`[data-owner-hex="${name}"]`).value = colors[index]; }); }
  if (event.target.matches("[data-owner-template]")) editor.querySelector("[data-owner-template-description]").textContent = templateDescription(event.target.value);
  if (event.target.matches("[data-owner-color]")) { const name = event.target.dataset.ownerColor; editor.querySelector(`[data-owner-hex="${name}"]`).value = event.target.value; editor.querySelector("[data-owner-theme]").value = "custom"; }
});
byId("business-list").addEventListener("input", (event) => {
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
    await loadBusinesses();
    await loadIncidents();
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
