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
const customerState = {
  profile: null,
  nextBooking: null,
  recentServices: [],
  bookings: [],
  todayCount: 0,
  selectedBooking: null,
  detailReturnFocus: null,
  month: new Date(new Date().getFullYear(), new Date().getMonth(), 1),
  selectedDate: dateKey(new Date()),
  view: "month",
  loading: false,
  savingProfile: false
};

function byId(id) { return document.getElementById(id); }
function element(tag, options = {}) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = String(options.text);
  if (options.type) node.type = options.type;
  return node;
}

function dateKey(value) {
  const date = value instanceof Date ? value : new Date(value);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function bookingDateKey(value) { return String(value || "").slice(0, 10); }
function firstName(profile) {
  return String(profile?.preferred_name || profile?.name || "").trim().split(/\s+/)[0] || "";
}
function bookingStatus(value) { return BOOKING_STATUS[value] || { label: "Actualizada", help: "Consulta el detalle con el negocio." }; }
function formatCivilDateTime(value, includeDate = true) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!match) return "Fecha pendiente";
  const [, year, month, day, hours, minutes] = match;
  const civil = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day), Number(hours), Number(minutes)));
  return new Intl.DateTimeFormat("es-ES", { timeZone: "UTC", ...(includeDate ? { dateStyle: "full" } : {}), timeStyle: "short" }).format(civil);
}
function formatMonth(value) { return new Intl.DateTimeFormat("es-ES", { month: "long", year: "numeric" }).format(value); }
function safeExternalUrl(value) {
  if (!value || typeof value !== "string") return "";
  try { const url = new URL(value, window.location.origin); return ["http:", "https:"].includes(url.protocol) ? url.href : ""; } catch (_) { return ""; }
}
function phoneDigits(value) {
  const digits = String(value || "").replace(/\D/g, "");
  return digits.length >= 7 && digits.length <= 15 ? digits : "";
}
function customerError(status) {
  if (status === 401) return "Tu sesión ha caducado. Vuelve a entrar para continuar.";
  if (status === 403) return "No tienes permiso para consultar esta información.";
  if (status === 404) return "La información ya no está disponible.";
  if (status === 409) return "No pudimos completar la vinculación de forma segura.";
  if (status === 400 || status === 422) return "Revisa los datos antes de guardar.";
  if (status === 429) return "Has realizado demasiados intentos. Espera un momento.";
  if (status >= 500) return "Tu espacio no está disponible temporalmente. Vuelve a intentarlo.";
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
    if (error.name === "AbortError") throw Object.assign(new Error("La operación está tardando demasiado."), { status: 408 });
    if (typeof error.status === "number") throw error;
    throw Object.assign(new Error("No se pudo conectar. Comprueba tu conexión."), { status: 0 });
  } finally { window.clearTimeout(timeout); }
}

function monthRange() {
  const start = new Date(customerState.month.getFullYear(), customerState.month.getMonth(), 1);
  const end = new Date(customerState.month.getFullYear(), customerState.month.getMonth() + 1, 0);
  return { from: dateKey(start), to: dateKey(end) };
}

function createEmptyState(title, copy, action = null) {
  const empty = element("div", { className: "empty-state" });
  empty.append(element("h3", { text: title }), element("p", { text: copy }));
  if (action) empty.append(action);
  return empty;
}

function landingLink(item, label = "Reservar otra vez") {
  const link = element("a", { className: "button-primary", text: label });
  const params = new URLSearchParams({ b: item.business_slug, repeat: "1" });
  if (item.service_id) params.set("service_id", String(item.service_id));
  link.href = `../autonogrow-landing/index.html?${params.toString()}`;
  return link;
}

function bookingButton(item, label = "Ver cita") {
  const button = element("button", { className: "button-secondary", text: label, type: "button" });
  button.addEventListener("click", () => openBookingDetail(item, button));
  return button;
}

