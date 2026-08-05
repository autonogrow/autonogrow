"use strict";

const API_BASE_URL = AutonoGrowAuth.API_BASE_URL;
const BOOKING_STATUS = {
  requested: { label: "Solicitud enviada", help: "El negocio debe revisar y confirmar la cita." },
  pending: { label: "Pendiente de confirmación", help: "El negocio está revisando la solicitud." },
  confirmed: { label: "Confirmada", help: "La cita está confirmada." },
  completed: { label: "Completada", help: "La cita ha finalizado." },
  cancelled: { label: "Cancelada", help: "La cita ya no está activa." },
  rejected: { label: "Rechazada", help: "El negocio no ha aceptado la solicitud." },
  no_show: { label: "No realizada", help: "La cita figura como no realizada." }
};
const CLOSED_STATUSES = new Set(["completed", "cancelled", "rejected", "no_show"]);
const customerState = {
  user: null,
  profile: null,
  bookings: [],
  selectedBooking: null,
  detailReturnFocus: null,
  loading: false,
  savingProfile: false
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

function safeExternalUrl(value) {
  if (!value || typeof value !== "string") return "";
  try {
    const url = new URL(value, window.location.origin);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch (_) {
    return "";
  }
}

function phoneDigits(value) {
  const digits = String(value || "").replace(/\D/g, "");
  return digits.length >= 7 && digits.length <= 15 ? digits : "";
}

function customerError(status) {
  if (status === 401) return "Tu sesión ha caducado. Vuelve a iniciar sesión para consultar tus citas.";
  if (status === 403) return "No tienes permiso para consultar esta información.";
  if (status === 404) return "La información solicitada ya no está disponible.";
  if (status === 422 || status === 400) return "Revisa los datos antes de guardar.";
  if (status === 429) return "Has realizado demasiados intentos. Espera un momento antes de continuar.";
  if (status >= 500) return "El portal no está disponible temporalmente. Vuelve a intentarlo.";
  return "No se pudo completar la acción. Vuelve a intentarlo.";
}

async function jsonRequest(path, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15000);
  try {
    const secureOptions = await AutonoGrowAuth.secureRequestOptions({ ...options, signal: controller.signal });
    const response = await fetch(`${API_BASE_URL}${path}`, secureOptions);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(customerError(response.status));
      error.status = response.status;
      if (response.status === 401) queueMicrotask(() => showCustomerLogin(true));
      throw error;
    }
    return body;
  } catch (error) {
    if (error.name === "AbortError") throw Object.assign(new Error("La operación está tardando demasiado. Vuelve a intentarlo."), { status: 408 });
    if (typeof error.status === "number") throw error;
    throw Object.assign(new Error("No se pudo conectar con el portal. Comprueba tu conexión y vuelve a intentarlo."), { status: 0 });
  } finally {
    window.clearTimeout(timeout);
  }
}

function bookingStatus(value) {
  return BOOKING_STATUS[value] || { label: "Estado actualizado", help: "Consulta el detalle con el negocio." };
}

function formatCivilDateTime(value) {
  if (!value) return "Fecha pendiente";
  const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!match) return "Fecha pendiente";
  const [, year, month, day, hours, minutes] = match;
  const civil = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day), Number(hours), Number(minutes)));
  return new Intl.DateTimeFormat("es-ES", {
    timeZone: "UTC", dateStyle: "medium", timeStyle: "short"
  }).format(civil);
}

function isUpcoming(item) {
  if (CLOSED_STATUSES.has(item.status) || !item.start_datetime) return false;
  const value = new Date(item.start_datetime);
  return Number.isNaN(value.getTime()) || value >= new Date();
}

function createEmptyState(title, copy) {
  const empty = element("div", { className: "empty-state" });
  empty.append(element("h3", { text: title }), element("p", { text: copy }));
  return empty;
}

function createBookingCard(item, index) {
  const card = element("article", { className: "booking-card" });
  const header = element("header");
  header.append(element("h3", { text: item.business_name || "Negocio" }));
  const status = bookingStatus(item.status);
  const badge = element("span", { className: `status-badge status-${String(item.status || "unknown").replace(/[^a-z_]/g, "")}`, text: status.label });
  header.append(badge);
  card.append(header, element("p", { className: "service-name", text: item.service_name || "Servicio" }), element("p", { text: formatCivilDateTime(item.start_datetime) }), element("p", { text: item.address || "Dirección no indicada" }));
  const actions = element("div", { className: "booking-actions" });
  const detail = element("button", { className: "primary-action", text: "Ver detalle", type: "button" });
  detail.dataset.bookingIndex = String(index);
  actions.append(detail);
  const landing = element("a", { text: "Abrir negocio" });
  landing.href = `../autonogrow-landing/index.html?b=${encodeURIComponent(item.business_slug)}`;
  actions.append(landing);
  card.append(actions);
  return card;
}

