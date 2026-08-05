"use strict";

/* Sprint 5C.2: directorio de negocios, altas y decisiones Owner. */
const OWNER_ONBOARDING_STATUSES = new Set(["draft", "onboarding", "configuration_pending", "ready"]);
const OWNER_BUSINESS_STATUS_LABELS = {
  active: "Activo",
  draft: "En preparación",
  onboarding: "Alta en curso",
  configuration_pending: "Configuración pendiente",
  ready: "Listo para activar",
  suspended: "Suspendido",
  archived: "Archivado",
};
const ownerBusinessHubState = {
  query: "",
  filter: "all",
  selectedBusinessId: null,
  detailSection: "summary",
  access: new Map(),
  accessSignature: "",
  accessVersion: 0,
  onboarding: new Map(),
  onboardingVersion: 0,
  hubView: "onboarding",
  currentCandidate: null,
};

function ownerSafeRequestError(response, fallback) {
  if (response?.status === 401) return "La sesión Owner ha caducado.";
  if (response?.status === 403) return "No tienes permiso para completar esta acción.";
  if (response?.status === 404) return "El recurso ya no está disponible. Actualiza la vista.";
  if (response?.status === 409) return "El estado cambió mientras revisabas la información. Actualiza y vuelve a comprobar.";
  if (response?.status === 422) return "Revisa el motivo y los datos antes de continuar.";
  return fallback;
}

async function ownerHubRequest(path, options = {}, fallback = "No se pudo completar la solicitud.") {
  const response = await fetch(`${API_BASE_URL}${path}`, options);
  const body = await readResponseBody(response);
  if (!response.ok) throw new Error(ownerSafeRequestError(response, fallback));
  return body;
}

function ownerBusinessStatus(business) {
  return business.status || (business.active ? "active" : "configuration_pending");
}

function ownerBusinessStatusLabel(status) {
  return OWNER_BUSINESS_STATUS_LABELS[status] || "Estado no disponible";
}

function ownerBusinessSnapshot(businessId) {
  return (ownerDashboardState.channels.data || []).find((item) => String(item.business.id) === String(businessId)) || null;
}

function ownerBusinessIncidents(businessId) {
  const source = ownerDashboardState.incidents.data;
  if (!source) return null;
  return (source.incidents || []).filter((item) => String(item.business_id) === String(businessId) && ["open", "acknowledged"].includes(item.status));
}

function ownerAccessEntry(businessId) {
  return ownerBusinessHubState.access.get(String(businessId)) || { status: "loading", users: [] };
}

function ownerActiveAdmins(businessId) {
  const entry = ownerAccessEntry(businessId);
  return entry.status === "ready" ? entry.users.filter((item) => item.active && item.role === "business_admin") : [];
}

function ownerBusinessNeedsAttention(business) {
  const snapshot = ownerBusinessSnapshot(business.id);
  const incidentsForBusiness = ownerBusinessIncidents(business.id);
  const access = ownerAccessEntry(business.id);
  return Boolean(
    snapshot?.instagramCandidates?.length
    || snapshot?.whatsappCandidates?.length
    || snapshot?.health?.some((item) => OWNER_DASHBOARD_HEALTH_ATTENTION.has(item.health_status))
    || incidentsForBusiness?.length
    || (access.status === "ready" && ownerActiveAdmins(business.id).length === 0)
  );
}

function ownerBusinessPriority(business) {
  const status = ownerBusinessStatus(business);
  if (ownerBusinessNeedsAttention(business)) return 0;
  if (OWNER_ONBOARDING_STATUSES.has(status)) return 1;
  if (status === "suspended") return 2;
  if (status === "active") return 3;
  return 4;
}

function ownerNormalizeSearch(value) {
  return String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
}

function ownerFilteredBusinesses() {
  const query = ownerNormalizeSearch(ownerBusinessHubState.query);
  return businesses.filter((business) => {
    const status = ownerBusinessStatus(business);
    const access = ownerAccessEntry(business.id);
    const adminEmails = access.status === "ready" ? access.users.filter((item) => item.role === "business_admin").map((item) => item.email) : [];
    const searchable = ownerNormalizeSearch([business.name, business.slug, business.city, ...adminEmails].filter(Boolean).join(" "));
    if (query && !searchable.includes(query)) return false;
    const filter = ownerBusinessHubState.filter;
    if (filter === "active") return status === "active";
    if (filter === "onboarding") return status === "onboarding";
    if (filter === "pending") return ["draft", "configuration_pending", "ready"].includes(status);
    if (filter === "suspended") return status === "suspended";
    if (filter === "attention") return ownerBusinessNeedsAttention(business);
    if (filter === "no-admin") return access.status === "ready" && ownerActiveAdmins(business.id).length === 0;
    return true;
  }).sort((left, right) => ownerBusinessPriority(left) - ownerBusinessPriority(right)
    || String(left.name).localeCompare(String(right.name), "es"));
}

function ownerAdminLabel(business) {
  const entry = ownerAccessEntry(business.id);
  if (entry.status === "loading") return "Comprobando…";
  if (entry.status === "error") return "No se pudo comprobar";
  const admins = ownerActiveAdmins(business.id);
  return admins.length ? (admins[0].name || admins[0].email) : "Sin administrador";
}

function ownerChannelSummary(business) {
  const snapshot = ownerBusinessSnapshot(business.id);
  if (!snapshot) return ownerDashboardState.channels.status === "error" ? "No se pudo comprobar" : "Comprobando…";
  const controls = snapshot.controls || [];
  if (!controls.length) return "Sin canales habilitados";
  return controls.map((item) => `${item.channel === "instagram" ? "Instagram" : "WhatsApp"}: ${ownerChannelControlStatusLabel(item.status)}`).join(" · ");
}

function ownerBusinessAlerts(business) {
  const alerts = [];
  const snapshot = ownerBusinessSnapshot(business.id);
  const incidentsForBusiness = ownerBusinessIncidents(business.id);
  const access = ownerAccessEntry(business.id);
  const candidates = (snapshot?.instagramCandidates?.length || 0) + (snapshot?.whatsappCandidates?.length || 0);
  if (candidates) alerts.push(`${candidates} decisión${candidates === 1 ? "" : "es"} pendiente${candidates === 1 ? "" : "s"}`);
  if (incidentsForBusiness?.length) alerts.push(`${incidentsForBusiness.length} incidencia${incidentsForBusiness.length === 1 ? "" : "s"} abierta${incidentsForBusiness.length === 1 ? "" : "s"}`);
  if (access.status === "ready" && !ownerActiveAdmins(business.id).length) alerts.push("Sin administrador activo");
  if (snapshot?.health?.some((item) => OWNER_DASHBOARD_HEALTH_ATTENTION.has(item.health_status))) alerts.push("Canal con atención");
  return alerts.slice(0, 2);
}

function ownerBusinessRow(business) {
  const status = ownerBusinessStatus(business);
  const alerts = ownerBusinessAlerts(business);
  const incidentsForBusiness = ownerBusinessIncidents(business.id);
  const admin = ownerAdminLabel(business);
  const noAdmin = admin === "Sin administrador";
  return `<article class="owner-business-row${ownerBusinessHubState.selectedBusinessId === business.id ? " selected" : ""}" role="listitem" data-business-row-id="${escapeHtml(business.id)}">
    <div class="owner-business-row__identity"><span class="owner-business-avatar" aria-hidden="true">${escapeHtml((business.name || "?").slice(0, 2).toUpperCase())}</span><div><h3>${escapeHtml(business.name)}</h3><p>${escapeHtml(business.slug)}${business.city ? ` · ${escapeHtml(business.city)}` : ""}</p></div></div>
    <div class="owner-business-row__state"><span class="ag-badge ${status === "active" ? "ag-badge--success" : status === "suspended" ? "ag-badge--danger" : "ag-badge--neutral"}">${escapeHtml(ownerBusinessStatusLabel(status))}</span><small>Alta: ${escapeHtml(OWNER_ONBOARDING_STATUSES.has(status) ? ownerBusinessStatusLabel(status) : status === "active" ? "Completada" : "No activa")}</small></div>
    <div class="owner-business-row__context"><p class="${noAdmin ? "owner-text-danger" : ""}"><strong>Administrador</strong>${escapeHtml(admin)}</p><p><strong>Canales</strong>${escapeHtml(ownerChannelSummary(business))}</p><p><strong>Incidencias</strong>${incidentsForBusiness === null ? "No se pudo comprobar" : incidentsForBusiness.length}</p></div>
    <div class="owner-business-row__alerts">${alerts.length ? alerts.map((item) => `<span class="ag-badge ag-badge--warning">${escapeHtml(item)}</span>`).join("") : '<span class="owner-business-ok">Sin alertas prioritarias</span>'}<small>Creado: ${escapeHtml(formatOwnerDate(business.created_at))}</small></div>
    <div class="owner-business-row__actions"><button class="button button-primary button-small" type="button" data-owner-business-open="${escapeHtml(business.id)}">Abrir negocio</button>${OWNER_ONBOARDING_STATUSES.has(status) ? `<button class="button button-secondary button-small" type="button" data-owner-business-onboarding="${escapeHtml(business.id)}">Continuar alta</button>` : ""}<a class="button button-secondary button-small" href="../autonogrow-admin/index.html?b=${encodeURIComponent(business.slug)}" target="_blank" rel="noopener">Abrir Admin</a></div>
  </article>`;
}

