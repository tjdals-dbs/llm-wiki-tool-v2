import unittest


class DesktopGuiModuleBoundaryTests(unittest.TestCase):
    def test_desktop_helpers_are_available_from_split_modules(self):
        from wiki_tool.desktop_chat import append_agent_exchange
        from wiki_tool.desktop_domain import DomainCreationRequest
        from wiki_tool.desktop_graph import build_local_graph_layout
        from wiki_tool.desktop_navigation import build_page_navigation_items
        from wiki_tool.desktop_runtime import GuiTaskSpec
        from wiki_tool.desktop_styles import GUI_PANEL_TITLES

        self.assertEqual(GUI_PANEL_TITLES[2], "Wiki Agent")
        self.assertTrue(callable(append_agent_exchange))
        self.assertTrue(callable(build_local_graph_layout))
        self.assertTrue(callable(build_page_navigation_items))
        self.assertEqual(DomainCreationRequest(name="n", slug="s").slug, "s")
        self.assertEqual(GuiTaskSpec.__name__, "GuiTaskSpec")


if __name__ == "__main__":
    unittest.main()
