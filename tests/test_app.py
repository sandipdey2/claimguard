"""Headless render of the Streamlit app (no LLM): every tab must render a saved live-run log without an exception."""
from streamlit.testing.v1 import AppTest


def test_app_renders_saved_run():
    at = AppTest.from_file("../app.py", default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    assert len(at.tabs) == 8
    labels = [t.label for t in at.tabs]
    assert labels[0] == "Appeal draft" and labels[-1] == "About" and "Coverage matrix" in labels