function renderOwnerBusinessRows() {
  const list = byId("business-list");
  if (!list) return;
  const filtered = ownerFilteredBusinesses();
  list.setAttribute("aria-busy", "false");
  list.innerHTML = filtered.length
    ? filtered.map(ownerBusinessRow).join("")
    : `<div class="empty-state"><strong>${businesses.length ? "No hay coincidencias" : "Todavía no hay negocios"}</strong><p>${businesses.length ? "Ajusta la búsqueda o el filtro." : "Las altas aparecerán aquí cuando se creen."}</p></div>`;
  byId("list-status").textContent = `${filtered.length} de ${businesses.length} negocio${businesses.length === 1 ? "" : "s"}`;
}

async function loadOwnerBusinessAccessIndex(force = false) {
  const signature = businesses.map((item) => `${item.id}:${item.slug}`).join("|");
  if (!force && signature === ownerBusinessHubState.accessSignature) return;
  ownerBusinessHubState.accessSignature = signature;
  const version = ++ownerBusinessHubState.accessVersion;
  businesses.forEach((business) => {
    if (force || !ownerBusinessHubState.access.has(String(business.id))) ownerBusinessHubState.access.set(String(business.id), { status: "loading", users: [] });
  });
  renderOwnerBusinessRows();
  for (let index = 0; index < businesses.length; index += 4) {
    const batch = await Promise.all(businesses.slice(index, index + 4).map(async (business) => {
      try {
        const body = await ownerHubRequest(`/api/owner/businesses/${encodeURIComponent(business.slug)}/users`, {}, "No se pudieron comprobar los accesos.");
        return [String(business.id), { status: "ready", users: body.users || [] }];
      } catch {
        return [String(business.id), { status: "error", users: [] }];
      }
    }));
    if (version !== ownerBusinessHubState.accessVersion) return;
    batch.forEach(([id, value]) => ownerBusinessHubState.access.set(id, value));
    renderOwnerBusinessRows();
  }
  const failed = Array.from(ownerBusinessHubState.access.values()).filter((item) => item.status === "error").length;
  byId("business-hub-partial").hidden = !failed;
  byId("business-hub-partial").textContent = failed ? `No se pudieron comprobar los accesos de ${failed} negocio${failed === 1 ? "" : "s"}; no se clasifican como sin administrador.` : "";
}

const renderBusinessesLegacy = renderBusinesses;
renderBusinesses = function renderBusinessesHub() {
  renderSummary();
  renderOwnerBusinessRows();
  if (ownerBusinessHubState.selectedBusinessId) renderOwnerBusinessDetail();
  loadOwnerBusinessAccessIndex().catch(() => {
    byId("business-hub-partial").hidden = false;
    byId("business-hub-partial").textContent = "No se pudieron completar los datos de acceso. La lista conserva el resto de fuentes.";
  });
};

function ownerBrandEditor(business) {
  return `<section class="owner-detail-block" data-owner-detail-panel="brand" hidden><header><div><h3>Datos y marca</h3><p>La apariencia se guarda en la fuente Owner existente. Los datos operativos se editan en el Admin del negocio.</p></div><a class="button button-secondary button-small" href="../autonogrow-admin/index.html?b=${encodeURIComponent(business.slug)}#business" target="_blank" rel="noopener">Editar datos en Admin</a></header>
    <div class="owner-data-summary"><p><strong>Categoría</strong>${escapeHtml(business.category || "Sin categoría")}</p><p><strong>Contacto</strong>${escapeHtml(business.phone || business.public_email || "Sin contacto público")}</p><p><strong>Dirección</strong>${escapeHtml([business.address, business.city].filter(Boolean).join(", ") || "Sin dirección")}</p><p><strong>Titular</strong>${escapeHtml(business.headline || "Sin titular")}</p></div>
    <details class="owner-brand-editor" data-owner-editor="${escapeHtml(business.slug)}" open><summary>Apariencia y recursos</summary>
      <div class="owner-brand-grid"><label>Paleta<select data-owner-theme>${paletteOptions(business.theme_key)}</select></label><label>Plantilla<select data-owner-template>${templateOptions(business.template_key)}</select></label><p class="wide helper" data-owner-template-description>${escapeHtml(templateDescription(business.template_key))}</p>${["primary", "secondary", "accent", "background"].map((name, index) => `<label>${name}<span class="owner-color"><input type="color" data-owner-color="${name}" value="${escapeHtml(business[`${name}_color`] || PALETTES.slate_gold[index])}"><input data-owner-hex="${name}" aria-label="Código hexadecimal: ${name}" value="${escapeHtml(business[`${name}_color`] || PALETTES.slate_gold[index])}"></span></label>`).join("")}<label>Texto alternativo del logo<input data-owner-logo-alt value="${escapeHtml(business.logo_alt || "")}"></label></div>
      <div class="owner-upload-row"><input id="owner-logo-input-${escapeHtml(business.slug)}" type="file" accept="image/jpeg,image/png,image/webp" hidden data-owner-media-input="logo" data-slug="${escapeHtml(business.slug)}"><button type="button" class="button button-secondary button-small" data-action="select-logo">Subir logo</button><button type="button" class="button button-danger button-small" data-action="delete-logo">Eliminar logo</button></div>
      <div class="owner-upload-row"><input id="owner-gallery-input-${escapeHtml(business.slug)}" type="file" accept="image/jpeg,image/png,image/webp" hidden data-owner-media-input="gallery" data-slug="${escapeHtml(business.slug)}"><input data-owner-gallery-alt placeholder="Texto alternativo" aria-label="Texto alternativo de la nueva foto"><button type="button" class="button button-secondary button-small" data-action="select-gallery">Subir foto</button></div>
      <div class="owner-gallery" data-owner-gallery><p>Cargando galería…</p></div><button type="button" class="button button-primary button-small" data-owner-brand-save>Guardar apariencia</button><span data-owner-feedback class="status-text"></span>
    </details></section>`;
}

function ownerUsersEditor(business) {
  return `<section class="owner-detail-block" data-owner-detail-panel="users" hidden><header><div><h3>Usuarios y acceso</h3><p>Solo se pueden asignar los roles Administrador y Personal de este negocio.</p></div></header><details class="owner-users-editor" data-owner-users="${escapeHtml(business.slug)}" open><summary>Accesos de ${escapeHtml(business.name)}</summary><div class="owner-user-form"><input data-owner-user-email type="email" autocomplete="email" placeholder="persona@negocio.com" aria-label="Email del usuario"><select data-owner-user-role aria-label="Rol a asignar"><option value="business_admin">Administrador</option><option value="business_staff">Personal</option></select><button type="button" class="button button-primary button-small" data-owner-user-action="add">Asignar usuario</button></div><div data-owner-users-list class="owner-users-list"><p>Cargando usuarios…</p></div><p data-owner-users-feedback class="status-text" role="status"></p></details></section>`;
}

