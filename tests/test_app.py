import pytest

from app import app
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


def test_load_model_uses_transformers_v5_dtype_and_left_truncation(monkeypatch):
    class FakeTokenizer:
        pad_token_id = 0
        eos_token_id = 1
        chat_template = "{{ messages }}"
        truncation_side = "right"

    class FakeModel:
        def __init__(self):
            self.eval_called = False

        def eval(self):
            self.eval_called = True

    tokenizer = FakeTokenizer()
    model = FakeModel()
    model_kwargs = {}
    monkeypatch.setattr(
        app.AutoTokenizer,
        "from_pretrained",
        lambda *args, **kwargs: tokenizer,
    )

    def fake_model_loader(*args, **kwargs):
        model_kwargs.update(kwargs)
        return model

    monkeypatch.setattr(app.AutoModelForCausalLM, "from_pretrained", fake_model_loader)
    monkeypatch.setattr(app.torch.cuda, "is_available", lambda: False)
    app.load_model.cache_clear()
    try:
        loaded_tokenizer, loaded_model = app.load_model("test/model")
    finally:
        app.load_model.cache_clear()

    assert loaded_tokenizer.truncation_side == "left"
    assert loaded_model.eval_called is True
    assert model_kwargs["dtype"] == "auto"
    assert "torch_dtype" not in model_kwargs
