"use strict";

const API_BASE_URL = AutonoGrowAuth.API_BASE_URL;
const nativeFetch = window.fetch.bind(window);
const SERVICE_VERIFICATION_CONCURRENCY = 3;
const BOOKING_STEPS = ["service", "staff", "datetime", "customer", "review", "result"];
const BOOKING_STATUS = {
  requested: { label: "Solicitud enviada", next: "El negocio tendrá que confirmar la cita." },
  pending: { label: "Pendiente de confirmación", next: "El negocio está revisando la solicitud." },
  confirmed: { label: "Cita confirmada", next: "Tu cita ya está confirmada." },
  rejected: { label: "Solicitud rechazada", next: "Contacta con el negocio si necesitas otra opción." },
  cancelled: { label: "Cita cancelada", next: "La cita ya no está activa." },
  completed: { label: "Cita completada", next: "La cita ha finalizado." },
  no_show: { label: "Cita no realizada", next: "Contacta con el negocio si necesitas ayuda." }
};
const DAY_STATUS = {
  available: "Disponible",
  special: "Horario especial",
  full: "Sin huecos",
  closed: "Cerrado",
  past: "Fecha pasada"
};
const bookingState = {
  business: null,
  service: null,
  staff: null,
  date: null,
  slot: null,
  customer: { name: "", phone: "", notes: "", files: [] },
  booking: null,
  manageToken: ""
};
const landingState = {
  settings: null,
  customerProfile: null,
  staff: [],
  compatibleStaff: [],
  gallery: [],
  step: "service",
  calendarOffset: 0,
  calendarDays: [],
  galleryIndex: 0,
  galleryReturnFocus: null,
  staffLoadVersion: 0,
  calendarLoadVersion: 0,
  slotLoadVersion: 0,
  businessLoadVersion: 0,
  serviceVerificationVersion: 0,
  serviceVerificationStatus: "idle",
  serviceVerificationMessage: "",
  serviceVerificationRetry: null,
  serviceStaffCache: new Map(),
  cacheBusinessSlug: "",
  submitting: false,
  slotCache: new Map(),
  calendarCache: new Map()
};

function byId(id) {
  return document.getElementById(id);
}

function element(tag, options = {}) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = String(options.text);
  if (options.type) node.type = options.type;
  return node;
}

function appendTextRow(container, label, value) {
  const row = element("div");
  row.append(element("strong", { text: label }), document.createTextNode(String(value || "No indicado")));
  container.append(row);
  return row;
}

function getBusinessSlug() {
  const value = new URLSearchParams(window.location.search).get("b");
  if (!value) return "";
  return /^[a-z0-9]+(?:-[a-z0-9]+)*$/i.test(value) && value.length <= 200 ? value : "";
}

function getOpportunityAttributionToken() {
  const value = new URLSearchParams(window.location.search).get("oa");
  return value && value.length <= 512 ? value : "";
}

function getLinkedServiceId() {
  const value = Number(new URLSearchParams(window.location.search).get("service_id"));
  return Number.isInteger(value) && value > 0 ? value : null;
}

function isRepeatBooking() {
  return new URLSearchParams(window.location.search).get("repeat") === "1";
}

function safeExternalUrl(value) {
  if (!value || typeof value !== "string") return "";
  try {
    const url = new URL(value, window.location.origin);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch (_) {
    return "";
  }
}

function safeMediaUrl(value) {
  if (!value || typeof value !== "string") return "";
  if (value.startsWith("/uploads/")) return `${API_BASE_URL}${value}`;
  return safeExternalUrl(value);
}

function safeColor(value, fallback) {
  return /^#[0-9a-f]{6}$/i.test(String(value || "")) ? value : fallback;
}

function colorText(hex) {
  const channels = hex.slice(1).match(/.{2}/g).map((part) => Number.parseInt(part, 16) / 255);
  const linear = channels.map((value) => value <= .03928 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
  const luminance = .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2];
  return luminance > .42 ? "#111827" : "#ffffff";
}

function phoneDigits(value) {
  const digits = String(value || "").replace(/\D/g, "");
  return digits.length >= 7 && digits.length <= 15 ? digits : "";
}

function whatsappUrl(phone) {
  const digits = phoneDigits(phone);
  return digits ? `https://wa.me/${digits}` : "";
}

function isValidPublicService(service) {
  const serviceId = Number(service?.id);
  return Boolean(service)
    && service.active !== false
    && Number.isInteger(serviceId)
    && serviceId > 0
    && typeof service.name === "string"
    && Boolean(service.name.trim());
}

function setSafeLink(id, value) {
  const link = byId(id);
  const href = safeExternalUrl(value);
  link.hidden = !href;
  if (href) link.href = href;
  else link.removeAttribute("href");
  return Boolean(href);
}

function safeResponseMessage(status, code, context = "general") {
  if (status === 401) return "Tu sesión ha caducado. Vuelve a iniciar sesión para continuar con tu cuenta.";
  if (status === 403) return "No tienes permiso para realizar esta acción.";
  if (status === 404 && context === "landing") return "Este negocio no está disponible para reservas en este momento.";
  if (status === 404 && context === "booking") return "El negocio o el servicio ya no está disponible para reserva.";
  if (status === 409 && ["slot_unavailable", "Ese hueco ya no está disponible"].includes(code)) return "Ese horario ya no está disponible. Elige otro hueco.";
  if (status === 409 && ["no_staff_available_for_service", "no_bookable_staff"].includes(code)) return "Ahora mismo no hay profesionales disponibles para este servicio.";
  if (status === 409 && code === "staff_not_available_for_service") return "El profesional seleccionado ya no está disponible para este servicio.";
  if (status === 422 || status === 400) return "Revisa los datos de la solicitud antes de continuar.";
  if (status === 429) return "Has realizado demasiados intentos. Espera un momento antes de volver a probar.";
  if (status >= 500) return "El servicio no está disponible temporalmente. Vuelve a intentarlo.";
  return context === "availability"
    ? "No se pudieron comprobar los horarios. Vuelve a intentarlo."
    : "No se pudo completar la acción. Vuelve a intentarlo.";
}

async function requestJson(path, options = {}, context = "general") {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15000);
  try {
    const secureOptions = await AutonoGrowAuth.secureRequestOptions({ ...options, signal: controller.signal });
    const response = await nativeFetch(`${API_BASE_URL}${path}`, secureOptions);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const code = typeof body.detail === "string" ? body.detail : typeof body.message === "string" ? body.message : "";
      const error = new Error(safeResponseMessage(response.status, code, context));
      error.status = response.status;
      error.code = code;
      throw error;
    }
    return body;
  } catch (error) {
    if (error.name === "AbortError") {
      const timeoutError = new Error("La comprobación está tardando demasiado. Vuelve a intentarlo.");
      timeoutError.status = 408;
      throw timeoutError;
    }
    if (typeof error.status === "number") throw error;
    throw Object.assign(new Error(context === "availability"
      ? "No se pudieron comprobar los horarios. Vuelve a intentarlo."
      : "No se pudo conectar con el servicio. Comprueba tu conexión y vuelve a intentarlo."), { status: 0 });
  } finally {
    window.clearTimeout(timeout);
  }
}