function ownerActivationPanel(business) {
  const status = ownerBusinessStatus(business);
  return `<section class="owner-detail-block" data-owner-detail-panel="activation" hidden><header><div><h3>Activación y estado</h3><p>Onboarding, readiness, publicación y estado comercial se comprueban por separado.</p></div><button class="button button-secondary button-small" type="button" data-owner-readiness-refresh="${escapeHtml(business.id)}">Comprobar readiness</button></header><div class="owner-activation-layers"><p><strong>Onboarding</strong>${escapeHtml(OWNER_ONBOARDING_STATUSES.has(status) ? ownerBusinessStatusLabel(status) : status === "active" ? "Completado" : "No activo")}</p><p><strong>Estado comercial</strong>${escapeHtml(ownerBusinessStatusLabel(status))}</p><p><strong>Página pública</strong>${status === "active" ? "Publicada según la configuración vigente" : "No publicada como negocio activo"}</p><p><strong>Readiness</strong><span data-owner-readiness-summary>Sin comprobar en esta vista</span></p></div><div data-owner-readiness-content class="readiness-list"><p class="owner-empty-inline">Comprueba readiness para ver bloqueos y recomendaciones actuales.</p></div><div data-owner-preview-content></div><div class="owner-detail-actions"><button class="button button-secondary" type="button" data-owner-business-onboarding="${escapeHtml(business.id)}">Volver al onboarding</button><button class="button button-secondary" type="button" data-owner-preview="${escapeHtml(business.id)}">Abrir vista previa</button>${status === "active" ? `<button class="button button-danger" type="button" data-business-state-id="${escapeHtml(business.id)}" data-business-status="active">Suspender negocio</button>` : status === "suspended" ? `<button class="button button-primary" type="button" data-business-state-id="${escapeHtml(business.id)}" data-business-status="suspended">Reactivar negocio</button>` : `<button class="button button-primary" type="button" data-owner-activate="${escapeHtml(business.id)}" disabled>Activar negocio</button>`}</div><p data-owner-activation-feedback class="status-text" role="status"></p></section>`;
}

function ownerChannelsPanel(business) {
  return `<section class="owner-detail-block" data-owner-detail-panel="channels" hidden><header><div><h3>Canales</h3><p>Se conservan por separado candidatura, integración activa, control comercial, capacidades y salud.</p></div><button class="button button-secondary button-small" type="button" data-owner-business-integration="${escapeHtml(business.id)}">Abrir Integraciones</button></header><details class="owner-channel-control-editor" data-owner-channel-control-id="${escapeHtml(business.id)}" open><summary>Control y salud de canales</summary><div data-owner-channel-control-content><p>Cargando permisos…</p></div></details><details class="owner-integration-editor" data-owner-integration-id="${escapeHtml(business.id)}" data-owner-integration-name="${escapeHtml(business.name)}"><summary>Instagram conectado</summary><div data-owner-integration-content><p>Cargando Instagram…</p></div></details><details class="owner-automation-editor" data-owner-automation-id="${escapeHtml(business.id)}" data-owner-automation-name="${escapeHtml(business.name)}"><summary>Plan, automatización y cuota</summary><div data-owner-automation-content><p>Cargando configuración…</p></div></details></section>`;
}

function ownerBusinessActivity(business) {
  const events = [];
  if (business.created_at) events.push({ at: business.created_at, text: "Negocio creado" });
  const access = ownerAccessEntry(business.id);
  if (access.status === "ready") access.users.forEach((item) => { if (item.created_at) events.push({ at: item.created_at, text: `${item.name || item.email} fue asignado como ${item.role === "business_admin" ? "administrador" : "personal"}` }); });
  const snapshot = ownerBusinessSnapshot(business.id);
  (snapshot?.controls || []).forEach((control) => [[control.approved_at, `${control.channel === "instagram" ? "Instagram" : "WhatsApp"} aprobado`], [control.suspended_at, `${control.channel === "instagram" ? "Instagram" : "WhatsApp"} suspendido`], [control.revoked_at, `${control.channel === "instagram" ? "Instagram" : "WhatsApp"} revocado`]].forEach(([at, text]) => { if (at) events.push({ at, text }); }));
  events.sort((left, right) => new Date(right.at) - new Date(left.at));
  return `<section class="owner-detail-block" data-owner-detail-panel="activity" hidden><header><div><h3>Actividad disponible</h3><p>Hitos derivados de fechas reales ya expuestas; este panel no sustituye la auditoría.</p></div></header>${events.length ? `<ol class="owner-activity-list">${events.slice(0, 12).map((item) => `<li><span>${escapeHtml(item.text)}</span><time datetime="${escapeHtml(item.at)}">${escapeHtml(formatOwnerDate(item.at))}</time></li>`).join("")}</ol>` : '<div class="empty-state">No hay hitos disponibles en estas fuentes.</div>'}${access.status === "error" ? '<p class="owner-partial-notice">No se pudo cargar la actividad de accesos.</p>' : ""}</section>`;
}

function ownerBusinessSummary(business) {
  const status = ownerBusinessStatus(business);
  const health = business.health || {};
  const incidentsForBusiness = ownerBusinessIncidents(business.id);
  return `<section class="owner-detail-block" data-owner-detail-panel="summary"><div class="owner-detail-hero"><div><p class="eyebrow">${escapeHtml(business.category || "Negocio")}</p><h3>${escapeHtml(business.name)}</h3><p>${escapeHtml(business.slug)}${business.city ? ` · ${escapeHtml(business.city)}` : ""}</p></div><span class="ag-badge ${status === "active" ? "ag-badge--success" : status === "suspended" ? "ag-badge--danger" : "ag-badge--neutral"}">${escapeHtml(ownerBusinessStatusLabel(status))}</span></div><div class="owner-data-summary"><p><strong>Alta</strong>${escapeHtml(OWNER_ONBOARDING_STATUSES.has(status) ? ownerBusinessStatusLabel(status) : "Completada")}</p><p><strong>Publicación</strong>${status === "active" ? "Activa" : "No activa"}</p><p><strong>Administrador</strong>${escapeHtml(ownerAdminLabel(business))}</p><p><strong>Servicios</strong>${health.has_active_services ? "Configurados" : "Pendientes"}</p><p><strong>Horarios</strong>${health.has_schedule ? "Configurados" : "Pendientes"}</p><p><strong>Canales</strong>${escapeHtml(ownerChannelSummary(business))}</p><p><strong>Incidencias</strong>${incidentsForBusiness === null ? "No se pudo comprobar" : incidentsForBusiness.length}</p><p><strong>Creado</strong>${escapeHtml(formatOwnerDate(business.created_at))}</p></div><div class="owner-detail-actions"><a class="button button-secondary" href="../autonogrow-admin/index.html?b=${encodeURIComponent(business.slug)}" target="_blank" rel="noopener">Abrir Business Admin</a><a class="button button-secondary" href="../autonogrow-landing/index.html?b=${encodeURIComponent(business.slug)}" target="_blank" rel="noopener">Abrir página pública</a><button class="button button-secondary" type="button" data-owner-detail-go="users">Revisar accesos</button><button class="button button-secondary" type="button" data-owner-detail-go="activation">Revisar activación</button><button class="button button-secondary" type="button" data-owner-business-integration="${escapeHtml(business.id)}">Abrir Integraciones</button></div></section>`;
}

function renderOwnerBusinessDetail() {
  const detail = byId("business-detail");
  const business = businesses.find((item) => String(item.id) === String(ownerBusinessHubState.selectedBusinessId));
  if (!detail || !business) { if (detail) detail.hidden = true; return; }
  detail.hidden = false;
  detail.innerHTML = `<header class="owner-business-detail__header"><div><p class="eyebrow">Detalle del negocio</p><h2 id="business-detail-title">${escapeHtml(business.name)}</h2></div><button class="button button-secondary button-small" type="button" data-owner-detail-close>Volver a la lista</button></header><nav class="owner-secondary-nav" aria-label="Detalle de ${escapeHtml(business.name)}">${[["summary", "Resumen"], ["brand", "Datos y marca"], ["users", "Usuarios y acceso"], ["activation", "Activación"], ["channels", "Canales"], ["activity", "Actividad"]].map(([key, label]) => `<button type="button" data-owner-detail-tab="${key}"${ownerBusinessHubState.detailSection === key ? ' class="active" aria-current="page"' : ""}>${label}</button>`).join("")}</nav><div class="owner-business-detail__content">${ownerBusinessSummary(business)}${ownerBrandEditor(business)}${ownerUsersEditor(business)}${ownerActivationPanel(business)}${ownerChannelsPanel(business)}${ownerBusinessActivity(business)}</div>`;
  activateOwnerBusinessDetailSection(ownerBusinessHubState.detailSection, false);
}

