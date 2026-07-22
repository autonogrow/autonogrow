const API_BASE_URL = AutonoGrowAuth.API_BASE_URL;
const browserFetch = window.fetch.bind(window);
const fetch = async (input, options = {}) => browserFetch(input, await AutonoGrowAuth.secureRequestOptions(options));

let currentBusiness = null;
let currentGalleryIndex = 0;
let selectedService = null;
let selectedDate = "";
let selectedDateLabel = "";
let selectedTime = "";
let selectedSlot = null;
let calendarDays = [];
let galleryTimer = null;
let landingAuthUser = null;
let currentLabels = null;
let bookableStaff = [];
let selectedStaffId = "";
let calendarLoadVersion = 0;
let slotLoadVersion = 0;
let staffLoadVersion = 0;

const LANDING_LABELS = {
  default: {
    servicesTitle: "Servicios", bookingTitle: "Reservar cita", galleryTitle: "Galería",
    contactTitle: "Contacto", informationTitle: "Sobre el negocio", bookingButton: "Reservar cita",
    serviceButton: "Reservar este servicio", servicesButton: "Ver servicios",
    servicesSubtitle: "Elige un servicio y consulta la disponibilidad.",
    bookingSubtitle: "Selecciona un servicio, elige un hueco disponible y confirma la reserva."
  },
  elegant: { galleryTitle: "Selección", bookingTitle: "Reserva", bookingButton: "Reservar cita" },
  beauty: { galleryTitle: "Trabajos", servicesTitle: "Servicios", bookingTitle: "Reservar cita" },
  clinic: { servicesTitle: "Tratamientos", bookingTitle: "Reservar consulta", galleryTitle: "Instalaciones", bookingButton: "Reservar consulta", serviceButton: "Reservar este tratamiento", servicesSubtitle: "Consulta los tratamientos disponibles y elige el más adecuado.", bookingSubtitle: "Selecciona un tratamiento y un horario disponible para solicitar tu consulta." },
  urban: { servicesTitle: "Servicios", bookingTitle: "Reserva tu hora", galleryTitle: "Galería", bookingButton: "Reservar", serviceButton: "Reservar" },
  minimal: { servicesTitle: "Servicios", bookingTitle: "Reserva", galleryTitle: "Galería", bookingButton: "Reservar" }
};

function getErrorMessage(error, fallback = "Se ha producido un error.") {
  if (!error) return fallback;
  if (typeof error === "string") return error;
  if (
    typeof error.message === "string" &&
    error.message.trim() &&
    error.message !== "[object Object]"
  ) return error.message;
  if (typeof error.detail === "string" && error.detail.trim()) return error.detail;
  if (error.detail && typeof error.detail === "object") {
    if (typeof error.detail.message === "string") return error.detail.message;
    try {
      return JSON.stringify(error.detail);
    } catch (_) {
      return fallback;
    }
  }
  if (typeof error.error === "string" && error.error.trim()) return error.error;
  try {
    const serialized = JSON.stringify(error);
    return serialized && serialized !== "{}" ? serialized : fallback;
  } catch (_) {
    return fallback;
  }
}

