from pathlib import Path

from streamlit.testing.v1 import AppTest

# Absolute path: AppTest resolves a relative path against the caller's compiled
# filename, which goes stale (and points at a missing folder) if the project
# directory is renamed while old __pycache__ files remain.
APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_chunking_lab_renders_strategy_comparison(monkeypatch):
    # The tab read keys ("total_chunks", "fragments_detected", ...) that
    # compare_strategies() never returned, so clicking it raised a KeyError.
    monkeypatch.setenv("API_URL", "http://127.0.0.1:9")  # no backend needed for this tab
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception

    at = at.button(key="btn_chunk").click().run()
    assert not at.exception
    assert any("No terminal punctuation" in m.value for m in at.markdown)