function activateOwnerBusinessDetailSection(section, focus = true) {
  const detail = byId("business-detail");
  if (!detail) return;
  const allowed = new Set(["summary", "brand", "users", "activation", "channels", "activity"]);
  ownerBusinessHubState.detailSection = allowed.has(section) ? section : "summary";
  detail.querySelectorAll("[data-owner-detail-panel]").forEach((panel) => { panel.hidden = panel.dataset.ownerDetailPanel !== ownerBusinessHubState.detailSection; });
  detail.querySelectorAll("[data-owner-detail-tab]").forEach((button) => {
    const active = button.dataset.ownerDetailTab === ownerBusinessHubState.detailSection;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  });
  const panel = detail.querySelector(`[data-owner-detail-panel="${ownerBusinessHubState.detailSection}"]`);
  if (ownerBusinessHubState.detailSection === "brand") panel.querySelectorAll("[data-owner-editor]").forEach(loadOwnerGallery);
  if (ownerBusinessHubState.detailSection === "users") panel.querySelectorAll("[data-owner-users]").forEach(loadOwnerUsers);
  if (ownerBusinessHubState.detailSection === "activation") loadOwnerBusinessReadiness(ownerBusinessHubState.selectedBusinessId).catch((error) => { panel.querySelector("[data-owner-activation-feedback]").textContent = error.message; });
  if (ownerBusinessHubState.detailSection === "channels") {
    panel.querySelectorAll("[data-owner-channel-control-id]").forEach(loadOwnerChannelControls);
    panel.querySelectorAll("[data-owner-integration-id]").forEach(loadOwnerIntegration);
    panel.querySelectorAll("[data-owner-automation-id]").forEach(loadOwnerAutomation);
  }
  if (focus) { panel?.querySelector("h3")?.setAttribute("tabindex", "-1"); panel?.querySelector("h3")?.focus({ preventScroll: true }); }
}

function openBusinessDetail(businessId, section = "summary") {
  const business = businesses.find((item) => String(item.id) === String(businessId));
  if (!business) return;
  ownerBusinessHubState.selectedBusinessId = business.id;
  ownerBusinessHubState.detailSection = section;
  renderOwnerBusinessRows();
  renderOwnerBusinessDetail();
  byId("business-detail").scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  byId("business-detail-title")?.focus?.({ preventScroll: true });
}

async function loadOwnerBusinessReadiness(businessId, force = false) {
  const panel = byId("business-detail")?.querySelector('[data-owner-detail-panel="activation"]');
  if (!panel) return null;
  panel.setAttribute("aria-busy", "true");
  try {
    const readiness = !force && ownerBusinessHubState.onboarding.get(String(businessId))?.readiness
      ? ownerBusinessHubState.onboarding.get(String(businessId)).readiness
      : await ownerHubRequest(`/api/owner/businesses/${encodeURIComponent(businessId)}/readiness`, {}, "No se pudo comprobar readiness.");
    const cached = ownerBusinessHubState.onboarding.get(String(businessId)) || {};
    ownerBusinessHubState.onboarding.set(String(businessId), { ...cached, readiness });
    panel.querySelector("[data-owner-readiness-summary]").textContent = readiness.ready ? "Lista para activar" : `Bloqueada por ${readiness.blocking_count} comprobaciones`;
    panel.querySelector("[data-owner-readiness-content]").innerHTML = (readiness.checks || []).map((item) => `<article class="readiness-item ${escapeHtml(item.status)}"><div><strong>${escapeHtml(item.label)}</strong><span class="ag-badge ${item.blocking ? "ag-badge--danger" : item.status === "warning" ? "ag-badge--warning" : "ag-badge--success"}">${item.blocking ? "Bloqueante" : item.status === "warning" ? "Recomendado" : item.status === "passed" ? "Correcto" : "No se pudo comprobar"}</span></div><p>${escapeHtml(item.message)}</p><small>${escapeHtml(item.remediation || "Sin acción necesaria")}</small>${item.related_step ? `<button class="owner-metric-link" type="button" data-owner-readiness-step="${escapeHtml(item.related_step)}">Resolver en onboarding</button>` : ""}</article>`).join("") || '<p class="owner-empty-inline">No hay comprobaciones disponibles.</p>';
    const activate = panel.querySelector("[data-owner-activate]");
    if (activate) activate.disabled = !readiness.ready;
    return readiness;
  } finally {
    panel.removeAttribute("aria-busy");
  }
}

async function showOwnerBusinessPreview(businessId) {
  const panel = byId("business-detail").querySelector('[data-owner-detail-panel="activation"]');
  const target = panel.querySelector("[data-owner-preview-content]");
  target.innerHTML = '<div class="owner-loading-inline"><span class="ag-loader" aria-hidden="true"></span> Cargando vista previa…</div>';
  try {
    const preview = await ownerHubRequest(`/api/owner/businesses/${encodeURIComponent(businessId)}/preview`, {}, "No se pudo abrir la vista previa.");
    target.innerHTML = `<article class="owner-preview-card"><span class="ag-badge ag-badge--neutral">Vista previa · noindex</span><h4>${escapeHtml(preview.business.name)}</h4><p>${escapeHtml(preview.business.headline || "Sin titular")}</p><p><strong>Esta página todavía no está publicada.</strong> Las reservas permanecen deshabilitadas hasta activar el negocio y no se consumen créditos.</p><div class="owner-detail-actions"><button class="button button-secondary button-small" type="button" data-owner-business-onboarding="${escapeHtml(businessId)}">Volver al onboarding</button><button class="button button-secondary button-small" type="button" data-owner-readiness-refresh="${escapeHtml(businessId)}">Revisar bloqueos</button></div></article>`;
  } catch (error) {
    target.innerHTML = `<div class="error-box">${escapeHtml(error.message)}</div>`;
  }
}

async function refreshOwnerBusinessContext() {
  const selected = ownerBusinessHubState.selectedBusinessId;
  ownerBusinessHubState.accessSignature = "";
  await loadOwnerDashboardBusinesses();
  await Promise.allSettled([loadOwnerDashboardChannels(), loadOwnerDashboardIncidents(), loadOwnerBusinessAccessIndex(true)]);
  ownerBusinessHubState.selectedBusinessId = selected && businesses.some((item) => String(item.id) === String(selected)) ? selected : null;
  renderBusinesses();
}

/* Diálogo crítico accesible y no optimista. */
let ownerCriticalDialogState = null;

function closeOwnerCriticalDialog(result) {
  const dialog = byId("owner-critical-dialog");
  if (!ownerCriticalDialogState || ownerCriticalDialogState.busy) return;
  const state = ownerCriticalDialogState;
  ownerCriticalDialogState = null;
  dialog.hidden = true;
  document.body.classList.remove("owner-dialog-open");
  state.returnFocus?.focus?.();
  state.resolve(result);
}

function confirmOwnerCriticalAction(config) {
  if (ownerCriticalDialogState) return Promise.resolve(false);
  const dialog = byId("owner-critical-dialog");
  byId("owner-dialog-title").textContent = config.title;
  byId("owner-dialog-kicker").textContent = config.kicker || "Acción crítica";
  byId("owner-dialog-context").innerHTML = [["Recurso", config.resource], ["Estado actual", config.current], ["Resultado", config.next], ...(config.context || [])].filter(([, value]) => value).map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
  byId("owner-dialog-consequence").textContent = config.consequence;
  byId("owner-dialog-reason-field").hidden = config.requiresReason === false;
  byId("owner-dialog-reason").value = config.reason || "";
  byId("owner-dialog-error").textContent = "";
  byId("owner-dialog-confirm").textContent = config.confirmLabel || "Confirmar";
  byId("owner-dialog-confirm").className = `button ${config.danger === false ? "button-primary" : "button-danger"}`;
  dialog.hidden = false;
  document.body.classList.add("owner-dialog-open");
  return new Promise((resolve) => {
    ownerCriticalDialogState = { config, resolve, returnFocus: document.activeElement, busy: false };
    window.requestAnimationFrame(() => (config.requiresReason === false ? byId("owner-dialog-confirm") : byId("owner-dialog-reason")).focus());
  });
}

async function submitOwnerCriticalDialog() {
  const state = ownerCriticalDialogState;
  if (!state || state.busy) return;
  const reason = byId("owner-dialog-reason").value.trim();
  if (state.config.requiresReason !== false && reason.length < 3) { byId("owner-dialog-error").textContent = "Escribe un motivo de al menos 3 caracteres."; byId("owner-dialog-reason").focus(); return; }
  state.busy = true;
  byId("owner-dialog-confirm").disabled = true;
  byId("owner-dialog-cancel").disabled = true;
  byId("owner-dialog-close").disabled = true;
  byId("owner-dialog-error").textContent = "Guardando y esperando confirmación del servidor…";
  try {
    await state.config.action(reason);
    state.busy = false;
    byId("owner-dialog-confirm").disabled = false;
    byId("owner-dialog-cancel").disabled = false;
    byId("owner-dialog-close").disabled = false;
    closeOwnerCriticalDialog(true);
  } catch (error) {
    state.busy = false;
    byId("owner-dialog-confirm").disabled = false;
    byId("owner-dialog-cancel").disabled = false;
    byId("owner-dialog-close").disabled = false;
    byId("owner-dialog-error").textContent = error.message || "No se pudo confirmar la acción.";
  }
}

