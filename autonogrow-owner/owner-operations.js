"use strict";

/* Sprint 5C.3: integraciones, incidencias, operaciones y actividad operativa. */
const OWNER_INTEGRATION_HEALTH_LABELS = {
  unknown: "Aún no comprobada",
  healthy: "Operativa",
  warning: "Funciona con avisos",
  degraded: "Funciona con problemas",
  action_required: "Requiere intervención",
  revoked: "Acceso revocado",
  suspended: "Suspendida",
  error: "No se pudo comprobar",
};
const OWNER_QUEUE_STATUS_LABELS = {
  pending: "Pendiente",
  queued: "Pendiente",
  processing: "En curso",
  retry: "Reintento programado",
  blocked: "Bloqueado",
  failed: "Fallido",
  dead_letter: "Reintentos agotados",
  completed: "Completado",
  processed: "Procesado",
  sent: "Enviado",
  cancelled: "Cancelado",
};
const OWNER_META_JOB_LABELS = {
  health_check: "Comprobación de salud",
  retry_subscription: "Reintento de suscripción",
  attempt_cleanup: "Limpieza de intentos caducados",
};
const ownerOperationsState = {
  integrationQuery: "",
  integrationFilter: "all",
  selectedIntegration: null,
  integrationDetailView: "summary",
  operationsView: "messages",
  incidentQuery: "",
  incidentOrigin: "",
  selectedIncidentId: null,
  metaJobs: [],
  metaJobErrors: 0,
  maintenance: null,
  sourceState: { queue: "idle", platform: "idle", jobs: "idle", maintenance: "idle" },
  healthChecks: new Map(),
  operationsInFlight: null,
  integrationsInFlight: null,
};