function normalizeCategory(value) {
  return String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function getLandingLabels(template, category) {
  const labels = { ...LANDING_LABELS.default, ...(LANDING_LABELS[template] || {}) };
  const normalized = normalizeCategory(category);
  if (["fisioterapia", "psicologia", "clinica", "dental", "salud"].some((term) => normalized.includes(term))) {
    Object.assign(labels, LANDING_LABELS.clinic);
  } else if (["manicura", "estetica", "peluqueria"].some((term) => normalized.includes(term))) {
    labels.galleryTitle = "Trabajos";
  }
  return labels;
}

function applyLandingLabels(labels) {
  const values = {
    "hero-booking-button": labels.bookingButton,
    "hero-services-button": labels.servicesButton,
    "quick-booking-label": labels.bookingTitle,
    "quick-services-label": labels.servicesTitle,
    "information-title": labels.informationTitle,
    "services-title": labels.servicesTitle,
    "services-subtitle": labels.servicesSubtitle,
    "gallery-title": labels.galleryTitle,
    "booking-title": labels.bookingTitle,
    "booking-subtitle": labels.bookingSubtitle,
    "booking-submit": labels.bookingButton,
    "contact-title": labels.contactTitle
  };
  Object.entries(values).forEach(([id, text]) => { document.getElementById(id).textContent = text; });
}

function getBusinessSlug() {
  const params = new URLSearchParams(window.location.search);
  return params.get("b") || "demo-manicura";
}

function resolveMediaUrl(url) {
  if (!url) return "";
  if (/^https?:\/\//i.test(url)) return url;
  if (url.startsWith("/uploads/")) return `${API_BASE_URL}${url}`;
  return url;
}

async function loadBusiness() {
  const slug = getBusinessSlug();

  try {
    const businessResponse = await fetch(`${API_BASE_URL}/api/businesses/${slug}`);

    if (!businessResponse.ok) {
      renderBusinessNotFound();
      return;
    }

    const business = await businessResponse.json();
    const servicesResponse = await fetch(`${API_BASE_URL}/api/businesses/${slug}/services`);
    const services = servicesResponse.ok ? await servicesResponse.json() : [];
    const settingsResponse = await fetch(`${API_BASE_URL}/api/businesses/${slug}/availability-settings`);
    const settings = settingsResponse.ok ? await settingsResponse.json() : null;
    const galleryResponse = await fetch(`${API_BASE_URL}/api/businesses/${slug}/media/gallery`);
    const galleryData = galleryResponse.ok ? await galleryResponse.json() : { images: [] };
    bookableStaff = [];

    currentBusiness = {
      ...business,
      services,
      maxDaysAhead: settings?.max_days_ahead || 14,
      promotions: [],
      gallery: galleryData.images || [],
      mapsUrl: business.maps_url,
      instagramUrl: business.instagram_url,
      reviewsUrl: business.reviews_url,
      primaryColor: business.primary_color
    };

    applyBusinessData(currentBusiness);
    renderStaffOptions();
  } catch (error) {
    console.error("Error cargando negocio:", error);
    renderBackendError();
  }
}

function renderBusinessNotFound() {
  document.body.innerHTML = `
    <main class="page">
      <section class="hero">
        <h1>Negocio no encontrado</h1>
        <p>Revisa el enlace o contacta con AutonoGrow.</p>
      </section>
    </main>
  `;
}

function renderBackendError() {
  document.body.innerHTML = `
    <main class="page">
      <section class="hero">
        <h1>No se pudo conectar con el sistema</h1>
        <p>Comprueba que el backend está encendido en http://127.0.0.1:8000.</p>
      </section>
    </main>
  `;
}

function applyBusinessData(business) {
  document.title = `${business.name} | Reserva y servicios`;
  const root = document.documentElement;
  root.style.setProperty("--color-primary", business.primary_color || "#334155");
  root.style.setProperty("--color-secondary", business.secondary_color || "#0f172a");
  root.style.setProperty("--color-accent", business.accent_color || "#f59e0b");
  root.style.setProperty("--color-background", business.background_color || "#f8fafc");
  root.style.setProperty("--primary", business.primary_color || "#334155");
  const templates = ["classic", "elegant", "beauty", "clinic", "urban", "minimal"];
  const template = templates.includes(business.template_key) ? business.template_key : "classic";
  document.body.className = `template-${template}`;
  currentLabels = getLandingLabels(template, business.category);
  applyLandingLabels(currentLabels);

  const logo = document.getElementById("business-logo");
  if (business.logo_url) {
    logo.src = resolveMediaUrl(business.logo_url);
    logo.alt = business.logo_alt || `Logo de ${business.name}`;
    logo.hidden = false;
  } else {
    logo.hidden = true;
    logo.removeAttribute("src");
  }

  document.getElementById("business-category").textContent = business.category || "Negocio local";
  document.getElementById("business-name").textContent = business.name;
  document.getElementById("business-headline").textContent = business.headline || "";
  document.getElementById("business-description").textContent = business.description || "";
  document.getElementById("business-address").textContent = business.address || "";
  document.getElementById("business-schedule").textContent = business.schedule || "";
  document.getElementById("business-city").textContent = business.city || "";

  setLink("maps-link", business.mapsUrl);
  setLink("instagram-link", business.instagramUrl);
  setLink("reviews-link", business.reviewsUrl);
  setWhatsAppLink(business.phone);

  renderInformation(business);
  renderServices(business.services || []);
  renderServiceOptions(business.services || []);
  renderGallery(business.gallery || []);
  renderCalendarPicker();
}

function setLink(id, url) {
  const element = document.getElementById(id);

  if (!element) {
    return;
  }

  if (!url) {
    element.style.display = "none";
    return;
  }

  element.href = url;
}

function setWhatsAppLink(phone) {
  const whatsappLink = document.getElementById("whatsapp-direct-link");

  if (!whatsappLink) {
    return;
  }

  if (!phone) {
    whatsappLink.style.display = "none";
    return;
  }

  whatsappLink.href = buildWhatsAppUrl(phone, "Hola, tengo una duda sobre los servicios o una cita.");
}

function buildWhatsAppUrl(phone, text) {
  const cleanPhone = String(phone).replace(/[^\d]/g, "");
  return `https://wa.me/${cleanPhone}?text=${encodeURIComponent(text)}`;
}

function renderInformation(business) {
  const container = document.getElementById("promotions-list");
  container.innerHTML = "";
  const card = document.createElement("article");
  card.className = "promo-card";
  const title = document.createElement("h3");
  title.textContent = business.category || "Negocio local";
  const copy = document.createElement("p");
  copy.textContent = business.description || "Consulta los servicios, horarios y formas de contacto disponibles.";
  card.append(title, copy);
  container.appendChild(card);
}

function renderServices(services) {
  const container = document.getElementById("services-list");
  container.innerHTML = "";

  if (!services.length) {
    container.innerHTML = "<p>No hay servicios configurados todavía.</p>";
    return;
  }

  services.forEach((service) => {
    const card = document.createElement("article");
    card.className = "service-card";

    card.innerHTML = `
      <h3>${service.name}</h3>
      <p>${service.description || ""}</p>
      <div class="service-meta">
        <span class="pill">${service.price_text || "Consultar precio"}</span>
        <span class="pill">${service.duration_text || "Duración variable"}</span>
      </div>
    `;

    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-primary";
    button.textContent = currentLabels?.serviceButton || LANDING_LABELS.default.serviceButton;

    button.addEventListener("click", () => {
      const select = document.getElementById("service-select");

      if (select) {
        select.value = String(service.id);
        select.dispatchEvent(new Event("change"));
      }

      document.getElementById("booking")?.scrollIntoView({
        behavior: "smooth",
        block: "start"
      });
    });

    card.appendChild(button);
    container.appendChild(card);
  });
}

function renderServiceOptions(services) {
  const select = document.getElementById("service-select");
  select.innerHTML = `<option value="">Selecciona un servicio</option>`;

  services.forEach((service) => {
    const option = document.createElement("option");
    option.value = String(service.id);
    option.textContent = `${service.name} · ${service.price_text || "Consultar"}`;
    select.appendChild(option);
  });
}

async function loadStaffForService(serviceId) {
  const requestVersion = ++staffLoadVersion;
  bookableStaff = [];
  selectedStaffId = "";
  renderStaffOptions();
  if (!serviceId) return true;

  const slug = getBusinessSlug();
  const response = await fetch(
    `${API_BASE_URL}/api/businesses/${slug}/staff?service_id=${encodeURIComponent(serviceId)}`
  );
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(getErrorMessage(body, "No se pudieron cargar los profesionales."));
  }
  if (requestVersion !== staffLoadVersion) return false;
  bookableStaff = body?.staff || [];
  renderStaffOptions();
  return true;
}

function renderStaffOptions(errorMessage = "") {
  const field = document.getElementById("staff-select-field");
  const select = document.getElementById("staff-select");
  const unavailable = document.getElementById("online-booking-unavailable");
  const unavailableMessage = document.getElementById("online-booking-unavailable-message");
  const contactLink = document.getElementById("booking-contact-link");
  const hasBookableStaff = bookableStaff.length > 0;
  const hasSelectedService = Boolean(selectedService);
  field.hidden = !hasSelectedService || !hasBookableStaff;
  unavailable.hidden = !hasSelectedService || hasBookableStaff;
  unavailableMessage.textContent = errorMessage ||
    "Ahora mismo no hay profesionales disponibles para este servicio.";
  select.innerHTML = `<option value="">Cualquiera disponible</option>`;
  bookableStaff.forEach((member) => {
    const option = document.createElement("option");
    option.value = String(member.id);
    option.textContent = member.public_name;
    select.appendChild(option);
  });
  selectedStaffId = "";
  select.value = "";

  const picker = document.getElementById("calendar-picker");
  if (picker) picker.hidden = !hasSelectedService || !hasBookableStaff;
  const submitButton = document.getElementById("booking-submit");
  if (submitButton) submitButton.disabled = !hasSelectedService || !hasBookableStaff;
  if (currentBusiness?.phone) {
    contactLink.href = buildWhatsAppUrl(
      currentBusiness.phone,
      "Hola, quisiera consultar la disponibilidad para una cita."
    );
    contactLink.hidden = false;
  } else {
    contactLink.hidden = true;
    contactLink.removeAttribute("href");
  }
  if (!hasBookableStaff) resetSelectedSlot();
}

function renderGallery(gallery) {
  const section = document.getElementById("gallery-section");
  const image = document.getElementById("gallery-image");
  const prevButton = document.getElementById("prev-image");
  const nextButton = document.getElementById("next-image");

  if (!gallery.length) {
    section.hidden = true;
    clearInterval(galleryTimer);
    return;
  }
  section.hidden = false;
  currentGalleryIndex = 0;
  const showImage = () => {
    const item = gallery[currentGalleryIndex];
    image.src = resolveMediaUrl(item.url || item);
    image.alt = item.alt_text || `Imagen ${currentGalleryIndex + 1} de ${gallery.length}`;
    document.querySelectorAll(".gallery-indicator").forEach((dot, index) => dot.classList.toggle("active", index === currentGalleryIndex));
  };
  document.getElementById("gallery-indicators").innerHTML = gallery.map((_, index) => `<button class="gallery-indicator" type="button" aria-label="Ver imagen ${index + 1}" data-gallery-index="${index}"></button>`).join("");
  document.getElementById("gallery-indicators").onclick = (event) => {
    const dot = event.target.closest("[data-gallery-index]");
    if (dot) { currentGalleryIndex = Number(dot.dataset.galleryIndex); showImage(); }
  };
  prevButton.onclick = () => {
    currentGalleryIndex = (currentGalleryIndex - 1 + gallery.length) % gallery.length;
    showImage();
  };

  nextButton.onclick = () => {
    currentGalleryIndex = (currentGalleryIndex + 1) % gallery.length;
    showImage();
  };
  prevButton.hidden = gallery.length < 2;
  nextButton.hidden = gallery.length < 2;
  showImage();
  clearInterval(galleryTimer);
  if (gallery.length > 1) galleryTimer = setInterval(() => { currentGalleryIndex = (currentGalleryIndex + 1) % gallery.length; showImage(); }, 5000);
}

function getServiceById(serviceId) {
  return (currentBusiness?.services || []).find((service) => String(service.id) === String(serviceId)) || null;
}

async function fetchAvailableSlots(serviceId, date) {
  const slug = getBusinessSlug();
  const params = new URLSearchParams({ service_id: serviceId, date });
  if (selectedStaffId) params.set("staff_business_user_id", selectedStaffId);
  const response = await fetch(`${API_BASE_URL}/api/businesses/${slug}/available-slots?${params.toString()}`);

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(getErrorMessage(body, "No se pudo cargar la disponibilidad."));
  }

  return await response.json();
}