byId("owner-dialog-confirm").addEventListener("click", submitOwnerCriticalDialog);
byId("owner-dialog-cancel").addEventListener("click", () => closeOwnerCriticalDialog(false));
byId("owner-dialog-close").addEventListener("click", () => closeOwnerCriticalDialog(false));
byId("owner-critical-dialog").addEventListener("keydown", (event) => {
  if (event.key === "Escape") { event.preventDefault(); closeOwnerCriticalDialog(false); return; }
  if (event.key !== "Tab") return;
  const focusable = Array.from(event.currentTarget.querySelectorAll('button:not(:disabled), textarea:not(:disabled), input:not(:disabled), select:not(:disabled), a[href]')).filter((item) => !item.hidden && !item.closest("[hidden]"));
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});

/* Usuarios: el último administrador se protege en la interfaz sin ampliar backend. */
loadOwnerUsers = async function loadOwnerUsersHub(panel) {
  const slug = panel.dataset.ownerUsers;
  const business = businesses.find((item) => item.slug === slug);
  const feedback = panel.querySelector("[data-owner-users-feedback]");
  try {
    const body = await ownerHubRequest(`/api/owner/businesses/${encodeURIComponent(slug)}/users`, {}, "No se pudieron cargar los usuarios.");
    const users = body.users || [];
    if (business) ownerBusinessHubState.access.set(String(business.id), { status: "ready", users });
    const admins = users.filter((item) => item.active && item.role === "business_admin");
    panel.querySelector("[data-owner-users-list]").innerHTML = users.length ? users.map((item) => {
      const lastAdmin = item.active && item.role === "business_admin" && admins.length === 1;
      return `<article data-business-user-id="${escapeHtml(item.id)}" data-current-role="${escapeHtml(item.role)}" data-user-active="${item.active ? "true" : "false"}" data-user-name="${escapeHtml(item.name || item.email)}"><div><strong>${escapeHtml(item.name || item.email)}</strong><span>${escapeHtml(item.email)}</span><small>${item.active ? "Acceso activo" : "Acceso desactivado"} · ${item.pending ? "Pendiente de vincular Google" : "Cuenta vinculada"}${item.created_at ? ` · Asignado ${escapeHtml(formatOwnerDate(item.created_at))}` : ""}</small>${lastAdmin ? '<span class="owner-last-admin">Último administrador activo protegido</span>' : ""}</div><select data-membership-role aria-label="Rol de ${escapeHtml(item.name || item.email)}"><option value="business_admin" ${item.role === "business_admin" ? "selected" : ""}>Administrador</option><option value="business_staff" ${item.role === "business_staff" ? "selected" : ""}>Personal</option></select><button type="button" class="button button-secondary button-small" data-owner-user-action="save">${item.active ? "Guardar cambio" : "Reactivar"}</button><button type="button" class="button button-danger button-small" data-owner-user-action="deactivate" ${item.active && !lastAdmin ? "" : "disabled"}>Desactivar</button></article>`;
    }).join("") : '<div class="empty-state"><strong>Sin usuarios asignados</strong><p>Asigna al menos un administrador funcional.</p></div>';
    feedback.textContent = admins.length ? "" : "Este negocio no tiene administrador activo.";
    renderOwnerBusinessRows();
  } catch (error) {
    if (business) ownerBusinessHubState.access.set(String(business.id), { status: "error", users: ownerAccessEntry(business.id).users || [] });
    feedback.textContent = error.message;
  }
};

handleOwnerUserAction = async function handleOwnerUserCriticalAction(button) {
  const panel = button.closest("[data-owner-users]");
  const business = businesses.find((item) => item.slug === panel.dataset.ownerUsers);
  if (!business) return;
  const feedback = panel.querySelector("[data-owner-users-feedback]");
  const action = button.dataset.ownerUserAction;
  const row = button.closest("[data-business-user-id]");
  const users = ownerAccessEntry(business.id).users;
  let url = `/api/owner/businesses/${encodeURIComponent(business.slug)}/users`;
  let options;
  let config;
  if (action === "add") {
    const email = panel.querySelector("[data-owner-user-email]").value.trim();
    const role = panel.querySelector("[data-owner-user-role]").value;
    if (!email) { feedback.textContent = "Introduce un email válido."; return; }
    options = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, role }) };
    config = { title: "Asignar acceso", resource: email, current: "Sin acceso a este negocio", next: role === "business_admin" ? "Administrador" : "Personal", consequence: `${email} podrá acceder únicamente a ${business.name} con el rol seleccionado. Este flujo nunca concede permisos Owner.`, confirmLabel: "Asignar usuario", danger: false, requiresReason: false };
  } else {
    const currentRole = row.dataset.currentRole;
    const active = row.dataset.userActive === "true";
    const nextRole = row.querySelector("[data-membership-role]").value;
    const name = row.dataset.userName;
    const activeAdmins = users.filter((item) => item.active && item.role === "business_admin");
    if (active && currentRole === "business_admin" && activeAdmins.length === 1 && (action === "deactivate" || nextRole !== "business_admin")) {
      feedback.textContent = "No puedes desactivar ni degradar al último administrador activo. Asigna otro administrador primero.";
      row.querySelector("[data-membership-role]").value = "business_admin";
      return;
    }
    url += `/${encodeURIComponent(row.dataset.businessUserId)}`;
    if (action === "deactivate") {
      options = { method: "DELETE" };
      config = { title: "Desactivar acceso", resource: name, current: currentRole === "business_admin" ? "Administrador activo" : "Personal activo", next: "Sin acceso activo", consequence: `${name} dejará de acceder a ${business.name}. Su cuenta y los datos del negocio se conservan; el acceso Owner no se modifica desde aquí.`, confirmLabel: "Desactivar acceso", requiresReason: false };
    } else {
      options = { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role: nextRole, active: true }) };
      const changingRole = active && currentRole !== nextRole;
      config = { title: active ? "Cambiar rol" : "Reactivar acceso", resource: name, current: active ? (currentRole === "business_admin" ? "Administrador" : "Personal") : "Acceso desactivado", next: nextRole === "business_admin" ? "Administrador activo" : "Personal activo", consequence: changingRole ? `${name} ${nextRole === "business_admin" ? "podrá administrar" : "dejará de administrar y conservará acceso como personal a"} ${business.name}.` : `${name} recuperará el acceso a ${business.name} con el rol indicado.`, confirmLabel: active ? "Guardar cambio" : "Reactivar acceso", danger: changingRole && nextRole === "business_staff", requiresReason: false };
    }
  }
  const confirmed = await confirmOwnerCriticalAction({ ...config, context: [["Negocio", business.name]], action: (reason) => ownerHubRequest(url, { ...options, headers: { ...(options.headers || {}), ...(options.method === "DELETE" ? {} : {}) } }, "No se pudo actualizar el acceso.") });
  if (!confirmed) return;
  feedback.textContent = "Accesos actualizados.";
  await loadOwnerUsers(panel);
  await refreshOwnerBusinessContext();
};

changeBusinessState = async function changeBusinessStateCritical(businessId, status) {
  if (!["active", "suspended"].includes(status)) { await openOwnerOnboarding(businessId); return; }
  const business = businesses.find((item) => String(item.id) === String(businessId));
  if (!business) return;
  const suspending = status === "active";
  const action = suspending ? "suspend" : "reactivate";
  const confirmed = await confirmOwnerCriticalAction({
    title: suspending ? "Suspender negocio" : "Reactivar negocio",
    resource: business.name,
    current: suspending ? "Activo" : "Suspendido",
    next: suspending ? "Suspendido" : "Activo",
    consequence: suspending
      ? "El negocio dejará de figurar como activo. Sus datos y accesos se conservan; los canales, capacidades y automatizaciones mantienen sus controles independientes."
      : "El servidor volverá a comprobar readiness antes de recuperar el estado activo. No se habilitarán canales ni automatizaciones automáticamente.",
    confirmLabel: suspending ? "Suspender negocio" : "Reactivar negocio",
    danger: suspending,
    action: (reason) => ownerHubRequest(`/api/owner/businesses/${encodeURIComponent(businessId)}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }) }, "No se pudo cambiar el estado del negocio."),
  });
  if (confirmed) await refreshOwnerBusinessContext();
};

async function activateOwnerBusiness(businessId) {
  const business = businesses.find((item) => String(item.id) === String(businessId));
  const readiness = await loadOwnerBusinessReadiness(businessId, true);
  if (!business || !readiness?.ready) return;
  const confirmed = await confirmOwnerCriticalAction({ title: "Activar negocio", resource: business.name, current: ownerBusinessStatusLabel(ownerBusinessStatus(business)), next: "Activo", consequence: "La página pública dejará de estar en noindex y el negocio podrá operar según su configuración vigente. Los canales y automatizaciones conservan sus controles actuales.", confirmLabel: "Activar negocio", danger: false, action: (reason) => ownerHubRequest(`/api/owner/businesses/${encodeURIComponent(businessId)}/activate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason, expected_readiness_version: readiness.version }) }, "No se pudo activar el negocio.") });
  if (confirmed) await refreshOwnerBusinessContext();
}