function ownerOperationalDate(value) {
  if (!value) return "Sin dato";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Sin dato";
  return new Intl.DateTimeFormat("es-ES", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function ownerBusinessById(businessId) {
  return businesses.find((business) => String(business.id) === String(businessId)) || null;
}

function ownerIntegrationHealthLabel(status) {
  return OWNER_INTEGRATION_HEALTH_LABELS[status] || "Aún no comprobada";
}

function ownerIntegrationRecords() {
  const records = [];
  (ownerDashboardState.channels.data || []).forEach((snapshot) => {
    const business = ownerBusinessById(snapshot.business.id) || snapshot.business;
    (snapshot.controls || []).forEach((control) => {
      const health = (snapshot.health || []).find((item) => item.channel === control.channel) || null;
      const candidates = control.channel === "instagram" ? snapshot.instagramCandidates || [] : snapshot.whatsappCandidates || [];
      const candidateName = candidates[0]
        ? control.channel === "instagram"
          ? candidates[0].candidate_external_account_name
          : candidates[0].candidate_verified_name || candidates[0].candidate_display_phone_number_redacted
        : null;
      const publicAccount = control.channel === "instagram"
        ? candidateName || "Nombre público no disponible"
        : health?.display_phone_number_redacted || candidateName || "Teléfono redactado no disponible";
      records.push({ business, snapshot, control, health, candidates, publicAccount });
    });
  });
  return records;
}

function ownerIntegrationIsActive(record) {
  return Boolean(record.health && ["connected", "degraded"].includes(record.health.integration_status));
}

function ownerIntegrationHasProblem(record) {
  return Boolean(
    record.candidates.length
    || ["suspended", "revoked"].includes(record.control.status)
    || record.health?.reconnection_required
    || ["warning", "degraded", "action_required", "revoked", "suspended", "error"].includes(record.health?.health_status)
  );
}

function ownerIntegrationRecommendation(record) {
  if (record.candidates.length) return "Revisar candidatura en Altas y aprobaciones";
  if (record.health?.reconnection_required) return "Iniciar una reconexión segura";
  if (record.health?.subscription_status === "missing") return "Reintentar la suscripción";
  if (["suspended", "revoked"].includes(record.control.status)) return "Revisar el control comercial";
  if (!ownerIntegrationIsActive(record)) return "Completar la conexión técnica";
  if (!record.control.integrated_delivery_enabled) return "Envío integrado desactivado";
  if (!record.control.automation_enabled) return "Automatización desactivada";
  return "Sin acciones prioritarias";
}

function ownerIntegrationHealthCheckKey(record) {
  return `${record.business.id}:${record.control.channel}`;
}

function ownerIntegrationHealthDiagnosis(record) {
  const code = String(record.health?.safe_error_code || "").toLowerCase();
  if (record.health?.reconnection_required || ["token_expired", "token_revoked", "integration_expired", "integration_revoked"].includes(code)) {
    return "La autorización ya no permite comprobar todas las funciones. Vuelve a conectar la cuenta.";
  }
  if (code.includes("permission") || code.includes("scope")) return "La conexión no dispone de todos los permisos necesarios. Es necesario volver a autorizarla.";
  if (record.health?.subscription_status === "missing") return "La suscripción del canal no está activa y debe reintentarse.";
  if (["account_suspended", "suspended"].includes(code) || record.health?.health_status === "suspended") return "La cuenta está suspendida y no puede operar hasta resolver su estado.";
  if (record.health?.health_status === "healthy") return "La conexión y sus capacidades comprobadas funcionan correctamente.";
  if (record.health?.safe_error_message) return record.health.safe_error_message;
  if (["warning", "degraded"].includes(record.health?.health_status)) return "Algunas funciones pueden no estar disponibles temporalmente.";
  if (["action_required", "revoked", "error"].includes(record.health?.health_status)) return "La conexión necesita una revisión antes de continuar.";
  return "Todavía no existe un resultado de comprobación.";
}

function ownerIntegrationHealthActions(record) {
  if (record.health?.reconnection_required && record.control.channel === "instagram") return '<button class="button button-primary button-small" type="button" data-owner-integration-reconnect>Reconectar Instagram</button>';
  if (record.health?.reconnection_required && record.control.channel === "whatsapp") return `<a class="button button-primary button-small" href="../autonogrow-admin/index.html?b=${encodeURIComponent(record.business.slug)}#channels" target="_blank" rel="noopener">Abrir reconexión en Admin</a>`;
  if (record.health?.subscription_status === "missing") return '<button class="button button-secondary button-small" type="button" data-owner-integration-retry-subscription>Reintentar suscripción</button>';
  return record.health?.next_health_check_at ? '<p class="helper">AutonoGrow volverá a comprobarlo automáticamente.</p>' : "";
}

function ownerIntegrationHealthFeedback(record) {
  const check = ownerOperationsState.healthChecks.get(ownerIntegrationHealthCheckKey(record));
  if (!check) return "";
  if (check.phase === "checking") return "Comprobando la conexión con el estado real del backend…";
  if (check.phase === "error") return "No hemos podido comprobar la conexión. Se conserva el último estado conocido.";
  if (check.previousStatus !== "healthy" && record.health?.health_status === "healthy") return "Conexión funcionando correctamente. La comprobación acaba de completarse.";
  if (record.health?.health_status === check.previousStatus && record.health?.health_status !== "healthy") return "Comprobación completada. El problema continúa.";
  if (record.health?.health_status === "healthy") return "Comprobación completada. La conexión sigue funcionando correctamente.";
  return "Comprobación completada. El estado mostrado está actualizado.";
}

function ownerIntegrationFilterMatches(record) {
  const filter = ownerOperationsState.integrationFilter;
  if (filter === "instagram" || filter === "whatsapp") return record.control.channel === filter;
  if (filter === "pending") return record.candidates.length > 0 || record.control.status === "pending_approval";
  if (filter === "problems") return ownerIntegrationHasProblem(record);
  if (filter === "reconnect") return Boolean(record.health?.reconnection_required);
  if (filter === "suspended") return record.control.status === "suspended" || record.health?.health_status === "suspended";
  if (filter === "revoked") return record.control.status === "revoked" || record.health?.health_status === "revoked";
  return true;
}

function ownerFilteredIntegrations() {
  const query = ownerNormalizeSearch(ownerOperationsState.integrationQuery);
  return ownerIntegrationRecords().filter((record) => {
    if (!ownerIntegrationFilterMatches(record)) return false;
    const searchable = ownerNormalizeSearch([record.business.name, record.business.slug, record.publicAccount].filter(Boolean).join(" "));
    return !query || searchable.includes(query);
  }).sort((left, right) => Number(ownerIntegrationHasProblem(right)) - Number(ownerIntegrationHasProblem(left))
    || String(left.business.name).localeCompare(String(right.business.name), "es")
    || String(left.control.channel).localeCompare(String(right.control.channel)));
}

function renderOwnerIntegrationsSummary() {
  const target = byId("owner-integrations-summary");
  if (!target) return;
  if (ownerDashboardState.channels.status === "error") {
    target.setAttribute("aria-busy", "false");
    target.innerHTML = '<div class="error-box"><strong>Resumen no disponible</strong><p>No se convierten fuentes fallidas en indicadores a cero.</p></div>';
    return;
  }
  const records = ownerIntegrationRecords();
  const metrics = [
    ["Integraciones activas", records.filter(ownerIntegrationIsActive).length],
    ["Pendientes de revisión", records.filter((record) => record.candidates.length || record.control.status === "pending_approval").length],
    ["Necesitan reconexión", records.filter((record) => record.health?.reconnection_required).length],
    ["Salud degradada", records.filter((record) => ["warning", "degraded", "action_required", "error"].includes(record.health?.health_status)).length],
    ["Envío habilitado", records.filter((record) => record.control.integrated_delivery_enabled).length],
    ["Automatización habilitada", records.filter((record) => record.control.automation_enabled).length],
  ];
  target.setAttribute("aria-busy", "false");
  target.innerHTML = metrics.map(([label, value]) => `<article><span>${escapeHtml(label)}</span><strong>${value}</strong></article>`).join("");
}

function ownerIntegrationRow(record) {
  const channel = record.control.channel === "instagram" ? "Instagram" : "WhatsApp";
  const active = ownerIntegrationIsActive(record);
  const health = ownerIntegrationHealthLabel(record.health?.health_status);
  return `<article class="owner-integration-row${ownerIntegrationHasProblem(record) ? " needs-attention" : ""}" role="listitem">
    <div class="owner-integration-row__identity"><span class="owner-channel-mark" aria-hidden="true">${channel.slice(0, 2)}</span><div><h3>${escapeHtml(record.business.name)}</h3><p>${channel} · ${escapeHtml(record.publicAccount)}</p></div></div>
    <div class="owner-integration-states"><p><strong>Disponibilidad</strong>${escapeHtml(ownerChannelControlStatusLabel(record.control.status))}</p><p><strong>Integración activa</strong>${active ? "Sí" : "No"}</p><p><strong>Aprobación</strong>${record.control.status === "approved" ? "Aprobada" : record.control.status === "pending_approval" ? "Pendiente" : "No aprobada"}</p><p><strong>Envío</strong>${record.control.integrated_delivery_enabled ? "Activado" : "Desactivado"}</p><p><strong>Automatización</strong>${record.control.automation_enabled ? "Activada" : "Desactivada"}</p><p><strong>Salud</strong>${escapeHtml(health)}</p></div>
    <div class="owner-integration-row__status"><p>${escapeHtml(ownerIntegrationRecommendation(record))}</p><small>Última comprobación: ${escapeHtml(ownerOperationalDate(record.health?.last_health_check_at))}</small></div>
    <div class="owner-integration-row__actions"><button class="button button-primary button-small" type="button" data-owner-integration-open data-business-id="${escapeHtml(record.business.id)}" data-channel="${record.control.channel}">Abrir integración</button>${record.candidates.length ? `<button class="button button-secondary button-small" type="button" data-owner-integration-candidate data-business-id="${escapeHtml(record.business.id)}" data-channel="${record.control.channel}">Revisar candidatura</button>` : ""}</div>
  </article>`;
}

function renderOwnerIntegrationsList() {
  const target = byId("owner-integrations-list");
  if (!target) return;
  const records = ownerFilteredIntegrations();
  const channelSource = ownerDashboardState.channels;
  target.setAttribute("aria-busy", "false");
  if (channelSource.status === "error") {
    target.innerHTML = '<div class="error-box"><strong>No se pudieron comprobar las integraciones</strong><p>No se presenta la fuente fallida como una lista vacía.</p></div>';
  } else {
    const partial = channelSource.errors ? `<p class="owner-partial-notice">${channelSource.errors} negocio${channelSource.errors === 1 ? "" : "s"} tiene fuentes parciales; los canales disponibles se conservan.</p>` : "";
    target.innerHTML = partial + (records.length ? records.map(ownerIntegrationRow).join("") : '<div class="empty-state"><strong>Sin coincidencias</strong><p>Ajusta la búsqueda o el filtro. Esto no afirma que una fuente fallida esté vacía.</p></div>');
  }
  byId("owner-integrations-status").textContent = `${records.length} integración${records.length === 1 ? "" : "es"} visible${records.length === 1 ? "" : "s"}`;
  renderOwnerIntegrationsSummary();
}

function ownerIntegrationDetailNav() {
  return [["summary", "Resumen"], ["control", "Control comercial"], ["capabilities", "Capacidades"], ["health", "Salud"], ["recovery", "Recuperación"], ["candidates", "Candidaturas"], ["activity", "Actividad"]]
    .map(([key, label]) => `<button type="button" data-owner-integration-tab="${key}"${ownerOperationsState.integrationDetailView === key ? ' class="active" aria-current="page"' : ""}>${label}</button>`).join("");
}

function ownerIntegrationControlActions(record) {
  const control = record.control;
  const candidatePending = record.candidates.length > 0;
  const allow = ["not_allowed", "suspended", "revoked"].includes(control.status)
    ? `<label>Quién puede conectar<select data-owner-connector-policy><option value="business_admin"${control.connector_policy !== "owner_only" ? " selected" : ""}>Administrador del negocio</option><option value="owner_only"${control.connector_policy === "owner_only" ? " selected" : ""}>Solo Owner</option></select></label><button class="button button-primary" type="button" data-owner-integration-control="grant">Permitir disponibilidad</button>` : "";
  const approve = control.status === "pending_approval" && !candidatePending && control.connection_mode === "simulated"
    ? '<button class="button button-primary" type="button" data-owner-integration-control="approve">Aprobar control</button>' : "";
  const stop = !["not_allowed", "revoked"].includes(control.status)
    ? '<button class="button button-danger" type="button" data-owner-integration-control="suspend">Suspender</button><button class="button button-danger" type="button" data-owner-integration-control="revoke">Revocar</button>' : "";
  return `<div class="owner-operation-actions">${allow}${approve}${stop}</div>`;
}

function ownerCapabilityState(record, key) {
  if (record.control.status !== "approved") return "Bloqueada: canal no aprobado";
  if (!ownerIntegrationIsActive(record)) return "Bloqueada: integración no activa";
  if (["revoked", "suspended", "error"].includes(record.health?.health_status)) return "Bloqueada por salud";
  return record.control[key] ? "Activada" : "Desactivada";
}

function ownerIntegrationDetailMarkup(record) {
  const channel = record.control.channel === "instagram" ? "Instagram" : "WhatsApp";
  const active = ownerIntegrationIsActive(record);
  const canChangeCapabilities = record.control.status === "approved" && active && !["revoked", "suspended", "error"].includes(record.health?.health_status);
  const jobs = ownerOperationsState.metaJobs.filter((entry) => String(entry.businessId) === String(record.business.id) && (!entry.channel || entry.channel === record.control.channel));
  const subscriptionJobActive = jobs.some((entry) => entry.job.job_type === "retry_subscription" && ["queued", "processing", "retry"].includes(entry.job.status));
  const healthCheck = ownerOperationsState.healthChecks.get(ownerIntegrationHealthCheckKey(record));
  const healthChecking = healthCheck?.phase === "checking";
  const healthButtonLabel = healthChecking ? "⟳ Comprobando..." : healthCheck?.phase === "error" ? "Reintentar" : "Comprobar ahora";
  return `<header class="owner-integration-detail__header"><div><p class="eyebrow">Detalle de integración</p><h2 id="owner-integration-detail-title">${channel} · ${escapeHtml(record.business.name)}</h2></div><button class="button button-secondary button-small" type="button" data-owner-integration-close>Volver a la lista</button></header><nav class="owner-secondary-nav" aria-label="Detalle de integración">${ownerIntegrationDetailNav()}</nav>
    <section data-owner-integration-panel="summary"><div class="owner-integration-detail-grid"><p><strong>Negocio</strong>${escapeHtml(record.business.name)}</p><p><strong>Canal</strong>${channel}</p><p><strong>Cuenta pública</strong>${escapeHtml(record.publicAccount)}</p><p><strong>Integración activa</strong>${active ? "Sí" : "No"}</p><p><strong>Aprobación</strong>${record.control.status === "approved" ? "Aprobada" : "No aprobada"}</p><p><strong>Salud</strong>${escapeHtml(ownerIntegrationHealthLabel(record.health?.health_status))}</p><p><strong>Última comprobación</strong>${escapeHtml(ownerOperationalDate(record.health?.last_health_check_at))}</p><p><strong>Recomendación</strong>${escapeHtml(ownerIntegrationRecommendation(record))}</p></div><div class="owner-operation-actions"><button class="button button-secondary" type="button" data-owner-integration-business>Abrir negocio</button><button class="button button-secondary" type="button" data-owner-integration-incidents>Ver incidencias asociadas</button></div></section>
    <section data-owner-integration-panel="control" hidden><h3>Control comercial</h3><p>La disponibilidad y aprobación no describen la salud técnica.</p><div class="owner-integration-detail-grid"><p><strong>Disponibilidad</strong>${escapeHtml(ownerChannelControlStatusLabel(record.control.status))}</p><p><strong>Solicitud del negocio</strong>${record.control.requested_at ? `Recibida ${escapeHtml(ownerOperationalDate(record.control.requested_at))}` : "Sin solicitud"}</p><p><strong>Aprobación Owner</strong>${record.control.approved_at ? `Aprobada ${escapeHtml(ownerOperationalDate(record.control.approved_at))}` : "No aprobada"}</p></div>${ownerIntegrationControlActions(record)}</section>
    <section data-owner-integration-panel="capabilities" hidden><h3>Capacidades</h3><p>Conectar no aprueba; aprobar no activa capacidades. El modo asistido pertenece al flujo conversacional y no tiene un control Owner independiente en este contrato.</p><div class="owner-capability-grid"><label><span>Envío integrado</span><small>${escapeHtml(ownerCapabilityState(record, "integrated_delivery_enabled"))}</small><input type="checkbox" data-owner-capability="delivery" ${record.control.integrated_delivery_enabled ? "checked" : ""} ${canChangeCapabilities ? "" : "disabled"}></label><label><span>Automatización</span><small>${escapeHtml(ownerCapabilityState(record, "automation_enabled"))}</small><input type="checkbox" data-owner-capability="automation" ${record.control.automation_enabled ? "checked" : ""} ${canChangeCapabilities ? "" : "disabled"}></label><p><strong>Modo asistido</strong>Sin interruptor Owner en el backend actual</p></div><button class="button button-primary" type="button" data-owner-integration-capabilities ${canChangeCapabilities ? "" : "disabled"}>Guardar capacidades</button></section>
    <section data-owner-integration-panel="health" hidden aria-busy="${healthChecking}"><h3>Salud de la conexión</h3><div class="owner-integration-detail-grid"><p><strong>Estado</strong>${escapeHtml(ownerIntegrationHealthLabel(record.health?.health_status))}</p><p><strong>Última comprobación</strong>${escapeHtml(ownerOperationalDate(record.health?.last_health_check_at))}</p><p><strong>Próxima comprobación</strong>${escapeHtml(ownerOperationalDate(record.health?.next_health_check_at))}</p><p><strong>Reconexión</strong>${record.health?.reconnection_required ? "Requerida" : "No requerida"}</p><p><strong>Qué ocurre</strong>${escapeHtml(ownerIntegrationHealthDiagnosis(record))}</p><p><strong>Acción recomendada</strong>${escapeHtml(ownerIntegrationRecommendation(record))}</p></div><div class="owner-operation-actions"><button class="button button-secondary" type="button" data-owner-integration-health-check ${healthChecking ? "disabled" : ""}>${healthButtonLabel}</button>${ownerIntegrationHealthActions(record)}</div><p data-owner-integration-health-feedback class="status-text" role="status">${escapeHtml(ownerIntegrationHealthFeedback(record))}</p></section>
    <section data-owner-integration-panel="recovery" hidden><h3>Recuperación</h3><p>Las acciones crean trabajos idempotentes o una nueva conexión. No solicitan credenciales ni sustituyen la integración antes de su revisión.</p><div class="owner-operation-actions">${record.health?.reconnection_required && record.control.channel === "instagram" ? '<button class="button button-primary" type="button" data-owner-integration-reconnect>Solicitar reconexión</button>' : ""}${record.health?.reconnection_required && record.control.channel === "whatsapp" ? `<a class="button button-primary" href="../autonogrow-admin/index.html?b=${encodeURIComponent(record.business.slug)}#channels" target="_blank" rel="noopener">Abrir reconexión en Admin</a>` : ""}${record.health?.subscription_status === "missing" && !subscriptionJobActive ? '<button class="button button-secondary" type="button" data-owner-integration-retry-subscription>Reintentar suscripción</button>' : ""}${record.candidates.length ? '<button class="button button-secondary" type="button" data-owner-integration-candidate>Volver a la candidatura</button>' : ""}</div>${subscriptionJobActive ? '<p class="owner-partial-notice">Ya existe un reintento de suscripción activo para este negocio. Actualiza antes de solicitar otro.</p>' : ""}<div data-owner-integration-feedback class="status-text" role="status"></div></section>
    <section data-owner-integration-panel="candidates" hidden><h3>Candidaturas</h3>${record.candidates.length ? record.candidates.map((candidate) => `<article class="owner-candidate-history"><span class="ag-badge ag-badge--warning">Pendiente</span><p><strong>${channel}</strong> · ${escapeHtml(record.publicAccount)}</p><p>Creada ${escapeHtml(ownerOperationalDate(candidate.created_at))}. La integración anterior se conserva hasta que la candidatura sea revisada.</p><button class="button button-secondary button-small" type="button" data-owner-integration-candidate>Revisar en Altas y aprobaciones</button></article>`).join("") : '<div class="empty-state"><strong>Sin candidaturas pendientes</strong><p>El backend actual no expone historial Owner de candidaturas resueltas; no se inventan estados anteriores.</p></div>'}</section>
    <section data-owner-integration-panel="activity" hidden><h3>Actividad disponible</h3>${jobs.length ? `<ol class="owner-audit-list">${jobs.slice(0, 10).map((entry) => `<li><strong>${escapeHtml(OWNER_META_JOB_LABELS[entry.job.job_type] || "Trabajo de integración")}</strong><span>${escapeHtml(OWNER_QUEUE_STATUS_LABELS[entry.job.status] || entry.job.status)} · ${escapeHtml(ownerOperationalDate(entry.job.created_at))}</span></li>`).join("")}</ol>` : '<div class="empty-state">No hay jobs recientes consultables para esta integración.</div>'}</section>`;
}

function renderOwnerIntegrationDetail() {
  const target = byId("owner-integration-detail");
  if (!target || !ownerOperationsState.selectedIntegration) return;
  const record = ownerIntegrationRecords().find((item) => String(item.business.id) === String(ownerOperationsState.selectedIntegration.businessId) && item.control.channel === ownerOperationsState.selectedIntegration.channel);
  if (!record) { target.hidden = true; return; }
  target.hidden = false;
  target.dataset.businessId = record.business.id;
  target.dataset.channel = record.control.channel;
  target.innerHTML = ownerIntegrationDetailMarkup(record);
  setOwnerIntegrationDetailView(ownerOperationsState.integrationDetailView, false);
}

function setOwnerIntegrationDetailView(view, focus = true) {
  const allowed = new Set(["summary", "control", "capabilities", "health", "recovery", "candidates", "activity"]);
  ownerOperationsState.integrationDetailView = allowed.has(view) ? view : "summary";
  const detail = byId("owner-integration-detail");
  if (!detail) return;
  detail.querySelectorAll("[data-owner-integration-panel]").forEach((panel) => { panel.hidden = panel.dataset.ownerIntegrationPanel !== ownerOperationsState.integrationDetailView; });
  detail.querySelectorAll("[data-owner-integration-tab]").forEach((button) => {
    const active = button.dataset.ownerIntegrationTab === ownerOperationsState.integrationDetailView;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  });
  if (focus) { const title = detail.querySelector(`[data-owner-integration-panel="${ownerOperationsState.integrationDetailView}"] h3`) || byId("owner-integration-detail-title"); title?.setAttribute("tabindex", "-1"); title?.focus(); }
}

function openOwnerIntegrationDetail(businessId, channel, view = "summary") {
  const record = ownerIntegrationRecords().find((item) => String(item.business.id) === String(businessId) && item.control.channel === channel);
  if (!record) return;
  ownerOperationsState.selectedIntegration = { businessId: record.business.id, channel };
  ownerOperationsState.integrationDetailView = view;
  renderOwnerIntegrationDetail();
  byId("owner-integration-detail").scrollIntoView({ block: "start", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
}

async function loadOwnerIntegrationsHub(force = false) {
  if (ownerOperationsState.integrationsInFlight && !force) return ownerOperationsState.integrationsInFlight;
  const task = (async () => {
    byId("owner-integrations-list")?.setAttribute("aria-busy", "true");
    if (force || ownerDashboardState.businesses.status !== "ready") await loadOwnerDashboardBusinesses();
    const tasks = [];
    if (force || ownerDashboardState.channels.status !== "ready") tasks.push(loadOwnerDashboardChannels());
    if (force || ownerOperationsState.sourceState.jobs === "idle") tasks.push(loadOwnerMetaJobs());
    if (tasks.length) await Promise.allSettled(tasks);
    renderOwnerIntegrationsList();
    if (ownerOperationsState.selectedIntegration) renderOwnerIntegrationDetail();
  })();
  ownerOperationsState.integrationsInFlight = task;
  try { await task; } finally { if (ownerOperationsState.integrationsInFlight === task) ownerOperationsState.integrationsInFlight = null; }
}

function openOwnerIntegrationContext(businessId, channel) {
  ownerOperationsState.integrationFilter = "all";
  byId("owner-integration-filter").value = "all";
  loadOwnerIntegrationsHub().then(() => openOwnerIntegrationDetail(businessId, channel || "instagram"));
}

function currentOwnerIntegrationRecord() {
  const selected = ownerOperationsState.selectedIntegration;
  return selected ? ownerIntegrationRecords().find((item) => String(item.business.id) === String(selected.businessId) && item.control.channel === selected.channel) : null;
}

async function refreshOwnerIntegrationContext() {
  await Promise.allSettled([loadOwnerDashboardChannels(), loadOwnerMetaJobs()]);
  renderOwnerIntegrationsList();
  renderOwnerIntegrationDetail();
  renderOwnerDashboard();
}

async function mutateOwnerIntegrationControl(action) {
  const record = currentOwnerIntegrationRecord();
  const endpoints = {
    grant: "access",
    approve: "approve",
    suspend: "suspend",
    revoke: "revoke",
  };
  if (!record || !endpoints[action]) return;
  const detail = byId("owner-integration-detail");
  const channelName = record.control.channel === "instagram" ? "Instagram" : "WhatsApp";
  const businessId = encodeURIComponent(record.business.id);
  const channel = encodeURIComponent(record.control.channel);
  let title;
  let next;
  let consequence;
  let method = "POST";
  let endpoint = `/api/owner/businesses/${businessId}/channel-controls/${channel}/${endpoints[action]}`;
  let extraPayload = {};
  if (action === "grant") {
    title = "Cambiar disponibilidad comercial";
    next = "Canal disponible para conexión";
    consequence = "Se permitirá iniciar la conexión según el actor seleccionado. Esto no aprueba una candidatura ni activa envío o automatización.";
    method = "PUT";
    endpoint = `/api/owner/businesses/${businessId}/channel-controls/${channel}/access`;
    extraPayload.connector_policy = detail.querySelector("[data-owner-connector-policy]").value;
  } else if (action === "approve") {
    title = "Aprobar control comercial";
    next = "Canal aprobado";
    consequence = "Se aprobará el control simulado. Envío y automatización permanecerán desactivados. Las candidaturas OAuth o Embedded Signup solo se aprueban en Altas y aprobaciones.";
  } else if (action === "suspend") {
    title = "Suspender canal";
    next = "Canal suspendido";
    consequence = "El control comercial quedará suspendido y las capacidades se desactivarán. La integración y sus datos no se eliminan.";
  } else {
    title = "Revocar canal";
    next = "Canal revocado";
    consequence = "Se revocará el acceso comercial, se desactivarán capacidades y se invalidarán candidaturas pendientes. No se borran datos operativos.";
  }
  const confirmed = await confirmOwnerCriticalAction({ title, resource: `${channelName} · ${record.business.name}`, current: ownerChannelControlStatusLabel(record.control.status), next, consequence, confirmLabel: title, danger: ["suspend", "revoke"].includes(action), action: (reason) => ownerHubRequest(endpoint, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...extraPayload, reason }) }, "No se pudo cambiar el control del canal.") });
  if (confirmed) await refreshOwnerIntegrationContext();
}

async function saveOwnerIntegrationCapabilities() {
  const record = currentOwnerIntegrationRecord();
  const detail = byId("owner-integration-detail");
  if (!record || !detail) return;
  const delivery = detail.querySelector('[data-owner-capability="delivery"]').checked;
  const automation = detail.querySelector('[data-owner-capability="automation"]').checked;
  if (record.control.status !== "approved" || !ownerIntegrationIsActive(record) || ["revoked", "suspended", "error"].includes(record.health?.health_status)) return;
  const confirmed = await confirmOwnerCriticalAction({ title: "Cambiar capacidades", resource: `${record.control.channel === "instagram" ? "Instagram" : "WhatsApp"} · ${record.business.name}`, current: `Envío ${record.control.integrated_delivery_enabled ? "activo" : "inactivo"}; automatización ${record.control.automation_enabled ? "activa" : "inactiva"}`, next: `Envío ${delivery ? "activo" : "inactivo"}; automatización ${automation ? "activa" : "inactiva"}`, consequence: "Solo cambian las capacidades seleccionadas. La aprobación, la integración técnica y la salud mantienen sus estados independientes.", confirmLabel: "Guardar capacidades", danger: false, action: (reason) => ownerHubRequest(`/api/owner/businesses/${encodeURIComponent(record.business.id)}/channel-controls/${encodeURIComponent(record.control.channel)}/capabilities`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ integrated_delivery_enabled: delivery, automation_enabled: automation, reason }) }, "No se pudieron cambiar las capacidades.") });
  if (confirmed) await refreshOwnerIntegrationContext();
}