async function fetchCalendarDays(serviceId) {
  const slug = getBusinessSlug();
  const days = getNextDays(currentBusiness?.maxDaysAhead || 14);
  const params = new URLSearchParams({
    from: days[0].date,
    to: days[days.length - 1].date
  });

  if (serviceId) {
    params.set("service_id", serviceId);
  }
  if (selectedStaffId) params.set("staff_business_user_id", selectedStaffId);

  const response = await fetch(`${API_BASE_URL}/api/businesses/${slug}/calendar-days?${params.toString()}`);

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(getErrorMessage(body, "No se pudo cargar el calendario."));
  }

  return await response.json();
}

function renderCalendarPicker() {
  const form = document.getElementById("booking-form");
  const oldPicker = document.getElementById("calendar-picker");

  if (oldPicker) {
    oldPicker.remove();
  }

  const picker = document.createElement("div");
  picker.id = "calendar-picker";
  picker.className = "calendar-picker";
  picker.hidden = bookableStaff.length === 0;
  picker.innerHTML = `
    <div>
      <p class="calendar-title">1. Elige un día disponible</p>
      <div class="calendar-legend">
        <span><i class="legend-dot legend-available"></i>Disponible</span>
        <span><i class="legend-dot legend-closed"></i>Cerrado</span>
        <span><i class="legend-dot legend-special"></i>Horario especial</span>
        <span><i class="legend-dot legend-full"></i>Sin huecos</span>
      </div>
      <div id="calendar-days" class="calendar-days"></div>
    </div>
    <div>
      <p class="calendar-title">2. Elige un hueco</p>
      <div id="time-slots" class="time-slots">
        <p class="empty-slots">Selecciona primero un servicio</p>
      </div>
    </div>
    <div id="selected-slot-summary" class="selected-slot-summary" style="display: none;"></div>
  `;

  const staffLabel = document.getElementById("staff-select-field");
  const serviceLabel = document.getElementById("service-select")?.closest("label");

  if (staffLabel) {
    staffLabel.after(picker);
  } else if (serviceLabel) {
    serviceLabel.after(picker);
  } else {
    form.prepend(picker);
  }

  resetSelectedSlot();
  renderAvailableDays();
}