/* Altas y aprobaciones. */
function ownerOnboardingProgress(session) {
  const completed = new Set([...(session.completed_steps || []), ...(session.skipped_steps || [])]);
  return { completed: completed.size, total: Object.keys(session.steps || {}).length || window.OWNER_ONBOARDING_STEPS?.length || 15 };
}

function ownerOnboardingStateLabel(entry, business) {
  if (ownerBusinessStatus(business) === "active") return "Activada";
  if (!entry?.session) return "No iniciada";
  if (entry.readiness?.ready) return "Lista para activar";
  if (entry.readiness?.blocking_count) return "Bloqueada";
  if (entry.session.status === "blocked") return "Bloqueada";
  if (entry.session.current_step === "readiness_review") return "Lista para revisar";
  return "En curso";
}

function renderOwnerOnboardingList() {
  const target = byId("owner-onboarding-list");
  if (!target) return;
  const pending = businesses.filter((item) => OWNER_ONBOARDING_STATUSES.has(ownerBusinessStatus(item)));
  target.setAttribute("aria-busy", "false");
  if (!pending.length) { target.innerHTML = '<div class="empty-state"><strong>No hay altas en curso</strong><p>Las nuevas altas aparecerán aquí sin mezclarse con incidencias.</p></div>'; return; }
  target.innerHTML = pending.map((business) => {
    const entry = ownerBusinessHubState.onboarding.get(String(business.id));
    if (!entry || entry.status === "loading") return `<article class="owner-onboarding-row"><div><h4>${escapeHtml(business.name)}</h4><p>Cargando pasos reales…</p></div><span class="ag-loader" aria-hidden="true"></span></article>`;
    if (entry.status === "error") return `<article class="owner-onboarding-row"><div><h4>${escapeHtml(business.name)}</h4><p>No se pudo cargar esta alta. El resto permanece disponible.</p></div><button class="button button-secondary button-small" type="button" data-owner-onboarding-retry="${escapeHtml(business.id)}">Reintentar</button></article>`;
    const progress = ownerOnboardingProgress(entry.session);
    const blockers = entry.readiness ? `${entry.readiness.blocking_count} bloqueo${entry.readiness.blocking_count === 1 ? "" : "s"}` : "Readiness sin comprobar";
    const step = window.ownerOnboardingStepLabel?.(entry.session.current_step) || "Paso no disponible";
    return `<article class="owner-onboarding-row"><div><h4>${escapeHtml(business.name)}</h4><p><strong>${escapeHtml(ownerOnboardingStateLabel(entry, business))}</strong> · Paso actual: ${escapeHtml(step)}</p><p>${progress.completed} de ${progress.total} pasos · ${escapeHtml(blockers)}</p><small>Última actualización: ${escapeHtml(formatOwnerDate(entry.session.last_activity_at))}</small></div><div class="owner-onboarding-row__actions"><button class="button button-primary button-small" type="button" data-owner-business-onboarding="${escapeHtml(business.id)}">Continuar alta</button><button class="button button-secondary button-small" type="button" data-owner-onboarding-readiness="${escapeHtml(business.id)}">Revisar readiness</button></div></article>`;
  }).join("");
}

async function loadOwnerOnboardingEntry(business, version) {
  ownerBusinessHubState.onboarding.set(String(business.id), { status: "loading" });
  renderOwnerOnboardingList();
  const results = await Promise.allSettled([
    ownerHubRequest(`/api/owner/businesses/${encodeURIComponent(business.id)}/onboarding`, {}, "No se pudo cargar el onboarding."),
    ownerHubRequest(`/api/owner/businesses/${encodeURIComponent(business.id)}/readiness`, {}, "No se pudo comprobar readiness."),
  ]);
  if (version !== ownerBusinessHubState.onboardingVersion) return;
  if (results[0].status === "rejected") ownerBusinessHubState.onboarding.set(String(business.id), { status: "error" });
  else ownerBusinessHubState.onboarding.set(String(business.id), { status: "ready", session: results[0].value.onboarding, readiness: results[1].status === "fulfilled" ? results[1].value : null, readinessError: results[1].status === "rejected" });
  renderOwnerOnboardingList();
}

async function loadOwnerOnboardingHub(force = false) {
  if (!byId("owner-onboarding-list")) return;
  const version = force ? ++ownerBusinessHubState.onboardingVersion : ownerBusinessHubState.onboardingVersion || ++ownerBusinessHubState.onboardingVersion;
  renderOwnerApprovalsHub();
  const pending = businesses.filter((item) => OWNER_ONBOARDING_STATUSES.has(ownerBusinessStatus(item)));
  if (!pending.length) { renderOwnerOnboardingList(); return; }
  byId("owner-onboarding-hub-status").textContent = "Comprobando pasos y readiness…";
  for (let index = 0; index < pending.length; index += 4) {
    const slice = pending.slice(index, index + 4).filter((item) => force || !ownerBusinessHubState.onboarding.has(String(item.id)));
    await Promise.all(slice.map((business) => loadOwnerOnboardingEntry(business, version)));
  }
  if (version === ownerBusinessHubState.onboardingVersion) byId("owner-onboarding-hub-status").textContent = `Actualizado ${new Intl.DateTimeFormat("es-ES", { timeStyle: "short" }).format(new Date())}`;
}

function ownerCandidateItems() {
  const items = [];
  (ownerDashboardState.channels.data || []).forEach((snapshot) => {
    (snapshot.instagramCandidates || []).forEach((candidate) => items.push({ business: snapshot.business, channel: "instagram", candidate, snapshot }));
    (snapshot.whatsappCandidates || []).forEach((candidate) => items.push({ business: snapshot.business, channel: "whatsapp", candidate, snapshot }));
  });
  return items.sort((left, right) => new Date(right.candidate.created_at || 0) - new Date(left.candidate.created_at || 0));
}

function ownerCandidatePublicName(item) {
  return item.channel === "instagram"
    ? item.candidate.candidate_external_account_name || "Cuenta profesional sin nombre público"
    : item.candidate.candidate_verified_name || item.candidate.candidate_display_phone_number_redacted || "Cuenta de WhatsApp verificada";
}

function ownerCandidateHasPrevious(item) {
  const control = (item.snapshot.controls || []).find((entry) => entry.channel === item.channel);
  const health = (item.snapshot.health || []).find((entry) => entry.channel === item.channel);
  return item.candidate.purpose === "replacement" || Boolean(health) || ["approved", "suspended", "revoked"].includes(control?.status);
}

function renderOwnerApprovalsHub() {
  const target = byId("owner-approvals-list");
  if (!target) return;
  const items = ownerCandidateItems();
  byId("owner-approvals-count").textContent = ownerDashboardState.channels.status === "error" ? "—" : items.length;
  target.setAttribute("aria-busy", "false");
  const sourceWarning = ownerDashboardState.channels.status === "error"
    ? '<div class="error-box">No se pudieron comprobar las candidaturas. No se afirma que la cola esté vacía.</div>'
    : ownerDashboardState.channels.errors ? `<p class="owner-partial-notice">${ownerDashboardState.channels.errors} negocio${ownerDashboardState.channels.errors === 1 ? "" : "s"} tiene fuentes parciales; Instagram y WhatsApp disponibles se muestran por separado.</p>` : "";
  target.innerHTML = sourceWarning + (items.length ? items.map((item) => {
    const previous = ownerCandidateHasPrevious(item);
    return `<article class="owner-approval-row"><div><span class="ag-badge ag-badge--warning">Pendiente de revisión</span><h4>${escapeHtml(item.business.name)}</h4><p><strong>${item.channel === "instagram" ? "Instagram" : "WhatsApp"}</strong> · ${escapeHtml(ownerCandidatePublicName(item))}</p><p>${previous ? "La conexión actual seguirá funcionando hasta que apruebes la nueva candidatura." : "La aprobación decidirá qué cuenta queda conectada; las capacidades comerciales seguirán bajo su control independiente."}</p><small>Solicitada: ${escapeHtml(formatOwnerDate(item.candidate.created_at))}</small></div><button class="button button-primary button-small" type="button" data-owner-candidate-review="${escapeHtml(item.candidate.id)}" data-owner-candidate-business="${escapeHtml(item.business.id)}" data-owner-candidate-channel="${item.channel}">Revisar</button></article>`;
  }).join("") : ownerDashboardState.channels.status === "error" ? "" : '<div class="empty-state"><strong>No hay decisiones pendientes</strong><p>Las candidaturas de Instagram y WhatsApp aparecerán aquí.</p></div>');
}