function showUnavailable(kind = "not-found") {
  byId("landing-loading").hidden = true;
  byId("landing-app").hidden = true;
  byId("landing-unavailable").hidden = false;
  const network = kind === "network";
  byId("unavailable-title").textContent = network
    ? "No se pudo cargar la página del negocio."
    : "Este negocio no está disponible para reservas en este momento.";
  byId("unavailable-copy").textContent = network
    ? "Comprueba tu conexión y vuelve a intentarlo."
    : "Comprueba que el enlace sea correcto o vuelve a intentarlo más tarde.";
  byId("retry-landing").hidden = !network;
  document.querySelector('meta[name="robots"]').content = "noindex, nofollow";
}

function isCurrentBusinessLoad(slug, businessLoadVersion) {
  return landingState.businessLoadVersion === businessLoadVersion
    && getBusinessSlug() === slug
    && bookingState.business?.slug === slug;
}

function compatibleStaffCacheKey(slug, serviceId) {
  return `${slug}:${serviceId}`;
}

function loadCompatibleStaffCached(slug, serviceId) {
  const key = compatibleStaffCacheKey(slug, serviceId);
  if (landingState.serviceStaffCache.has(key)) return landingState.serviceStaffCache.get(key);
  const pending = requestJson(
    `/api/businesses/${encodeURIComponent(slug)}/staff?service_id=${encodeURIComponent(serviceId)}`,
    {},
    "availability"
  ).then((data) => Array.isArray(data.staff) ? data.staff : [])
    .catch((error) => {
      landingState.serviceStaffCache.delete(key);
      throw error;
    });
  landingState.serviceStaffCache.set(key, pending);
  return pending;
}

async function verifyReservableServices(services, slug, businessLoadVersion, verificationVersion) {
  const candidates = (Array.isArray(services) ? services : []).filter(isValidPublicService);
  const verified = new Array(candidates.length);
  let nextIndex = 0;
  let failedCount = 0;

  async function worker() {
    while (nextIndex < candidates.length) {
      const index = nextIndex;
      nextIndex += 1;
      const service = candidates[index];
      try {
        const staff = await loadCompatibleStaffCached(slug, service.id);
        if (!isCurrentBusinessLoad(slug, businessLoadVersion)
          || landingState.serviceVerificationVersion !== verificationVersion) return;
        if (staff.length > 0) verified[index] = service;
      } catch (_) {
        if (!isCurrentBusinessLoad(slug, businessLoadVersion)
          || landingState.serviceVerificationVersion !== verificationVersion) return;
        failedCount += 1;
      }
    }
  }

  const workerCount = Math.min(SERVICE_VERIFICATION_CONCURRENCY, candidates.length);
  await Promise.all(Array.from({ length: workerCount }, () => worker()));
  return {
    candidatesCount: candidates.length,
    failedCount,
    services: verified.filter(Boolean)
  };
}

function setVerifiedServices(status, services, message = "", retry = null) {
  landingState.serviceVerificationStatus = status;
  landingState.serviceVerificationMessage = message;
  landingState.serviceVerificationRetry = retry;
  bookingState.business.services = services;
  if (bookingState.service && !services.some((service) => String(service.id) === String(bookingState.service.id))) {
    bookingState.service = null;
    bookingState.staff = null;
    bookingState.date = null;
    bookingState.slot = null;
    landingState.compatibleStaff = [];
  }
  renderServices(services, message, retry);
}

async function loadVerifiedReservableServices(slug, businessLoadVersion) {
  const verificationVersion = ++landingState.serviceVerificationVersion;
  setVerifiedServices("checking", [], "Comprobando servicios disponibles…");
  let publicServices;
  try {
    publicServices = await requestJson(
      `/api/businesses/${encodeURIComponent(slug)}/services`,
      {},
      "landing"
    );
  } catch (_) {
    if (!isCurrentBusinessLoad(slug, businessLoadVersion)
      || landingState.serviceVerificationVersion !== verificationVersion) return;
    setVerifiedServices(
      "error",
      [],
      "No se pudieron comprobar los servicios reservables. Vuelve a intentarlo.",
      () => loadVerifiedReservableServices(slug, businessLoadVersion)
    );
    return;
  }

  const result = await verifyReservableServices(
    publicServices,
    slug,
    businessLoadVersion,
    verificationVersion
  );
  if (!isCurrentBusinessLoad(slug, businessLoadVersion)
    || landingState.serviceVerificationVersion !== verificationVersion) return;

  if (result.candidatesCount > 0 && result.failedCount === result.candidatesCount) {
    setVerifiedServices(
      "error",
      [],
      "No se pudieron comprobar los servicios reservables. Vuelve a intentarlo.",
      () => loadVerifiedReservableServices(slug, businessLoadVersion)
    );
    return;
  }
  if (result.services.length === 0 && result.failedCount > 0) {
    setVerifiedServices(
      "error",
      [],
      "No se pudieron comprobar todos los servicios y no hay servicios verificados para reserva online. Vuelve a intentarlo.",
      () => loadVerifiedReservableServices(slug, businessLoadVersion)
    );
    return;
  }
  if (result.services.length === 0) {
    setVerifiedServices("empty", [], "No hay servicios disponibles para reserva online.");
    return;
  }
  setVerifiedServices(
    result.failedCount > 0 ? "partial" : "ready",
    result.services,
    result.failedCount > 0 ? "Algunos servicios no se pudieron comprobar. Solo mostramos los verificados." : "",
    result.failedCount > 0 ? () => loadVerifiedReservableServices(slug, businessLoadVersion) : null
  );
}

async function loadPublicBusiness() {
  const businessLoadVersion = ++landingState.businessLoadVersion;
  const slug = getBusinessSlug();
  if (!slug) {
    showUnavailable("not-found");
    return;
  }
  byId("landing-loading").hidden = false;
  byId("landing-unavailable").hidden = true;
  try {
    const business = await requestJson(`/api/businesses/${encodeURIComponent(slug)}`, {}, "landing");
    if (landingState.businessLoadVersion !== businessLoadVersion || getBusinessSlug() !== slug) return;
    if (business.status !== "active") {
      showUnavailable("not-found");
      return;
    }
    if (landingState.cacheBusinessSlug && landingState.cacheBusinessSlug !== slug) {
      landingState.serviceStaffCache.clear();
    }
    landingState.cacheBusinessSlug = slug;
    bookingState.business = { ...business, services: [] };
    renderPublicLanding(business);
    const servicesPromise = loadVerifiedReservableServices(slug, businessLoadVersion);
    byId("landing-loading").hidden = true;
    byId("landing-app").hidden = false;
    document.querySelector('meta[name="robots"]').content = "index, follow";
    await loadSecondarySources(slug, businessLoadVersion);
    await servicesPromise;
    const linkedServiceId = getLinkedServiceId();
    const linkedService = (bookingState.business.services || []).find(
      (service) => Number(service.id) === linkedServiceId
    );
    if (linkedService && !bookingState.service) await selectBookingService(linkedService, false);
  } catch (error) {
    if (landingState.businessLoadVersion !== businessLoadVersion) return;
    showUnavailable(error.status === 404 ? "not-found" : "network");
  }
}