function renderNextBooking() {
  const container = byId("next-booking");
  container.replaceChildren();
  const item = customerState.nextBooking;
  const todayCount = customerState.todayCount;
  byId("today-summary").textContent = todayCount ? `Hoy tienes ${todayCount} ${todayCount === 1 ? "cita" : "citas"}` : "Hoy no tienes citas";
  if (!item) {
    const action = element("a", { className: "button-primary", text: "Reservar un servicio" });
    action.href = "../autonogrow-landing/index.html";
    container.append(createEmptyState("No tienes próximas citas", "Cuando reserves, la siguiente aparecerá aquí.", action));
    return;
  }
  const card = element("article", { className: "next-booking" });
  const status = bookingStatus(item.status);
  card.append(element("p", { className: "booking-business", text: item.business_name }), element("h3", { text: item.service_name }), element("p", { className: "booking-time", text: formatCivilDateTime(item.start_datetime) }));
  const footer = element("div", { className: "booking-actions" });
  footer.append(element("span", { className: `status-badge status-${item.status}`, text: status.label }), bookingButton(item));
  card.append(footer); container.append(card);
}

function renderRecentServices() {
  const container = byId("recent-services");
  container.replaceChildren();
  if (!customerState.recentServices.length) {
    container.append(createEmptyState("Aún no tienes servicios anteriores", "Cuando completes una visita, podrás repetirla desde aquí."));
    return;
  }
  customerState.recentServices.forEach((item) => {
    const row = element("article", { className: "recent-service" });
    const copy = element("div");
    copy.append(element("h3", { text: item.service_name }), element("p", { text: item.business_name }), element("small", { text: formatCivilDateTime(item.start_datetime) }));
    row.append(copy, landingLink(item, "Repetir")); container.append(row);
  });
}

function bookingsOn(date) { return customerState.bookings.filter((item) => bookingDateKey(item.start_datetime) === date); }
function renderDay(date) {
  customerState.selectedDate = date;
  const headingDate = new Date(`${date}T12:00:00`);
  byId("day-agenda-title").textContent = new Intl.DateTimeFormat("es-ES", { weekday: "long", day: "numeric", month: "long" }).format(headingDate);
  const container = byId("day-bookings");
  container.replaceChildren();
  const items = bookingsOn(date);
  if (!items.length) {
    container.append(createEmptyState(date === dateKey(new Date()) ? "Hoy no tienes citas" : "No tienes citas este día", "Puedes reservar otro servicio cuando lo necesites."));
    return;
  }
  items.forEach((item) => {
    const row = element("button", { className: "day-booking", type: "button" });
    row.append(element("time", { text: formatCivilDateTime(item.start_datetime, false) }), element("span", { className: "day-booking-copy", text: `${item.service_name} · ${item.business_name}` }), element("span", { className: "day-booking-state", text: bookingStatus(item.status).label }));
    row.addEventListener("click", () => openBookingDetail(item, row)); container.append(row);
  });
}

function renderCalendar() {
  document.querySelectorAll("[data-calendar-view]").forEach((button) => button.setAttribute("aria-selected", String(button.dataset.calendarView === customerState.view)));
  byId("calendar-navigation").hidden = customerState.view === "today";
  const calendar = byId("customer-calendar");
  calendar.replaceChildren();
  if (customerState.view === "today") {
    calendar.hidden = true; renderDay(dateKey(new Date())); return;
  }
  calendar.hidden = false;
  byId("calendar-period").textContent = formatMonth(customerState.month);
  ["L", "M", "X", "J", "V", "S", "D"].forEach((day) => calendar.append(element("span", { className: "weekday", text: day })));
  const first = new Date(customerState.month.getFullYear(), customerState.month.getMonth(), 1);
  const cursor = new Date(first); cursor.setDate(1 - ((first.getDay() + 6) % 7));
  for (let index = 0; index < 42; index += 1) {
    const key = dateKey(cursor); const items = bookingsOn(key);
    const button = element("button", { className: "calendar-day", type: "button" });
    if (cursor.getMonth() !== customerState.month.getMonth()) button.classList.add("outside");
    if (key === dateKey(new Date())) button.classList.add("today");
    if (key === customerState.selectedDate) button.setAttribute("aria-current", "date");
    button.setAttribute("aria-label", `${cursor.getDate()} de ${formatMonth(cursor)}. ${items.length ? `${items.length} citas` : "Sin citas"}`);
    button.append(element("span", { text: cursor.getDate() }));
    if (items.length) button.append(element("strong", { text: items.length > 1 ? String(items.length) : "•" }));
    button.addEventListener("click", () => { renderDay(key); renderCalendar(); });
    calendar.append(button); cursor.setDate(cursor.getDate() + 1);
  }
  renderDay(customerState.selectedDate);
}