function renderBookings(bookings) {
  const upcoming = [];
  const past = [];
  bookings.forEach((item, index) => (isUpcoming(item) ? upcoming : past).push({ item, index }));
  const upcomingContainer = byId("upcoming-bookings");
  const pastContainer = byId("past-bookings");
  upcomingContainer.replaceChildren();
  pastContainer.replaceChildren();
  upcoming.forEach(({ item, index }) => upcomingContainer.append(createBookingCard(item, index)));
  past.forEach(({ item, index }) => pastContainer.append(createBookingCard(item, index)));
  if (!upcoming.length) upcomingContainer.append(createEmptyState("No tienes próximas citas", "Cuando una reserva vinculada a tu cuenta esté activa, aparecerá aquí."));
  if (!past.length) pastContainer.append(createEmptyState("Todavía no hay historial", "Las citas completadas, canceladas o anteriores se conservarán en esta sección."));
  byId("upcoming-count").textContent = String(upcoming.length);
  byId("past-count").textContent = String(past.length);
  upcomingContainer.setAttribute("aria-busy", "false");
  pastContainer.setAttribute("aria-busy", "false");
}

async function loadCustomerPortal() {
  if (customerState.loading) return;
  customerState.loading = true;
  setPageBusy(true);
  hidePageError();
  try {
    const [profile, bookingData] = await Promise.all([
      jsonRequest("/api/customer/profile"),
      jsonRequest("/api/customer/bookings")
    ]);
    customerState.profile = profile;
    customerState.bookings = bookingData.bookings || [];
    byId("customer-identity").textContent = `${profile.preferred_name || profile.name || "Cliente"} · ${profile.email}`;
    byId("customer-preferred-name").value = profile.preferred_name || "";
    byId("customer-phone").value = profile.phone || "";
    renderBookings(customerState.bookings);
  } catch (error) {
    if (error.status !== 401) showPageError(error.message);
  } finally {
    customerState.loading = false;
    setPageBusy(false);
  }
}

function setPageBusy(busy) {
  byId("refresh-customer").disabled = busy;
  byId("upcoming-bookings").setAttribute("aria-busy", String(busy));
  byId("past-bookings").setAttribute("aria-busy", String(busy));
  if (busy && !customerState.bookings.length) {
    byId("upcoming-bookings").replaceChildren(createEmptyState("Cargando citas…", "Estamos consultando las reservas vinculadas a tu sesión."));
    byId("past-bookings").replaceChildren(createEmptyState("Cargando historial…", "Espera un momento."));
  }
}

function showPageError(message) {
  const status = byId("customer-page-status");
  status.replaceChildren(element("strong", { text: "No pudimos actualizar Mis citas" }), element("p", { text: message }));
  const retry = element("button", { className: "button-secondary", text: "Volver a intentar", type: "button" });
  retry.addEventListener("click", loadCustomerPortal, { once: true });
  status.append(retry);
  status.hidden = false;
  status.focus();
}

function hidePageError() {
  byId("customer-page-status").hidden = true;
  byId("customer-page-status").replaceChildren();
}

async function showCustomerLogin(expired = false) {
  closeBookingDetail();
  byId("customer-loading").hidden = true;
  byId("customer-app").hidden = true;
  byId("customer-auth-gate").hidden = false;
  byId("customer-login-copy").textContent = expired
    ? "Tu sesión ha caducado. Accede de nuevo para consultar únicamente tus citas."
    : "Consulta únicamente las reservas vinculadas a tu cuenta.";
  byId("customer-login-status").textContent = "";
  try {
    await AutonoGrowAuth.renderGoogleButton(byId("customer-google-button"), bootstrapCustomer);
  } catch (_) {
    byId("customer-login-status").textContent = "No se pudo cargar el acceso. Vuelve a intentarlo más tarde.";
  }
}

async function bootstrapCustomer() {
  byId("customer-loading").hidden = false;
  byId("customer-auth-gate").hidden = true;
  try {
    customerState.user = await AutonoGrowAuth.getMe();
    if (!customerState.user) {
      await showCustomerLogin(false);
      return;
    }
    byId("customer-loading").hidden = true;
    byId("customer-app").hidden = false;
    await loadCustomerPortal();
  } catch (_) {
    await showCustomerLogin(false);
  }
}

function addDetailRow(list, label, value) {
  const row = element("div");
  row.append(element("dt", { text: label }), element("dd", { text: value || "No indicado" }));
  list.append(row);
}