async function loadSecondarySources(slug, businessLoadVersion) {
  const sources = await Promise.allSettled([
    requestJson(`/api/businesses/${encodeURIComponent(slug)}/staff`, {}, "landing"),
    requestJson(`/api/businesses/${encodeURIComponent(slug)}/media/gallery`, {}, "landing"),
    requestJson(`/api/businesses/${encodeURIComponent(slug)}/availability-settings`, {}, "availability")
  ]);
  if (!isCurrentBusinessLoad(slug, businessLoadVersion)) return;
  const [staff, gallery, settings] = sources;

  if (staff.status === "fulfilled") {
    landingState.staff = staff.value.staff || [];
    renderStaff(landingState.staff);
  } else {
    renderStaff([], "No se pudo cargar el equipo. La reserva seguirá mostrando profesionales compatibles cuando elijas servicio.");
  }

  if (gallery.status === "fulfilled") {
    landingState.gallery = gallery.value.images || [];
    renderGallery(landingState.gallery);
  } else {
    renderGallery([], "No se pudo cargar la galería. El resto de la información sigue disponible.");
  }

  landingState.settings = settings.status === "fulfilled" ? settings.value : null;
  renderBookingTimezone();
  updateBookingAvailability();
}

function renderPublicLanding(business) {
  applyBranding(business);
  setText("business-name", business.name);
  setText("nav-business-name", business.name);
  setText("business-category", business.category || "Negocio local");
  setText("business-headline", business.headline || "");
  setText("business-description", business.description || "");
  setText("business-city", business.city || "");
  setText("business-city-hero", business.city || "");
  byId("business-city-hero").hidden = !business.city;
  setText("business-address", business.address || "No indicada");
  setText("business-schedule", business.schedule || "El negocio no ha publicado un horario habitual.");
  byId("address-row").hidden = !business.address;
  byId("city-row").hidden = !business.city;
  renderInformation(business);
  renderLogo("business-logo", business);
  renderLogo("nav-business-logo", business);
  renderLocation(business);
  renderReviews(business);
  renderContact(business);
  updateMetadata(business);
}

function setText(id, value) {
  byId(id).textContent = value == null ? "" : String(value);
}

function applyBranding(business) {
  const root = document.documentElement;
  const primary = safeColor(business.primary_color, "#334155");
  root.style.setProperty("--color-primary", primary);
  root.style.setProperty("--color-secondary", safeColor(business.secondary_color, "#0f172a"));
  root.style.setProperty("--color-accent", safeColor(business.accent_color, "#d97706"));
  root.style.setProperty("--color-background", safeColor(business.background_color, "#f8fafc"));
  root.style.setProperty("--color-on-primary", colorText(primary));
  const templates = new Set(["classic", "elegant", "beauty", "clinic", "urban", "minimal"]);
  const template = templates.has(business.template_key) ? business.template_key : "classic";
  document.body.className = `template-${template}`;
}

function renderLogo(id, business) {
  const image = byId(id);
  const url = safeMediaUrl(business.logo_url);
  image.hidden = !url;
  if (!url) {
    image.removeAttribute("src");
    return;
  }
  image.src = url;
  image.alt = business.logo_alt || `Logo de ${business.name}`;
  image.addEventListener("error", () => {
    image.hidden = true;
    image.removeAttribute("src");
  }, { once: true });
}

function updateMetadata(business) {
  const title = `${business.name} | Servicios y reserva`;
  const description = String(business.headline || business.description || `Consulta los servicios y solicita una cita en ${business.name}.`).slice(0, 160);
  document.title = title;
  document.querySelector('meta[name="description"]').content = description;
  document.querySelector('meta[property="og:title"]').content = title;
  document.querySelector('meta[property="og:description"]').content = description;
  const logo = safeMediaUrl(business.logo_url);
  if (logo) {
    let imageMeta = document.querySelector('meta[property="og:image"]');
    if (!imageMeta) {
      imageMeta = document.createElement("meta");
      imageMeta.setAttribute("property", "og:image");
      document.head.append(imageMeta);
    }
    imageMeta.content = logo;
  }
}

function renderInformation(business) {
  const container = byId("promotions-list");
  container.replaceChildren();
  const copy = business.description || business.headline || "Consulta los servicios, el equipo y las formas de contacto que este negocio ha publicado.";
  container.append(element("p", { text: copy }));
}

function servicePrice(service) {
  return service.price_text ? String(service.price_text) : "Precio no indicado";
}

function serviceDuration(service) {
  if (service.duration_text) return String(service.duration_text);
  if (service.duration_minutes) return `${service.duration_minutes} min`;
  return "Duración no indicada";
}

function renderServices(services, statusMessage = "", retry = null) {
  const status = byId("services-status");
  const container = byId("services-list");
  const bookingOptions = byId("booking-service-options");
  const select = byId("service-select");
  container.replaceChildren();
  bookingOptions.replaceChildren();
  select.replaceChildren(new Option("Selecciona un servicio", ""));
  status.replaceChildren();
  if (statusMessage) status.append(element("p", { text: statusMessage }));
  if (retry) {
    const retryButton = element("button", { className: "btn btn-secondary", text: "Volver a comprobar", type: "button" });
    retryButton.addEventListener("click", retry, { once: true });
    status.append(retryButton);
  }

  if (!services.length) {
    if (!statusMessage) status.append(element("p", { text: "No hay servicios disponibles para reserva online." }));
    updateBookingAvailability();
    return;
  }

  services.forEach((service) => {
    const card = element("article", { className: "service-card" });
    card.append(element("h3", { text: service.name }));
    if (service.description) card.append(element("p", { text: service.description }));
    const meta = element("div", { className: "service-meta" });
    meta.append(element("span", { className: "pill", text: serviceDuration(service) }));
    meta.append(element("span", { className: "pill", text: servicePrice(service) }));
    card.append(meta);
    const action = element("button", { className: "btn btn-primary", text: "Reservar este servicio", type: "button" });
    action.addEventListener("click", () => selectBookingService(service, true));
    card.append(action);
    container.append(card);

    const option = new Option(`${service.name} · ${serviceDuration(service)} · ${servicePrice(service)}`, String(service.id));
    select.add(option);
    bookingOptions.append(createChoiceButton(
      service.name,
      `${serviceDuration(service)} · ${servicePrice(service)}`,
      bookingState.service && String(bookingState.service.id) === String(service.id),
      () => selectBookingService(service, false)
    ));
  });
  updateBookingAvailability();
}

function renderStaff(staff, errorMessage = "") {
  const section = byId("team");
  const status = byId("team-status");
  const container = byId("team-list");
  container.replaceChildren();
  status.textContent = errorMessage;
  if (!staff.length) {
    if (!errorMessage) section.hidden = true;
    setNavigationVisibility("team", false);
    return;
  }
  section.hidden = false;
  setNavigationVisibility("team", true);
  staff.forEach((member) => {
    const card = element("article", { className: "team-card" });
    const avatarUrl = safeMediaUrl(member.avatar_url);
    if (avatarUrl) {
      const avatar = element("img", { className: "team-avatar" });
      avatar.src = avatarUrl;
      avatar.alt = `Retrato de ${member.public_name}`;
      avatar.width = 76;
      avatar.height = 76;
      avatar.loading = "lazy";
      avatar.addEventListener("error", () => avatar.remove(), { once: true });
      card.append(avatar);
    } else {
      card.append(element("span", { className: "team-initial", text: String(member.public_name || "P").slice(0, 1).toUpperCase() }));
    }
    card.append(element("h3", { text: member.public_name || "Profesional" }));
    if (member.bio) card.append(element("p", { text: member.bio }));
    const action = element("button", { className: "btn btn-secondary staff-booking-action", text: `Reservar con ${member.public_name || "este profesional"}`, type: "button" });
    action.hidden = true;
    action.addEventListener("click", () => startBookingWithStaff(member));
    card.append(action);
    container.append(card);
  });
}