function getNextDays(count) {
  const formatter = new Intl.DateTimeFormat("es-ES", {
    weekday: "short",
    day: "2-digit",
    month: "short"
  });
  const days = [];

  for (let index = 0; index < count; index += 1) {
    const value = new Date();
    value.setDate(value.getDate() + index);
    days.push({
      date: value.toISOString().slice(0, 10),
      day_label: formatter.format(value).replace(",", "")
    });
  }

  return days;
}

function resetSelectedSlot() {
  slotLoadVersion += 1;
  selectedDate = "";
  selectedDateLabel = "";
  selectedTime = "";
  selectedSlot = null;

  document.getElementById("preferred-day").value = "";
  document.getElementById("preferred-time").value = "";
  updateSelectedSlotSummary();
}

async function renderAvailableDays() {
  const requestVersion = ++calendarLoadVersion;
  const container = document.getElementById("calendar-days");
  container.innerHTML = "";

  if (!bookableStaff.length) {
    container.innerHTML = `<p class="empty-slots">Ahora mismo no hay profesionales disponibles para este servicio.</p>`;
    document.getElementById("time-slots").innerHTML = "";
    return;
  }

  if (!selectedService) {
    container.innerHTML = `<p class="empty-slots">Selecciona primero un servicio</p>`;
    document.getElementById("time-slots").innerHTML = `<p class="empty-slots">Selecciona primero un servicio</p>`;
    return;
  }

  container.innerHTML = `<p class="empty-slots">Cargando calendario...</p>`;

  try {
    const data = await fetchCalendarDays(selectedService.id);
    if (requestVersion !== calendarLoadVersion) return;
    calendarDays = data.days || [];
  } catch (error) {
    if (requestVersion !== calendarLoadVersion) return;
    console.error(error);
    calendarDays = [];
    container.innerHTML = `<p class="empty-slots">${escapeHtml(getErrorMessage(error, "No se pudo cargar el calendario."))}</p>`;
    return;
  }

  container.innerHTML = "";

  calendarDays.forEach((day) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `calendar-day calendar-day-${day.status}`;

    const dayLabel = day.label || day.day_label;
    const firstPart = dayLabel.split(" ")[0];
    const secondPart = dayLabel.replace(`${firstPart} `, "");

    button.innerHTML = `
      <strong>${firstPart}</strong>
      <span>${secondPart}</span>
    `;

    button.addEventListener("click", async () => {
      selectedDate = day.date;
      selectedDateLabel = dayLabel;
      selectedTime = "";
      selectedSlot = null;

      document.getElementById("preferred-day").value = selectedDateLabel;
      document.getElementById("preferred-time").value = "";

      document.querySelectorAll(".calendar-day").forEach((btn) => btn.classList.remove("active"));
      button.classList.add("active");

      const handled = handleSelectedDayStatus(day);
      if (!handled) {
        await loadAndRenderTimeSlots(day);
      }
      updateSelectedSlotSummary();
    });

    container.appendChild(button);
  });
}