async function openOwnerCandidateReview(item) {
  ownerBusinessHubState.currentCandidate = item;
  const panel = byId("owner-candidate-review");
  panel.hidden = false;
  panel.setAttribute("aria-busy", "true");
  let activeIntegration = null;
  let activeIntegrationError = false;
  if (item.channel === "instagram") {
    try { activeIntegration = await ownerHubRequest(`/api/owner/businesses/${encodeURIComponent(item.business.id)}/integrations/instagram`, {}, "No se pudo comprobar la integración activa."); }
    catch (error) { if (!String(error.message).includes("ya no está disponible")) activeIntegrationError = true; }
  }
  const previous = item.channel === "instagram" ? Boolean(activeIntegration) : ownerCandidateHasPrevious(item);
  const control = (item.snapshot.controls || []).find((entry) => entry.channel === item.channel);
  const health = (item.snapshot.health || []).find((entry) => entry.channel === item.channel);
  panel.innerHTML = `<header><div><p class="eyebrow">Revisión de candidatura</p><h3 id="owner-candidate-review-title">${item.channel === "instagram" ? "Instagram" : "WhatsApp"} · ${escapeHtml(item.business.name)}</h3></div><button class="button button-secondary button-small" type="button" data-owner-candidate-close>Cerrar revisión</button></header>${activeIntegrationError ? '<p class="owner-partial-notice">No se pudo comprobar la conexión anterior; no se modifica mientras revisas la candidatura.</p>' : ""}<div class="owner-candidate-layers"><article><span>Candidatura</span><strong>Pendiente de revisión</strong><p>${escapeHtml(ownerCandidatePublicName(item))}</p><small>Solicitada ${escapeHtml(formatOwnerDate(item.candidate.created_at))}</small></article><article><span>Integración activa</span><strong>${previous ? "Existe una conexión anterior" : "No consta una conexión anterior"}</strong><p>${previous ? "Se conserva hasta confirmar la aprobación." : "No se sustituirá ninguna conexión conocida."}</p></article><article><span>Control comercial</span><strong>${escapeHtml(control ? ownerChannelControlStatusLabel(control.status) : "No comprobado")}</strong><p>Envío: ${control?.integrated_delivery_enabled ? "habilitado" : "deshabilitado"} · Automatización: ${control?.automation_enabled ? "habilitada" : "deshabilitada"}</p></article><article><span>Salud conocida</span><strong>${escapeHtml(health ? ownerHealthLabel(health.health_status) : "No comprobada")}</strong><p>La salud no equivale a aprobación ni a capacidad de envío.</p></article></div><div class="owner-candidate-explanation"><h4>Consecuencia de la decisión</h4><p>${previous ? "La conexión actual seguirá funcionando hasta que apruebes la nueva. " : ""}Aprobar promoverá esta candidatura según el reemplazo seguro del servidor. No habilita por sí solo envío ni automatización. Rechazar descarta la candidatura y conserva cualquier integración anterior.</p></div><div class="owner-detail-actions"><button class="button button-secondary" type="button" data-owner-candidate-business-link="${escapeHtml(item.business.id)}">Abrir negocio</button><button class="button button-danger" type="button" data-owner-candidate-decision="reject">Rechazar candidatura</button><button class="button button-primary" type="button" data-owner-candidate-decision="approve"${item.channel === "instagram" && item.candidate.webhook_subscription_status !== "subscribed" ? " disabled" : ""}>Aprobar candidatura</button></div><p data-owner-candidate-feedback class="status-text" role="status"></p>`;
  panel.removeAttribute("aria-busy");
  panel.querySelector("h3").setAttribute("tabindex", "-1");
  panel.querySelector("h3").focus();
}

async function decideOwnerCandidate(item, decision) {
  const approving = decision === "approve";
  const previous = ownerCandidateHasPrevious(item);
  const endpoint = item.channel === "instagram"
    ? `/api/owner/businesses/${encodeURIComponent(item.business.id)}/integrations/instagram/oauth/candidates/${encodeURIComponent(item.candidate.id)}/${decision}`
    : `/api/owner/businesses/${encodeURIComponent(item.business.id)}/integrations/whatsapp/embedded-signup/candidates/${encodeURIComponent(item.candidate.id)}/${decision}`;
  const confirmed = await confirmOwnerCriticalAction({ title: `${approving ? "Aprobar" : "Rechazar"} candidatura de ${item.channel === "instagram" ? "Instagram" : "WhatsApp"}`, resource: ownerCandidatePublicName(item), current: "Candidatura pendiente", next: approving ? "Candidatura aprobada" : "Candidatura rechazada", context: [["Negocio", item.business.name], ["Integración anterior", previous ? "Se conserva hasta confirmar" : "No consta"]], consequence: approving ? `${previous ? "La conexión anterior se conservará hasta que el servidor confirme el reemplazo. " : ""}La candidatura quedará activa, pero envío y automatización no se habilitarán automáticamente.` : "La candidatura se descartará. Cualquier integración activa anterior se conservará y no se revocará.", confirmLabel: approving ? "Aprobar candidatura" : "Rechazar candidatura", danger: !approving, action: (reason) => ownerHubRequest(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }) }, "No se pudo registrar la decisión.") });
  if (!confirmed) return;
  byId("owner-candidate-review").hidden = true;
  ownerBusinessHubState.currentCandidate = null;
  await loadOwnerDashboardChannels();
  renderOwnerApprovalsHub();
  renderOwnerBusinessRows();
  if (ownerBusinessHubState.selectedBusinessId) renderOwnerBusinessDetail();
}

function setOwnerHubView(view) {
  ownerBusinessHubState.hubView = view === "approvals" ? "approvals" : "onboarding";
  document.querySelectorAll("[data-owner-hub-view]").forEach((button) => { const active = button.dataset.ownerHubView === ownerBusinessHubState.hubView; button.classList.toggle("active", active); if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current"); });
  document.querySelectorAll("[data-owner-hub-panel]").forEach((panel) => { panel.hidden = panel.dataset.ownerHubPanel !== ownerBusinessHubState.hubView; });
}

function openOwnerApprovalContext(businessId, channel) {
  setOwnerHubView("approvals");
  const item = ownerCandidateItems().find((candidate) => String(candidate.business.id) === String(businessId) && (!channel || candidate.channel === channel));
  if (item) openOwnerCandidateReview(item);
  else {
    byId("owner-approvals-list").focus?.();
    byId("owner-onboarding-hub-status").textContent = "La decisión ya no está pendiente o no pudo comprobarse. Actualiza para confirmar.";
  }
}

const legacyOwnerIntegrationAction = handleOwnerIntegrationAction;
handleOwnerIntegrationAction = async function handleOwnerIntegrationDecision(button) {
  if (["candidate-approve", "candidate-reject"].includes(button.dataset.ownerIntegrationAction)) {
    const panel = button.closest("[data-owner-integration-id]");
    const item = ownerCandidateItems().find((candidate) => candidate.channel === "instagram" && String(candidate.business.id) === String(panel.dataset.ownerIntegrationId) && String(candidate.candidate.id) === String(button.dataset.attemptId));
    if (item) await decideOwnerCandidate(item, button.dataset.ownerIntegrationAction === "candidate-approve" ? "approve" : "reject");
    return;
  }
  if (["disconnect", "delete-credentials"].includes(button.dataset.ownerIntegrationAction)) {
    const panel = button.closest("[data-owner-integration-id]");
    const deleting = button.dataset.ownerIntegrationAction === "delete-credentials";
    const confirmed = await confirmOwnerCriticalAction({
      title: deleting ? "Eliminar credenciales de Instagram" : "Desconectar Instagram",
      resource: panel.dataset.ownerIntegrationName,
      current: "Integración conectada",
      next: deleting ? "Credenciales eliminadas" : "Integración desconectada",
      consequence: deleting ? "Las credenciales cifradas se eliminarán definitivamente. Esta acción no borra el negocio." : "Se impedirán nuevos envíos por Instagram hasta completar una reconexión.",
      confirmLabel: deleting ? "Eliminar credenciales" : "Desconectar",
      action: (reason) => ownerHubRequest(`/api/owner/businesses/${encodeURIComponent(panel.dataset.ownerIntegrationId)}/integrations/instagram${deleting ? "/credentials" : "/disconnect"}`, { method: deleting ? "DELETE" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }) }, "No se pudo actualizar Instagram."),
    });
    if (confirmed) { await loadOwnerIntegration(panel); await loadOwnerDashboardChannels(); renderOwnerBusinessRows(); }
    return;
  }
  return legacyOwnerIntegrationAction(button);
};