async function runOwnerIntegrationHealthCheck(button) {
  const record = currentOwnerIntegrationRecord();
  if (!record) return;
  const key = ownerIntegrationHealthCheckKey(record);
  if (ownerOperationsState.healthChecks.get(key)?.phase === "checking") return;
  ownerOperationsState.healthChecks.set(key, { phase: "checking", previousStatus: record.health?.health_status || "unknown", previousCheckedAt: record.health?.last_health_check_at || null });
  button.disabled = true;
  button.textContent = "⟳ Comprobando...";
  renderOwnerIntegrationDetail();
  try {
    const result = await ownerHubRequest(`/api/owner/businesses/${encodeURIComponent(record.business.id)}/channels/${encodeURIComponent(record.control.channel)}/health-check`, { method: "POST" }, "No se pudo solicitar la comprobación.");
    const jobId = result.job?.id;
    let terminalJob = result.job || null;
    for (let attempt = 0; attempt < 20 && !["completed", "failed", "dead_letter"].includes(terminalJob?.status); attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 750));
      const jobs = await ownerHubRequest(`/api/owner/businesses/${encodeURIComponent(record.business.id)}/channels/jobs`, {}, "No se pudo consultar el resultado de la comprobación.");
      terminalJob = (jobs.jobs || []).find((job) => String(job.id) === String(jobId)) || terminalJob;
    }
    if (terminalJob?.status !== "completed") throw new Error("No se pudo confirmar la comprobación.");
    const current = ownerOperationsState.healthChecks.get(key) || {};
    const healthPayload = await ownerHubRequest(`/api/owner/businesses/${encodeURIComponent(record.business.id)}/channels/health`, {}, "No se pudo leer el resultado de la comprobaciÃ³n.");
    const refreshedHealth = (healthPayload.channels || []).find((health) => health.channel === record.control.channel);
    if (!refreshedHealth?.last_health_check_at || refreshedHealth.last_health_check_at === current.previousCheckedAt) throw new Error("La comprobaciÃ³n no devolviÃ³ un resultado nuevo.");
    const snapshot = (ownerDashboardState.channels.data || []).find((item) => String(item.business.id) === String(record.business.id));
    if (!snapshot) throw new Error("No se pudo actualizar el negocio comprobado.");
    snapshot.health = (healthPayload.channels || []).slice();
    await loadOwnerMetaJobs();
    ownerOperationsState.healthChecks.set(key, { ...current, phase: "success" });
    renderOwnerIntegrationsList();
    renderOwnerIntegrationDetail();
    renderOwnerDashboard();
  } catch (error) {
    const current = ownerOperationsState.healthChecks.get(key) || {};
    ownerOperationsState.healthChecks.set(key, { ...current, phase: "error" });
    renderOwnerIntegrationDetail();
  }
}

