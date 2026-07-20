const API_BASE_URL = AutonoGrowAuth.API_BASE_URL;
const api = async (path, options = {}) => fetch(`${API_BASE_URL}${path}`, await AutonoGrowAuth.secureRequestOptions(options));
let customerUser = null;

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

async function jsonRequest(path, options = {}) {
  const response = await api(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) queueMicrotask(showCustomerLogin);
    throw Object.assign(new Error(body.detail || `Error ${response.status}`), { status: response.status });
  }
  return body;
}

function bookingCard(item) {
  const date = item.start_datetime ? new Date(item.start_datetime).toLocaleString("es-ES", { dateStyle: "medium", timeStyle: "short" }) : "Fecha pendiente";
  const whatsapp = item.phone ? `<a href="https://wa.me/${String(item.phone).replace(/\D/g, "")}" target="_blank" rel="noopener">Contactar por WhatsApp</a>` : "";
  return `<article class="booking-card"><span class="status status-${escapeHtml(item.status)}">${escapeHtml(item.status)}</span><h3>${escapeHtml(item.business_name)}</h3><p><strong>${escapeHtml(item.service_name)}</strong></p><p>${escapeHtml(date)}</p><p>${escapeHtml(item.address || "Dirección no indicada")}</p><div class="booking-actions"><a href="../autonogrow-landing/index.html?b=${encodeURIComponent(item.business_slug)}">Abrir negocio</a>${whatsapp}</div></article>`;
}

function renderBookings(bookings) {
  const now = new Date();
  const upcoming = bookings.filter((item) => item.start_datetime && new Date(item.start_datetime) >= now && !["completed", "cancelled", "rejected"].includes(item.status));
  const past = bookings.filter((item) => !upcoming.includes(item));
  document.getElementById("upcoming-bookings").innerHTML = upcoming.map(bookingCard).join("") || '<p class="empty">No tienes próximas citas.</p>';
  document.getElementById("past-bookings").innerHTML = past.map(bookingCard).join("") || '<p class="empty">Todavía no hay historial.</p>';
}

async function loadCustomerPortal() {
  const [profile, bookingData] = await Promise.all([jsonRequest("/api/customer/profile"), jsonRequest("/api/customer/bookings")]);
  document.getElementById("customer-identity").textContent = `${profile.preferred_name || profile.name || "Cliente"} · ${profile.email}`;
  document.getElementById("customer-preferred-name").value = profile.preferred_name || "";
  document.getElementById("customer-phone").value = profile.phone || "";
  renderBookings(bookingData.bookings || []);
}

async function showCustomerLogin() {
  document.getElementById("customer-app").hidden = true;
  document.getElementById("customer-auth-gate").hidden = false;
  await AutonoGrowAuth.renderGoogleButton(document.getElementById("customer-google-button"), bootstrapCustomer);
}

async function bootstrapCustomer() {
  try {
    customerUser = await AutonoGrowAuth.getMe();
    if (!customerUser) return showCustomerLogin();
    document.getElementById("customer-auth-gate").hidden = true;
    document.getElementById("customer-app").hidden = false;
    await loadCustomerPortal();
  } catch (error) {
    console.error("Customer portal failed", error);
    document.getElementById("customer-auth-gate").hidden = false;
  }
}

document.getElementById("save-customer-profile").addEventListener("click", async () => {
  const status = document.getElementById("customer-profile-status");
  try {
    await jsonRequest("/api/customer/profile", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ preferred_name: document.getElementById("customer-preferred-name").value, phone: document.getElementById("customer-phone").value }) });
    status.textContent = "Perfil guardado.";
  } catch (error) { status.textContent = error.message; }
});
document.getElementById("customer-logout").addEventListener("click", async () => { await AutonoGrowAuth.logout(); await showCustomerLogin(); });
bootstrapCustomer();