function handleSelectedDayStatus(day) {
  const container = document.getElementById("time-slots");

  if (day.status === "closed") {
    container.innerHTML = `<p class="empty-slots">Este día el negocio está cerrado.</p>`;
    return true;
  }

  if (day.status === "past") {
    container.innerHTML = `<p class="empty-slots">Este día ya ha pasado.</p>`;
    return true;
  }

  if (day.status === "full") {
    container.innerHTML = `<p class="empty-slots">No quedan huecos disponibles para este día.</p>`;
    return true;
  }

  if (day.status === "special") {
    container.innerHTML = `<p class="empty-slots">Este día tiene horario especial.</p>`;
  }

  return false;
}

async function loadAndRenderTimeSlots(day = null) {
  const requestVersion = ++slotLoadVersion;
  const container = document.getElementById("time-slots");
  const prefix = day?.status === "special"
    ? `<p class="empty-slots calendar-notice">Este día tiene horario especial.</p>`
    : "";
  container.innerHTML = `${prefix}<p class="empty-slots">Cargando huecos disponibles...</p>`;

  if (!selectedService) {
    container.innerHTML = `<p class="empty-slots">Selecciona primero un servicio</p>`;
    return;
  }

  if (!selectedDate) {
    container.innerHTML = `<p class="empty-slots">Selecciona primero un día para ver los huecos.</p>`;
    return;
  }

  try {
    const data = await fetchAvailableSlots(selectedService.id, selectedDate);
    if (requestVersion !== slotLoadVersion) return;
    renderTimeSlotsFromBackend(data.slots || [], prefix);
  } catch (error) {
    if (requestVersion !== slotLoadVersion) return;
    console.error(error);
    container.innerHTML = `<p class="empty-slots">${escapeHtml(getErrorMessage(error, "No se pudo cargar la disponibilidad."))}</p>`;
  }
}

