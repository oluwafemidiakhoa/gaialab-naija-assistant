import pytest

from app.app import ModelConfigurationError, generate_response, respond


def test_generation_requires_configured_model(monkeypatch):
    monkeypatch.delenv("GAIALAB_MODEL_ID", raising=False)
    with pytest.raises(ModelConfigurationError, match="No model is configured"):
        generate_response("Write a reply", "Nigerian English")


def test_rejects_invalid_mode_before_loading_model(monkeypatch):
    monkeypatch.setenv("GAIALAB_MODEL_ID", "unused/model")
    with pytest.raises(ValueError, match="Unsupported language mode"):
        generate_response("Write a reply", "Unsupported mode")


def test_gradio_wrapper_returns_clear_empty_input_error(monkeypatch):
    monkeypatch.setenv("GAIALAB_MODEL_ID", "unused/model")
    assert respond("  ", "Nigerian English", 32) == (
        "Error: Please enter a message or business question."
    )
