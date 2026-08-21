(function () {
  const isLocal = ["127.0.0.1", "localhost"].includes(window.location.hostname);
  const API_BASE_URL = window.AUTONOGROW_API_BASE_URL || (isLocal ? "http://127.0.0.1:8000" : window.location.origin);
  let csrfToken;

  function isMutable(options = {}) {
    return !["GET", "HEAD", "OPTIONS"].includes(String(options.method || "GET").toUpperCase());
  }

  async function getCsrfToken(force = false) {
    if (csrfToken !== undefined && !force) return csrfToken;
    const response = await window.fetch(`${API_BASE_URL}/api/auth/csrf`, { credentials: "include" });
    if (!response.ok) throw Object.assign(new Error("No se pudo preparar la protección CSRF"), { status: response.status });
    const body = await response.json();
    csrfToken = body.csrf_token;
    return csrfToken;
  }

  async function secureRequestOptions(options = {}, path = "") {
    const secured = { ...options, credentials: "include" };
    if (isMutable(secured) && path !== "/api/auth/google") {
      const headers = new Headers(secured.headers || {});
      const token = await getCsrfToken();
      if (token) headers.set("X-CSRF-Token", token);
      secured.headers = headers;
    }
    return secured;
  }

  async function request(path, options = {}) {
    const secured = await secureRequestOptions(options, path);
    const response = await window.fetch(`${API_BASE_URL}${path}`, secured);
    const text = await response.text();
    let body = {};
    try { body = text ? JSON.parse(text) : {}; } catch { body = { detail: text }; }
    if (!response.ok) {
      const error = new Error(body.detail || `Error ${response.status}`);
      error.status = response.status;
      error.body = body;
      throw error;
    }
    return body;
  }

  async function getMe() {
    try { return await request("/api/auth/me"); }
    catch (error) { if (error.status === 401) return null; throw error; }
  }

  async function waitForGoogle() {
    for (let index = 0; index < 80; index += 1) {
      if (window.google?.accounts?.id) return window.google.accounts.id;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    throw new Error("No se pudo cargar Google Identity Services")
  }

  async function renderGoogleButton(container, onAuthenticated, onError) {
    container.innerHTML = "";
    try {
      const config = await request("/api/config/public");
      if (!config.google_client_id) throw new Error("GOOGLE_CLIENT_ID no está configurado en el backend")
      const identity = await waitForGoogle();
      identity.initialize({
        client_id: config.google_client_id,
        callback: async ({ credential }) => {
          try {
            const result = await request("/api/auth/google", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ credential }),
            });
            await onAuthenticated(result.user);
          } catch (error) {
            console.error("Google login failed", { status: error.status || 0 });
            onError?.(error);
          }
        },
      });
      identity.renderButton(container, { theme: "outline", size: "large", text: "signin_with", shape: "pill" });
    } catch (error) {
      console.error("Google Identity setup failed", { status: error.status || 0 });
      container.textContent = "No se pudo cargar el acceso con Google. Vuelve a intentarlo más tarde.";
      container.classList.add("auth-error");
      onError?.(error);
    }
  }

  async function logout() {
    await request("/api/auth/logout", { method: "POST" });
    csrfToken = undefined;
  }

  async function showEnvironmentMarker() {
    const config = await request("/api/config/public");
    if (config.app_env !== "staging" || document.querySelector("[data-ag-environment-marker]")) return;
    const marker = document.createElement("span");
    marker.className = "ag-environment-marker";
    marker.dataset.agEnvironmentMarker = "staging";
    marker.textContent = "STAGING";
    marker.setAttribute("aria-label", "Entorno de staging");
    document.body.appendChild(marker);
  }

  window.AutonoGrowAuth = { API_BASE_URL, request, getMe, getCsrfToken, secureRequestOptions, renderGoogleButton, logout, showEnvironmentMarker };
  showEnvironmentMarker().catch(() => {});
})();