function renderTimeSlotsFromBackend(slots, prefix = "") {
  const container = document.getElementById("time-slots");
  container.innerHTML = prefix;

  if (!slots.length) {
    container.innerHTML = `${prefix}<p class="empty-slots">No quedan huecos disponibles para este día.</p>`;
    return;
  }

  slots.forEach((slot) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "time-slot";
    button.textContent = slot.label;

    button.addEventListener("click", () => {
      selectedSlot = slot;
      selectedTime = slot.label;
      document.getElementById("preferred-time").value = selectedTime;

      document.querySelectorAll(".time-slot").forEach((btn) => btn.classList.remove("active"));
      button.classList.add("active");

      updateSelectedSlotSummary();
    });

    container.appendChild(button);
  });
}

function updateSelectedSlotSummary() {
  const summary = document.getElementById("selected-slot-summary");

  if (!summary) {
    return;
  }

  if (!selectedService) {
    summary.style.display = "none";
    return;
  }

  const professionalLabel = getSelectedProfessionalLabel();

  if (!selectedDateLabel) {
    summary.style.display = "block";
    summary.textContent = `Servicio: ${selectedService.name}. Profesional: ${professionalLabel}. Ahora elige un día.`;
    return;
  }

  if (!selectedTime) {
    summary.style.display = "block";
    summary.textContent = `Servicio: ${selectedService.name}. Profesional: ${professionalLabel}. Día: ${selectedDateLabel}. Ahora elige un hueco.`;
    return;
  }

  summary.style.display = "block";
  summary.textContent = `Servicio: ${selectedService.name}. Profesional: ${professionalLabel}. Fecha y hora: ${selectedDateLabel} a las ${selectedTime}.`;
}

function getSelectedProfessionalLabel() {
  if (!selectedStaffId) return "Cualquiera disponible";
  return bookableStaff.find((member) => String(member.id) === String(selectedStaffId))?.public_name || "Profesional seleccionado";
}