async function retryOwnerIntegrationSubscription() {
  const record = currentOwnerIntegrationRecord();
  if (!record) return;
  const confirmed = await confirmOwnerCriticalAction({ title: "Reintentar suscripción", resource: `${record.control.channel === "instagram" ? "Instagram" : "WhatsApp"} · ${record.business.name}`, current: "Suscripción ausente", next: "Reintento encolado", consequence: "El backend creará como máximo un job equivalente activo. No se cambian aprobación ni capacidades mientras se procesa.", confirmLabel: "Encolar reintento", danger: false, requiresReason: false, action: () => ownerHubRequest(`/api/owner/businesses/${encodeURIComponent(record.business.id)}/channels/${encodeURIComponent(record.control.channel)}/retry-subscription`, { method: "POST" }, "No se pudo solicitar el reintento.") });
  if (confirmed) await refreshOwnerIntegrationContext();
}

async function requestOwnerIntegrationReconnection() {
  const record = currentOwnerIntegrationRecord();
  if (!record || record.control.channel !== "instagram") return;
  let authorizationUrl = "";
  const confirmed = await confirmOwnerCriticalAction({ title: "Solicitar reconexión", resource: `Instagram · ${record.business.name}`, current: ownerIntegrationHealthLabel(record.health?.health_status), next: "Nueva conexión iniciada", consequence: "Se iniciará una nueva conexión. La integración actual seguirá disponible hasta que la nueva sea revisada y aprobada en Altas y aprobaciones.", confirmLabel: "Continuar con Instagram", danger: false, requiresReason: false, action: async () => { const body = await ownerHubRequest(`/api/owner/businesses/${encodeURIComponent(record.business.id)}/channels/instagram/request-reconnection`, { method: "POST" }, "No se pudo iniciar la reconexión."); const url = String(body.authorization_url || ""); if (!url.startsWith("https://www.instagram.com/oauth/authorize?")) throw new Error("Instagram devolvió un destino de autorización no válido."); authorizationUrl = url; } });
  if (confirmed && authorizationUrl) window.location.assign(authorizationUrl);
}

function openOwnerCandidateFromIntegration(businessId = null, channel = null) {
  const record = businessId
    ? ownerIntegrationRecords().find((item) => String(item.business.id) === String(businessId) && item.control.channel === channel)
    : currentOwnerIntegrationRecord();
  if (!record) return;
  setActiveTab("new-business");
  openOwnerApprovalContext(record.business.id, record.control.channel);
}

/* Incidencias: lista segura, detalle y mutaciones no optimistas. */
function ownerIncidentStatusLabel(status) {
  return ({ open: "Abierta", acknowledged: "Reconocida", resolved: "Resuelta", ignored: "Ignorada" })[status] || "Estado no disponible";
}

function ownerIncidentSeverityLabel(severity) {
  return ({ critical: "Crítica", high: "Alta", medium: "Media", low: "Baja" })[severity] || "Sin clasificar";
}

