/* Sprint 5D.1: flujo Owner sobre los contratos de onboarding existentes. */
(function () {
  "use strict";

  const STEPS = [
    ["template", "Plantilla", "Inicio"],
    ["business_identity", "Identidad", "Identidad"],
    ["contact_and_location", "Contacto y ubicación", "Identidad"],
    ["services", "Servicios", "Operación"],
    ["staff", "Equipo", "Operación"],
    ["schedules", "Horario habitual", "Disponibilidad"],
    ["booking_rules", "Reglas de reserva", "Disponibilidad"],
    ["branding", "Marca", "Página pública"],
    ["landing_content", "Contenido público", "Página pública"],
    ["automations", "Automatizaciones", "Operación"],
    ["integrations", "Canales", "Canales"],
    ["credits_and_plan", "Plan y créditos", "Plan"],
    ["readiness_review", "Revisión y readiness", "Cierre"],
    ["preview", "Vista previa", "Cierre"],
    ["activation", "Activación", "Cierre"],
  ];
  window.OWNER_ONBOARDING_STEPS = Object.freeze(STEPS.map(([key, label]) => Object.freeze([key, label])));
  window.ownerOnboardingStepLabel = (key) => STEPS.find(([candidate]) => candidate === key)?.[1] || null;
  const STATUS = {
    pending: "No iniciado",
    in_progress: "En curso",
    completed: "Completado",
    skipped: "Omitido",
    blocked: "Bloqueado",
  };
  const BUSINESS_STATUS = { draft: "Borrador", onboarding: "En alta", active: "Activo", suspended: "Suspendido", archived: "Archivado" };
  const HELP = {
    template: "Elige una configuración de partida. Si cambias de plantilla, los datos existentes se conservan y el servidor exige confirmación.",
    business_identity: "Datos internos que identifican el negocio. Cambiar el slug de un negocio activo exige confirmación.",
    contact_and_location: "Contacto y enlaces públicos. Las URLs deben usar HTTPS o HTTP y no pueden incluir credenciales.",
    services: "Readiness exige al menos un servicio activo y reservable. Este editor cubre los campos reales del alta.",
    staff: "Los perfiles profesionales y los usuarios con acceso son entidades distintas; crear personal no concede acceso.",
    schedules: "Define ventanas semanales reales. Los días cerrados no contienen intervalos y las ventanas no pueden solaparse.",
    booking_rules: "Configura cómo se generan reservas; la disponibilidad se calcula en el servidor y no se simula aquí.",
    branding: "Colores y plantilla afectan a la página pública. Logo y galería permanecen en el editor canónico de Negocios.",
    landing_content: "Contenido que verá el cliente. Mientras no se active, permanece sin publicar y con noindex.",
    automations: "Configura los controles existentes. Guardar este paso no activa canales ni cambia su aprobación.",
    integrations: "Consulta disponibilidad comercial, conexión, candidaturas y salud. No se solicitan credenciales ni se aprueban canales aquí.",
    credits_and_plan: "Inicializa el plan operativo y sus créditos. No es facturación y no activa el negocio.",
    readiness_review: "La revisión resume los pasos; solo el readiness calculado por backend decide si puede activarse.",
    preview: "La vista previa real mantiene noindex, deshabilita reservas y automatizaciones y no consume créditos.",
    activation: "Acción crítica: requiere readiness vigente y motivo. No conecta canales ni habilita automatizaciones.",
  };
  const state = {
    dirty: false,
    saving: false,
    creating: false,
    loadPromise: null,
    loadingBusinessId: null,
    readiness: null,
    preview: null,
    activation: null,
    templates: [],
    supplemental: {},
    pendingNavigation: null,
    entryOrigin: null,
    returnTab: "new-business",
    lastFocus: null,
  };
  const q = (id) => document.getElementById(id);
  const esc = (value) => escapeHtml(value === null || value === undefined ? "" : String(value));
  const attr = (value) => esc(value).replace(/`/g, "&#96;");
  const value = (name, fallback = "") => onboardingData?.business?.[name] ?? fallback;
  const clean = (input) => input && input.value.trim() ? input.value.trim() : null;
  const num = (input) => Number(input.value);
  const checked = (condition) => condition ? " checked" : "";
  const selected = (left, right) => String(left ?? "") === String(right ?? "") ? " selected" : "";
  const formatDate = (raw) => raw ? new Intl.DateTimeFormat("es-ES", { dateStyle: "short", timeStyle: "short" }).format(new Date(raw)) : "—";
  const stepKey = () => STEPS[onboardingStepIndex]?.[0] || STEPS[0][0];
  const stepIndex = (key) => Math.max(0, STEPS.findIndex(([candidate]) => candidate === key));
  const sessionStep = (key) => onboardingData?.onboarding?.steps?.find((item) => item.key === key);
  const isActive = () => onboardingData?.business?.status === "active";
  const publicUrl = () => `../autonogrow-landing/index.html?b=${encodeURIComponent(onboardingData.business.slug)}`;
  const adminUrl = (hash = "") => `../autonogrow-admin/index.html?b=${encodeURIComponent(onboardingData.business.slug)}${hash}`;

  function safeError(status) {
    if (status === 401) return "La sesión Owner ha caducado. Vuelve a identificarte.";
    if (status === 403) return "Tu cuenta no tiene permiso para esta operación.";
    if (status === 404) return "El negocio o la configuración ya no están disponibles.";
    if (status === 409) return "Este paso cambió desde otra sesión. Actualiza los datos antes de volver a guardar.";
    if (status === 422) return "Revisa los campos indicados; alguno no cumple las reglas del servidor.";
    return "No se pudo completar la operación. Los datos introducidos se conservan en esta pantalla.";
  }

  async function request(path, options = {}) {
    const response = await fetch(`${API_BASE_URL}/api/owner${path}`, options);
    if (!response.ok) {
      const error = new Error(safeError(response.status));
      error.status = response.status;
      error.conflict = response.status === 409;
      throw error;
    }
    return response.json();
  }

  async function secondaryRequest(path) {
    const response = await fetch(`${API_BASE_URL}${path}`);
    if (!response.ok) throw new Error("Fuente secundaria no disponible");
    return response.json();
  }

  function showError(message, conflict = false) {
    const box = q("owner-onboarding-error-summary");
    box.hidden = false;
    box.innerHTML = `<strong>${conflict ? "Conflicto de edición" : "No se pudo guardar"}</strong><p>${esc(message)}</p>${conflict ? '<button class="button button-secondary button-small" type="button" data-ob-reload>Recargar datos guardados</button><p class="helper">La copia introducida permanece temporalmente en este formulario hasta que recargues o cierres.</p>' : ""}`;
    box.focus();
  }

  function clearError() {
    q("owner-onboarding-error-summary").hidden = true;
    q("owner-onboarding-error-summary").innerHTML = "";
    q("onboarding-feedback").textContent = "";
  }

  function setBusy(busy) {
    state.saving = busy;
    q("onboarding-step-content").setAttribute("aria-busy", String(busy));
    ["onboarding-save-only", "onboarding-save", "onboarding-next", "onboarding-back", "onboarding-later"].forEach((id) => { q(id).disabled = busy; });
    if (!busy) q("onboarding-back").disabled = onboardingStepIndex === 0;
    if (busy) q("onboarding-save-state").textContent = "Guardando…";
  }

  window.markOwnerOnboardingDirty = function () {
    if (state.saving || isActive()) return;
    state.dirty = true;
    q("onboarding-save-state").textContent = "Cambios sin guardar";
  };

  async function loadTemplates() {
    const select = q("onboarding-template");
    try {
      const body = await request("/onboarding/templates");
      state.templates = body.templates || [];
      select.innerHTML = '<option value="">Elegir después</option>' + state.templates.map((item) => `<option value="${attr(item.key)}" data-version="${attr(item.version)}">${esc(item.name)} · ${esc(item.category || "General")}</option>`).join("");
    } catch {
      select.innerHTML = '<option value="">No se pudieron cargar</option>';
      q("owner-onboarding-create-status").textContent = "Las plantillas no están disponibles. Puedes reintentar abriendo de nuevo Nueva alta.";
    }
  }

  async function loadSupplemental(data) {
    const slug = encodeURIComponent(data.business.slug);
    const businessId = encodeURIComponent(data.business.id);
    const sources = {
      availability: secondaryRequest(`/api/admin/${slug}/availability-settings`),
      exceptions: secondaryRequest(`/api/admin/${slug}/availability-exceptions`),
      automation: secondaryRequest(`/api/owner/businesses/${businessId}/automation-settings`),
      credits: secondaryRequest(`/api/owner/businesses/${businessId}/automation-credits`),
      access: secondaryRequest(`/api/owner/businesses/${slug}/users`),
    };
    const entries = await Promise.all(Object.entries(sources).map(async ([name, promise]) => {
      try { return [name, { status: "ready", data: await promise }]; }
      catch { return [name, { status: "error", data: null }]; }
    }));
    if (onboardingData?.business?.id !== data.business.id) return;
    state.supplemental = Object.fromEntries(entries);
    if (state.dirty || state.saving) { sourceWarning(stepKey()); return; }
    renderOnboarding(false);
  }

  async function loadOwnerOnboarding(businessId, requestedStep = null) {
    if (state.loadPromise) {
      const pending = state.loadPromise;
      const sameBusiness = String(state.loadingBusinessId) === String(businessId);
      const data = await pending;
      if (sameBusiness) {
        if (requestedStep && STEPS.some(([key]) => key === requestedStep)) { onboardingStepIndex = stepIndex(requestedStep); renderOnboarding(false); }
        return data;
      }
    }
    const workspace = q("onboarding-workspace");
    q("onboarding-wizard").hidden = false;
    q("onboarding-start").hidden = true;
    q("owner-onboarding-result").hidden = true;
    workspace.hidden = false;
    workspace.setAttribute("aria-busy", "true");
    q("owner-onboarding-business-name").textContent = "Cargando alta…";
    state.loadingBusinessId = businessId;
    state.loadPromise = request(`/businesses/${encodeURIComponent(businessId)}/onboarding`)
      .then((data) => {
        onboardingData = data;
        onboardingReadiness = null;
        state.readiness = null;
        state.preview = null;
        state.activation = null;
        state.supplemental = {};
        state.dirty = false;
        onboardingStepIndex = requestedStep && STEPS.some(([key]) => key === requestedStep) ? stepIndex(requestedStep) : stepIndex(data.onboarding.current_step);
        renderOnboarding(false);
        loadSupplemental(data);
        return data;
      })
      .finally(() => { state.loadPromise = null; state.loadingBusinessId = null; workspace.removeAttribute("aria-busy"); });
    return state.loadPromise;
  }

  window.resumeOnboarding = async function (businessId, requestedStep = null) {
    setActiveTab("new-business");
    q("onboarding-new-toggle").setAttribute("aria-expanded", "true");
    const data = await loadOwnerOnboarding(businessId, requestedStep);
    q("onboarding-wizard").scrollIntoView({ block: "start" });
    return data;
  };

  window.openOwnerOnboarding = async function (businessId, requestedStep = null) {
    const active = document.querySelector("[data-tab].active")?.dataset.tab;
    state.returnTab = state.entryOrigin || (active && active !== "new-business" ? active : "new-business");
    state.entryOrigin = null;
    setActiveTab("new-business");
    q("onboarding-new-toggle").setAttribute("aria-expanded", "true");
    const data = await loadOwnerOnboarding(businessId, requestedStep);
    q("onboarding-wizard").scrollIntoView({ block: "start" });
    return data;
  };

  window.startOnboarding = async function () {
    if (state.creating) return;
    const form = q("onboarding-start");
    const name = q("onboarding-name");
    const slug = q("onboarding-slug");
    const status = q("owner-onboarding-create-status");
    clearError();
    if (!form.reportValidity()) return;
    state.creating = true;
    q("onboarding-create").disabled = true;
    form.setAttribute("aria-busy", "true");
    status.textContent = "Creando el negocio…";
    const template = state.templates.find((item) => item.key === q("onboarding-template").value);
    const payload = { name: name.value.trim(), slug: slug.value.trim() || null, template_key: template?.key || null, template_version: template?.version || null };
    try {
      const data = await request("/businesses/onboarding", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      onboardingData = data;
      onboardingReadiness = null;
      state.dirty = false;
      state.readiness = null;
      state.supplemental = {};
      onboardingStepIndex = stepIndex(data.onboarding.current_step);
      status.textContent = "Negocio creado. Abriendo su configuración…";
      renderOnboarding(false);
      loadSupplemental(data);
      await Promise.allSettled([
        typeof loadOwnerDashboardBusinesses === "function" ? loadOwnerDashboardBusinesses() : Promise.resolve(),
        typeof loadBusinesses === "function" ? loadBusinesses() : Promise.resolve(),
        typeof loadOwnerOnboardingHub === "function" ? loadOwnerOnboardingHub(true) : Promise.resolve(),
      ]);
    } catch (error) {
      status.textContent = error.message;
      if (error.conflict) slug.setAttribute("aria-invalid", "true");
    } finally {
      state.creating = false;
      q("onboarding-create").disabled = false;
      form.removeAttribute("aria-busy");
    }
  };

  function renderSteps() {
    const steps = onboardingData.onboarding.steps || [];
    const map = Object.fromEntries(steps.map((item) => [item.key, item.status]));
    let group = "";
    q("onboarding-steps").innerHTML = STEPS.map(([key, label, nextGroup], index) => {
      const heading = group !== nextGroup ? `<span class="owner-onboarding-step-group">${esc(nextGroup)}</span>` : "";
      group = nextGroup;
      const status = map[key] || "pending";
      return `<li>${heading}<button type="button" data-ob-step="${index}" class="${index === onboardingStepIndex ? "active" : ""} status-${attr(status)}"${index === onboardingStepIndex ? ' aria-current="step"' : ""}><span>${index + 1}. ${esc(label)}</span><small>${esc(STATUS[status] || status)}</small></button></li>`;
    }).join("");
    q("owner-onboarding-step-select").innerHTML = STEPS.map(([key, label], index) => `<option value="${index}"${selected(index, onboardingStepIndex)}>${index + 1}. ${esc(label)} · ${esc(STATUS[map[key]] || map[key] || "No iniciado")}</option>`).join("");
    const completed = steps.filter((item) => ["completed", "skipped"].includes(item.status)).length;
    const percent = Math.round(completed * 100 / STEPS.length);
    q("onboarding-progress-bar").style.width = `${percent}%`;
    q("owner-onboarding-progress-text").textContent = `${completed} de ${STEPS.length} pasos confirmados por backend`;
  }

  function renderShell() {
    const business = onboardingData.business;
    const session = onboardingData.onboarding;
    const activity = session.step_activity?.[stepKey()]?.updated_at || session.last_activity_at;
    q("onboarding-start").hidden = true;
    q("onboarding-workspace").hidden = false;
    q("owner-onboarding-business-name").textContent = `Alta de ${business.name}`;
    q("owner-onboarding-business-status").textContent = BUSINESS_STATUS[business.status] || business.status;
    q("owner-onboarding-current-summary").textContent = `Paso ${onboardingStepIndex + 1} de ${STEPS.length} · ${STEPS[onboardingStepIndex][1]}`;
    q("owner-onboarding-last-saved").textContent = `Último guardado: ${formatDate(activity)}`;
    const origin = q("owner-onboarding-origin");
    origin.hidden = state.returnTab === "new-business";
    origin.textContent = state.returnTab === "overview" ? "Volver a Dashboard" : state.returnTab === "businesses" ? "Volver a Negocios" : "Volver al origen";
    q("onboarding-step-title").textContent = `${onboardingStepIndex + 1}. ${STEPS[onboardingStepIndex][1]}`;
    q("owner-onboarding-step-help").textContent = HELP[stepKey()];
    renderSteps();
  }

  function templateForm() {
    const current = onboardingData.onboarding.template?.key || "";
    return `<fieldset><legend>Plantilla de partida</legend><label>Plantilla<select data-ob="template_key" required><option value="">Selecciona una plantilla</option>${state.templates.map((item) => `<option value="${attr(item.key)}" data-version="${attr(item.version)}"${selected(item.key, current)}>${esc(item.name)} · versión ${esc(item.version)}</option>`).join("")}</select></label><label class="checkbox-row"><input data-ob="retain_existing" type="checkbox" checked> Conservar los datos ya introducidos</label>${current ? '<label class="checkbox-row"><input data-ob="confirm_change" type="checkbox"> Confirmo el cambio si selecciono otra plantilla</label>' : ""}</fieldset>`;
  }

  function identityForm() {
    return `<fieldset><legend>Identidad interna y pública</legend><div class="form-grid"><label>Nombre comercial <span aria-hidden="true">*</span><input data-ob="name" value="${attr(value("name"))}" required maxlength="200"></label><label>Slug <span aria-hidden="true">*</span><input data-ob="slug" value="${attr(value("slug"))}" required maxlength="120" pattern="[a-z0-9]+(?:-[a-z0-9]+)*" aria-describedby="ob-identity-slug-help"><small id="ob-identity-slug-help">Ruta pública estable; no equivale a un dominio propio.</small></label><label>Categoría<input data-ob="category" value="${attr(value("category"))}" maxlength="160"></label><label>Razón social<input data-ob="legal_name" value="${attr(value("legal_name"))}" maxlength="240"><small>Dato interno.</small></label><label>Identificación fiscal<input data-ob="tax_identifier" value="${attr(value("tax_identifier"))}" maxlength="80"><small>Dato interno.</small></label><label>Idioma<input data-ob="language_code" value="${attr(value("language_code", "es"))}" pattern="[a-z]{2}(?:-[A-Z]{2})?"></label><label>Zona horaria<input data-ob="timezone" value="${attr(value("timezone", "Europe/Madrid"))}" maxlength="80"></label><label>Moneda<input data-ob="currency" value="${attr(value("currency", "EUR"))}" pattern="[A-Z]{3}" maxlength="3"></label><label class="wide">Descripción pública<textarea data-ob="description" maxlength="5000">${esc(value("description"))}</textarea></label></div>${isActive() ? '<label class="checkbox-row"><input data-ob="confirm_active_slug_change" type="checkbox"> Confirmo el cambio del slug activo, si lo he modificado</label>' : ""}</fieldset>`;
  }

  function contactForm() {
    const fields = [
      ["phone", "Teléfono público", "tel", 40], ["whatsapp_phone", "Teléfono de WhatsApp", "tel", 40], ["public_email", "Email público", "email", 320],
      ["city", "Ciudad", "text", 120], ["address", "Dirección", "text", 1000], ["postal_code", "Código postal", "text", 20],
      ["region", "Región", "text", 120], ["country_code", "País (ISO, 2 letras)", "text", 2], ["maps_url", "Google Maps", "url", null],
      ["instagram_url", "Instagram", "url", null], ["tiktok_url", "TikTok", "url", null], ["external_website_url", "Web externa", "url", null],
    ];
    return `<fieldset><legend>Contacto y ubicación públicos</legend><div class="form-grid">${fields.map(([key, label, type, max]) => `<label${key === "address" ? ' class="wide"' : ""}>${esc(label)}<input data-ob="${key}" type="${type}" value="${attr(value(key))}"${max ? ` maxlength="${max}"` : ""}${key === "country_code" ? ' pattern="[A-Z]{2}"' : ""}></label>`).join("")}</div><p class="helper">No introduzcas credenciales en enlaces. Los datos vacíos se guardan como no configurados.</p></fieldset>`;
  }

  function serviceRow(service = {}, index = 0) {
    return `<fieldset class="owner-onboarding-repeat" data-ob-service${service.id ? ` data-record-id="${attr(service.id)}"` : ""}><legend>Servicio ${index + 1}</legend><button class="button button-ghost button-small" type="button" data-ob-remove-service>Quitar de este alta</button><div class="form-grid"><label>Nombre <span aria-hidden="true">*</span><input data-field="name" value="${attr(service.name)}" required maxlength="200"></label><label>Duración (minutos) <span aria-hidden="true">*</span><input data-field="duration_minutes" type="number" value="${attr(service.duration_minutes || 30)}" min="1" max="1440" required></label><label>Precio (EUR)<input data-field="price_amount" type="number" value="${attr(service.price_amount)}" min="0" step="0.01" inputmode="decimal"></label><label>Moneda<input data-field="currency" value="${attr(service.currency || "EUR")}" pattern="[A-Z]{3}" maxlength="3"></label><label>Orden<input data-field="position" type="number" value="${attr(service.position ?? index)}" min="0" max="10000"></label><label class="wide">Descripción<textarea data-field="description" maxlength="3000">${esc(service.description)}</textarea></label></div><div class="owner-inline-checks"><label class="checkbox-row"><input data-field="active" type="checkbox"${checked(service.active !== false)}> Activo</label><label class="checkbox-row"><input data-field="visible" type="checkbox"${checked(service.visible !== false)}> Visible</label><label class="checkbox-row"><input data-field="bookable" type="checkbox"${checked(service.bookable !== false)}> Reservable</label></div></fieldset>`;
  }

  function servicesForm() {
    const items = onboardingData.services?.length ? onboardingData.services : [{}];
    return `<div class="owner-onboarding-section-heading"><p>Solo los servicios activos y reservables satisfacen el bloqueo de readiness.</p><button class="button button-secondary button-small" type="button" data-ob-add-service>Añadir servicio</button></div><div data-ob-service-list>${items.map(serviceRow).join("")}</div><p class="owner-source-note">Desactivar conserva el servicio. “Quitar de este alta” evita enviarlo, pero el endpoint no elimina registros existentes.</p>`;
  }

  function staffRow(member = {}, index = 0) {
    const serviceOptions = (onboardingData.services || []).map((service) => `<label class="checkbox-row"><input data-service-ref="${attr(service.id)}" type="checkbox"${checked((member.service_ids || []).map(String).includes(String(service.id)))}> ${esc(service.name)}</label>`).join("");
    return `<fieldset class="owner-onboarding-repeat" data-ob-staff${member.id ? ` data-record-id="${attr(member.id)}"` : ""}><legend>Profesional ${index + 1}</legend><button class="button button-ghost button-small" type="button" data-ob-remove-staff>Quitar de este alta</button><div class="form-grid"><label>Nombre público <span aria-hidden="true">*</span><input data-field="public_name" value="${attr(member.public_name)}" required maxlength="200"></label><label>Email de perfil<input data-field="email" value="${attr(member.email)}" type="email" maxlength="320"></label><label>Rol descriptivo<input data-field="role_label" value="${attr(member.role_label || "professional")}" required maxlength="120"></label><label>Capacidad<input data-field="capacity" type="number" value="${attr(member.capacity || 1)}" min="1" max="100"></label></div><label class="checkbox-row"><input data-field="active" type="checkbox"${checked(member.active !== false)}> Perfil activo</label><fieldset><legend>Servicios que atiende</legend><div class="owner-inline-checks">${serviceOptions || "No hay servicios guardados para asignar."}</div></fieldset><p class="helper">Acceso a la aplicación: ${member.has_application_access ? "vinculado según backend" : "no vinculado"}. Este formulario no crea cuentas.</p></fieldset>`;
  }

  function staffForm() {
    const items = onboardingData.staff?.length ? onboardingData.staff : [{}];
    const access = state.supplemental.access;
    const accessText = access?.status === "ready" ? "Los usuarios con acceso se gestionan aparte, con protección del último administrador activo." : "No se pudieron comprobar los usuarios con acceso; los perfiles profesionales siguen disponibles.";
    return `<div class="owner-onboarding-section-heading"><p>${esc(accessText)}</p><button class="button button-secondary button-small" type="button" data-ob-open-business-users>Gestionar usuarios y roles</button><button class="button button-secondary button-small" type="button" data-ob-add-staff>Añadir profesional</button></div><div data-ob-staff-list>${items.map(staffRow).join("")}</div><p class="owner-source-note">Owner no puede asignar el rol owner desde este flujo. La garantía del último administrador también debe permanecer en backend.</p>`;
  }

  const DAYS = [["0", "Lunes"], ["1", "Martes"], ["2", "Miércoles"], ["3", "Jueves"], ["4", "Viernes"], ["5", "Sábado"], ["6", "Domingo"]];
  function scheduleForm() {
    const schedule = onboardingData.availability?.weekly_schedule || state.supplemental.availability?.data?.weekly_schedule || {};
    return `<label>Zona horaria<input data-ob="timezone" value="${attr(onboardingData.availability?.timezone || value("timezone", "Europe/Madrid"))}" maxlength="80"></label><fieldset><legend>Horario habitual semanal</legend><div class="owner-schedule-list">${DAYS.map(([day, label]) => {
      const windows = schedule[day] || [];
      return `<section class="owner-schedule-day" data-ob-day="${day}"><header><h4>${label}</h4><button class="button button-secondary button-small" type="button" data-ob-add-window>Añadir intervalo</button></header><div data-ob-windows>${windows.length ? windows.map((window) => `<div class="owner-schedule-window"><label>Apertura<input data-field="start" type="time" value="${attr(window.start)}" required></label><label>Cierre<input data-field="end" type="time" value="${attr(window.end)}" required></label><button class="button button-ghost button-small" type="button" data-ob-remove-window>Quitar</button></div>`).join("") : '<p class="owner-closed-day">Cerrado</p>'}</div></section>`;
    }).join("")}</div></fieldset><div class="owner-related-source"><strong>Excepciones y bloqueos</strong><p>${state.supplemental.exceptions?.status === "ready" ? `${(state.supplemental.exceptions.data.exceptions || state.supplemental.exceptions.data || []).length} excepciones devueltas por la fuente actual.` : "No se pudieron comprobar; el horario habitual permanece editable."}</p><a class="button button-secondary button-small" href="${adminUrl("#availability")}" target="_blank" rel="noopener">Gestionar excepciones en Business Admin</a></div>`;
  }

  function bookingForm() {
    const saved = state.supplemental.availability?.data || onboardingData.availability || {};
    const completeSource = ["buffer_between_bookings_minutes", "auto_confirm_bookings", "cancellation_allowed", "cancellation_notice_minutes", "reschedule_allowed", "max_simultaneous_bookings"].every((key) => Object.prototype.hasOwnProperty.call(saved, key));
    return `<fieldset><legend>Generación de reservas</legend><div class="form-grid"><label>Antelación mínima (min)<input data-ob="min_notice_minutes" type="number" value="${attr(saved.min_notice_minutes ?? 120)}" min="0" max="525600" required></label><label>Horizonte (días)<input data-ob="max_days_ahead" type="number" value="${attr(saved.max_days_ahead ?? 30)}" min="1" max="730" required></label><label>Intervalo de slots (min)<input data-ob="slot_interval_minutes" type="number" value="${attr(saved.slot_interval_minutes ?? 15)}" min="1" max="720" required></label><label>Margen entre reservas (min)<input data-ob="buffer_between_bookings_minutes" type="number" value="${attr(saved.buffer_between_bookings_minutes ?? 0)}" min="0" max="1440" required></label><label>Aviso de cancelación (min)<input data-ob="cancellation_notice_minutes" type="number" value="${attr(saved.cancellation_notice_minutes ?? 120)}" min="0" max="525600" required></label><label>Capacidad simultánea<input data-ob="max_simultaneous_bookings" type="number" value="${attr(saved.max_simultaneous_bookings ?? 1)}" min="1" max="100" required></label></div><div class="owner-inline-checks"><label class="checkbox-row"><input data-ob="auto_confirm_bookings" type="checkbox"${checked(saved.auto_confirm_bookings ?? true)}> Confirmación automática</label><label class="checkbox-row"><input data-ob="cancellation_allowed" type="checkbox"${checked(saved.cancellation_allowed ?? true)}> Permitir cancelación</label><label class="checkbox-row"><input data-ob="reschedule_allowed" type="checkbox"${checked(saved.reschedule_allowed ?? true)}> Permitir cambio de cita</label></div>${completeSource ? "" : '<label class="checkbox-row owner-confirm-source"><input data-ob="confirm_booking_defaults" type="checkbox" required> Confirmo aplicar estos valores: la lectura Owner actual no expone todas las reglas avanzadas.</label>'}</fieldset><p class="owner-source-note">La disponibilidad real y los huecos se calculan en backend. Este paso no genera una agenda ficticia.</p>`;
  }

  function brandingForm() {
    return `<fieldset><legend>Plantilla y paleta</legend><div class="form-grid"><label>Tema<input data-ob="theme_key" value="${attr(value("theme_key"))}" maxlength="40"></label><label>Plantilla pública<input data-ob="template_key" value="${attr(value("template_key"))}" maxlength="40"></label>${[["primary_color", "Principal", "#176b48"], ["secondary_color", "Secundario", "#17211b"], ["accent_color", "Acento", "#d4a72c"], ["background_color", "Fondo", "#ffffff"]].map(([key, label, fallback]) => `<label>Color ${label}<input data-ob="${key}" type="color" value="${attr(value(key, fallback) || fallback)}"></label>`).join("")}<label class="wide">Texto alternativo del logo<input data-ob="logo_alt" value="${attr(value("logo_alt"))}" maxlength="240"></label></div></fieldset><div class="owner-related-source"><strong>Logo y galería</strong><p>${value("logo_url") ? "El backend confirma un logo configurado." : "No hay logo confirmado por la fuente del onboarding; es recomendado, no bloqueante."}</p><button class="button button-secondary" type="button" data-ob-open-brand>Editar medios en Negocios</button></div>`;
  }

  function landingForm() {
    const fields = [["headline", "Titular", 500], ["description", "Descripción", 5000], ["landing_cta", "Texto de llamada a la acción", 120], ["schedule", "Horario comercial en texto", 1000], ["reviews_url", "Enlace de reseñas", null], ["seo_title", "Título SEO", 160], ["seo_description", "Descripción SEO", 320]];
    return `<fieldset><legend>Contenido público</legend><div class="form-grid">${fields.map(([key, label, max]) => key === "description" || key === "schedule" || key === "seo_description" ? `<label class="wide">${label}<textarea data-ob="${key}"${max ? ` maxlength="${max}"` : ""}>${esc(value(key))}</textarea></label>` : `<label${key === "headline" ? ' class="wide"' : ""}>${label}<input data-ob="${key}"${key === "reviews_url" ? ' type="url"' : ""} value="${attr(value(key))}"${max ? ` maxlength="${max}"` : ""}></label>`).join("")}</div></fieldset><p class="owner-partial-notice">Aún no está publicada. El servidor mantiene noindex hasta que la activación final tenga éxito.</p>`;
  }

  function automationsForm() {
    const source = state.supplemental.automation;
    if (!source) return '<div class="owner-inline-loading" aria-busy="true"><span class="ag-loader" aria-hidden="true"></span><p>Cargando configuración actual…</p></div>';
    if (source?.status === "error") return '<p class="owner-partial-notice">No se pudo leer la configuración de automatizaciones. Recarga antes de editar para no asumir valores.</p><button class="button button-secondary" type="button" data-ob-reload-supplemental>Reintentar fuente</button>';
    const data = source?.data || {};
    return `<fieldset><legend>Controles de automatización</legend><label class="checkbox-row"><input data-ob="automation_enabled" type="checkbox"${checked(data.automation_enabled === true)}> Automatizaciones habilitadas</label><div class="form-grid"><label>Umbral automático<input data-ob="auto_threshold" type="number" value="${attr(data.auto_threshold ?? 80)}" min="0" max="100"></label><label>Pausa tras respuesta humana (min)<input data-ob="human_reply_pause_minutes" type="number" value="${attr(data.human_reply_pause_minutes ?? 60)}" min="0" max="10080"></label></div></fieldset><p class="owner-source-note">Este guardado no modifica mensajes existentes, no aprueba canales y no habilita capacidades externas.</p>`;
  }

  function integrationsForm() {
    const direct = onboardingData.integrations || [];
    const snapshots = ownerDashboardState?.channels?.data || [];
    const snapshot = snapshots.find((item) => String(item.business?.id) === String(onboardingData.business.id));
    const channels = ["instagram", "whatsapp"].map((channel) => {
      const integration = direct.find((item) => item.channel === channel);
      const control = snapshot?.controls?.find((item) => item.channel === channel);
      const candidates = channel === "instagram" ? snapshot?.instagramCandidates : snapshot?.whatsappCandidates;
      const health = snapshot?.health?.find?.((item) => item.channel === channel);
      const commercial = ({ approved: "Disponible y aprobada", pending_approval: "Pendiente de aprobación", not_allowed: "No disponible", suspended: "Suspendida", revoked: "Revocada" })[control?.status] || "No se pudo comprobar";
      return `<article class="owner-channel-preparation"><h4>${channel === "instagram" ? "Instagram" : "WhatsApp"}</h4><dl><div><dt>Disponibilidad comercial</dt><dd>${esc(commercial)}</dd></div><div><dt>Conexión</dt><dd>${esc(integration?.status || "No conectada")}</dd></div><div><dt>Candidatura</dt><dd>${esc(candidates?.length ? "Pendiente o registrada" : "Sin candidatura confirmada")}</dd></div><div><dt>Aprobación</dt><dd>${esc(control?.status === "approved" ? "Aprobada" : "No aprobada")}</dd></div><div><dt>Salud</dt><dd>${esc(health?.health_status || "No se pudo comprobar")}</dd></div></dl></article>`;
    }).join("");
    return `<div class="owner-channel-grid">${channels}</div>${ownerDashboardState?.channels?.status === "error" ? '<p class="owner-partial-notice">La fuente de canales falló parcialmente. No se interpreta como desconectado ni correcto.</p>' : ""}<div class="owner-onboarding-actions"><button class="button button-secondary" type="button" data-ob-open-integrations>Configurar Instagram o WhatsApp</button><button class="button button-secondary" type="button" data-ob-open-approvals>Revisar candidaturas</button></div><p class="owner-source-note">Continuar sin conectar registra el paso como omitido en backend. Meta no bloquea el alta salvo que readiness real lo indique.</p>`;
  }

  function creditsForm() {
    const source = state.supplemental.credits;
    if (!source) return '<div class="owner-inline-loading" aria-busy="true"><span class="ag-loader" aria-hidden="true"></span><p>Comprobando plan actual…</p></div>';
    if (source?.status === "error") return '<p class="owner-partial-notice">No se pudo comprobar el plan actual. Recarga antes de inicializar créditos.</p><button class="button button-secondary" type="button" data-ob-reload-supplemental>Reintentar fuente</button>';
    const data = source?.data || {};
    const already = sessionStep("credits_and_plan")?.status === "completed";
    if (already) return `<div class="owner-review-card"><h4>Plan inicializado</h4><p>Plan: ${esc(data.plan_key || "Confirmado por backend")}</p><p>Saldo disponible: ${esc(data.available_credits ?? data.balance ?? "No expuesto")}</p><p>La inicialización es idempotente; este paso se muestra en modo consulta para no prometer una reasignación.</p></div>`;
    return `<fieldset><legend>Asignación inicial</legend><div class="form-grid"><label>Clave del plan<input data-ob="plan_key" value="${attr(data.plan_key || "starter")}" pattern="[a-z0-9_-]+" maxlength="60" required></label><label>Créditos incluidos<input data-ob="included_credits" type="number" value="${attr(data.included_credits ?? 100)}" min="0" max="10000000" required></label><label>Créditos adicionales<input data-ob="additional_credits" type="number" value="${attr(data.additional_credits ?? 0)}" min="0" max="10000000" required></label><label>Duración del periodo (días)<input data-ob="period_days" type="number" value="30" min="1" max="366" required></label></div></fieldset><p class="owner-source-note">El periodo comienza cuando backend inicializa el plan. No representa precio, IVA, renovación ni cobro, y no activa el negocio.</p>`;
  }

  function readinessGroup(checks, title, kind) {
    if (!checks.length) return "";
    return `<section class="owner-readiness-group"><h4>${esc(title)} (${checks.length})</h4><div class="readiness-list">${checks.map((item) => `<article class="readiness-item ${attr(kind)}"><div><strong>${esc(item.label)}</strong><span class="ag-badge ag-badge--${kind === "blocking" || kind === "error" ? "danger" : kind === "recommended" ? "warning" : "success"}">${esc(item.status)}</span></div><p>${esc(item.message)}</p>${item.remediation ? `<small>${esc(item.remediation)}</small>` : ""}${item.related_step && STEPS.some(([key]) => key === item.related_step) ? `<button class="button button-secondary button-small" type="button" data-ob-go-step="${attr(item.related_step)}">Ir al paso</button>` : ""}</article>`).join("")}</div></section>`;
  }

  function readinessHtml() {
    if (!state.readiness) return '<div class="empty-state"><strong>Readiness sin comprobar</strong><p>Solicita una evaluación actual al servidor. Un fallo no se mostrará como correcto.</p></div>';
    const checks = state.readiness.checks || [];
    const blocking = checks.filter((item) => item.blocking && item.status !== "passed");
    const errors = checks.filter((item) => !item.blocking && ["error", "failed"].includes(item.status));
    const recommended = checks.filter((item) => !item.blocking && !["passed", "not_applicable", "error", "failed"].includes(item.status));
    const passed = checks.filter((item) => ["passed", "not_applicable"].includes(item.status));
    return `<div class="owner-readiness-summary"><strong>${state.readiness.ready ? "Listo para activar" : `${state.readiness.blocking_count} bloqueos impiden activar`}</strong><span>Puntuación: ${esc(state.readiness.score ?? "No expuesta")}</span></div>${readinessGroup(blocking, "Bloqueos", "blocking")}${readinessGroup(recommended, "Recomendaciones", "recommended")}${readinessGroup(passed, "Comprobaciones correctas o no aplicables", "passed")}${readinessGroup(errors, "Errores de comprobación", "error")}`;
  }

  function reviewForm() {
    const groups = [
      ["Identidad", ["business_identity", "contact_and_location"]], ["Servicios", ["services"]], ["Equipo", ["staff"]],
      ["Horarios y disponibilidad", ["schedules", "booking_rules"]], ["Página pública", ["branding", "landing_content"]],
      ["Canales", ["integrations"]], ["Plan", ["credits_and_plan"]],
    ];
    const cards = groups.map(([label, keys]) => {
      const items = keys.map((key) => sessionStep(key)).filter(Boolean);
      const blocked = items.some((item) => item.status === "blocked");
      const complete = items.every((item) => ["completed", "skipped"].includes(item.status));
      const status = blocked ? "Bloqueante" : complete ? "Correcto" : "Incompleto";
      return `<article class="owner-review-card"><h4>${esc(label)}</h4><span class="ag-badge ag-badge--${blocked ? "danger" : complete ? "success" : "warning"}">${status}</span><ul>${items.map((item) => `<li>${esc(STEPS.find(([key]) => key === item.key)?.[1] || item.key)}: ${esc(STATUS[item.status] || item.status)}</li>`).join("")}</ul><button class="button button-secondary button-small" type="button" data-ob-go-step="${attr(keys[0])}">Revisar</button></article>`;
    }).join("");
    return `<p class="owner-source-note">Este resumen usa estados de pasos del backend; no sustituye la decisión de readiness.</p><div class="owner-review-grid">${cards}</div><div class="owner-onboarding-section-heading"><h4>Readiness del servidor</h4><button class="button button-primary" type="button" data-ob-readiness>Comprobar ahora</button></div><div id="onboarding-readiness">${readinessHtml()}</div>`;
  }

  function previewForm() {
    if (!state.preview) return '<div class="empty-state"><strong>Vista previa aún no cargada</strong><p>Se consultará la ruta real sin publicar ni activar nada.</p></div><button class="button button-primary" type="button" data-ob-preview>Abrir vista previa</button><button class="button button-secondary" type="button" data-ob-go-step="readiness_review">Volver a revisión</button>';
    const data = state.preview;
    const services = data.services || [];
    return `<article class="owner-preview-card"><p class="eyebrow">Vista privada Owner</p><h4>${esc(data.business?.name || onboardingData.business.name)}</h4><p>${esc(data.business?.headline || "Titular pendiente")}</p><ul><li>${data.noindex !== false ? "noindex y nofollow" : "Estado de indexación no confirmado"}</li><li>Reservas ${data.booking_enabled === false ? "deshabilitadas" : "sin garantía de desactivación"}</li><li>Automatizaciones ${data.automation_enabled === false ? "deshabilitadas" : "sin garantía de desactivación"}</li><li>Créditos ${data.credits_enabled === false ? "sin consumo" : "sin garantía de consumo desactivado"}</li></ul><h5>Servicios visibles en la respuesta</h5>${services.length ? `<ul>${services.map((service) => `<li>${esc(service.name)} · ${esc(service.duration_minutes)} min</li>`).join("")}</ul>` : "<p>No hay servicios en la vista previa.</p>"}</article><div class="owner-onboarding-actions"><button class="button button-secondary" type="button" data-ob-preview>Actualizar vista previa</button><button class="button button-secondary" type="button" data-ob-go-step="readiness_review">Volver a revisión</button>${state.readiness?.ready ? '<button class="button button-primary" type="button" data-ob-go-step="activation">Ir a activar</button>' : '<button class="button button-secondary" type="button" data-ob-readiness>Corregir o comprobar bloqueos</button>'}</div><p class="owner-partial-notice">Esta representación usa la respuesta de preview. Todavía no está publicada.</p>`;
  }

  function activationForm() {
    const readiness = state.readiness;
    return `<div class="owner-activation-summary"><dl><div><dt>Negocio</dt><dd>${esc(onboardingData.business.name)}</dd></div><div><dt>Estado actual</dt><dd>${esc(BUSINESS_STATUS[onboardingData.business.status] || onboardingData.business.status)}</dd></div><div><dt>Estado resultante</dt><dd>Activo</dd></div><div><dt>Readiness</dt><dd>${readiness ? readiness.ready ? "Vigente y listo" : `${readiness.blocking_count} bloqueos` : "Sin comprobar"}</dd></div><div><dt>Página pública</dt><dd>Dejará de estar en noindex si backend activa</dd></div><div><dt>Reservas</dt><dd>Operarán según la configuración vigente</dd></div><div><dt>Business Admin</dt><dd>Disponible para usuarios con acceso existente</dd></div><div><dt>Canales</dt><dd>No se conectan ni aprueban</dd></div><div><dt>Automatizaciones</dt><dd>No se habilitan automáticamente</dd></div><div><dt>Plan</dt><dd>Conserva su configuración actual</dd></div></dl></div><label>Motivo de activación <span aria-hidden="true">*</span><textarea data-ob="reason" minlength="3" maxlength="500" required></textarea></label>${readiness?.ready ? '<button class="button button-primary" type="button" data-ob-activate>Activar negocio</button>' : '<button class="button button-secondary" type="button" data-ob-readiness>Comprobar readiness vigente</button>'}`;
  }

  function activeSummary() {
    const business = onboardingData.business;
    const snapshot = (ownerDashboardState?.channels?.data || []).find((item) => String(item.business?.id) === String(business.id));
    const pendingChannels = ["instagram", "whatsapp"].filter((channel) => !snapshot?.controls?.some((control) => control.channel === channel && control.approved_at));
    const access = state.supplemental.access;
    let admin = "No se pudo comprobar";
    if (access?.status === "ready") {
      const users = access.data.users || access.data || [];
      admin = users.some((item) => item.active && item.role === "business_admin") ? "Administrador activo confirmado" : "Administrador pendiente";
    }
    return `<p class="eyebrow">Alta completada</p><h3>Negocio activado</h3><div class="owner-result-grid"><p><strong>Estado actual</strong>Activo</p><p><strong>Administrador</strong>${esc(admin)}</p><p><strong>Canales pendientes</strong>${pendingChannels.length ? esc(pendingChannels.map((item) => item === "instagram" ? "Instagram" : "WhatsApp").join(", ")) : "Ninguno confirmado"}</p></div><p>La activación no ha conectado canales ni habilitado automatizaciones. Revisa los elementos pendientes con sus fuentes reales.</p><div class="owner-onboarding-actions"><a class="button button-primary" href="${adminUrl()}" target="_blank" rel="noopener">Abrir Business Admin</a><a class="button button-secondary" href="${publicUrl()}" target="_blank" rel="noopener">Abrir página pública</a><button class="button button-secondary" type="button" data-ob-open-integrations>Revisar canales</button><button class="button button-ghost" type="button" data-ob-return-businesses>Volver a Negocios</button></div>`;
  }

  function sourceWarning(key) {
    const warning = q("owner-onboarding-source-warning");
    const sourceByStep = { staff: "access", schedules: "exceptions", booking_rules: "availability", automations: "automation", integrations: "channels", credits_and_plan: "credits" };
    const source = sourceByStep[key];
    const failed = source === "channels" ? ownerDashboardState?.channels?.status === "error" : source && state.supplemental[source]?.status === "error";
    warning.hidden = !failed;
    warning.textContent = failed ? "Una fuente secundaria no está disponible. El formulario principal y el progreso guardado permanecen visibles; no se interpreta el fallo como un estado correcto." : "";
  }

  function renderStep() {
    const forms = {
      template: templateForm, business_identity: identityForm, contact_and_location: contactForm, services: servicesForm,
      staff: staffForm, schedules: scheduleForm, booking_rules: bookingForm, branding: brandingForm,
      landing_content: landingForm, automations: automationsForm, integrations: integrationsForm,
      credits_and_plan: creditsForm, readiness_review: reviewForm, preview: previewForm, activation: activationForm,
    };
    q("onboarding-step-content").innerHTML = forms[stepKey()]();
    sourceWarning(stepKey());
    const special = ["readiness_review", "preview", "activation"].includes(stepKey());
    const completedCredits = stepKey() === "credits_and_plan" && sessionStep("credits_and_plan")?.status === "completed";
    q("onboarding-save-only").hidden = special || completedCredits || isActive();
    q("onboarding-save").hidden = special || completedCredits || isActive();
    q("onboarding-next").hidden = onboardingStepIndex === STEPS.length - 1 || isActive();
    q("onboarding-back").disabled = onboardingStepIndex === 0;
    q("onboarding-save").textContent = stepKey() === "integrations" ? "Continuar sin conectar" : "Guardar y continuar";
  }

  window.renderOnboarding = function (focus = true) {
    if (!onboardingData?.onboarding) return;
    clearError();
    renderShell();
    if (isActive()) {
      q("onboarding-workspace").hidden = true;
      q("owner-onboarding-result").hidden = false;
      q("owner-onboarding-result").innerHTML = activeSummary();
      q("owner-onboarding-result").querySelector("h3")?.setAttribute("tabindex", "-1");
      if (focus) q("owner-onboarding-result").querySelector("h3")?.focus();
      return;
    }
    q("owner-onboarding-result").hidden = true;
    renderStep();
    state.dirty = false;
    q("onboarding-save-state").textContent = `Guardado · ${formatDate(onboardingData.onboarding.step_activity?.[stepKey()]?.updated_at || onboardingData.onboarding.last_activity_at)}`;
    if (focus) q("onboarding-step-title").focus();
  };

  function control(name) { return q("onboarding-step-content").querySelector(`[data-ob="${name}"]`); }
  function nullable(name) { return clean(control(name)); }
  function scalarPayload(names) { return Object.fromEntries(names.map((name) => [name, nullable(name)])); }

  function collectServices() {
    const rows = [...q("onboarding-step-content").querySelectorAll("[data-ob-service]")];
    const names = rows.map((row) => row.querySelector('[data-field="name"]').value.trim().toLocaleLowerCase("es"));
    if (new Set(names).size !== names.length) throw new Error("Los nombres de servicio no pueden repetirse.");
    return rows.map((row) => ({
      ...(row.dataset.recordId ? { id: Number(row.dataset.recordId) } : {}),
      name: row.querySelector('[data-field="name"]').value.trim(),
      description: clean(row.querySelector('[data-field="description"]')),
      duration_minutes: num(row.querySelector('[data-field="duration_minutes"]')),
      price_amount: clean(row.querySelector('[data-field="price_amount"]')),
      currency: row.querySelector('[data-field="currency"]').value.trim(),
      visible: row.querySelector('[data-field="visible"]').checked,
      bookable: row.querySelector('[data-field="bookable"]').checked,
      position: num(row.querySelector('[data-field="position"]')),
      active: row.querySelector('[data-field="active"]').checked,
    }));
  }

  function collectStaff() {
    return [...q("onboarding-step-content").querySelectorAll("[data-ob-staff]")].map((row) => ({
      ...(row.dataset.recordId ? { id: Number(row.dataset.recordId) } : {}),
      public_name: row.querySelector('[data-field="public_name"]').value.trim(),
      email: clean(row.querySelector('[data-field="email"]')),
      role_label: row.querySelector('[data-field="role_label"]').value.trim(),
      capacity: num(row.querySelector('[data-field="capacity"]')),
      active: row.querySelector('[data-field="active"]').checked,
      service_ids: [...row.querySelectorAll("[data-service-ref]:checked")].map((item) => Number(item.dataset.serviceRef)),
    }));
  }

  function collectSchedule() {
    const weekly_schedule = {};
    q("onboarding-step-content").querySelectorAll("[data-ob-day]").forEach((day) => {
      const windows = [...day.querySelectorAll(".owner-schedule-window")].map((row) => ({ start: row.querySelector('[data-field="start"]').value, end: row.querySelector('[data-field="end"]').value })).sort((left, right) => left.start.localeCompare(right.start));
      for (let index = 0; index < windows.length; index += 1) {
        if (windows[index].end <= windows[index].start) throw new Error(`${DAYS.find(([key]) => key === day.dataset.obDay)[1]}: el cierre debe ser posterior a la apertura.`);
        if (index && windows[index - 1].end > windows[index].start) throw new Error(`${DAYS.find(([key]) => key === day.dataset.obDay)[1]}: los intervalos no pueden solaparse.`);
      }
      weekly_schedule[day.dataset.obDay] = windows;
    });
    return { timezone: nullable("timezone"), weekly_schedule };
  }

  function collectPayload(key) {
    if (key === "template") {
      const option = control("template_key").selectedOptions[0];
      return { route: "template", method: "POST", body: { template_key: control("template_key").value, template_version: Number(option.dataset.version), retain_existing: control("retain_existing").checked, confirm_change: control("confirm_change")?.checked || false } };
    }
    if (key === "business_identity") return { route: "identity", body: { ...scalarPayload(["name", "slug", "category", "description", "legal_name", "tax_identifier", "language_code", "timezone", "currency"]), confirm_active_slug_change: control("confirm_active_slug_change")?.checked || false } };
    if (key === "contact_and_location") return { route: "contact", body: scalarPayload(["phone", "whatsapp_phone", "public_email", "city", "address", "postal_code", "region", "country_code", "maps_url", "instagram_url", "tiktok_url", "external_website_url"]) };
    if (key === "services") return { route: "services", body: { services: collectServices() } };
    if (key === "staff") return { route: "staff", body: { staff: collectStaff() } };
    if (key === "schedules") return { route: "schedules", body: collectSchedule() };
    if (key === "booking_rules") return { route: "booking", body: { min_notice_minutes: num(control("min_notice_minutes")), max_days_ahead: num(control("max_days_ahead")), slot_interval_minutes: num(control("slot_interval_minutes")), buffer_between_bookings_minutes: num(control("buffer_between_bookings_minutes")), auto_confirm_bookings: control("auto_confirm_bookings").checked, cancellation_allowed: control("cancellation_allowed").checked, cancellation_notice_minutes: num(control("cancellation_notice_minutes")), reschedule_allowed: control("reschedule_allowed").checked, max_simultaneous_bookings: num(control("max_simultaneous_bookings")) } };
    if (key === "branding") {
      const body = scalarPayload(["theme_key", "template_key", "primary_color", "secondary_color", "accent_color", "background_color"]);
      if (nullable("logo_alt")) body.logo_alt = nullable("logo_alt");
      return { route: "branding", body };
    }
    if (key === "landing_content") return { route: "landing", body: scalarPayload(["headline", "description", "landing_cta", "schedule", "reviews_url", "seo_title", "seo_description"]) };
    if (key === "automations") return { route: "automations", body: { automation_enabled: control("automation_enabled").checked, auto_threshold: num(control("auto_threshold")), human_reply_pause_minutes: num(control("human_reply_pause_minutes")), messages: {} } };
    if (key === "integrations") return { route: "steps/integrations/skip", method: "POST", body: { reason: "Canales opcionales revisados por Owner" } };
    if (key === "credits_and_plan") return { route: "credits", body: { plan_key: control("plan_key").value.trim(), included_credits: num(control("included_credits")), additional_credits: num(control("additional_credits")), period_days: num(control("period_days")) } };
    return null;
  }

  async function refreshContext() {
    await Promise.allSettled([
      typeof loadOwnerDashboardBusinesses === "function" ? loadOwnerDashboardBusinesses() : Promise.resolve(),
      typeof loadOwnerDashboardChannels === "function" ? loadOwnerDashboardChannels() : Promise.resolve(),
      typeof loadOwnerOnboardingHub === "function" ? loadOwnerOnboardingHub(true) : Promise.resolve(),
      typeof loadOwnerBusinessAccessIndex === "function" ? loadOwnerBusinessAccessIndex(true) : Promise.resolve(),
    ]);
  }

  async function reloadMain(render = true) {
    const data = await request(`/businesses/${encodeURIComponent(onboardingData.business.id)}/onboarding`);
    onboardingData = data;
    if (render) renderOnboarding(false);
    return data;
  }

  window.saveOwnerOnboardingStep = async function ({ continueAfter = true } = {}) {
    if (state.saving || isActive()) return false;
    const form = q("onboarding-step-content");
    clearError();
    if (!form.reportValidity()) {
      showError("Revisa los campos marcados antes de guardar.");
      form.querySelector(":invalid")?.focus();
      return false;
    }
    const current = stepKey();
    if (["readiness_review", "preview", "activation"].includes(current)) return false;
    let operation;
    try { operation = collectPayload(current); }
    catch (error) { showError(error.message); return false; }
    if (!operation) return false;
    const savedIndex = onboardingStepIndex;
    setBusy(true);
    try {
      await request(`/businesses/${encodeURIComponent(onboardingData.business.id)}/onboarding/${operation.route}`, { method: operation.method || "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(operation.body) });
      state.dirty = false;
      state.readiness = null;
      onboardingReadiness = null;
      state.preview = null;
      await reloadMain(false);
      onboardingStepIndex = continueAfter ? Math.min(savedIndex + 1, STEPS.length - 1) : savedIndex;
      renderOnboarding(continueAfter);
      q("onboarding-feedback").textContent = "Cambios confirmados por backend.";
      refreshContext();
      return true;
    } catch (error) {
      showError(error.message, error.conflict);
      q("onboarding-save-state").textContent = error.conflict ? "Conflicto · copia temporal conservada" : "Error · cambios sin guardar";
      state.dirty = true;
      return false;
    } finally { setBusy(false); }
  };

  window.saveOnboardingStep = function () { return saveOwnerOnboardingStep({ continueAfter: true }); };

  async function loadReadiness(navigate = false) {
    if (state.saving) return;
    clearError();
    setBusy(true);
    try {
      state.readiness = await request(`/businesses/${encodeURIComponent(onboardingData.business.id)}/readiness`);
      onboardingReadiness = state.readiness;
      await reloadMain(false);
      if (navigate) onboardingStepIndex = stepIndex("readiness_review");
      renderOnboarding(navigate);
      q("onboarding-feedback").textContent = state.readiness.ready ? "Readiness vigente: listo para activar." : `Readiness vigente: ${state.readiness.blocking_count} bloqueos.`;
    } catch (error) {
      state.readiness = null;
      onboardingReadiness = null;
      showError("No se pudo comprobar readiness. No se considera que el negocio esté listo.", error.conflict);
    } finally { setBusy(false); }
  }

  async function loadPreview() {
    if (state.saving) return;
    clearError();
    setBusy(true);
    try {
      state.preview = await request(`/businesses/${encodeURIComponent(onboardingData.business.id)}/preview`);
      await reloadMain(false);
      onboardingStepIndex = stepIndex("preview");
      renderOnboarding(false);
      q("onboarding-feedback").textContent = "Vista previa privada actualizada.";
    } catch (error) { showError("No se pudo cargar la vista previa. Los pasos guardados no han cambiado.", error.conflict); }
    finally { setBusy(false); }
  }

  async function activate() {
    const reason = control("reason");
    if (!state.readiness) { await loadReadiness(false); return; }
    if (!state.readiness.ready) { q("onboarding-feedback").textContent = `La activación está bloqueada por ${state.readiness.blocking_count} comprobaciones.`; return; }
    if (!reason.value.trim() || reason.value.trim().length < 3) { reason.setCustomValidity("Escribe un motivo de al menos 3 caracteres."); reason.reportValidity(); reason.addEventListener("input", () => reason.setCustomValidity(""), { once: true }); return; }
    const expectedVersion = state.readiness.version;
    const action = (confirmedReason) => request(`/businesses/${encodeURIComponent(onboardingData.business.id)}/activate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: confirmedReason || reason.value.trim(), expected_readiness_version: expectedVersion }) });
    try {
      setBusy(true);
      const confirmed = typeof confirmOwnerCriticalAction === "function" ? await confirmOwnerCriticalAction({ title: "Activar negocio", resource: onboardingData.business.name, current: BUSINESS_STATUS[onboardingData.business.status] || onboardingData.business.status, next: "Activo", consequence: "La página pública dejará de estar en noindex y las reservas operarán con la configuración vigente. Canales y automatizaciones no cambian.", confirmLabel: "Activar negocio", reason: reason.value.trim(), action }) : (await action(reason.value.trim()), true);
      if (!confirmed) return;
      state.activation = true;
      await reloadMain(false);
      await refreshContext();
      renderOnboarding(true);
    } catch (error) {
      if (error.conflict) { state.readiness = null; onboardingReadiness = null; }
      showError(error.message, error.conflict);
    } finally { setBusy(false); }
  }

  function closeUnsavedDialog() {
    const dialog = q("owner-onboarding-unsaved-dialog");
    dialog.hidden = true;
    q("owner-onboarding-unsaved-error").textContent = "";
    state.lastFocus?.focus?.();
  }

  function runPendingNavigation() {
    const action = state.pendingNavigation;
    state.pendingNavigation = null;
    closeUnsavedDialog();
    action?.();
  }

  function warnUnsaved(action) {
    state.pendingNavigation = action;
    state.lastFocus = document.activeElement;
    const backdrop = q("owner-onboarding-unsaved-dialog");
    backdrop.hidden = false;
    backdrop.querySelector(".owner-dialog").focus();
  }

  function navigateOrWarn(action) {
    if (state.dirty) warnUnsaved(action);
    else action();
  }

  window.ownerOnboardingNavigate = function (index) {
    const target = Math.max(0, Math.min(Number(index), STEPS.length - 1));
    if (target === onboardingStepIndex) return;
    navigateOrWarn(() => { onboardingStepIndex = target; renderOnboarding(true); });
  };

  function leaveWizard() {
    q("onboarding-wizard").hidden = true;
    q("onboarding-new-toggle").setAttribute("aria-expanded", "false");
    q("owner-onboarding-hub-status").textContent = "El progreso confirmado permanece guardado. Puedes retomarlo desde esta lista.";
    q("onboarding-new-toggle").focus();
  }

  window.ownerOnboardingLeave = function () { navigateOrWarn(leaveWizard); };

  window.openOwnerOnboardingCreation = function (toggle) {
    const wizard = q("onboarding-wizard");
    if (!wizard.hidden && !q("onboarding-start").hidden) {
      wizard.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
      return;
    }
    navigateOrWarn(() => {
      if (state.entryOrigin) { state.returnTab = state.entryOrigin; state.entryOrigin = null; }
      wizard.hidden = false;
      q("onboarding-start").hidden = false;
      q("onboarding-workspace").hidden = true;
      q("owner-onboarding-result").hidden = true;
      toggle.setAttribute("aria-expanded", "true");
      q("onboarding-name").focus();
    });
  };

  function openBusinessSection(section) {
    navigateOrWarn(() => {
      q("onboarding-wizard").hidden = true;
      setActiveTab("businesses");
      window.requestAnimationFrame(() => typeof openBusinessDetail === "function" && openBusinessDetail(onboardingData.business.id, section));
    });
  }

  function openIntegrations() {
    navigateOrWarn(() => {
      q("onboarding-wizard").hidden = true;
      setActiveTab("integrations");
      window.requestAnimationFrame(() => typeof openOwnerIntegrationContext === "function" && openOwnerIntegrationContext(onboardingData.business.id));
    });
  }

  function openApprovals() {
    navigateOrWarn(() => {
      q("onboarding-wizard").hidden = true;
      if (typeof setOwnerHubView === "function") setOwnerHubView("approvals");
      q("owner-approvals-hub-title")?.focus?.();
    });
  }

  function addWindow(button) {
    const target = button.closest("[data-ob-day]").querySelector("[data-ob-windows]");
    target.querySelector(".owner-closed-day")?.remove();
    target.insertAdjacentHTML("beforeend", '<div class="owner-schedule-window"><label>Apertura<input data-field="start" type="time" value="09:00" required></label><label>Cierre<input data-field="end" type="time" value="18:00" required></label><button class="button button-ghost button-small" type="button" data-ob-remove-window>Quitar</button></div>');
    markOwnerOnboardingDirty();
    target.querySelector(".owner-schedule-window:last-child input")?.focus();
  }

  q("onboarding-start").addEventListener("submit", (event) => {
    event.preventDefault();
    startOnboarding().catch((error) => { q("owner-onboarding-create-status").textContent = error.message; });
  });
  q("onboarding-save").addEventListener("click", () => saveOwnerOnboardingStep({ continueAfter: true }));
  q("onboarding-save-only").addEventListener("click", () => saveOwnerOnboardingStep({ continueAfter: false }));
  q("onboarding-back").addEventListener("click", () => ownerOnboardingNavigate(Math.max(0, onboardingStepIndex - 1)));
  q("onboarding-later").addEventListener("click", ownerOnboardingLeave);
  q("onboarding-steps").addEventListener("click", (event) => {
    const button = event.target.closest("[data-ob-step]");
    if (button) ownerOnboardingNavigate(Number(button.dataset.obStep));
  });
  q("owner-onboarding-origin").addEventListener("click", () => navigateOrWarn(() => { q("onboarding-wizard").hidden = true; setActiveTab(state.returnTab); }));
  q("onboarding-next").addEventListener("click", () => ownerOnboardingNavigate(onboardingStepIndex + 1));
  q("owner-onboarding-step-select").addEventListener("change", (event) => ownerOnboardingNavigate(Number(event.target.value)));
  q("onboarding-step-content").addEventListener("input", markOwnerOnboardingDirty);
  q("onboarding-step-content").addEventListener("change", markOwnerOnboardingDirty);
  q("onboarding-step-content").addEventListener("click", (event) => {
    const target = event.target;
    if (target.closest("[data-ob-add-service]")) {
      const list = q("onboarding-step-content").querySelector("[data-ob-service-list]");
      list.insertAdjacentHTML("beforeend", serviceRow({}, list.children.length)); markOwnerOnboardingDirty(); list.lastElementChild.querySelector("input")?.focus(); return;
    }
    if (target.closest("[data-ob-remove-service]")) { target.closest("[data-ob-service]").remove(); markOwnerOnboardingDirty(); return; }
    if (target.closest("[data-ob-add-staff]")) {
      const list = q("onboarding-step-content").querySelector("[data-ob-staff-list]");
      list.insertAdjacentHTML("beforeend", staffRow({}, list.children.length)); markOwnerOnboardingDirty(); list.lastElementChild.querySelector("input")?.focus(); return;
    }
    if (target.closest("[data-ob-remove-staff]")) { target.closest("[data-ob-staff]").remove(); markOwnerOnboardingDirty(); return; }
    if (target.closest("[data-ob-add-window]")) { addWindow(target.closest("[data-ob-add-window]")); return; }
    if (target.closest("[data-ob-remove-window]")) {
      const windows = target.closest("[data-ob-windows]"); target.closest(".owner-schedule-window").remove();
      if (!windows.querySelector(".owner-schedule-window")) windows.innerHTML = '<p class="owner-closed-day">Cerrado</p>';
      markOwnerOnboardingDirty(); return;
    }
    const go = target.closest("[data-ob-go-step]"); if (go) { ownerOnboardingNavigate(stepIndex(go.dataset.obGoStep)); return; }
    if (target.closest("[data-ob-readiness]")) { loadReadiness(stepKey() !== "readiness_review"); return; }
    if (target.closest("[data-ob-preview]")) { loadPreview(); return; }
    if (target.closest("[data-ob-activate]")) { activate(); return; }
    if (target.closest("[data-ob-reload]")) { state.dirty = false; reloadMain(true); return; }
    if (target.closest("[data-ob-reload-supplemental]")) { loadSupplemental(onboardingData); return; }
    if (target.closest("[data-ob-open-business-users]")) { openBusinessSection("users"); return; }
    if (target.closest("[data-ob-open-brand]")) { openBusinessSection("brand"); return; }
    if (target.closest("[data-ob-open-integrations]")) { openIntegrations(); return; }
    if (target.closest("[data-ob-open-approvals]")) { openApprovals(); return; }
    if (target.closest("[data-ob-return-businesses]")) { q("onboarding-wizard").hidden = true; setActiveTab("businesses"); }
  });

  q("owner-onboarding-result").addEventListener("click", (event) => {
    if (event.target.closest("[data-ob-open-integrations]")) openIntegrations();
    if (event.target.closest("[data-ob-return-businesses]")) { q("onboarding-wizard").hidden = true; setActiveTab("businesses"); }
  });

  q("owner-onboarding-unsaved-cancel").addEventListener("click", () => { state.pendingNavigation = null; closeUnsavedDialog(); });
  q("owner-onboarding-unsaved-close").addEventListener("click", () => { state.pendingNavigation = null; closeUnsavedDialog(); });
  q("owner-onboarding-unsaved-discard").addEventListener("click", () => { state.dirty = false; runPendingNavigation(); });
  q("owner-onboarding-unsaved-save").addEventListener("click", async () => {
    q("owner-onboarding-unsaved-error").textContent = "Guardando…";
    const saved = await saveOwnerOnboardingStep({ continueAfter: false });
    if (saved) runPendingNavigation();
    else q("owner-onboarding-unsaved-error").textContent = "No se pudo guardar. Revisa el paso o sal sin guardar.";
  });

  q("owner-onboarding-unsaved-dialog").addEventListener("keydown", (event) => {
    if (event.key === "Escape") { event.preventDefault(); state.pendingNavigation = null; closeUnsavedDialog(); return; }
    if (event.key !== "Tab") return;
    const focusable = [...event.currentTarget.querySelectorAll("button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled])")];
    if (!focusable.length) return;
    const first = focusable[0]; const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });

  window.addEventListener("beforeunload", (event) => { if (state.dirty) { event.preventDefault(); event.returnValue = ""; } });

  const originalSetActiveTab = window.setActiveTab;
  if (typeof originalSetActiveTab === "function") {
    window.setActiveTab = function (name) {
      const current = document.querySelector("[data-tab].active")?.dataset.tab;
      if (name === "new-business" && current && current !== "new-business") state.entryOrigin = current;
      const leaving = !q("onboarding-wizard").hidden && !q("onboarding-workspace").hidden && name !== "new-business";
      if (leaving && state.dirty) { warnUnsaved(() => { state.dirty = false; originalSetActiveTab(name); }); return; }
      originalSetActiveTab(name);
    };
  }

  q("onboarding-slug").addEventListener("blur", (event) => {
    if (!event.target.value.trim() || typeof slugify !== "function") return;
    event.target.value = slugify(event.target.value);
  });

  q("onboarding-wizard").addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s" && !q("onboarding-workspace").hidden) {
      event.preventDefault(); saveOwnerOnboardingStep({ continueAfter: false });
    }
  });

  q("onboarding-new-toggle").setAttribute("aria-controls", "onboarding-wizard");
  window.loadOwnerOnboardingTemplates = loadTemplates;
  if (!q("owner-app").hidden) loadTemplates();
}());
