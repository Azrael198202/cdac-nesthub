from presentation_brain.link_renderer import LinkRenderer


def test_link_renderer_converts_bare_urls_to_markdown_links():
    renderer = LinkRenderer()
    out = renderer.render("Sources:\n- https://example.com/path/item", source_titles={"https://example.com/path/item": "Example Item"})
    assert "[Example Item](https://example.com/path/item)" in out


def test_link_renderer_does_not_rewrite_existing_markdown_links():
    renderer = LinkRenderer()
    text = "See [Example](https://example.com/a)."
    assert renderer.render(text) == text
