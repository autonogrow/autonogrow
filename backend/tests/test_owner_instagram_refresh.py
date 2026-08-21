from __future__ import annotations

from pathlib import Path

from app.middleware.rate_limit import RateLimitMiddleware

ROOT = Path(__file__).resolve().parents[2]
OWNER_HTML = ROOT / "autonogrow-owner" / "index.html"
OWNER_JS = ROOT / "autonogrow-owner" / "owner.js"
RATE_LIMIT_DOC = ROOT / "docs" / "owner_instagram_rate_limit_hotfix.md"
RATE_LIMIT_SOURCE = ROOT / "backend" / "app" / "middleware" / "rate_limit.py"


def source_block(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def test_owner_instagram_load_has_constant_request_count_and_is_single_flight() -> None:
    js = OWNER_JS.read_text(encoding="utf-8")
    load = source_block(
        js,
        "function loadOwnerInstagramPanel",
        "async function updateOwnerInstagramService",
    )
    workspace = source_block(
        js,
        "async function loadOwnerInstagramWorkspace",
        "async function loadOwnerInstagramCalendarPeriod",
    )
    period = source_block(
        js,
        "async function loadOwnerInstagramCalendarPeriod",
        "function shiftOwnerInstagramCalendar",
    )

    assert 'ownerInstagramJson(`${api}/settings`)' in load
    assert "await loadOwnerInstagramWorkspace(api)" in load
    assert workspace.count("ownerInstagramJson(") == 2
    assert 'ownerInstagramJson(`${api}/raw-assets`)' in workspace
    assert 'ownerInstagramJson(`${api}/contents?${range.toString()}`)' in workspace
    assert period.count("ownerInstagramJson(") == 1
    assert 'ownerInstagramJson(`${api}/contents?${range.toString()}`)' in period
    assert "contentList.contents.map" not in load + workspace
    assert 'ownerInstagramJson(`${api}/contents/${item.id}`)' not in load + workspace

    assert "if (ownerInstagramLoadPromise) return ownerInstagramLoadPromise" in load
    assert "ownerInstagramLoadPromise = task.finally" in load
    assert "ownerInstagramLoadPromise = null" in load
    assert "ownerInstagramLoading = true" in load
    assert "ownerInstagramLoading = false" in load
    assert 'button.setAttribute("aria-busy", "true")' in js
    assert 'button.textContent = ownerInstagramLoading ? "Actualizando…" : "Actualizar"' in js


def test_owner_instagram_retry_after_creates_a_safe_client_cooldown() -> None:
    js = OWNER_JS.read_text(encoding="utf-8")
    retry_after = source_block(
        js,
        "function ownerInstagramRetryAfterSeconds",
        "function ownerInstagramCooldownSeconds",
    )
    request = source_block(
        js,
        "async function ownerInstagramJson",
        "function upsertOwnerInstagramContent",
    )
    rate_limit_branch = request.split("if (response.status === 429)", 1)[1].split(
        "if (!response.ok)", 1
    )[0]

    assert 'response.headers.get("Retry-After")' in retry_after
    assert "Date.parse(value)" in retry_after
    assert "startOwnerInstagramCooldown(retryAfter)" in rate_limit_branch
    assert "ownerInstagramRateLimitError(retryAfter)" in rate_limit_branch
    assert "body.detail" not in rate_limit_branch
    assert "Too many requests" not in js
    assert "ownerInstagramCooldownSeconds()" in request
    assert "window.setTimeout" in js


def test_owner_instagram_upload_errors_are_specific_safe_and_restore_controls() -> None:
    js = OWNER_JS.read_text(encoding="utf-8")
    request = source_block(
        js,
        "async function ownerInstagramJson",
        "async function ownerInstagramFileResponse",
    )
    uploads = source_block(
        js,
        "async function uploadOwnerInstagramRaw",
        "async function deleteOwnerInstagramRaw",
    ) + source_block(
        js,
        "async function uploadOwnerInstagramFinal",
        "let onboardingReadiness",
    )

    assert 'typeof detail === "string" ? detail : detail?.message' in request
    assert '"No se pudo completar la operación editorial."' in request
    assert "showOwnerInstagramError(error)" in uploads
    assert uploads.count("setOwnerInstagramFormBusy(form, false)") == 2
    assert 'form.dataset.ownerInstagramSubmitting === "true"' in uploads
    assert "ownerInstagramRateLimitError(retryAfter)" in js


def test_owner_instagram_mutations_reject_duplicate_submissions_and_avoid_full_reload() -> None:
    js = OWNER_JS.read_text(encoding="utf-8")
    mutations = source_block(
        js,
        "async function updateOwnerInstagramService",
        "let onboardingReadiness",
    )

    for function_name in (
        "uploadOwnerInstagramRaw",
        "createOwnerInstagramContent",
        "uploadOwnerInstagramFinal",
    ):
        block = source_block(mutations, f"async function {function_name}", "\n}")
        assert 'form.dataset.ownerInstagramSubmitting === "true"' in block
        assert "setOwnerInstagramFormBusy(form, true" in block
        assert "setOwnerInstagramFormBusy(form, false)" in block
        assert "beginOwnerInstagramMutation(mutationKey)" in block
        assert "endOwnerInstagramMutation(mutationKey)" in block

    actions = source_block(
        mutations,
        "async function handleOwnerInstagramAction",
        "async function uploadOwnerInstagramFinal",
    )
    assert "beginOwnerInstagramMutation(mutationKey)" in actions
    assert "endOwnerInstagramMutation(mutationKey)" in actions
    assert 'const mutationKey = `content:${contentId}`' in actions
    assert "setOwnerInstagramScopeBusy(card, true" in actions
    assert "await refreshOwnerInstagramContent(api, contentId)" in actions
    assert "await loadOwnerInstagramPanel()" not in mutations

    refresh_state = source_block(
        js,
        "function updateOwnerInstagramRefreshState",
        "function startOwnerInstagramCooldown",
    )
    assert "ownerInstagramMutationKeys.size > 0" in refresh_state
    assert "ownerInstagramLoading || coolingDown || mutating" in refresh_state


def test_owner_instagram_removal_is_confirmed_reactive_and_conflict_safe() -> None:
    js = OWNER_JS.read_text(encoding="utf-8")
    actions = source_block(
        js,
        "async function handleOwnerInstagramAction",
        "async function uploadOwnerInstagramFinal",
    )
    reconcile = source_block(
        js,
        "async function reconcileOwnerInstagramContent",
        "function setOwnerInstagramFormBusy",
    )

    assert 'data-owner-instagram-action="remove"' in js
    assert 'item.status === "published" ? "Archivar" : "Eliminar"' in js
    for status in ("ready_for_review", "validated", "scheduled", "published"):
        assert f'item.status === "{status}"' in js
    assert "window.confirm(ownerInstagramRemovalConfirmation(item))" in actions
    assert 'options = { method: "DELETE" }' in actions
    assert "ownerInstagramContents = ownerInstagramContents.filter" in actions
    assert "renderOwnerInstagramContents()" in actions
    assert "await loadOwnerInstagramPanel()" not in actions
    assert "error.status === 409" in actions
    assert "await reconcileOwnerInstagramContent(api, contentId)" in actions
    assert "error.status !== 404" in reconcile
    assert '"Eliminando…"' in actions
    assert '"Archivando…"' in actions


def test_owner_instagram_raw_removal_and_busy_copy_are_guarded() -> None:
    js = OWNER_JS.read_text(encoding="utf-8")
    raw_delete = source_block(
        js,
        "async function deleteOwnerInstagramRaw",
        "async function createOwnerInstagramContent",
    )

    assert 'data-owner-instagram-raw-delete="${asset.id}"' in js
    assert "beginOwnerInstagramMutation(mutationKey)" in raw_delete
    assert 'method: "DELETE"' in raw_delete
    assert "ownerInstagramRawAssets = ownerInstagramRawAssets.filter" in raw_delete
    assert "setOwnerInstagramScopeBusy(scope, true, button, \"Eliminando…\")" in raw_delete
    for label in (
        "Creando…",
        "Subiendo…",
        "Guardando…",
        "Reprogramando…",
        "Cancelando…",
        "Validando…",
        "Programando…",
        "Enviando…",
    ):
        assert label in js


def test_owner_raw_library_actions_are_secure_reactive_and_single_flight() -> None:
    html = OWNER_HTML.read_text(encoding="utf-8")
    js = OWNER_JS.read_text(encoding="utf-8")
    handler = source_block(
        js,
        "async function handleOwnerInstagramRawAction",
        "async function downloadOwnerInstagramPreviewAsset",
    )

    for label in (
        "Previsualizar",
        "Descargar",
        "Usar en contenido",
        "Crear contenido con este material",
        "Usar como final",
        "Eliminar",
        "Ver",
        "Desasociar",
        "Material de origen",
        "Assets finales",
    ):
        assert label in js or label in html
    for state in (
        "Abriendo…",
        "Descargando…",
        "Asociando…",
        "Desasociando…",
        "Preparando contenido…",
        "Usando como final…",
    ):
        assert state in handler
    assert "beginOwnerInstagramMutationGroup(mutationKeys)" in handler
    assert "endOwnerInstagramMutationGroup(mutationKeys)" in handler
    assert "applyOwnerInstagramRawContentPayload(payload)" in handler
    assert "await loadOwnerInstagramPanel()" not in handler
    assert "error.status === 409" in handler
    assert "/associations/${contentId}" in handler
    assert "/create-content`" in handler
    assert "/use-as-final`" in handler


def test_owner_raw_preview_and_download_use_authenticated_fetch_and_accessible_dialog() -> None:
    html = OWNER_HTML.read_text(encoding="utf-8")
    js = OWNER_JS.read_text(encoding="utf-8")
    preview = source_block(
        js,
        "async function ownerInstagramFileResponse",
        "function beginOwnerInstagramMutation",
    )

    assert 'id="owner-instagram-preview-dialog"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-label="Cerrar previsualización"' in html
    assert "await fetch(url)" in preview
    assert "ownerInstagramRetryAfterSeconds(response)" in preview
    assert "URL.createObjectURL" in preview
    assert "URL.revokeObjectURL" in preview
    assert 'anchor.download = ownerInstagramDownloadFilename' in preview
    assert 'event.key === "Escape"' in js
    assert "File System Access" not in js


def test_owner_raw_association_manager_is_accessible_reactive_and_server_authoritative() -> None:
    html = OWNER_HTML.read_text(encoding="utf-8")
    js = OWNER_JS.read_text(encoding="utf-8")
    styles = (ROOT / "autonogrow-owner" / "styles.css").read_text(encoding="utf-8")

    assert 'id="owner-instagram-associations-dialog"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-describedby="owner-instagram-associations-description"' in html
    assert 'aria-label="Cerrar gestor de asociaciones"' in html
    for label in (
        "Asociaciones",
        "Abrir contenido",
        "Desasociar",
        "Desasociar todos los permitidos",
        "Eliminar material",
    ):
        assert label in js or label in html

    assert "association.modifiable ?" in js
    assert "association.protected_reason" in js
    assert "data-owner-instagram-association-mutation" in js
    assert 'error.code === "raw_asset_in_use"' in js
    assert "showOwnerInstagramAssociationManager(error.detail, button)" in js
    assert "payload.association_manager" in js
    assert "renderOwnerInstagramAssociationManager()" in js
    assert "scrollIntoView" in js
    assert "instagram-content-card--located" in js
    assert 'document.querySelector("main").inert = true' in js
    assert 'event.key === "Escape" && !ownerInstagramAssociationBusy' in js
    assert 'event.key === "Tab"' in js
    assert "ownerInstagramRetryAfterSeconds(response)" in js
    assert "setOwnerInstagramAssociationBusy(false, button)" in js
    assert "height: 100%" in styles


def test_owner_instagram_copy_tracks_real_or_simulated_publishing_mode() -> None:
    html = OWNER_HTML.read_text(encoding="utf-8")
    js = OWNER_JS.read_text(encoding="utf-8")
    copy = source_block(
        js,
        "function renderOwnerInstagramModeCopy",
        "function ownerInstagramJobPanel",
    )

    assert "Sprint 6B · planificación simulada" not in html
    assert "publicación simulada sin conectar con Meta" not in html
    assert 'ownerInstagramSettings?.publishing_mode === "meta"' in copy
    assert '"Publicación en Instagram"' in copy
    assert '"Entorno de simulación"' in copy
    assert 'id="owner-instagram-mode-label"' in html
    assert 'id="owner-instagram-mode-copy"' in html


def test_authenticated_rate_limit_is_shared_by_ip_and_documented_as_single_process() -> None:
    policies = {
        RateLimitMiddleware.policy("/api/owner/businesses/1", "GET"),
        RateLimitMiddleware.policy("/api/admin/businesses/demo", "GET"),
        RateLimitMiddleware.policy("/api/customer/bookings", "GET"),
    }
    assert policies == {("authenticated", 180, 60)}
    limiter = RATE_LIMIT_SOURCE.read_text(encoding="utf-8")
    assert 'path.startswith(("/api/owner/", "/api/admin/", "/api/customer/"))' in limiter
    assert "key = (client_ip, bucket_name)" in limiter

    documentation = RATE_LIMIT_DOC.read_text(encoding="utf-8")
    normalized_documentation = " ".join(documentation.split())
    assert "Owner, Admin y Customer" in normalized_documentation
    assert "IP" in normalized_documentation
    assert "memoria" in normalized_documentation
    assert "un solo proceso" in normalized_documentation
    assert "Redis" in normalized_documentation