function renderProfile() {
  const profile = customerState.profile;
  const givenName = firstName(profile);
  byId("customer-greeting").textContent = givenName ? `Hola, ${givenName}` : "Hola";
  byId("customer-identity").textContent = "Aquí tienes lo importante, sin formularios de más.";
  byId("customer-preferred-name").value = profile.preferred_name || profile.name || "";
  byId("customer-phone").value = profile.phone || "";
  byId("customer-email").value = profile.email || "";
  byId("customer-instagram").value = profile.instagram_username ? `@${profile.instagram_username}` : "";
}

async function loadCustomerPortal() {
  if (customerState.loading) return;
  customerState.loading = true; hidePageError();
  const range = monthRange();
  try {
    const data = await jsonRequest(`/api/customer/home?from=${range.from}&to=${range.to}`);
    customerState.profile = data.profile;
    customerState.nextBooking = data.next_booking;
    customerState.recentServices = data.recent_services || [];
    customerState.bookings = data.bookings || [];
    customerState.todayCount = Number(data.today_count || 0);
    renderProfile(); renderNextBooking(); renderRecentServices(); renderCalendar();
  } catch (error) { if (error.status !== 401) showPageError(error.message); }
  finally { customerState.loading = false; byId("customer-loading").hidden = true; }
}

function showPageError(message) {
  const status = byId("customer-page-status");
  status.replaceChildren(element("strong", { text: "No pudimos actualizar tus citas" }), element("p", { text: message }));
  const retry = element("button", { className: "button-secondary", text: "Volver a intentar", type: "button" });
  retry.addEventListener("click", loadCustomerPortal, { once: true }); status.append(retry); status.hidden = false; status.focus();
}
function hidePageError() { byId("customer-page-status").hidden = true; byId("customer-page-status").replaceChildren(); }

async function showCustomerLogin(expired = false) {
  customerState.profile = null; customerState.nextBooking = null; customerState.recentServices = []; customerState.bookings = []; customerState.selectedBooking = null;
  closeBookingDetail(); byId("customer-loading").hidden = true; byId("customer-app").hidden = true; byId("customer-auth-gate").hidden = false;
  byId("customer-login-copy").textContent = expired ? "Tu sesión ha caducado. Entra de nuevo para recuperar tus citas." : "Guarda tus citas, repite servicios y reserva más rápido la próxima vez.";
  byId("customer-login-status").textContent = "";
  try { await AutonoGrowAuth.renderGoogleButton(byId("customer-google-button"), bootstrapCustomer); }
  catch (_) { byId("customer-login-status").textContent = "No se pudo cargar el acceso. Vuelve a intentarlo más tarde."; }
}

async function bootstrapCustomer() {
  byId("customer-loading").hidden = false; byId("customer-auth-gate").hidden = true;
  try {
    const user = await AutonoGrowAuth.getMe();
    if (!user) { await showCustomerLogin(false); return; }
    byId("customer-app").hidden = false; await loadCustomerPortal();
  } catch (_) { await showCustomerLogin(false); }
}