function renderGallery(images, errorMessage = "") {
  const section = byId("gallery-section");
  const status = byId("gallery-status");
  const grid = byId("gallery-grid");
  grid.replaceChildren();
  status.textContent = errorMessage;
  const validImages = images.map((item) => ({ ...item, safeUrl: safeMediaUrl(item.url || item) })).filter((item) => item.safeUrl);
  landingState.gallery = validImages;
  if (!validImages.length) {
    if (!errorMessage) section.hidden = true;
    setNavigationVisibility("gallery-section", false);
    return;
  }
  section.hidden = false;
  setNavigationVisibility("gallery-section", true);
  validImages.forEach((item, index) => {
    const button = element("button", { className: "gallery-item", type: "button" });
    button.setAttribute("aria-label", `Abrir imagen ${index + 1} de ${validImages.length}`);
    const image = element("img");
    image.src = item.safeUrl;
    image.alt = item.alt_text || `Imagen pública de ${bookingState.business.name}`;
    image.loading = "lazy";
    image.width = 640;
    image.height = 480;
    image.addEventListener("error", () => button.remove(), { once: true });
    button.append(image);
    button.addEventListener("click", () => openGallery(index, button));
    grid.append(button);
  });
}

function renderLocation(business) {
  const mapsAvailable = setSafeLink("maps-link", business.maps_url);
  byId("maps-link").hidden = !mapsAvailable;
  if (!business.address && !business.city && !business.schedule && !mapsAvailable) {
    byId("location").hidden = true;
    setNavigationVisibility("location", false);
  }
}

function renderReviews(business) {
  const visible = setSafeLink("reviews-link", business.reviews_url);
  byId("reviews").hidden = !visible;
  setNavigationVisibility("reviews", visible);
}

function renderContact(business) {
  let count = 0;
  const phone = String(business.phone || "").trim();
  const digits = phoneDigits(phone);
  const phoneLink = byId("phone-link");
  phoneLink.hidden = !digits;
  if (digits) {
    phoneLink.href = `tel:+${digits}`;
    setText("business-phone", phone);
    count += 1;
  }
  const whatsapp = whatsappUrl(phone);
  const whatsappLink = byId("whatsapp-direct-link");
  whatsappLink.hidden = !whatsapp;
  if (whatsapp) {
    whatsappLink.href = whatsapp;
    byId("booking-contact-link").href = whatsapp;
    count += 1;
  } else {
    byId("booking-contact-link").hidden = true;
  }
  if (setSafeLink("instagram-link", business.instagram_url)) count += 1;
  byId("contact-empty").hidden = count > 0;
}

function setNavigationVisibility(sectionId, visible) {
  const link = document.querySelector(`[data-nav-section="${sectionId}"]`);
  if (link) link.hidden = !visible;
}

function createChoiceButton(title, detail, selected, action) {
  const button = element("button", { className: "choice-button", type: "button" });
  button.setAttribute("aria-pressed", String(Boolean(selected)));
  button.append(element("strong", { text: title }), element("small", { text: detail }), element("span", { className: "choice-check" }));
  button.addEventListener("click", action);
  return button;
}

function startBookingWithStaff(member) {
  bookingState.staff = member;
  showBookingStep("service");
  showBookingMessage(`Elige un servicio. Comprobaremos si ${member.public_name || "el profesional"} puede realizarlo.`, "info");
  focusBooking();
}

async function selectBookingService(service, fromLanding) {
  const previousStaff = bookingState.staff;
  bookingState.service = service;
  bookingState.date = null;
  bookingState.slot = null;
  bookingState.booking = null;
  landingState.calendarOffset = 0;
  landingState.slotCache.clear();
  syncServiceSelection();
  if (fromLanding) focusBooking();
  showBookingStep("staff");
  await loadStaffForService(service.id, previousStaff);
  if (isRepeatBooking() && landingState.compatibleStaff.length) {
    bookingState.staff = null;
    renderBookingStaffOptions();
    showBookingStep("datetime");
  }
}

function syncServiceSelection() {
  byId("service-select").value = bookingState.service ? String(bookingState.service.id) : "";
  renderServices(
    bookingState.business.services || [],
    landingState.serviceVerificationMessage,
    landingState.serviceVerificationRetry
  );
}

async function loadStaffForService(serviceId, preferredStaff = null) {
  const version = ++landingState.staffLoadVersion;
  const status = byId("staff-loading");
  landingState.compatibleStaff = [];
  byId("booking-staff-options").replaceChildren();
  status.textContent = "Comprobando profesionales compatibles…";
  byId("online-booking-unavailable").hidden = true;
  updateBookingControls();
  try {
    const staff = await loadCompatibleStaffCached(getBusinessSlug(), serviceId);
    if (version !== landingState.staffLoadVersion || String(bookingState.service?.id) !== String(serviceId)) return;
    landingState.compatibleStaff = staff;
    const compatiblePreferred = preferredStaff && landingState.compatibleStaff.find((item) => String(item.id) === String(preferredStaff.id));
    bookingState.staff = compatiblePreferred || null;
    status.textContent = preferredStaff && !compatiblePreferred && landingState.compatibleStaff.length
      ? `${preferredStaff.public_name || "El profesional"} no atiende este servicio. Elige otra opción.`
      : "";
    renderBookingStaffOptions();
  } catch (error) {
    if (version !== landingState.staffLoadVersion) return;
    landingState.compatibleStaff = [];
    bookingState.staff = null;
    status.textContent = "";
    renderBookingStaffOptions(error.message);
  }
}

function renderBookingStaffOptions(errorMessage = "") {
  const container = byId("booking-staff-options");
  const select = byId("staff-select");
  const unavailable = byId("online-booking-unavailable");
  container.replaceChildren();
  select.replaceChildren(new Option("Cualquiera disponible", ""));
  const staff = landingState.compatibleStaff;
  if (!staff.length) {
    unavailable.hidden = false;
    byId("online-booking-unavailable-message").textContent = errorMessage || "Ahora mismo no hay profesionales disponibles para este servicio.";
    updateBookingControls();
    return;
  }
  unavailable.hidden = true;
  container.append(createChoiceButton(
    "Cualquier profesional disponible",
    "El backend asignará una persona compatible que tenga libre el horario elegido.",
    !bookingState.staff,
    () => selectBookingStaff(null)
  ));
  staff.forEach((member) => {
    select.add(new Option(member.public_name, String(member.id)));
    container.append(createChoiceButton(
      member.public_name,
      member.bio || "Profesional disponible para este servicio",
      bookingState.staff && String(bookingState.staff.id) === String(member.id),
      () => selectBookingStaff(member)
    ));
  });
  select.value = bookingState.staff ? String(bookingState.staff.id) : "";
  updateBookingControls();
}

function selectBookingStaff(member) {
  bookingState.staff = member;
  bookingState.date = null;
  bookingState.slot = null;
  landingState.calendarOffset = 0;
  landingState.slotCache.clear();
  renderBookingStaffOptions();
}

function renderBookingTimezone() {
  const timezone = landingState.settings?.timezone;
  byId("booking-timezone").textContent = timezone
    ? `Fechas y horas mostradas en la zona del negocio: ${timezone}.`
    : "Las fechas y horas válidas serán las devueltas por el negocio.";
}