async function uploadBookingPhotos(slug, bookingId, bookingManageToken) {
  const input = document.getElementById("booking-photos");

  if (!input) {
    return [];
  }

  const files = Array.from(input.files || []);

  if (files.length === 0) {
    return [];
  }

  if (files.length > 5) {
    alert("Puedes adjuntar como máximo 5 fotos.");
    return [];
  }

  const allowedTypes = ["image/jpeg", "image/png", "image/webp"];
  const maxSizeBytes = 5 * 1024 * 1024;

  for (const file of files) {
    if (!allowedTypes.includes(file.type)) {
      alert(`El archivo ${file.name} no es válido. Solo se permiten JPG, PNG o WEBP.`);
      return [];
    }

    if (file.size > maxSizeBytes) {
      alert(`El archivo ${file.name} supera el límite de 5 MB.`);
      return [];
    }
  }

  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));

  const response = await fetch(`${API_BASE_URL}/api/businesses/${slug}/bookings/${bookingId}/attachments`, {
    method: "POST",
    headers: bookingManageToken ? { "X-Booking-Token": bookingManageToken } : {},
    body: formData
  });

  if (!response.ok) {
    const error = await response.json().catch(() => null);
    console.error("Error subiendo fotos:", error);
    alert("La cita se registró, pero no se pudieron subir las fotos.");
    return [];
  }

  const result = await response.json();
  return result.attachments || [];
}

