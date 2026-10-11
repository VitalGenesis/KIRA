
def test_browser_tools_registered():
    from tools import registry
    assert "browser_observe" in registry.TOOLS
    assert "browser_click" in registry.TOOLS
    assert "browser_fill" in registry.TOOLS
    assert "browser_scroll" in registry.TOOLS
    assert "youtube_play" in registry.TOOLS