function businessTimezone() {
  return landingState.settings?.timezone || bookingState.business?.timezone || "Europe/Madrid";
}

function dateKeyInTimezone(date = new Date()) {
  try {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: businessTimezone(), year: "numeric", month: "2-digit", day: "2-digit"
    }).formatToParts(date);
    const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${value.year}-${value.month}-${value.day}`;
  } catch (_) {
    return date.toISOString().slice(0, 10);
  }
}

function addDays(dateKey, days) {
  const date = new Date(`${dateKey}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function formatDateKey(dateKey) {
  try {
    return new Intl.DateTimeFormat("es-ES", {
      timeZone: businessTimezone(), weekday: "short", day: "numeric", month: "short"
    }).format(new Date(`${dateKey}T12:00:00Z`));
  } catch (_) {
    return dateKey;
  }
}

async function loadBookingDates(force = false) {
  if (!bookingState.service || !landingState.compatibleStaff.length) return;
  const maxDays = Math.max(1, Math.min(Number(landingState.settings?.max_days_ahead) || 14, 365));
  const pageSize = 14;
  const startOffset = Math.min(landingState.calendarOffset, maxDays);
  const endOffset = Math.min(startOffset + pageSize - 1, maxDays);
  const today = dateKeyInTimezone();
  const dateFrom = addDays(today, startOffset);
  const dateTo = addDays(today, endOffset);
  const staffKey = bookingState.staff ? String(bookingState.staff.id) : "any";
  const key = `${bookingState.service.id}:${staffKey}:${dateFrom}:${dateTo}`;
  const version = ++landingState.calendarLoadVersion;
  const container = byId("calendar-days");
  const picker = byId("calendar-picker");
  picker.setAttribute("aria-busy", "true");
  container.replaceChildren(element("p", { className: "empty-slots", text: "Comprobando fechas disponibles…" }));
  try {
    let data = !force ? landingState.calendarCache.get(key) : null;
    if (!data) {
      const params = new URLSearchParams({ from: dateFrom, to: dateTo, service_id: String(bookingState.service.id) });
      if (bookingState.staff) params.set("staff_business_user_id", String(bookingState.staff.id));
      data = await requestJson(`/api/businesses/${encodeURIComponent(getBusinessSlug())}/calendar-days?${params.toString()}`, {}, "availability");
      landingState.calendarCache.set(key, data);
    }
    if (version !== landingState.calendarLoadVersion) return;
    landingState.calendarDays = data.days || [];
    renderCalendarDays();
    byId("calendar-previous").disabled = startOffset === 0;
    byId("calendar-next").disabled = endOffset >= maxDays;
  } catch (error) {
    if (version !== landingState.calendarLoadVersion) return;
    landingState.calendarDays = [];
    const errorNode = element("p", { className: "empty-slots slot-error", text: "No se pudieron comprobar las fechas. Vuelve a intentarlo." });
    const retry = element("button", { className: "btn btn-secondary", text: "Reintentar fechas", type: "button" });
    retry.addEventListener("click", () => loadBookingDates(true));
    container.replaceChildren(errorNode, retry);
  } finally {
    if (version === landingState.calendarLoadVersion) picker.setAttribute("aria-busy", "false");
  }
}

function renderCalendarDays() {
  const container = byId("calendar-days");
  container.replaceChildren();
  if (!landingState.calendarDays.length) {
    container.append(element("p", { className: "empty-slots", text: "No hay fechas disponibles en este periodo." }));
    return;
  }
  landingState.calendarDays.forEach((day) => {
    const status = DAY_STATUS[day.status] || "No disponible";
    const selectable = ["available", "special"].includes(day.status);
    const button = element("button", { className: `calendar-day calendar-day-${day.status || "unknown"}`, type: "button" });
    button.disabled = !selectable;
    button.setAttribute("aria-pressed", String(bookingState.date?.value === day.date));
    button.setAttribute("aria-label", `${formatDateKey(day.date)}. ${status}`);
    button.append(element("strong", { text: formatDateKey(day.date).split(" ")[0] }), element("span", { text: formatDateKey(day.date).split(" ").slice(1).join(" ") }), element("small", { text: status }));
    if (selectable) button.addEventListener("click", () => selectBookingDate(day));
    container.append(button);
  });
}

async function selectBookingDate(day) {
  bookingState.date = { value: day.date, label: day.label || day.day_label || formatDateKey(day.date), status: day.status };
  bookingState.slot = null;
  byId("preferred-day").value = bookingState.date.label;
  byId("preferred-time").value = "";
  renderCalendarDays();
  updateSelectedSlotSummary();
  await loadBookingSlots(false);
}

async function loadBookingSlots(force = false) {
  if (!bookingState.service || !bookingState.date) return;
  const staffKey = bookingState.staff ? String(bookingState.staff.id) : "any";
  const key = `${bookingState.service.id}:${staffKey}:${bookingState.date.value}`;
  const version = ++landingState.slotLoadVersion;
  const container = byId("time-slots");
  container.replaceChildren(element("p", { className: "empty-slots", text: "Comprobando horarios disponibles…" }));
  byId("calendar-picker").setAttribute("aria-busy", "true");
  try {
    let data = !force ? landingState.slotCache.get(key) : null;
    if (!data) {
      const params = new URLSearchParams({ service_id: String(bookingState.service.id), date: bookingState.date.value });
      if (bookingState.staff) params.set("staff_business_user_id", String(bookingState.staff.id));
      data = await requestJson(`/api/businesses/${encodeURIComponent(getBusinessSlug())}/available-slots?${params.toString()}`, {}, "availability");
      landingState.slotCache.set(key, data);
    }
    if (version !== landingState.slotLoadVersion) return;
    renderBookingSlots(data.slots || []);
  } catch (error) {
    if (version !== landingState.slotLoadVersion) return;
    const copy = element("p", { className: "empty-slots slot-error", text: "No se pudieron comprobar los horarios. Vuelve a intentarlo." });
    const retry = element("button", { className: "btn btn-secondary", text: "Reintentar horarios", type: "button" });
    retry.addEventListener("click", () => loadBookingSlots(true));
    container.replaceChildren(copy, retry);
  } finally {
    if (version === landingState.slotLoadVersion) byId("calendar-picker").setAttribute("aria-busy", "false");
  }
}

function renderBookingSlots(slots) {
  const container = byId("time-slots");
  container.replaceChildren();
  if (!slots.length) {
    container.append(element("p", { className: "empty-slots", text: "No hay horarios disponibles para esta fecha. Prueba otro día o profesional." }));
    return;
  }
  slots.forEach((slot) => {
    const button = element("button", { className: "time-slot", text: slot.label, type: "button" });
    button.setAttribute("aria-pressed", String(bookingState.slot?.start === slot.start));
    button.addEventListener("click", () => {
      bookingState.slot = slot;
      byId("preferred-time").value = slot.label;
      renderBookingSlots(slots);
      updateSelectedSlotSummary();
      updateBookingControls();
    });
    container.append(button);
  });
}

function updateSelectedSlotSummary() {
  const summary = byId("selected-slot-summary");
  summary.hidden = !bookingState.date;
  if (!bookingState.date) return;
  const professional = bookingState.staff?.public_name || "Cualquier profesional disponible";
  summary.textContent = bookingState.slot
    ? `${bookingState.service.name} · ${professional} · ${bookingState.date.label} a las ${bookingState.slot.label}`
    : `${bookingState.service.name} · ${professional} · ${bookingState.date.label}. Elige una hora.`;
}

