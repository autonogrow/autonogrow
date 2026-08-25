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
    assert workspace.count("ownerInstagramJson(") == 3
    assert "/idea-reviews" in workspace
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
    raw_upload = source_block(
        js,
        "async function uploadOwnerInstagramRaw",
        "async function deleteOwnerInstagramRaw",
    )
    composer_upload = source_block(
        js,
        "async function ownerInstagramComposerUploadLocalMedia",
        "async function ownerInstagramComposerPatchDate",
    )

    assert 'typeof detail === "string" ? detail : detail?.message' in request
    assert '"No se pudo completar la operación editorial."' in request
    assert "showOwnerInstagramError(error)" in raw_upload
    assert "setOwnerInstagramFormBusy(form, false)" in raw_upload
    assert 'form.dataset.ownerInstagramSubmitting === "true"' in raw_upload
    assert "new FormData()" in composer_upload
    assert "/final-assets`" in composer_upload
    assert "media.file = null" in composer_upload
    assert "ownerInstagramRateLimitError(retryAfter)" in js


def test_owner_instagram_mutations_reject_duplicate_submissions_and_avoid_full_reload() -> None:
    js = OWNER_JS.read_text(encoding="utf-8")
    mutations = source_block(
        js,
        "async function updateOwnerInstagramService",
        "let onboardingReadiness",
    )

    raw_upload = source_block(
        mutations,
        "async function uploadOwnerInstagramRaw",
        "async function deleteOwnerInstagramRaw",
    )
    assert 'form.dataset.ownerInstagramSubmitting === "true"' in raw_upload
    assert "setOwnerInstagramFormBusy(form, true" in raw_upload
    assert "setOwnerInstagramFormBusy(form, false)" in raw_upload
    assert "beginOwnerInstagramMutation(mutationKey)" in raw_upload
    assert "endOwnerInstagramMutation(mutationKey)" in raw_upload

    for start, end in (
        (
            "async function saveOwnerInstagramComposerDraft",
            "async function publishOwnerInstagramComposer",
        ),
        (
            "async function publishOwnerInstagramComposer",
            "async function cancelOwnerInstagramComposerContent",
        ),
        (
            "async function cancelOwnerInstagramComposerContent",
            "function ownerInstagramRetryAfterSeconds",
        ),
    ):
        action = source_block(js, start, end)
        assert "beginOwnerInstagramMutation(mutationKey)" in action
        assert "endOwnerInstagramMutation(mutationKey)" in action
        assert "state.busy" in action
    assert "setOwnerInstagramComposerBusy(true" in js
    assert "ownerInstagramComposerSave" in js
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
    cancel = source_block(
        js,
        "async function cancelOwnerInstagramComposerContent",
        "function ownerInstagramRetryAfterSeconds",
    )
    reconcile = source_block(
        js,
        "async function reconcileOwnerInstagramContent",
        "function setOwnerInstagramFormBusy",
    )

    for status in ("ready_for_review", "validated", "scheduled", "published"):
        assert f'item.status === "{status}"' in js
    assert "window.confirm(ownerInstagramRemovalConfirmation(state.content))" in cancel
    assert "/cancel`" in cancel
    assert "upsertOwnerInstagramContent(content)" in cancel
    assert "closeOwnerInstagramComposer" in cancel
    assert "await loadOwnerInstagramPanel()" not in cancel
    assert "error.status !== 404" in reconcile
    assert '"Cancelando publicación…"' in cancel


def test_owner_instagram_raw_removal_and_busy_copy_are_guarded() -> None:
    js = OWNER_JS.read_text(encoding="utf-8")
    raw_delete = source_block(
        js,
        "async function deleteOwnerInstagramRaw",
        "async function handleOwnerInstagramRawAction",
    )

    assert 'data-owner-instagram-raw-delete="${asset.id}"' in js
    assert "beginOwnerInstagramMutation(mutationKey)" in raw_delete
    assert 'method: "DELETE"' in raw_delete
    assert "ownerInstagramRawAssets = ownerInstagramRawAssets.filter" in raw_delete
    assert "setOwnerInstagramScopeBusy(scope, true, button, \"Eliminando…\")" in raw_delete
    for label in (
        "Subiendo…",
        "Guardando…",
        "Cancelando publicación…",
        "Preparando la programación…",
        "Preparando la publicación…",
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
    assert "openOwnerInstagramContentDetail(contentId)" in js
    assert 'id="owner-instagram-composer"' in html
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
        "function ownerInstagramLocalInput",
    )

    assert "Sprint 6B · planificación simulada" not in html
    assert "publicación simulada sin conectar con Meta" not in html
    assert 'ownerInstagramSettings?.publishing_mode === "meta"' in copy
    assert '"Publicación en Instagram"' in copy
    assert '"Entorno de simulación"' in copy
    assert 'id="owner-instagram-mode-label"' in html
    assert 'id="owner-instagram-mode-copy"' in html