function setupBookingForm() {
  const form = document.getElementById("booking-form");
  const serviceSelect = document.getElementById("service-select");
  const staffSelect = document.getElementById("staff-select");

  serviceSelect.addEventListener("change", async () => {
    selectedService = getServiceById(serviceSelect.value);
    const requestedServiceId = selectedService?.id || null;
    resetSelectedSlot();
    try {
      if (await loadStaffForService(requestedServiceId)) renderAvailableDays();
    } catch (error) {
      if (String(selectedService?.id || "") !== String(requestedServiceId || "")) return;
      console.error("Error cargando profesionales:", error);
      bookableStaff = [];
      renderStaffOptions(getErrorMessage(error, "No se pudieron cargar los profesionales."));
    }
  });

  staffSelect.addEventListener("change", () => {
    selectedStaffId = staffSelect.value;
    resetSelectedSlot();
    renderAvailableDays();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    document.getElementById("booking-confirmation").hidden = true;

    const submitButton = form.querySelector('button[type="submit"]');
    const name = document.getElementById("client-name").value.trim();
    const phone = document.getElementById("client-phone").value.trim();
    const notes = document.getElementById("notes").value.trim();

    if (!selectedService) {
      alert("Selecciona primero un servicio");
      return;
    }

    if (!bookableStaff.length) {
      alert("Ahora mismo no hay profesionales disponibles para este servicio.");
      return;
    }

    if (!selectedSlot) {
      alert("Selecciona un día y un hueco disponible antes de confirmar la reserva.");
      return;
    }

    const slug = getBusinessSlug();

    try {
      if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = "Confirmando reserva...";
      }

      const response = await fetch(`${API_BASE_URL}/api/businesses/${slug}/bookings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_name: name,
          customer_phone: phone,
          service_id: selectedService.id,
          staff_business_user_id: selectedStaffId ? Number(selectedStaffId) : null,
          start_datetime: selectedSlot.start,
          preferred_day_label: selectedDateLabel,
          notes: notes || null,
          source: "landing"
        })
      });

      if (!response.ok) {
        const error = await response.json().catch(() => null);
        console.error("Error backend:", error);
        alert(getErrorMessage(error, "Ese hueco ya no está disponible"));
        await loadAndRenderTimeSlots();
        return;
      }

      const result = await response.json();

      if (submitButton) {
        submitButton.textContent = "Subiendo fotos...";
      }

      const attachments = await uploadBookingPhotos(slug, result.booking.id, result.booking_manage_token);

      const confirmationData = {
        booking: result.booking,
        service: selectedService,
        date: selectedDate,
        dayLabel: selectedDateLabel,
        time: selectedTime,
        businessName: currentBusiness.name,
        businessAddress: currentBusiness.address,
        businessPhone: currentBusiness.phone,
        attachments,
        linkedToAccount: Boolean(result.linked_to_account)
      };

      form.reset();
      selectedService = null;
      selectedStaffId = "";
      bookableStaff = [];
      resetSelectedSlot();
      renderStaffOptions();
      renderAvailableDays();
      showBookingConfirmation(confirmationData);
    } catch (error) {
      console.error("Error enviando reserva:", error);
      alert(getErrorMessage(error, "No se pudo conectar con el sistema de reservas."));
    } finally {
      if (submitButton) {
        submitButton.disabled = bookableStaff.length === 0;
        submitButton.textContent = currentLabels?.bookingButton || LANDING_LABELS.default.bookingButton;
      }
    }
  });
}

function showBookingConfirmation({ booking, service, date, dayLabel, time, businessName, businessAddress, businessPhone, attachments, linkedToAccount }) {
  const feedback = document.getElementById("booking-confirmation");
  const calendarDetails = [
    `Tienes una cita para ${service.name} en ${businessName}. Te esperamos.`,
    booking.staff_display_name ? `Profesional: ${booking.staff_display_name}` : null,
    businessAddress ? `Dirección: ${businessAddress}` : null,
    businessPhone ? `Teléfono del negocio: ${businessPhone}` : null
  ].filter(Boolean).join("\n");
  const calendarUrl = buildGoogleCalendarUrl({
    title: `Cita: ${service.name} en ${businessName}`,
    details: calendarDetails,
    location: businessAddress || "",
    date,
    time,
    durationMinutes: booking.duration_minutes || service.duration_minutes || 60
  });

  const photosText =
    attachments.length > 0
      ? `<p>Fotos adjuntas: <strong>${attachments.length}</strong></p>`
      : `<p>No se adjuntaron fotos.</p>`;
  const accountText = linkedToAccount
    ? `<p>Reserva guardada en tu cuenta. <a href="../autonogrow-customer/index.html"><strong>Ver mis citas</strong></a>.</p>`
    : `<p>Puedes iniciar sesión para guardar y consultar tus citas.</p>`;

  feedback.hidden = false;
  feedback.innerHTML = `
    <h3>Cita creada correctamente</h3>
    <p>Hemos registrado tu cita para <strong>${dayLabel}</strong> a las <strong>${time}</strong>.</p>
    <p>Te confirmaremos cualquier detalle por WhatsApp.</p>
    ${photosText}
    ${accountText}
    <p>Las fotos adjuntas, si las hubiera, se conservarán durante un máximo de 14 días.</p>
    <a class="btn btn-primary" href="${calendarUrl}" target="_blank" rel="noopener">
      Añadir a mi calendario
    </a>
  `;

  feedback.scrollIntoView({ behavior: "smooth", block: "start" });
}

function buildGoogleCalendarUrl({ title, details, location, date, time, durationMinutes }) {
  const start = buildCalendarDateTime(date, time);
  const end = new Date(start.getTime() + durationMinutes * 60 * 1000);
  const formatForGoogle = (value) => {
    return value.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  };
  const params = new URLSearchParams({
    action: "TEMPLATE",
    text: title,
    details,
    location,
    dates: `${formatForGoogle(start)}/${formatForGoogle(end)}`
  });

  return `https://calendar.google.com/calendar/render?${params.toString()}`;
}

function buildCalendarDateTime(date, time) {
  const [hours, minutes] = time.split(":").map(Number);
  const value = new Date(`${date}T00:00:00`);
  value.setHours(hours);
  value.setMinutes(minutes);
  value.setSeconds(0);
  value.setMilliseconds(0);
  return value;
}

document.addEventListener("DOMContentLoaded", () => {
  loadBusiness();
  setupBookingForm();
  setupLandingAuth();
});

async function setupLandingAuth() {
  const userLabel = document.getElementById("landing-auth-user");
  const googleContainer = document.getElementById("landing-google-button");
  const logoutButton = document.getElementById("landing-logout");
  try {
    landingAuthUser = await AutonoGrowAuth.getMe();
    if (landingAuthUser) {
      userLabel.textContent = landingAuthUser.preferred_name || landingAuthUser.name || landingAuthUser.email;
      googleContainer.innerHTML = "";
      logoutButton.hidden = false;
      return;
    }
    userLabel.textContent = "";
    logoutButton.hidden = true;
    await AutonoGrowAuth.renderGoogleButton(googleContainer, async (user) => {
      landingAuthUser = user;
      await setupLandingAuth();
    });
  } catch (error) {
    console.error("Optional landing login failed", error);
    googleContainer.textContent = "Entrar no disponible";
  }
}

document.getElementById("landing-logout").addEventListener("click", async () => {
  await AutonoGrowAuth.logout();
  landingAuthUser = null;
  await setupLandingAuth();
});