function openBookingDetail(index, returnFocus) {
  const booking = customerState.bookings[index];
  if (!booking) return;
  customerState.selectedBooking = booking;
  customerState.detailReturnFocus = returnFocus;
  const status = bookingStatus(booking.status);
  byId("booking-detail-title").textContent = booking.business_name || "Tu cita";
  const content = byId("booking-detail-content");
  content.replaceChildren();
  const badge = element("span", { className: `status-badge status-${String(booking.status || "unknown").replace(/[^a-z_]/g, "")}`, text: status.label });
  content.append(badge, element("p", { text: status.help }));
  const list = element("dl", { className: "detail-list" });
  addDetailRow(list, "Servicio", booking.service_name || "Servicio");
  addDetailRow(list, "Fecha y hora", formatCivilDateTime(booking.start_datetime));
  addDetailRow(list, "Estado", status.label);
  addDetailRow(list, "Dirección", booking.address || "No indicada");
  content.append(list);

  const management = byId("booking-management");
  management.replaceChildren(element("strong", { text: "Cambios y cancelaciones" }), element("span", { text: "Este portal no tiene autorización backend para reagendar o cancelar citas. Contacta con el negocio para solicitar un cambio." }));
  const actions = byId("booking-detail-actions");
  actions.replaceChildren();
  const landing = element("a", { className: "primary-action", text: "Abrir negocio" });
  landing.href = `../autonogrow-landing/index.html?b=${encodeURIComponent(booking.business_slug)}`;
  actions.append(landing);
  const map = safeExternalUrl(booking.maps_url);
  if (map) {
    const mapLink = element("a", { text: "Abrir mapa" });
    mapLink.href = map;
    mapLink.target = "_blank";
    mapLink.rel = "noopener noreferrer";
    actions.append(mapLink);
  }
  const digits = phoneDigits(booking.phone);
  if (digits) {
    const contact = element("a", { text: "Contactar por WhatsApp" });
    contact.href = `https://wa.me/${digits}`;
    contact.target = "_blank";
    contact.rel = "noopener noreferrer";
    actions.append(contact);
  }
  const dialog = byId("booking-detail-dialog");
  dialog.hidden = false;
  dialog.setAttribute("aria-hidden", "false");
  document.body.classList.add("dialog-open");
  byId("booking-detail-close").focus();
}

function closeBookingDetail() {
  const dialog = byId("booking-detail-dialog");
  if (!dialog || dialog.hidden) return;
  dialog.hidden = true;
  dialog.setAttribute("aria-hidden", "true");
  document.body.classList.remove("dialog-open");
  customerState.selectedBooking = null;
  customerState.detailReturnFocus?.focus();
  customerState.detailReturnFocus = null;
}

function handleDetailKeydown(event) {
  const dialog = byId("booking-detail-dialog");
  if (dialog.hidden) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeBookingDetail();
    return;
  }
  if (event.key !== "Tab") return;
  const focusable = Array.from(dialog.querySelectorAll("button, a[href], [tabindex]:not([tabindex='-1'])"));
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

async function saveCustomerProfile() {
  if (customerState.savingProfile) return;
  const status = byId("customer-profile-status");
  const button = byId("save-customer-profile");
  customerState.savingProfile = true;
  button.disabled = true;
  status.classList.remove("error");
  status.textContent = "Guardando…";
  try {
    const result = await jsonRequest("/api/customer/profile", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        preferred_name: byId("customer-preferred-name").value,
        phone: byId("customer-phone").value
      })
    });
    customerState.profile = result.profile;
    status.textContent = "Perfil guardado.";
    byId("customer-identity").textContent = `${result.profile.preferred_name || result.profile.name || "Cliente"} · ${result.profile.email}`;
  } catch (error) {
    status.classList.add("error");
    status.textContent = error.message;
  } finally {
    customerState.savingProfile = false;
    button.disabled = false;
  }
}

function setupCustomerEvents() {
  byId("save-customer-profile").addEventListener("click", saveCustomerProfile);
  byId("refresh-customer").addEventListener("click", loadCustomerPortal);
  byId("customer-logout").addEventListener("click", async () => {
    await AutonoGrowAuth.logout();
    customerState.user = null;
    customerState.profile = null;
    customerState.bookings = [];
    await showCustomerLogin(false);
  });
  document.addEventListener("click", (event) => {
    const detail = event.target.closest("[data-booking-index]");
    if (detail) openBookingDetail(Number(detail.dataset.bookingIndex), detail);
  });
  byId("booking-detail-close").addEventListener("click", closeBookingDetail);
  document.querySelector("[data-detail-close]").addEventListener("click", closeBookingDetail);
  document.addEventListener("keydown", handleDetailKeydown);
}

setupCustomerEvents();
bootstrapCustomer();