def test_owner_instagram_async_lifecycle_is_centralized_polled_and_action_safe() -> None:
    js = OWNER_JS.read_text(encoding="utf-8")
    lifecycle = source_block(
        js,
        "function ownerInstagramPublicationUxState",
        "function ownerInstagramFormatLabel",
    )
    polling = source_block(
        js,
        "function stopOwnerInstagramLifecyclePolling",
        "function upsertOwnerInstagramContent",
    )
    composer = source_block(
        js,
        "function renderOwnerInstagramComposer()",
        "function ownerInstagramComposerChangeFormat",
    )

    for status in (
        "queued",
        "claimed",
        "creating_container",
        "publishing",
        "simulating_publish",
        "retry_wait",
        "action_required",
        "failed",
        "published",
    ):
        assert status in lifecycle
    for label in (
        "Preparando publicación",
        "Procesando en Instagram",
        "Publicando en Instagram",
        "Publicado",
        "Publicación fallida",
        "Reconectar Instagram",
        "Verificar publicación",
    ):
        assert label in lifecycle
    assert 'tone: "scheduled"' in lifecycle
    assert 'status === "retry_wait"' in lifecycle
    assert "ownerInstagramPublicationUxState(item)" in js
    assert "ownerInstagramPublicationUxState(state.content)" in composer
    assert "lifecycle.actionLocked" in composer
    assert "owner-instagram-composer-primary" in composer

    assert "window.setTimeout" in polling
    assert "10_000" in polling
    assert "document.hidden" in polling
    assert "ownerInstagramMutationKeys.size > 0" in polling
    assert "loadOwnerInstagramCalendarPeriod()" in polling
    assert "ownerInstagramJson(" not in polling
    assert "stopOwnerInstagramLifecyclePolling()" in js
    assert 'document.addEventListener("visibilitychange"' in js
    assert "fetch(" not in lifecycle
    assert "Meta" not in polling

    advanced = source_block(
        js,
        "function ownerInstagramComposerAdvanced",
        "function ownerInstagramComposerMediaMarkup",
    )
    for field in (
        "provider_status",
        "next_attempt_at",
        "last_provider_error",
        "error_subcode",
        "is_transient",
        "container_status",
        "carousel_position",
    ):
        assert field in advanced
    assert "access_token" not in advanced
    assert "signed" not in advanced


def test_owner_instagram_composer_submits_review_without_final_approval_bypass() -> None:
    html = OWNER_HTML.read_text(encoding="utf-8")
    js = OWNER_JS.read_text(encoding="utf-8")
    ensure = source_block(
        js,
        "async function ownerInstagramComposerEnsureValidated",
        "async function saveOwnerInstagramComposerDraft",
    )
    publish = source_block(
        js,
        "async function publishOwnerInstagramComposer",
        "async function cancelOwnerInstagramComposerContent",
    )

    assert 'id="owner-instagram-composer"' in html
    assert 'id="owner-instagram-create"' in html
    assert 'data-owner-instagram-create-date="${key}"' in js
    assert 'multiple = state.format === "carousel"' in js
    assert 'single_image: { label: "Publicación", accept: "image/jpeg"' in js
    assert 'reel: { label: "Reel", accept: "video/mp4"' in js
    assert 'story: { label: "Historia", accept: "image/jpeg,image/png,image/webp,video/mp4"' in js
    assert 'data-owner-composer-move="-1"' in js
    assert 'draggable="true"' in js
    assert 'data-owner-composer-preview="previous"' in html
    assert '<video src="${escapeHtml(media.url)}" controls muted playsinline' in js

    assert "/submit-for-review`" in ensure
    assert "/validate`" not in ensure
    assert "ownerInstagramComposerClearPlannedDate" not in ensure
    assert 'content.status === "ready_for_review"' in publish
    assert "Versión enviada a revisión AutonoGrow" in publish
    assert "/publish-now`" in publish
    assert "/schedule`" in publish
    assert "ownerInstagramComposerPatchDate" in publish
    assert 'id="owner-instagram-composer-advanced"' in html
    assert "Versión" in js and "Intentos" in js and "provider_media_id" in js
    assert 'id="owner-instagram-composer-reuse"' in html
    assert "Reutilizar publicación" in html
    assert "Material del negocio" in html
    assert 'data-instagram-library-source="business"' in html
    assert "data-instagram-library-raw" in js
    assert "/raw-assets?limit=200" in js
    assert 'id="owner-instagram-detail"' not in html


def test_owner_story_editor_and_instagram_library_share_a_versioned_contract() -> None:
    html = OWNER_HTML.read_text(encoding="utf-8")
    js = OWNER_JS.read_text(encoding="utf-8")

    for field in (
        "story_mode",
        "owner-instagram-story-zoom",
        "owner-instagram-story-x",
        "owner-instagram-story-y",
        "story_background",
    ):
        assert field in html
    for value in ('value="fill"', 'value="fit"', 'value="dark"', 'value="light"'):
        assert value in html
    assert "ownerInstagramStoryGeometry" in js
    assert "Math.floor(sourceWidth * scale + 0.5)" in js
    assert "source_raw_asset_id" in js
    assert "/story-image`" in js
    assert 'data.append("transform", JSON.stringify(state.storyTransform))' in js
    assert 'id="owner-instagram-library-dialog"' in html
    assert "/instagram-media?filter=" in js
    assert "/instagram-media/sync`" in js
    assert "¿Qué imagen quieres usar?" in js
    assert "Reel no compatible en P1" in js
    assert "provider_preview_url" not in js


def test_autonogrow_owner_surface_has_owner_first_and_version_review_queues() -> None:
    html = OWNER_HTML.read_text(encoding="utf-8")
    js = OWNER_JS.read_text(encoding="utf-8")

    for marker in (
        'id="owner-social-review-list"',
        'id="owner-editorial-review-list"',
        "Ideas que interesan al negocio",
        "La aprobación editorial queda ligada a la versión exacta",
    ):
        assert marker in html
    for marker in (
        "/idea-reviews",
        "data-owner-idea-review",
        "data-owner-promotion-proposal",
        "data-owner-editorial-review",
        "/editorial-review`",
    ):
        assert marker in js
    assert "Guardar y enviar a revisión" in js


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