function addDetailRow(list, label, value) { const row = element("div"); row.append(element("dt", { text: label }), element("dd", { text: value || "No indicado" })); list.append(row); }
function openBookingDetail(booking, returnFocus) {
  if (!booking) return;
  customerState.selectedBooking = booking; customerState.detailReturnFocus = returnFocus;
  const status = bookingStatus(booking.status); byId("booking-detail-title").textContent = booking.business_name || "Tu cita";
  const content = byId("booking-detail-content"); content.replaceChildren(element("span", { className: `status-badge status-${booking.status}`, text: status.label }), element("p", { text: status.help }));
  const list = element("dl", { className: "detail-list" }); addDetailRow(list, "Servicio", booking.service_name); addDetailRow(list, "Fecha y hora", formatCivilDateTime(booking.start_datetime)); addDetailRow(list, "Dirección", booking.address); content.append(list);
  byId("booking-management").replaceChildren(element("strong", { text: "¿Necesitas cambiar algo?" }), element("span", { text: "Contacta con el negocio. Solo mostramos acciones que realmente están disponibles." }));
  const actions = byId("booking-detail-actions"); actions.replaceChildren(landingLink(booking));
  const map = safeExternalUrl(booking.maps_url); if (map) { const link = element("a", { text: "Cómo llegar" }); link.href = map; link.target = "_blank"; link.rel = "noopener noreferrer"; actions.append(link); }
  const digits = phoneDigits(booking.phone); if (digits) { const link = element("a", { text: "Contactar" }); link.href = `https://wa.me/${digits}`; link.target = "_blank"; link.rel = "noopener noreferrer"; actions.append(link); }
  const dialog = byId("booking-detail-dialog"); dialog.hidden = false; dialog.setAttribute("aria-hidden", "false"); document.body.classList.add("dialog-open"); byId("booking-detail-close").focus();
}
function closeBookingDetail() { const dialog = byId("booking-detail-dialog"); if (!dialog || dialog.hidden) return; dialog.hidden = true; dialog.setAttribute("aria-hidden", "true"); document.body.classList.remove("dialog-open"); customerState.selectedBooking = null; customerState.detailReturnFocus?.focus(); customerState.detailReturnFocus = null; }
function handleDetailKeydown(event) {
  const dialog = byId("booking-detail-dialog"); if (dialog.hidden) return;
  if (event.key === "Escape") { event.preventDefault(); closeBookingDetail(); return; }
  if (event.key !== "Tab") return;
  const focusable = Array.from(dialog.querySelectorAll("button, a[href], [tabindex]:not([tabindex='-1'])")); if (!focusable.length) return;
  const first = focusable[0]; const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
}

async function saveCustomerProfile() {
  if (customerState.savingProfile) return;
  const status = byId("customer-profile-status"); const button = byId("save-customer-profile"); customerState.savingProfile = true; button.disabled = true; status.classList.remove("error"); status.textContent = "Guardando…";
  try {
    const result = await jsonRequest("/api/customer/profile", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ preferred_name: byId("customer-preferred-name").value, phone: byId("customer-phone").value, instagram_username: byId("customer-instagram").value }) });
    customerState.profile = result.profile; renderProfile(); status.textContent = "Datos guardados.";
  } catch (error) { status.classList.add("error"); status.textContent = error.message; }
  finally { customerState.savingProfile = false; button.disabled = false; }
}

function setupCustomerEvents() {
  byId("save-customer-profile").addEventListener("click", saveCustomerProfile); byId("refresh-customer").addEventListener("click", loadCustomerPortal);
  byId("customer-logout").addEventListener("click", async () => { await AutonoGrowAuth.logout(); customerState.profile = null; customerState.bookings = []; await showCustomerLogin(false); });
  document.querySelectorAll("[data-calendar-view]").forEach((button) => button.addEventListener("click", () => { customerState.view = button.dataset.calendarView; renderCalendar(); }));
  document.querySelectorAll("[data-calendar-nav]").forEach((button) => button.addEventListener("click", async () => { customerState.month = new Date(customerState.month.getFullYear(), customerState.month.getMonth() + Number(button.dataset.calendarNav), 1); customerState.selectedDate = dateKey(customerState.month); await loadCustomerPortal(); }));
  byId("booking-detail-close").addEventListener("click", closeBookingDetail); document.querySelector("[data-detail-close]").addEventListener("click", closeBookingDetail); document.addEventListener("keydown", handleDetailKeydown);
}

setupCustomerEvents(); bootstrapCustomer();
