(function () {
  "use strict";

  const desktopQuery = window.matchMedia("(min-width: 1024px)");

  function setInert(element, value) {
    if (!element || !("inert" in element)) return;
    element.inert = value;
  }

  function initShell(shell) {
    const sidebar = shell.querySelector("[data-ag-shell-sidebar]");
    const backdrop = shell.querySelector("[data-ag-shell-backdrop]");
    const openButtons = shell.querySelectorAll("[data-ag-shell-open]");
    const closeButtons = shell.querySelectorAll("[data-ag-shell-close]");
    const nav = shell.querySelector("[data-ag-shell-nav]");
    const navSlot = sidebar?.querySelector("[data-ag-shell-nav-slot]");
    const mainArea = shell.querySelector(".ag-shell__main");
    const mainContent = shell.querySelector(".ag-shell__content");
    let returnFocus = null;

    if (!sidebar || !backdrop || !openButtons.length) return;
    if (nav && navSlot) navSlot.replaceWith(nav);

    function applyViewportState() {
      const desktop = desktopQuery.matches;
      if (desktop) {
        shell.classList.remove("ag-shell--drawer-open");
        document.body.classList.remove("ag-drawer-open");
        backdrop.hidden = true;
        sidebar.removeAttribute("aria-hidden");
        setInert(sidebar, false);
        setInert(mainArea, false);
        openButtons.forEach((button) => button.setAttribute("aria-expanded", "false"));
      } else if (!shell.classList.contains("ag-shell--drawer-open")) {
        sidebar.setAttribute("aria-hidden", "true");
        setInert(sidebar, true);
      }
    }

    function openDrawer(trigger) {
      if (desktopQuery.matches) return;
      returnFocus = trigger || document.activeElement;
      shell.classList.add("ag-shell--drawer-open");
      document.body.classList.add("ag-drawer-open");
      backdrop.hidden = false;
      sidebar.setAttribute("aria-hidden", "false");
      setInert(sidebar, false);
      setInert(mainArea, true);
      openButtons.forEach((button) => button.setAttribute("aria-expanded", "true"));
      const closeButton = sidebar.querySelector("[data-ag-shell-close]");
      window.requestAnimationFrame(() => closeButton?.focus());
    }

    function closeDrawer(options = {}) {
      if (!shell.classList.contains("ag-shell--drawer-open")) return;
      shell.classList.remove("ag-shell--drawer-open");
      document.body.classList.remove("ag-drawer-open");
      backdrop.hidden = true;
      openButtons.forEach((button) => button.setAttribute("aria-expanded", "false"));
      if (!desktopQuery.matches) {
        sidebar.setAttribute("aria-hidden", "true");
        setInert(sidebar, true);
      }
      setInert(mainArea, false);
      if (options.restoreFocus !== false && returnFocus instanceof HTMLElement) returnFocus.focus();
      returnFocus = null;
    }

    function currentKey() {
      return shell.querySelector(".admin-tab-active[data-section]")?.dataset.section
        || shell.querySelector(".tab.active[data-tab]")?.dataset.tab
        || "";
    }

    function syncCurrentNavigation() {
      const key = currentKey();
      shell.querySelectorAll("[data-ag-shell-nav] [data-section], [data-ag-shell-nav] [data-tab]").forEach((item) => {
        const itemKey = item.dataset.section || item.dataset.tab;
        if (itemKey === key) item.setAttribute("aria-current", "page");
        else item.removeAttribute("aria-current");
      });
      shell.querySelectorAll("[data-ag-mobile-nav] [data-ag-shell-section], [data-ag-mobile-nav] [data-ag-shell-more]").forEach((item) => {
        const aliases = (item.dataset.agShellSections || item.dataset.agShellSection || "").split(",").map((value) => value.trim()).filter(Boolean);
        if (aliases.includes(key)) item.setAttribute("aria-current", "page");
        else item.removeAttribute("aria-current");
      });
    }

    openButtons.forEach((button) => button.addEventListener("click", () => openDrawer(button)));
    closeButtons.forEach((button) => button.addEventListener("click", () => closeDrawer()));
    backdrop.addEventListener("click", () => closeDrawer());
    nav?.addEventListener("click", (event) => {
      if (event.target.closest("[data-section], [data-tab]")) {
        window.requestAnimationFrame(syncCurrentNavigation);
        if (!desktopQuery.matches) {
          closeDrawer({ restoreFocus: false });
          window.requestAnimationFrame(() => mainContent?.focus());
        }
      }
    });

    shell.querySelectorAll("[data-ag-shell-section]").forEach((button) => button.addEventListener("click", () => {
      const section = button.dataset.agShellSection;
      const target = shell.querySelector(`[data-ag-shell-nav] [data-section="${section}"]`);
      target?.click();
      window.requestAnimationFrame(syncCurrentNavigation);
    }));

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && shell.classList.contains("ag-shell--drawer-open")) closeDrawer();
    });
    window.addEventListener("hashchange", syncCurrentNavigation);
    desktopQuery.addEventListener?.("change", applyViewportState);

    if (nav) new MutationObserver(syncCurrentNavigation).observe(nav, { attributes: true, subtree: true, attributeFilter: ["class"] });
    applyViewportState();
    syncCurrentNavigation();
  }

  document.querySelectorAll("[data-ag-shell]").forEach(initShell);
}());