function collectCustomerData() {
  clearFieldErrors();
  const nameInput = byId("client-name");
  const phoneInput = byId("client-phone");
  const notesInput = byId("notes");
  const files = Array.from(byId("booking-photos").files || []);
  const errors = [];
  const name = nameInput.value.trim();
  const phone = phoneInput.value.trim();
  const notes = notesInput.value.trim();
  if (name.length < 2 || name.length > 200) errors.push([nameInput, "Escribe un nombre de entre 2 y 200 caracteres."]);
  if (phone.length > 40) errors.push([phoneInput, "El teléfono no puede superar 40 caracteres."]);
  if (notes.length > 1000) errors.push([notesInput, "Los comentarios no pueden superar 1000 caracteres."]);
  if (files.length > 5) errors.push([byId("booking-photos"), "Puedes adjuntar como máximo 5 imágenes."]);
  files.forEach((file) => {
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) errors.push([byId("booking-photos"), "Solo se admiten imágenes JPG, PNG o WEBP."]);
    if (file.size > 5 * 1024 * 1024) errors.push([byId("booking-photos"), "Cada imagen debe ocupar 5 MB o menos."]);
  });
  if (errors.length) {
    showValidationErrors(errors);
    return false;
  }
  bookingState.customer = { name, phone, notes, files };
  return true;
}

function clearFieldErrors() {
  document.querySelectorAll("[aria-invalid='true']").forEach((field) => {
    field.removeAttribute("aria-invalid");
    const descriptions = String(field.getAttribute("aria-describedby") || "").split(/\s+/).filter((id) => id && !id.startsWith("booking-error-"));
    if (descriptions.length) field.setAttribute("aria-describedby", descriptions.join(" "));
    else field.removeAttribute("aria-describedby");
  });
  byId("booking-error-summary").hidden = true;
  byId("booking-error-summary").replaceChildren();
}

function showValidationErrors(errors) {
  const summary = byId("booking-error-summary");
  summary.replaceChildren(element("strong", { text: "Revisa los datos para continuar" }));
  const list = element("ul");
  errors.forEach(([field, message], index) => {
    field.setAttribute("aria-invalid", "true");
    const item = element("li", { text: message });
    item.id = `booking-error-${field.id}-${index}`;
    list.append(item);
    const current = String(field.getAttribute("aria-describedby") || "").trim();
    field.setAttribute("aria-describedby", `${current} ${item.id}`.trim());
  });
  summary.append(list);
  summary.hidden = false;
  summary.focus();
  errors[0][0].focus();
}

function renderBookingReview() {
  const container = byId("booking-review");
  container.replaceChildren();
  const blocks = [
    ["Negocio", [bookingState.business.name], "service"],
    ["Servicio", [bookingState.service.name, serviceDuration(bookingState.service), servicePrice(bookingState.service)], "service"],
    ["Profesional", [bookingState.staff?.public_name || "Cualquier profesional disponible"], "staff"],
    ["Fecha y hora", [bookingState.date.label, bookingState.slot.label, `Zona: ${businessTimezone()}`], "datetime"],
    ["Tus datos", [bookingState.customer.name, bookingState.customer.phone || "Teléfono no indicado"], "customer"]
  ];
  if (bookingState.customer.notes) blocks.push(["Comentarios", [bookingState.customer.notes], "customer"]);
  blocks.forEach(([title, values, target]) => {
    const block = element("article", { className: "review-block" });
    block.append(element("h3", { text: title }));
    values.forEach((value) => block.append(element("p", { text: value })));
    const edit = element("button", { className: "review-edit", text: "Editar", type: "button" });
    edit.addEventListener("click", () => showBookingStep(target));
    block.append(edit);
    container.append(block);
  });
}

function showBookingStep(step) {
  if (!BOOKING_STEPS.includes(step)) return;
  landingState.step = step;
  document.querySelectorAll("[data-booking-step]").forEach((field) => { field.hidden = field.dataset.bookingStep !== step; });
  byId("booking-form").hidden = step === "result";
  byId("booking-confirmation").hidden = step !== "result";
  if (step === "result") document.querySelector('meta[name="robots"]').content = "noindex, nofollow";
  document.querySelectorAll("[data-booking-progress]").forEach((item) => {
    const itemIndex = BOOKING_STEPS.indexOf(item.dataset.bookingProgress);
    const currentIndex = BOOKING_STEPS.indexOf(step);
    item.classList.toggle("complete", itemIndex < currentIndex);
    if (item.dataset.bookingProgress === step) item.setAttribute("aria-current", "step");
    else item.removeAttribute("aria-current");
  });
  clearFieldErrors();
  updateBookingControls();
  if (step === "datetime") loadBookingDates();
}

function updateBookingControls() {
  const stepIndex = BOOKING_STEPS.indexOf(landingState.step);
  const back = byId("booking-back");
  const next = byId("booking-next");
  const submit = byId("booking-submit");
  back.hidden = stepIndex <= 0 || landingState.step === "result";
  next.hidden = !["service", "staff", "datetime", "customer"].includes(landingState.step);
  submit.hidden = landingState.step !== "review";
  next.disabled = (landingState.step === "service" && !bookingState.service)
    || (landingState.step === "staff" && !landingState.compatibleStaff.length)
    || (landingState.step === "datetime" && !bookingState.slot);
  submit.disabled = landingState.submitting;
}

function updateBookingAvailability() {
  const verificationComplete = ["ready", "partial"].includes(landingState.serviceVerificationStatus);
  const available = verificationComplete && Boolean(bookingState.business?.services?.length);
  byId("nav-booking-button").hidden = !available;
  byId("hero-booking-button").hidden = !available;
  byId("mobile-booking-cta").hidden = !available;
  document.querySelectorAll(".staff-booking-action").forEach((action) => { action.hidden = !available; });
  const statusLabel = landingState.serviceVerificationStatus === "checking"
    ? "Comprobando servicios disponibles…"
    : landingState.serviceVerificationStatus === "error"
      ? "Servicios online no comprobados"
      : available
        ? "Reservas online disponibles"
        : "Sin servicios disponibles para reserva online";
  setText("business-booking-status", statusLabel);
  if (landingState.step !== "result") byId("booking-form").hidden = !available;
  if (available) {
    byId("booking-error-summary").hidden = true;
    byId("booking-error-summary").replaceChildren();
  } else if (landingState.serviceVerificationStatus === "checking") {
    showBookingMessage("Comprobando servicios disponibles…", "info");
  } else if (landingState.serviceVerificationStatus === "error") {
    showBookingMessage(landingState.serviceVerificationMessage || "No se pudieron comprobar los servicios reservables. Vuelve a intentarlo.");
  } else {
    showBookingMessage("No hay servicios disponibles para reserva online.", "info");
  }
}

function showBookingMessage(message, kind = "error") {
  const summary = byId("booking-error-summary");
  summary.replaceChildren(element("strong", { text: kind === "error" ? "No pudimos continuar" : "Información" }), element("p", { text: message }));
  summary.hidden = false;
}

function focusBooking() {
  byId("booking").scrollIntoView({ behavior: "smooth", block: "start" });
  window.setTimeout(() => byId("booking-title").focus(), 250);
}

