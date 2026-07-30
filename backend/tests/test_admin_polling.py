import unittest
from pathlib import Path


class AdminPollingFrontendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[2]
        cls.admin_js = (root / "autonogrow-admin" / "admin.js").read_text(encoding="utf-8")
        cls.admin_html = (root / "autonogrow-admin" / "index.html").read_text(encoding="utf-8")
        cls.admin_css = (root / "autonogrow-admin" / "styles.css").read_text(encoding="utf-8")

    def test_visible_and_hidden_polling_intervals_are_configured(self):
        expected_intervals = (
            "conversationThread: { visible: 5000, hidden: 15000 }",
            "conversationList: { visible: 10000, hidden: 15000 }",
            "operations: { visible: 15000, hidden: 30000 }",
        )
        for interval in expected_intervals:
            with self.subTest(interval=interval):
                self.assertIn(interval, self.admin_js)
        self.assertIn(
            'document.addEventListener("visibilitychange", handleAdminVisibilityChange)',
            self.admin_js,
        )
        self.assertIn("if (!document.hidden) {", self.admin_js)
        self.assertIn("scheduleAdminPollTask(taskName)", self.admin_js)

    def test_polling_avoids_overlap_and_uses_bounded_backoff(self):
        self.assertIn("if (task.inFlight) {", self.admin_js)
        self.assertIn("task.rerunRequested = true", self.admin_js)
        self.assertIn("ADMIN_POLL_MAX_BACKOFF_MULTIPLIER = 4", self.admin_js)
        self.assertIn("2 ** task.failures", self.admin_js)

    def test_background_refresh_preserves_interactive_state(self):
        expected_markers = (
            "captureConversationUiState",
            "threadNearBottom",
            "conversation-new-messages",
            "Hay mensajes nuevos",
            "textarea.value = uiState.draft",
            "textarea.focus({ preventScroll: true })",
            "captureBookingEditorState",
            "restoreBookingEditorState",
            "container.scrollTop = previousScrollTop",
        )
        for marker in expected_markers:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.admin_js)
        self.assertIn(".conversation-new-messages", self.admin_css)

    def test_polling_is_non_destructive_and_skips_static_data(self):
        self.assertIn(
            "loadConversations({ background: true, refreshDetail: false })",
            self.admin_js,
        )
        self.assertIn("loadBookings({ background: true })", self.admin_js)
        self.assertIn("loadMessageOutbox({ background: true })", self.admin_js)
        operations_block = self.admin_js.split('adminPollingTasks.set("operations"', 1)[1].split(
            "function updateAdminSyncIndicator", 1
        )[0]
        self.assertNotIn("loadConversationAutomation", operations_block)
        self.assertNotIn("loadConversationTemplates", operations_block)
        self.assertGreaterEqual(self.admin_js.count("if (background) throw error"), 4)

    def test_sync_indicator_and_manual_refresh_remain_available(self):
        self.assertIn('id="admin-sync-status"', self.admin_html)
        self.assertIn('id="admin-sync-last-updated"', self.admin_html)
        self.assertIn('id="refresh-button"', self.admin_html)
        self.assertIn('"Actualizando"', self.admin_js)
        self.assertIn('"Error temporal"', self.admin_js)
        self.assertIn('"Conectado"', self.admin_js)
        self.assertIn("includeAutomation: true", self.admin_js)


if __name__ == "__main__":
    unittest.main()