function ownerIncidentOrigin(incident) {
  if (incident.channel === "instagram" || incident.provider === "instagram") return { key: "instagram", label: "Instagram" };
  if (incident.channel === "whatsapp" || incident.provider === "whatsapp") return { key: "whatsapp", label: "WhatsApp" };
  const value = `${incident.category || ""} ${incident.operation || ""}`.toLowerCase();
  if (/outbox|inbox|message|conversation/.test(value)) return { key: "messaging", label: "Mensajería" };
  if (/booking|reservation|reserva/.test(value)) return { key: "bookings", label: "Reservas" };
  if (/integration|oauth|subscription|webhook/.test(value)) return { key: "integrations", label: "Integraciones" };
  if (/worker|queue|processing|dead_letter/.test(value)) return { key: "processing", label: "Procesamiento" };
  return { key: "platform", label: "Plataforma" };
}

function ownerIncidentSafeMessage(incident) {
  const details = incident.safe_details;
  if (!details || typeof details !== "object") return "Consulta el contexto y la acción recomendada.";
  const allowed = ["message", "safe_message", "summary", "recommendation"];
  const value = allowed.map((key) => details[key]).find((item) => typeof item === "string" && item.trim());
  return value || "Consulta el contexto y la acción recomendada.";
}

function ownerFilteredIncidents() {
  const query = ownerNormalizeSearch(ownerOperationsState.incidentQuery);
  return incidents.filter((incident) => {
    const origin = ownerIncidentOrigin(incident);
    if (ownerOperationsState.incidentOrigin && origin.key !== ownerOperationsState.incidentOrigin) return false;
    const searchable = ownerNormalizeSearch([safeIncidentTitle(incident), incident.business_name, ownerIncidentSafeMessage(incident)].filter(Boolean).join(" "));
    return !query || searchable.includes(query);
  });
}

function ownerIncidentRow(incident) {
  const origin = ownerIncidentOrigin(incident);
  return `<article class="owner-incident-row severity-${escapeHtml(incident.severity)}" role="listitem"><div><h3>${escapeHtml(safeIncidentTitle(incident))}</h3><p>${escapeHtml(incident.business_name || "Plataforma")} · ${escapeHtml(origin.label)}</p><p>${escapeHtml(ownerIncidentSafeMessage(incident))}</p></div><div class="owner-incident-row__states"><span class="ag-badge ${["critical", "high"].includes(incident.severity) ? "ag-badge--danger" : "ag-badge--warning"}">${escapeHtml(ownerIncidentSeverityLabel(incident.severity))}</span><span class="ag-badge ag-badge--neutral">${escapeHtml(ownerIncidentStatusLabel(incident.status))}</span></div><div class="owner-incident-row__time"><span>Primera: ${escapeHtml(ownerOperationalDate(incident.first_occurred_at))}</span><span>Última: ${escapeHtml(ownerOperationalDate(incident.last_occurred_at))}</span>${incident.occurrence_count > 1 ? `<span>${incident.occurrence_count} apariciones</span>` : ""}</div><button class="button button-primary button-small" type="button" data-owner-incident-open="${escapeHtml(incident.id)}">Abrir incidencia</button></article>`;
}

renderIncidents = function renderOwnerIncidentsHub() {
  const target = byId("incident-list");
  const filtered = ownerFilteredIncidents();
  target.setAttribute("aria-busy", "false");
  target.innerHTML = filtered.length ? filtered.map(ownerIncidentRow).join("") : '<div class="empty-state"><strong>Sin coincidencias</strong><p>No hay incidencias para los filtros actuales.</p></div>';
  byId("incidents-status").textContent = `${filtered.length} incidencia${filtered.length === 1 ? "" : "s"}`;
  const businessSelect = byId("incident-filters").elements.business_id;
  const selected = businessSelect.value;
  businessSelect.innerHTML = '<option value="">Todos</option>' + businesses.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join("");
  businessSelect.value = selected;
  renderSummary();
  if (ownerOperationsState.selectedIncidentId) renderOwnerIncidentDetail();
};

function ownerIncidentActions(incident) {
  const actions = incident.status === "open" ? [["acknowledge", "Reconocer"], ["resolve", "Resolver"], ["ignore", "Ignorar"]]
    : incident.status === "acknowledged" ? [["resolve", "Resolver"], ["ignore", "Ignorar"]] : [["reopen", "Reabrir"]];
  return actions.map(([action, label]) => `<button class="button ${action === "ignore" ? "button-danger" : "button-secondary"}" type="button" data-incident-action="${action}" data-incident-id="${escapeHtml(incident.id)}">${label}</button>`).join("");
}

function renderOwnerIncidentDetail() {
  const target = byId("owner-incident-detail");
  const incident = incidents.find((item) => String(item.id) === String(ownerOperationsState.selectedIncidentId));
  if (!incident) { target.hidden = true; return; }
  const origin = ownerIncidentOrigin(incident);
  target.hidden = false;
  target.innerHTML = `<header><div><p class="eyebrow">Detalle de incidencia</p><h2 id="owner-incident-detail-title">${escapeHtml(safeIncidentTitle(incident))}</h2></div><button class="button button-secondary button-small" type="button" data-owner-incident-close>Volver a la lista</button></header><div class="owner-incident-detail-grid"><section><h3>Resumen</h3><p><strong>Estado</strong>${escapeHtml(ownerIncidentStatusLabel(incident.status))}</p><p><strong>Severidad</strong>${escapeHtml(ownerIncidentSeverityLabel(incident.severity))}</p><p>${escapeHtml(ownerIncidentSafeMessage(incident))}</p></section><section><h3>Impacto</h3><p>${incident.occurrence_count > 1 ? `${incident.occurrence_count} apariciones registradas.` : "Una aparición registrada."}</p><p>No se infiere impacto adicional sin una fuente fiable.</p></section><section><h3>Contexto</h3><p><strong>Negocio</strong>${escapeHtml(incident.business_name || "Plataforma")}</p><p><strong>Canal o componente</strong>${escapeHtml(origin.label)}</p></section><section><h3>Cronología</h3><p><strong>Primera aparición</strong>${escapeHtml(ownerOperationalDate(incident.first_occurred_at))}</p><p><strong>Última aparición</strong>${escapeHtml(ownerOperationalDate(incident.last_occurred_at))}</p><p><strong>Resolución</strong>${escapeHtml(ownerOperationalDate(incident.resolved_at))}</p></section></div><section class="owner-safe-technical"><h3>Información técnica segura</h3><p>Componente: ${escapeHtml(origin.label)} · Apariciones: ${incident.occurrence_count}. No se muestran códigos internos, trazas, cuerpos ni metadatos.</p></section><div class="owner-operation-actions">${ownerIncidentActions(incident)}${incident.business_id ? '<button class="button button-secondary" type="button" data-owner-incident-business>Abrir negocio</button>' : ""}${incident.business_id && incident.channel ? '<button class="button button-secondary" type="button" data-owner-incident-integration>Abrir integración</button>' : ""}${origin.key === "processing" || origin.key === "messaging" ? '<button class="button button-secondary" type="button" data-owner-incident-operation>Abrir operaciones</button>' : ""}</div><p data-owner-incident-feedback class="status-text" role="status"></p>`;
}

