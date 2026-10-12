from streamlit.testing.v1 import AppTest


def test_chunking_lab_renders_strategy_comparison(monkeypatch):
    # The tab read keys ("total_chunks", "fragments_detected", ...) that
    # compare_strategies() never returned, so clicking it raised a KeyError.
    monkeypatch.setenv("API_URL", "http://127.0.0.1:9")  # no backend needed for this tab
    at = AppTest.from_file("../app.py", default_timeout=60).run()
    assert not at.exception

    at = at.button(key="btn_chunk").click().run()
    assert not at.exception
    assert any("No terminal punctuation" in m.value for m in at.markdown)
