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
        "async function refreshOwnerInstagramContent",
    )

    assert 'ownerInstagramJson(`${api}/settings`)' in load
    assert "await loadOwnerInstagramWorkspace(api)" in load
    assert workspace.count("ownerInstagramJson(") == 2
    assert 'ownerInstagramJson(`${api}/raw-assets`)' in workspace
    assert 'ownerInstagramJson(`${api}/contents`)' in workspace
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