function previousBookingStep() {
  const index = BOOKING_STEPS.indexOf(landingState.step);
  if (index > 0) showBookingStep(BOOKING_STEPS[index - 1]);
}

function nextBookingStep() {
  if (landingState.step === "service" && !bookingState.service) {
    showBookingMessage("Elige un servicio para continuar.");
    return;
  }
  if (landingState.step === "staff" && !landingState.compatibleStaff.length) {
    showBookingMessage("No hay profesionales disponibles para este servicio.");
    return;
  }
  if (landingState.step === "datetime" && !bookingState.slot) {
    showBookingMessage("Elige una fecha y un horario disponibles.");
    return;
  }
  if (landingState.step === "customer" && !collectCustomerData()) return;
  const index = BOOKING_STEPS.indexOf(landingState.step);
  let next = BOOKING_STEPS[index + 1];
  if (landingState.step === "datetime" && landingState.customerProfile) {
    const profile = landingState.customerProfile;
    const knownName = String(profile.preferred_name || profile.name || "").trim();
    if (knownName) {
      bookingState.customer = {
        ...bookingState.customer,
        name: knownName,
        phone: profile.phone || ""
      };
      next = "review";
    }
  }
  if (next === "review") renderBookingReview();
  showBookingStep(next);
  byId(`booking-step-${next}`)?.querySelector("legend")?.focus?.();
}

