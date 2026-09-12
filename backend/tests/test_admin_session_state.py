from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADMIN_JS = ROOT / "autonogrow-admin" / "admin.js"


def function_block(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def test_session_reset_clears_privileged_state_and_invalidates_pending_requests() -> None:
    js = ADMIN_JS.read_text(encoding="utf-8")
    reset = function_block(
        js,
        "function resetAdminSessionState",
        "function renderAdminSessionNeutralState",
    )
    fetch_wrapper = js.split("let currentBusiness", 1)[0]

    assert "let adminSessionGeneration = 0" in js
    assert "new AbortController()" in js
    assert "adminSessionGeneration += 1" in reset
    assert "adminSessionAbortController.abort()" in reset
    for state in (
        "allBookings = []",
        "bookingCloseTasks = []",
        "reviewRequestsByBooking = new Map()",
        "messageOutbox = []",
        "adminServices = []",
        "staffMembers = []",
        "conversations = []",
        "conversationTemplates = []",
        "customerOpportunities = []",
        "businessGrowthSignals = []",
        "adminGallery = []",
        "adminInstagramContents = []",
        "socialContentProposals = []",
        "adminMembership = null",
    ):
        assert state in reset
    for cache in (
        "customerMemorySummaries.clear()",
        "bookingCustomerMemoryDrafts.clear()",
        "configurationSnapshots.clear()",
        "configurationDirtyKeys.clear()",
    ):
        assert cache in reset
    assert "const requestGeneration = adminSessionGeneration" in fetch_wrapper
    assert "adminSessionAbortController.signal" in fetch_wrapper
    assert "assertAdminSessionCurrent(requestGeneration)" in fetch_wrapper


def test_logout_purges_before_network_and_bootstrap_stays_neutral_until_authorized() -> None:
    js = ADMIN_JS.read_text(encoding="utf-8")
    logout = function_block(js, "async function adminLogout", "document.addEventListener")
    bootstrap = function_block(js, "async function bootstrapAdminAuth", "async function adminLogout")

    assert logout.index("resetAdminSessionState()") < logout.index("await AutonoGrowAuth.logout()")
    assert "const sessionGeneration = resetAdminSessionState()" in bootstrap
    assert "assertAdminSessionCurrent(sessionGeneration)" in bootstrap
    assert bootstrap.index("await loadAdminPanel()") < bootstrap.index(
        'document.getElementById("admin-app").hidden = false'
    )
    assert "renderAdminSessionNeutralState()" in js


def test_forbidden_contract_remains_distinct_from_session_reset() -> None:
    js = ADMIN_JS.read_text(encoding="utf-8")
    wrapper = js.split("let currentBusiness", 1)[0]
    forbidden = wrapper.split("response.status === 403", 1)[1]

    assert "showAdminPermissionFeedback(payload)" in forbidden
    assert "resetAdminSessionState" not in forbidden
    assert "showAdminLogin(" not in forbidden
