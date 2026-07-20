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
let ownerAuthUser = null;
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
}

function renderSummary() {
  byId("total-businesses").textContent = businesses.length;
  byId("active-businesses").textContent = businesses.filter((item) => item.active).length;
  byId("pending-bookings").textContent = sum(businesses, (item) => item.metrics.pending_bookings);
  byId("pending-messages").textContent = sum(businesses, (item) => item.metrics.message_outbox_pending);
  byId("pending-reviews").textContent = sum(businesses, (item) => item.metrics.review_requests_pending);
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
  restoreOwnerMediaStatus();
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
byId("refresh-button").addEventListener("click", loadBusinesses);
byId("add-service").addEventListener("click", addServiceRow);
byId("business-form").addEventListener("submit", createBusiness);
byId("business-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-toggle-slug]");
  if (button) toggleBusiness(button.dataset.toggleSlug, button.dataset.nextActive === "true", button);
  else if (event.target.closest("[data-owner-user-action]")) handleOwnerUserAction(event.target.closest("[data-owner-user-action]")).catch((error) => console.error("Business user action failed", error));
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