function openOwnerIncidentDetail(incidentId) {
  const incident = incidents.find((item) => String(item.id) === String(incidentId));
  if (!incident) return;
  ownerOperationsState.selectedIncidentId = incident.id;
  renderOwnerIncidentDetail();
  byId("owner-incident-detail").scrollIntoView({ block: "start", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
}

async function openOwnerIncidentContext(incidentId) {
  let incident = incidents.find((item) => String(item.id) === String(incidentId));
  if (!incident) {
    byId("incident-filters").elements.status.value = "";
    await loadIncidents();
    incident = incidents.find((item) => String(item.id) === String(incidentId));
  }
  if (incident) openOwnerIncidentDetail(incident.id);
}

updateIncident = async function mutateOwnerIncident(incidentId, action) {
  const incident = incidents.find((item) => String(item.id) === String(incidentId));
  if (!incident) return;
  const labels = { acknowledge: ["Reconocer incidencia", "Reconocida", "La incidencia seguirá abierta, pero constará que el Owner la está revisando."], resolve: ["Resolver incidencia", "Resuelta", "La incidencia quedará resuelta. No se borrará y podrá reabrirse si reaparece."], ignore: ["Ignorar incidencia", "Ignorada", "La incidencia dejará de figurar como activa sin eliminar su historial."], reopen: ["Reabrir incidencia", "Abierta", "La incidencia volverá a requerir intervención."] };
  const [title, next, consequence] = labels[action];
  const confirmed = await confirmOwnerCriticalAction({ title, resource: safeIncidentTitle(incident), current: ownerIncidentStatusLabel(incident.status), next, context: [["Negocio", incident.business_name || "Plataforma"], ["Severidad", ownerIncidentSeverityLabel(incident.severity)]], consequence, confirmLabel: title, danger: action === "ignore", requiresReason: false, action: () => ownerHubRequest(`/api/owner/incidents/${encodeURIComponent(incident.id)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }) }, "No se pudo actualizar la incidencia.") });
  if (!confirmed) return;
  await Promise.allSettled([loadIncidents(), loadOwnerDashboardIncidents()]);
  ownerOperationsState.selectedIncidentId = incident.id;
  renderOwnerIncidentDetail();
  renderOwnerDashboard();
};

/* Operaciones: señales reales de queue-status, health, jobs y mantenimiento. */
async function loadOwnerMetaJobs() {
  ownerOperationsState.sourceState.jobs = "loading";
  const jobs = [];
  let errors = 0;
  for (let index = 0; index < businesses.length; index += 4) {
    const batch = await Promise.all(businesses.slice(index, index + 4).map(async (business) => {
      try {
        const body = await ownerHubRequest(`/api/owner/businesses/${encodeURIComponent(business.id)}/channels/jobs`, {}, "No se pudieron cargar los jobs de integración.");
        return (body.jobs || []).map((job) => ({ businessId: business.id, businessName: business.name, channel: null, job }));
      } catch { errors += 1; return []; }
    }));
    batch.forEach((items) => jobs.push(...items));
  }
  ownerOperationsState.metaJobs = jobs.sort((left, right) => new Date(right.job.created_at) - new Date(left.job.created_at));
  ownerOperationsState.metaJobErrors = errors;
  ownerOperationsState.sourceState.jobs = errors === businesses.length && businesses.length ? "error" : errors ? "partial" : "ready";
  return jobs;
}

function ownerOperationsMetrics() {
  const queue = queueStatus || {};
  const metaPending = ownerOperationsState.metaJobs.filter((entry) => ["queued", "processing", "retry"].includes(entry.job.status)).length;
  const metrics = ownerOperationsState.sourceState.queue === "ready"
    ? [
      ["Procesamiento", queue.worker_active ? "Operativo" : queue.last_heartbeat ? "Necesita atención" : "No se pudo comprobar"],
      ["Pendientes", Number(queue.pending_inbox || 0) + Number(queue.pending_outbox || 0)],
      ["Reintentos", Number(queue.retry_inbox || 0) + Number(queue.retry_outbox || 0)],
      ["Agotados o bloqueados", Number(queue.dead_letter_inbox || 0) + Number(queue.dead_letter_outbox || 0) + Number(queue.blocked_outbox || 0)],
    ]
    : [["Procesamiento", "No se pudo comprobar"]];
  metrics.push(["Jobs de integración", ownerOperationsState.sourceState.jobs === "error" ? "No se pudo comprobar" : metaPending]);
  metrics.push(["Mantenimiento", ownerOperationsState.sourceState.maintenance === "error" ? "No se pudo comprobar" : ownerOperationsState.maintenance?.enabled ? "Activo" : "Inactivo"]);
  metrics.push(["Estado general", ownerOperationsState.sourceState.platform === "error" ? "No se pudo comprobar" : "Comprobado"]);
  return metrics;
}

function renderOwnerOperationsSummary() {
  const target = byId("owner-operations-summary");
  if (!target) return;
  target.setAttribute("aria-busy", "false");
  const failed = Object.values(ownerOperationsState.sourceState).filter((status) => status === "error" || status === "partial").length;
  const warning = failed ? `<p class="owner-partial-notice">Actualización parcial: ${failed} fuente${failed === 1 ? "" : "s"} no pudo comprobarse por completo.</p>` : "";
  target.innerHTML = warning + ownerOperationsMetrics().map(([label, value]) => `<article><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></article>`).join("");
}

function renderOwnerOutboxSummary() {
  const target = byId("owner-outbox-summary");
  if (!target) return;
  target.setAttribute("aria-busy", "false");
  if (ownerOperationsState.sourceState.queue === "error") {
    target.innerHTML = '<div class="error-box">No se pudieron comprobar los agregados de outbox.</div>';
    return;
  }
  const queue = queueStatus || {};
  target.innerHTML = [
    ["Pendientes", Number(queue.pending_outbox || 0)],
    ["Reintentos programados", Number(queue.retry_outbox || 0)],
    ["Bloqueados", Number(queue.blocked_outbox || 0)],
    ["Reintentos agotados", Number(queue.dead_letter_outbox || 0)],
  ].map(([label, value]) => `<article><strong>${escapeHtml(label)}</strong><span>${value}</span></article>`).join("");
}

function ownerQueueProblemRow(job) {
  const business = ownerBusinessById(job.business_id);
  const canRetry = ["failed", "dead_letter", "blocked"].includes(job.status);
  return `<article class="owner-operation-row"><div><h4>${job.job_type === "outbox" ? "Mensaje saliente" : "Evento entrante"}</h4><p>${escapeHtml(business?.name || "Negocio no disponible")} · ${escapeHtml(OWNER_QUEUE_STATUS_LABELS[job.status] || "Estado no disponible")}</p><small>Creado: ${escapeHtml(ownerOperationalDate(job.created_at))}${job.next_retry_at ? ` · Próximo intento: ${escapeHtml(ownerOperationalDate(job.next_retry_at))}` : ""}</small></div><div><span>${job.attempt_count} de ${job.max_attempts} intentos utilizados</span></div><div class="owner-operation-actions">${canRetry ? `<button class="button button-primary button-small" type="button" data-owner-queue-action="retry" data-job-type="${job.job_type}" data-job-id="${escapeHtml(job.id)}">Reintentar</button>` : ""}<button class="button button-secondary button-small" type="button" data-owner-queue-action="cancel" data-job-type="${job.job_type}" data-job-id="${escapeHtml(job.id)}">Cancelar procesamiento</button>${business ? `<button class="button button-secondary button-small" type="button" data-owner-operation-business="${escapeHtml(business.id)}">Abrir negocio</button>` : ""}</div></article>`;
}

function renderOwnerOutboxProblems() {
  const target = byId("owner-outbox-problems");
  if (!target) return;
  target.setAttribute("aria-busy", "false");
  if (ownerOperationsState.sourceState.queue === "error") { target.innerHTML = '<div class="error-box">No se pudo cargar mensajería. Workers y jobs conservan sus fuentes independientes.</div>'; return; }
  const jobs = (queueStatus?.jobs || []).filter((job) => job.job_type === "outbox");
  target.innerHTML = jobs.length ? jobs.map(ownerQueueProblemRow).join("") : '<div class="empty-state"><strong>Sin mensajes problemáticos</strong><p>La cola problemática está vacía en la última comprobación.</p></div>';
}

function renderOwnerWorkers() {
  const summary = byId("owner-workers-summary");
  const list = byId("owner-workers-list");
  if (!summary || !list) return;
  if (ownerOperationsState.sourceState.queue === "error") { summary.innerHTML = '<div class="error-box">No se pudieron comprobar workers y colas.</div>'; list.innerHTML = ""; return; }
  const queue = queueStatus || {};
  summary.setAttribute("aria-busy", "false");
  summary.innerHTML = [["Procesamiento activo", queue.worker_active ? "Sí" : queue.last_heartbeat ? "Señal sin actividad reciente" : "No se pudo comprobar"], ["Última actividad", ownerOperationalDate(queue.last_heartbeat)], ["Pendientes", Number(queue.pending_inbox || 0) + Number(queue.pending_outbox || 0)], ["Reintentos", Number(queue.retry_inbox || 0) + Number(queue.retry_outbox || 0)], ["Agotados", Number(queue.dead_letter_inbox || 0) + Number(queue.dead_letter_outbox || 0)], ["Workers con señal antigua", Number(queue.stale_worker_count || 0)]].map(([label, value]) => `<article><strong>${escapeHtml(label)}</strong><span>${escapeHtml(value)}</span></article>`).join("");
  list.innerHTML = (queue.workers || []).length ? (queue.workers || []).map((worker) => `<article class="owner-operation-row"><div><h4>${escapeHtml(worker.worker_type === "channel" ? "Procesamiento de canales" : "Worker de procesamiento")}</h4><p>${worker.stale ? "Sin actividad reciente" : "Operativo"}</p><small>Última señal: ${escapeHtml(ownerOperationalDate(worker.last_heartbeat))}</small></div><span class="ag-badge ${worker.stale ? "ag-badge--danger" : "ag-badge--success"}">${worker.stale ? "Necesita atención" : "Activo"}</span></article>`).join("") : '<div class="empty-state">No hay señales de workers disponibles.</div>';
}

function renderOwnerIntegrationJobs() {
  const target = byId("owner-integration-jobs");
  if (!target) return;
  target.setAttribute("aria-busy", "false");
  const warning = ownerOperationsState.metaJobErrors ? `<p class="owner-partial-notice">No se pudieron cargar los jobs de ${ownerOperationsState.metaJobErrors} negocio${ownerOperationsState.metaJobErrors === 1 ? "" : "s"}. Outbox y workers permanecen visibles.</p>` : "";
  target.innerHTML = warning + (ownerOperationsState.metaJobs.length ? ownerOperationsState.metaJobs.map((entry) => `<article class="owner-operation-row"><div><h4>${escapeHtml(OWNER_META_JOB_LABELS[entry.job.job_type] || "Job de integración")}</h4><p>${escapeHtml(entry.businessName)} · ${escapeHtml(OWNER_QUEUE_STATUS_LABELS[entry.job.status] || entry.job.status)}</p><small>Creado: ${escapeHtml(ownerOperationalDate(entry.job.created_at))}${entry.job.next_retry_at ? ` · Próxima ejecución: ${escapeHtml(ownerOperationalDate(entry.job.next_retry_at))}` : ""}</small></div><div><p>${escapeHtml(entry.job.safe_error_message || (entry.job.status === "completed" ? "Completado sin avisos" : "Sin resultado seguro disponible"))}</p><small>No existe un endpoint Owner seguro para reintentar este job manualmente.</small></div></article>`).join("") : ownerOperationsState.sourceState.jobs === "error" ? '<div class="error-box">No se pudieron comprobar los jobs de integración.</div>' : '<div class="empty-state">No hay jobs de integración recientes.</div>');
}

function renderOwnerMaintenance() {
  const target = byId("owner-maintenance-panel");
  if (!target) return;
  target.setAttribute("aria-busy", "false");
  if (ownerOperationsState.sourceState.maintenance === "error") { target.innerHTML = '<div class="error-box">No se pudo comprobar el modo mantenimiento.</div>'; byId("maintenance-toggle").disabled = true; return; }
  const maintenance = ownerOperationsState.maintenance || { enabled: false };
  byId("maintenance-toggle").disabled = false;
  target.innerHTML = `<article class="owner-maintenance-state ${maintenance.enabled ? "active" : ""}"><span class="ag-badge ${maintenance.enabled ? "ag-badge--danger" : "ag-badge--success"}">${maintenance.enabled ? "Mantenimiento activo" : "Operación normal"}</span><dl class="owner-maintenance-details"><div><dt>Estado actual</dt><dd>${maintenance.enabled ? "El middleware aplica el alcance configurado por el backend." : "El modo mantenimiento está desactivado."}</dd></div><div><dt>Motivo</dt><dd>${escapeHtml(maintenance.reason || "Sin motivo registrado")}</dd></div><div><dt>Último cambio</dt><dd>${escapeHtml(ownerOperationalDate(maintenance.updated_at))}</dd></div></dl><p>Los datos se conservan. Este panel no ejecuta backups, restauraciones, despliegues ni consultas.</p></article>`;
  byId("maintenance-toggle").textContent = maintenance.enabled ? "Desactivar mantenimiento" : "Activar mantenimiento";
}

function renderOwnerOperationsHub() {
  renderOwnerOperationsSummary();
  renderOwnerOutboxSummary();
  renderOwnerOutboxProblems();
  renderOwnerWorkers();
  renderOwnerIntegrationJobs();
  renderOwnerMaintenance();
  const partial = Object.values(ownerOperationsState.sourceState).some((status) => status === "error" || status === "partial");
  byId("operations-status").textContent = `${partial ? "Actualización parcial" : "Actualizado"} ${new Intl.DateTimeFormat("es-ES", { timeStyle: "short" }).format(new Date())}`;
  renderOwnerAuditEvents();
}

async function loadOwnerOperationsHub(force = false) {
  if (ownerOperationsState.operationsInFlight && !force) return ownerOperationsState.operationsInFlight;
  const task = (async () => {
    ["owner-operations-summary", "owner-outbox-summary", "owner-outbox-problems", "owner-workers-summary", "owner-integration-jobs", "owner-maintenance-panel"].forEach((id) => byId(id)?.setAttribute("aria-busy", "true"));
    Object.keys(ownerOperationsState.sourceState).forEach((key) => { ownerOperationsState.sourceState[key] = "loading"; });
    const results = await Promise.allSettled([
      ownerHubRequest("/api/owner/system/queue-status", {}, "No se pudo comprobar la cola."),
      ownerHubRequest("/api/owner/system/health", {}, "No se pudo comprobar la plataforma."),
      ownerHubRequest("/api/owner/system/maintenance", {}, "No se pudo comprobar mantenimiento."),
      loadOwnerMetaJobs(),
    ]);
    if (results[0].status === "fulfilled") { queueStatus = results[0].value; ownerOperationsState.sourceState.queue = "ready"; } else ownerOperationsState.sourceState.queue = "error";
    if (results[1].status === "fulfilled") { operationsStatus = results[1].value; ownerOperationsState.sourceState.platform = "ready"; } else ownerOperationsState.sourceState.platform = "error";
    if (results[2].status === "fulfilled") { ownerOperationsState.maintenance = results[2].value; ownerOperationsState.sourceState.maintenance = "ready"; } else ownerOperationsState.sourceState.maintenance = "error";
    renderOwnerOperationsHub();
  })();
  ownerOperationsState.operationsInFlight = task;
  try { await task; } finally { if (ownerOperationsState.operationsInFlight === task) ownerOperationsState.operationsInFlight = null; }
}

loadOperationsStatus = loadOwnerOperationsHub;
renderOperationsStatus = renderOwnerOperationsHub;
renderQueueStatus = function renderLegacyQueueAndOperations() {
  renderOwnerOperationsHub();
  if (byId("queue-summary")) {
    byId("queue-summary").innerHTML = ownerOperationsMetrics().slice(0, 5).map(([label, value]) => `<article class="summary-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></article>`).join("");
    byId("queue-jobs").innerHTML = (queueStatus?.jobs || []).map(ownerQueueProblemRow).join("") || '<div class="empty-state">No hay trabajos accionables.</div>';
    byId("queue-incidents").innerHTML = "";
  }
};

function setOwnerOperationsView(view) {
  const allowed = new Set(["messages", "workers", "jobs", "maintenance"]);
  ownerOperationsState.operationsView = allowed.has(view) ? view : "messages";
  document.querySelectorAll("[data-owner-operations-view]").forEach((button) => { const active = button.dataset.ownerOperationsView === ownerOperationsState.operationsView; button.classList.toggle("active", active); if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current"); });
  document.querySelectorAll("[data-owner-operations-panel]").forEach((panel) => { panel.hidden = panel.dataset.ownerOperationsPanel !== ownerOperationsState.operationsView; });
}

updateQueueJob = async function updateOwnerQueueJob(jobType, jobId, action) {
  const job = (queueStatus?.jobs || []).find((item) => item.job_type === jobType && String(item.id) === String(jobId));
  if (!job) return;
  const business = ownerBusinessById(job.business_id);
  const retrying = action === "retry";
  const confirmed = await confirmOwnerCriticalAction({ title: retrying ? "Reintentar operación" : "Cancelar procesamiento", resource: `${jobType === "outbox" ? "Mensaje saliente" : "Evento entrante"} · ${business?.name || "Negocio"}`, current: OWNER_QUEUE_STATUS_LABELS[job.status] || job.status, next: retrying ? "Pendiente de nuevo intento" : "Cancelado", consequence: retrying ? "La operación volverá a la cola respetando locks, idempotencia y límites del backend. No se garantiza envío inmediato." : "La operación dejará de procesarse. No se elimina el registro ni se marca como enviado.", confirmLabel: retrying ? "Reintentar" : "Cancelar procesamiento", danger: !retrying, action: (reason) => ownerHubRequest(`/api/owner/queue/${encodeURIComponent(jobType)}/${encodeURIComponent(jobId)}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }) }, "No se pudo actualizar la operación.") });
  if (confirmed) { await Promise.allSettled([loadOwnerOperationsHub(true), loadOwnerDashboardQueue()]); renderOwnerDashboard(); }
};

toggleMaintenance = async function toggleOwnerMaintenance() {
  const maintenance = ownerOperationsState.maintenance;
  if (!maintenance) return;
  const enabling = !maintenance.enabled;
  const confirmed = await confirmOwnerCriticalAction({ title: enabling ? "Activar mantenimiento" : "Desactivar mantenimiento", resource: "Plataforma AutonoGrow", current: maintenance.enabled ? "Mantenimiento activo" : "Operación normal", next: enabling ? "Mantenimiento activo" : "Operación normal", consequence: enabling ? "El procesamiento automático se pausará según el alcance real del modo mantenimiento. No se vacían colas ni se eliminan datos." : "Se retirará el modo mantenimiento y el procesamiento podrá continuar según el estado real de workers y colas.", confirmLabel: enabling ? "Activar mantenimiento" : "Desactivar mantenimiento", danger: enabling, action: (reason) => ownerHubRequest(`/api/owner/system/maintenance/${enabling ? "enable" : "disable"}?reason=${encodeURIComponent(reason)}`, { method: "POST" }, "No se pudo cambiar mantenimiento.") });
  if (confirmed) { await Promise.allSettled([loadOwnerOperationsHub(true), loadOwnerDashboardPlatform()]); renderOwnerDashboard(); }
};

/* Auditoría operativa: feed derivado, explícitamente distinto de AuditLog. */
function ownerAuditEvents() {
  const events = [];
  (ownerDashboardState.channels.data || []).forEach((snapshot) => (snapshot.controls || []).forEach((control) => {
    [[control.approved_at, "Canal aprobado"], [control.suspended_at, "Canal suspendido"], [control.revoked_at, "Canal revocado"]].forEach(([at, label]) => { if (at) events.push({ kind: "channel", businessId: snapshot.business.id, businessName: snapshot.business.name, at, label: `${label}: ${control.channel === "instagram" ? "Instagram" : "WhatsApp"}` }); });
  }));
  const incidentSource = incidents.length ? incidents : ownerDashboardState.incidents.data?.incidents || [];
  incidentSource.forEach((incident) => events.push({ kind: "incident", businessId: incident.business_id, businessName: incident.business_name || "Plataforma", at: incident.resolved_at || incident.updated_at || incident.created_at, label: incident.resolved_at ? "Incidencia resuelta" : `Incidencia ${ownerIncidentStatusLabel(incident.status).toLowerCase()}` }));
  ownerOperationsState.metaJobs.filter((entry) => ["completed", "failed", "dead_letter"].includes(entry.job.status)).forEach((entry) => events.push({ kind: "job", businessId: entry.businessId, businessName: entry.businessName, at: entry.job.completed_at || entry.job.failed_at || entry.job.created_at, label: `${OWNER_META_JOB_LABELS[entry.job.job_type] || "Job de integración"}: ${OWNER_QUEUE_STATUS_LABELS[entry.job.status] || entry.job.status}` }));
  if (ownerOperationsState.maintenance?.updated_at) events.push({ kind: "maintenance", businessId: null, businessName: "Plataforma", at: ownerOperationsState.maintenance.updated_at, label: ownerOperationsState.maintenance.enabled ? "Mantenimiento activado" : "Mantenimiento desactivado" });
  return events.filter((event) => event.at).sort((left, right) => new Date(right.at) - new Date(left.at));
}

function renderOwnerAuditEvents() {
  const target = byId("owner-audit-events");
  if (!target) return;
  const businessValue = byId("owner-audit-business")?.value || "";
  const kindValue = byId("owner-audit-kind")?.value || "";
  const events = ownerAuditEvents().filter((event) => (!businessValue || String(event.businessId) === businessValue) && (!kindValue || event.kind === kindValue));
  target.setAttribute("aria-busy", "false");
  const partial = ownerOperationsState.sourceState.jobs === "error" || ownerOperationsState.sourceState.jobs === "partial" || ownerOperationsState.sourceState.maintenance === "error";
  const warning = partial ? '<p class="owner-partial-notice">Actividad parcial: alguna fuente no pudo comprobarse. Se conservan los eventos confirmados.</p>' : "";
  target.innerHTML = warning + (events.length ? events.map((event) => `<article class="owner-audit-event" role="listitem"><div><strong>${escapeHtml(event.label)}</strong><p>${escapeHtml(event.businessName)}</p></div><time datetime="${escapeHtml(event.at)}">${escapeHtml(ownerOperationalDate(event.at))}</time><span>Actor y resultado detallado: no expuestos por esta fuente</span>${event.businessId ? `<button class="button button-secondary button-small" type="button" data-owner-audit-business="${escapeHtml(event.businessId)}">Abrir negocio</button>` : ""}</article>`).join("") : '<div class="empty-state"><strong>Sin eventos disponibles</strong><p>Los filtros no tienen coincidencias o las fuentes aún no se han cargado.</p></div>');
}

async function loadOwnerAuditHub(force = false) {
  const select = byId("owner-audit-business");
  const selected = select.value;
  select.innerHTML = '<option value="">Todos</option>' + businesses.map((business) => `<option value="${escapeHtml(business.id)}">${escapeHtml(business.name)}</option>`).join("");
  select.value = selected;
  if (force || !ownerOperationsState.metaJobs.length || !ownerOperationsState.maintenance) {
    const results = await Promise.allSettled([loadOwnerMetaJobs(), ownerHubRequest("/api/owner/system/maintenance")]);
    if (results[1].status === "fulfilled") { ownerOperationsState.maintenance = results[1].value; ownerOperationsState.sourceState.maintenance = "ready"; }
    else ownerOperationsState.sourceState.maintenance = "error";
  }
  renderOwnerAuditEvents();
}

/* Listeners delegados, uno por área. */
byId("owner-integration-filters").addEventListener("submit", (event) => event.preventDefault());
byId("owner-integration-search").addEventListener("input", (event) => { ownerOperationsState.integrationQuery = event.target.value; renderOwnerIntegrationsList(); });
byId("owner-integration-filter").addEventListener("change", (event) => { ownerOperationsState.integrationFilter = event.target.value; renderOwnerIntegrationsList(); });
byId("owner-integrations-refresh").addEventListener("click", () => loadOwnerIntegrationsHub(true));
byId("owner-integrations-section").addEventListener("click", (event) => {
  const open = event.target.closest("[data-owner-integration-open]");
  if (open) { openOwnerIntegrationDetail(open.dataset.businessId, open.dataset.channel); return; }
  if (event.target.closest("[data-owner-integration-close]")) { ownerOperationsState.selectedIntegration = null; byId("owner-integration-detail").hidden = true; byId("owner-integration-search").focus(); return; }
  const tab = event.target.closest("[data-owner-integration-tab]");
  if (tab) { setOwnerIntegrationDetailView(tab.dataset.ownerIntegrationTab); return; }
  const control = event.target.closest("[data-owner-integration-control]");
  if (control) { mutateOwnerIntegrationControl(control.dataset.ownerIntegrationControl); return; }
  if (event.target.closest("[data-owner-integration-capabilities]")) { saveOwnerIntegrationCapabilities(); return; }
  if (event.target.closest("[data-owner-integration-health-check]")) { runOwnerIntegrationHealthCheck(event.target.closest("button")); return; }
  if (event.target.closest("[data-owner-integration-retry-subscription]")) { retryOwnerIntegrationSubscription(); return; }
  if (event.target.closest("[data-owner-integration-reconnect]")) { requestOwnerIntegrationReconnection(); return; }
  const candidate = event.target.closest("[data-owner-integration-candidate]");
  if (candidate) { openOwnerCandidateFromIntegration(candidate.dataset.businessId, candidate.dataset.channel); return; }
  if (event.target.closest("[data-owner-integration-business]")) { const record = currentOwnerIntegrationRecord(); if (record) { setActiveTab("businesses"); openBusinessDetail(record.business.id, "summary"); } return; }
  if (event.target.closest("[data-owner-integration-incidents]")) { const record = currentOwnerIntegrationRecord(); if (record) { setActiveTab("incidents"); byId("incident-filters").elements.business_id.value = String(record.business.id); byId("incident-filters").elements.channel.value = record.control.channel; loadIncidents(); } }
});

byId("owner-incidents-section").addEventListener("click", (event) => {
  const view = event.target.closest("[data-owner-incident-view]");
  if (view) { document.querySelectorAll("[data-owner-incident-view]").forEach((button) => { const active = button === view; button.classList.toggle("active", active); if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current"); }); const status = view.dataset.ownerIncidentView; byId("incident-filters").elements.status.value = status === "all" ? "" : status; loadIncidents(); return; }
  const open = event.target.closest("[data-owner-incident-open]");
  if (open) { openOwnerIncidentDetail(open.dataset.ownerIncidentOpen); return; }
  const action = event.target.closest("[data-incident-action]");
  if (action) { updateIncident(action.dataset.incidentId, action.dataset.incidentAction).catch((error) => { const feedback = byId("owner-incident-detail").querySelector("[data-owner-incident-feedback]"); if (feedback) feedback.textContent = error.message; }); return; }
  if (event.target.closest("[data-owner-incident-close]")) { ownerOperationsState.selectedIncidentId = null; byId("owner-incident-detail").hidden = true; byId("owner-incident-search").focus(); return; }
  const incident = incidents.find((item) => String(item.id) === String(ownerOperationsState.selectedIncidentId));
  if (event.target.closest("[data-owner-incident-business]") && incident?.business_id) { setActiveTab("businesses"); openBusinessDetail(incident.business_id, "summary"); return; }
  if (event.target.closest("[data-owner-incident-integration]") && incident?.business_id && incident.channel) { setActiveTab("integrations"); openOwnerIntegrationContext(incident.business_id, incident.channel); return; }
  if (event.target.closest("[data-owner-incident-operation]")) { setActiveTab("operations"); setOwnerOperationsView("messages"); }
});
byId("owner-incident-search").addEventListener("input", (event) => { ownerOperationsState.incidentQuery = event.target.value; renderIncidents(); });
byId("owner-incident-origin").addEventListener("change", (event) => { ownerOperationsState.incidentOrigin = event.target.value; renderIncidents(); });

byId("owner-operations-section").addEventListener("click", (event) => {
  const view = event.target.closest("[data-owner-operations-view]");
  if (view) { setOwnerOperationsView(view.dataset.ownerOperationsView); return; }
  const queueAction = event.target.closest("[data-owner-queue-action]");
  if (queueAction) { updateQueueJob(queueAction.dataset.jobType, queueAction.dataset.jobId, queueAction.dataset.ownerQueueAction); return; }
  const business = event.target.closest("[data-owner-operation-business]");
  if (business) { setActiveTab("businesses"); openBusinessDetail(business.dataset.ownerOperationBusiness, "summary"); }
});

byId("owner-audit-refresh").addEventListener("click", () => loadOwnerAuditHub(true));
byId("owner-audit-filters").addEventListener("change", renderOwnerAuditEvents);
byId("owner-audit-section").addEventListener("click", (event) => {
  const business = event.target.closest("[data-owner-audit-business]");
  if (business) { setActiveTab("businesses"); openBusinessDetail(business.dataset.ownerAuditBusiness, "activity"); }
});
byId("businesses-section").addEventListener("click", (event) => {
  const integration = event.target.closest("[data-owner-business-integration]");
  if (integration) { setActiveTab("integrations"); openOwnerIntegrationContext(integration.dataset.ownerBusinessIntegration, integration.dataset.channel || "instagram"); }
});

setOwnerOperationsView("messages");