async function submitBooking(event) {
  event.preventDefault();
  if (landingState.submitting || landingState.step !== "review") return;
  if (!bookingState.business || !bookingState.service || !bookingState.date || !bookingState.slot || !bookingState.customer.name) {
    showBookingMessage("La selección ha cambiado. Revisa la solicitud antes de enviarla.");
    return;
  }
  const validService = ["ready", "partial"].includes(landingState.serviceVerificationStatus)
    && (bookingState.business.services || []).some((service) =>
      String(service.id) === String(bookingState.service.id)
    );
  const validStaff = !bookingState.staff || landingState.compatibleStaff.some((member) => String(member.id) === String(bookingState.staff.id));
  if (!validService || !validStaff) {
    showBookingMessage("El servicio o profesional ya no forma parte de esta solicitud. Vuelve a seleccionarlo.");
    showBookingStep(validService ? "staff" : "service");
    return;
  }

  landingState.submitting = true;
  updateBookingControls();
  const submit = byId("booking-submit");
  submit.textContent = "Enviando solicitud…";
  const payload = {
    customer_name: bookingState.customer.name,
    service_id: Number(bookingState.service.id),
    start_datetime: bookingState.slot.start,
    preferred_day_label: bookingState.date.label,
    source: "landing"
  };
  if (bookingState.customer.phone) payload.customer_phone = bookingState.customer.phone;
  if (bookingState.customer.notes) payload.notes = bookingState.customer.notes;
  if (bookingState.staff) payload.staff_business_user_id = Number(bookingState.staff.id);
  const attributionToken = getOpportunityAttributionToken();
  if (attributionToken) payload.attribution_token = attributionToken;

  try {
    const result = await requestJson(`/api/businesses/${encodeURIComponent(getBusinessSlug())}/bookings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }, "booking");
    let attachmentMessage = "No se adjuntaron imágenes.";
    if (bookingState.customer.files.length) {
      submit.textContent = "Adjuntando imágenes…";
      attachmentMessage = await uploadBookingPhotos(result.booking.id, result.booking_manage_token, bookingState.customer.files);
    }
    bookingState.booking = result.booking;
    bookingState.manageToken = result.booking_manage_token || "";
    renderBookingResult(result.booking, Boolean(result.linked_to_account), attachmentMessage);
    clearPersonalBookingData();
    showBookingStep("result");
    byId("booking-confirmation").focus();
  } catch (error) {
    if (error.status === 409) {
      showBookingStep(error.code?.includes("staff") || error.code === "no_bookable_staff" ? "staff" : "datetime");
      showBookingMessage(error.message);
      if (landingState.step === "datetime") {
        landingState.slotCache.clear();
        bookingState.slot = null;
        await loadBookingSlots(true);
      } else if (bookingState.service) {
        await loadStaffForService(bookingState.service.id);
      }
    } else if (error.status === 404) {
      showBookingStep("service");
      showBookingMessage(error.message);
    } else {
      showBookingMessage(error.message);
    }
    byId("booking-error-summary").focus();
  } finally {
    landingState.submitting = false;
    submit.textContent = "Enviar solicitud";
    updateBookingControls();
  }
}

async function uploadBookingPhotos(bookingId, bookingManageToken, files) {
  const data = new FormData();
  files.forEach((file) => data.append("files", file));
  try {
    const result = await requestJson(`/api/businesses/${encodeURIComponent(getBusinessSlug())}/bookings/${encodeURIComponent(bookingId)}/attachments`, {
      method: "POST",
      headers: bookingManageToken ? { "X-Booking-Token": bookingManageToken } : {},
      body: data
    }, "booking");
    const count = (result.attachments || []).length;
    return count ? `${count} ${count === 1 ? "imagen adjunta" : "imágenes adjuntas"}.` : "No se adjuntaron imágenes.";
  } catch (_) {
    return "La solicitud se registró, pero no se pudieron adjuntar las imágenes.";
  }
}

function clearPersonalBookingData() {
  bookingState.customer = { name: "", phone: "", notes: "", files: [] };
  byId("client-name").value = "";
  byId("client-phone").value = "";
  byId("notes").value = "";
  byId("booking-photos").value = "";
}

function applyKnownCustomerProfile(profile) {
  landingState.customerProfile = profile;
  const name = String(profile?.preferred_name || profile?.name || "").trim();
  const phone = String(profile?.phone || "").trim();
  byId("client-name").value = name;
  byId("client-phone").value = phone;
  bookingState.customer = { ...bookingState.customer, name, phone };
}

async function claimPendingBooking() {
  if (!bookingState.booking?.id || !bookingState.manageToken) return;
  const status = byId("post-booking-login-status");
  if (status) status.textContent = "Guardando esta cita en tu cuenta…";
  try {
    await requestJson("/api/customer/claim-booking", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        booking_id: bookingState.booking.id,
        manage_token: bookingState.manageToken
      })
    }, "booking");
    bookingState.manageToken = "";
    if (status) status.textContent = "Cita guardada. La encontrarás en tu espacio.";
  } catch (error) {
    if (status) status.textContent = error.message;
  }
}

function renderBookingResult(booking, linkedToAccount, attachmentMessage) {
  const container = byId("booking-result");
  container.replaceChildren();
  const status = BOOKING_STATUS[booking.status] || { label: "Solicitud actualizada", next: "Consulta el siguiente paso con el negocio." };
  container.append(element("p", { className: "eyebrow", text: "Resultado de la reserva" }), element("h3", { text: status.label }), element("p", { text: status.next }));
  const grid = element("div", { className: "result-grid" });
  appendTextRow(grid, "Negocio", bookingState.business.name);
  appendTextRow(grid, "Servicio", booking.service_name || bookingState.service.name);
  appendTextRow(grid, "Profesional", booking.staff_display_name || bookingState.staff?.public_name || "Asignado por el negocio");
  appendTextRow(grid, "Fecha", booking.preferred_day_label || bookingState.date.label);
  appendTextRow(grid, "Hora", booking.preferred_time || bookingState.slot.label);
  appendTextRow(grid, "Estado", status.label);
  container.append(grid, element("p", { text: attachmentMessage }));
  container.append(element("p", { text: linkedToAccount
    ? "La solicitud está vinculada a tu cuenta y puedes consultarla en Mis citas."
    : "Esta reserva es anónima. Mis citas solo muestra reservas vinculadas a una cuenta en el momento de crearlas." }));
  const actions = element("div", { className: "result-actions" });
  const customerLink = element("a", { className: "btn btn-primary", text: "Ir a Mis citas" });
  customerLink.href = "../autonogrow-customer/index.html";
  const contactLink = element("a", { className: "btn btn-secondary", text: "Contactar con el negocio" });
  contactLink.href = "#contact";
  const backLink = element("a", { className: "btn btn-secondary", text: "Volver al inicio" });
  backLink.href = "#main-content";
  actions.append(customerLink, contactLink, backLink);
  container.append(actions);
  if (!linkedToAccount) {
    const login = element("section", { className: "post-booking-login" });
    login.append(
      element("h3", { text: "La próxima vez, aún más rápido" }),
      element("p", { text: "Guarda tus citas y reserva sin volver a rellenar tus datos. Además, podremos ofrecerte una atención más personalizada." })
    );
    const google = element("div", { className: "auth-google-button" });
    google.id = "post-booking-google-button";
    const loginStatus = element("p", { className: "inline-status" });
    loginStatus.id = "post-booking-login-status";
    loginStatus.setAttribute("aria-live", "polite");
    login.append(google, loginStatus);
    container.append(login);
    AutonoGrowAuth.renderGoogleButton(google, setupLandingAuth, () => {
      loginStatus.textContent = "No se pudo completar el acceso. Tu reserva sigue guardada.";
    });
  }
}

function openGallery(index, returnFocus) {
  landingState.galleryIndex = index;
  landingState.galleryReturnFocus = returnFocus;
  renderGalleryDialog();
  const dialog = byId("gallery-dialog");
  dialog.hidden = false;
  dialog.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
  byId("gallery-dialog-close").focus();
}

function renderGalleryDialog() {
  const item = landingState.gallery[landingState.galleryIndex];
  if (!item) return;
  byId("gallery-dialog-image").src = item.safeUrl;
  byId("gallery-dialog-image").alt = item.alt_text || `Imagen pública de ${bookingState.business.name}`;
  byId("gallery-dialog-caption").textContent = item.alt_text || `Imagen ${landingState.galleryIndex + 1} de ${landingState.gallery.length}`;
  byId("gallery-previous").hidden = landingState.gallery.length < 2;
  byId("gallery-next").hidden = landingState.gallery.length < 2;
}

function moveGallery(direction) {
  const count = landingState.gallery.length;
  if (count < 2) return;
  landingState.galleryIndex = (landingState.galleryIndex + direction + count) % count;
  renderGalleryDialog();
}

function closeGallery() {
  const dialog = byId("gallery-dialog");
  dialog.hidden = true;
  dialog.setAttribute("aria-hidden", "true");
  document.body.classList.remove("modal-open");
  landingState.galleryReturnFocus?.focus();
}

function handleGalleryKeydown(event) {
  if (byId("gallery-dialog").hidden) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeGallery();
    return;
  }
  if (event.key === "ArrowLeft") moveGallery(-1);
  if (event.key === "ArrowRight") moveGallery(1);
  if (event.key !== "Tab") return;
  const focusable = Array.from(byId("gallery-dialog").querySelectorAll("button:not([hidden]), [href], [tabindex]:not([tabindex='-1'])"));
  if (!focusable.length) return;
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

function setupNavigation() {
  const toggle = byId("public-menu-toggle");
  const menu = byId("public-menu");
  toggle.addEventListener("click", () => {
    const open = !menu.classList.contains("open");
    menu.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", String(open));
  });
  menu.addEventListener("click", (event) => {
    if (!event.target.closest("a")) return;
    menu.classList.remove("open");
    toggle.setAttribute("aria-expanded", "false");
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && menu.classList.contains("open")) {
      menu.classList.remove("open");
      toggle.setAttribute("aria-expanded", "false");
      toggle.focus();
    }
  });
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.filter((entry) => entry.isIntersecting).forEach((entry) => {
        document.querySelectorAll("[data-nav-section]").forEach((link) => link.removeAttribute("aria-current"));
        document.querySelector(`[data-nav-section="${entry.target.id}"]`)?.setAttribute("aria-current", "location");
      });
    }, { rootMargin: "-25% 0px -65%", threshold: 0 });
    document.querySelectorAll("section[id]").forEach((section) => observer.observe(section));
  }
}

function setupBooking() {
  byId("booking-back").addEventListener("click", previousBookingStep);
  byId("booking-next").addEventListener("click", nextBookingStep);
  byId("booking-form").addEventListener("submit", submitBooking);
  byId("calendar-previous").addEventListener("click", () => {
    landingState.calendarOffset = Math.max(0, landingState.calendarOffset - 14);
    bookingState.date = null;
    bookingState.slot = null;
    loadBookingDates();
  });
  byId("calendar-next").addEventListener("click", () => {
    landingState.calendarOffset += 14;
    bookingState.date = null;
    bookingState.slot = null;
    loadBookingDates();
  });
  byId("service-select").addEventListener("change", () => {
    const service = (bookingState.business?.services || []).find((item) => String(item.id) === byId("service-select").value);
    if (service) selectBookingService(service, false);
  });
  byId("staff-select").addEventListener("change", () => {
    const member = landingState.compatibleStaff.find((item) => String(item.id) === byId("staff-select").value) || null;
    selectBookingStaff(member);
  });
}

function setupGallery() {
  byId("gallery-dialog-close").addEventListener("click", closeGallery);
  document.querySelector("[data-gallery-close]").addEventListener("click", closeGallery);
  byId("gallery-previous").addEventListener("click", () => moveGallery(-1));
  byId("gallery-next").addEventListener("click", () => moveGallery(1));
  document.addEventListener("keydown", handleGalleryKeydown);
}

async function setupLandingAuth() {
  const userLabel = byId("landing-auth-user");
  const googleContainer = byId("landing-google-button");
  const logoutButton = byId("landing-logout");
  try {
    const user = await AutonoGrowAuth.getMe();
    if (user) {
      userLabel.textContent = user.preferred_name || user.name || user.email;
      googleContainer.replaceChildren();
      logoutButton.hidden = false;
      const profile = await requestJson("/api/customer/profile", {}, "booking");
      applyKnownCustomerProfile(profile);
      await claimPendingBooking();
    } else {
      userLabel.textContent = "";
      logoutButton.hidden = true;
      await AutonoGrowAuth.renderGoogleButton(googleContainer, setupLandingAuth);
    }
  } catch (_) {
    userLabel.textContent = "Reserva sin iniciar sesión disponible";
    logoutButton.hidden = true;
  }
  logoutButton.addEventListener("click", async () => {
    await AutonoGrowAuth.logout();
    window.location.reload();
  }, { once: true });
}

document.addEventListener("DOMContentLoaded", () => {
  setupNavigation();
  setupBooking();
  setupGallery();
  byId("retry-landing").addEventListener("click", loadPublicBusiness);
  loadPublicBusiness();
  setupLandingAuth();
});