const legacyOwnerChannelAction = handleOwnerChannelControlAction;
handleOwnerChannelControlAction = async function handleOwnerWhatsAppDecision(button) {
  if (["whatsapp-approve", "whatsapp-reject"].includes(button.dataset.ownerChannelAction)) {
    const panel = button.closest("[data-owner-channel-control-id]");
    const item = ownerCandidateItems().find((candidate) => candidate.channel === "whatsapp" && String(candidate.business.id) === String(panel.dataset.ownerChannelControlId) && String(candidate.candidate.id) === String(button.dataset.attemptId));
    if (item) await decideOwnerCandidate(item, button.dataset.ownerChannelAction === "whatsapp-approve" ? "approve" : "reject");
    return;
  }
  if (["approve", "suspend", "revoke"].includes(button.dataset.ownerChannelAction)) {
    const panel = button.closest("[data-owner-channel-control-id]");
    const action = button.dataset.ownerChannelAction;
    const channel = button.dataset.channel;
    const labels = { approve: ["Aprobar uso del canal", "Uso aprobado", false], suspend: ["Suspender canal", "Canal suspendido", true], revoke: ["Revocar canal", "Canal revocado", true] };
    const confirmed = await confirmOwnerCriticalAction({
      title: labels[action][0],
      resource: `${channel === "instagram" ? "Instagram" : "WhatsApp"} · ${businesses.find((item) => String(item.id) === String(panel.dataset.ownerChannelControlId))?.name || "Negocio"}`,
      current: "Control comercial vigente",
      next: labels[action][1],
      consequence: action === "approve" ? "Se aprobará el uso comercial del canal. Envío y automatización conservarán sus controles y no se habilitarán automáticamente." : action === "suspend" ? "El canal quedará suspendido sin borrar la integración ni los datos conservados." : "El permiso comercial quedará revocado. La integración técnica y su salud seguirán siendo conceptos independientes.",
      confirmLabel: labels[action][0],
      danger: labels[action][2],
      action: (reason) => ownerHubRequest(`/api/owner/businesses/${encodeURIComponent(panel.dataset.ownerChannelControlId)}/channel-controls/${encodeURIComponent(channel)}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }) }, "No se pudo actualizar el control del canal."),
    });
    if (confirmed) { await loadOwnerChannelControls(panel); await loadOwnerDashboardChannels(); renderOwnerBusinessRows(); }
    return;
  }
  return legacyOwnerChannelAction(button);
};

byId("business-hub-filters").addEventListener("submit", (event) => event.preventDefault());
byId("business-hub-search").addEventListener("input", (event) => { ownerBusinessHubState.query = event.target.value; renderOwnerBusinessRows(); });
byId("business-hub-filter").addEventListener("change", (event) => { ownerBusinessHubState.filter = event.target.value; renderOwnerBusinessRows(); });
byId("businesses-section").addEventListener("click", (event) => {
  const open = event.target.closest("[data-owner-business-open]");
  if (open) { openBusinessDetail(open.dataset.ownerBusinessOpen); return; }
  const close = event.target.closest("[data-owner-detail-close]");
  if (close) { ownerBusinessHubState.selectedBusinessId = null; byId("business-detail").hidden = true; renderOwnerBusinessRows(); byId("business-hub-search").focus(); return; }
  const tab = event.target.closest("[data-owner-detail-tab]");
  if (tab) { activateOwnerBusinessDetailSection(tab.dataset.ownerDetailTab); return; }
  const go = event.target.closest("[data-owner-detail-go]");
  if (go) { activateOwnerBusinessDetailSection(go.dataset.ownerDetailGo); return; }
  const onboarding = event.target.closest("[data-owner-business-onboarding]");
  if (onboarding) { setActiveTab("new-business"); openOwnerOnboarding(onboarding.dataset.ownerBusinessOnboarding).catch((error) => { byId("owner-onboarding-hub-status").textContent = error.message; }); return; }
  const readiness = event.target.closest("[data-owner-readiness-refresh]");
  if (readiness) { loadOwnerBusinessReadiness(readiness.dataset.ownerReadinessRefresh, true).catch((error) => { byId("business-detail").querySelector("[data-owner-activation-feedback]").textContent = error.message; }); return; }
  const readinessStep = event.target.closest("[data-owner-readiness-step]");
  if (readinessStep) { setActiveTab("new-business"); openOwnerOnboarding(ownerBusinessHubState.selectedBusinessId, readinessStep.dataset.ownerReadinessStep).catch((error) => { byId("owner-onboarding-hub-status").textContent = error.message; }); return; }
  const preview = event.target.closest("[data-owner-preview]");
  if (preview) { showOwnerBusinessPreview(preview.dataset.ownerPreview); return; }
  const activate = event.target.closest("[data-owner-activate]");
  if (activate) activateOwnerBusiness(activate.dataset.ownerActivate);
});

document.querySelector('[data-panel="new-business"]').addEventListener("click", (event) => {
  const view = event.target.closest("[data-owner-hub-view]");
  if (view) { setOwnerHubView(view.dataset.ownerHubView); return; }
  const retry = event.target.closest("[data-owner-onboarding-retry]");
  if (retry) { const business = businesses.find((item) => String(item.id) === String(retry.dataset.ownerOnboardingRetry)); if (business) loadOwnerOnboardingEntry(business, ownerBusinessHubState.onboardingVersion); return; }
  const onboarding = event.target.closest("[data-owner-business-onboarding]");
  if (onboarding) { openOwnerOnboarding(onboarding.dataset.ownerBusinessOnboarding).catch((error) => { byId("owner-onboarding-hub-status").textContent = error.message; }); return; }
  const readiness = event.target.closest("[data-owner-onboarding-readiness]");
  if (readiness) { openOwnerOnboarding(readiness.dataset.ownerOnboardingReadiness, "readiness_review").catch((error) => { byId("owner-onboarding-hub-status").textContent = error.message; }); return; }
  const review = event.target.closest("[data-owner-candidate-review]");
  if (review) { const item = ownerCandidateItems().find((candidate) => String(candidate.candidate.id) === String(review.dataset.ownerCandidateReview) && String(candidate.business.id) === String(review.dataset.ownerCandidateBusiness) && candidate.channel === review.dataset.ownerCandidateChannel); if (item) openOwnerCandidateReview(item); return; }
  if (event.target.closest("[data-owner-candidate-close]")) { byId("owner-candidate-review").hidden = true; ownerBusinessHubState.currentCandidate = null; return; }
  const decision = event.target.closest("[data-owner-candidate-decision]");
  if (decision && ownerBusinessHubState.currentCandidate) { decideOwnerCandidate(ownerBusinessHubState.currentCandidate, decision.dataset.ownerCandidateDecision); return; }
  const businessLink = event.target.closest("[data-owner-candidate-business-link]");
  if (businessLink) { setActiveTab("businesses"); openBusinessDetail(businessLink.dataset.ownerCandidateBusinessLink, "channels"); }
});

byId("onboarding-new-toggle").addEventListener("click", (event) => {
  if (typeof openOwnerOnboardingCreation === "function") { openOwnerOnboardingCreation(event.currentTarget); return; }
  const wizard = byId("onboarding-wizard");
  wizard.hidden = !wizard.hidden;
  event.currentTarget.setAttribute("aria-expanded", String(!wizard.hidden));
  if (!wizard.hidden) { byId("onboarding-start").hidden = false; byId("onboarding-workspace").hidden = true; byId("onboarding-name").focus(); }
});

setOwnerHubView("onboarding");
