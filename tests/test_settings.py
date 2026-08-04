import tomllib
from pathlib import Path

from app.settings import CLI_MODEL_CHOICES, MODEL_TIERS, get_model


def test_model_tiers_have_three_levels():
    assert set(MODEL_TIERS) == {"cheap", "standard", "deep"}


def test_get_model_returns_configured_id():
    assert get_model("standard") == MODEL_TIERS["standard"]
    assert get_model("standard").startswith("claude-")


def test_get_model_rejects_unknown_tier():
    import pytest
    with pytest.raises(KeyError):
        get_model("nope")


def test_codex_cli_model_choices_are_current_recommended_models():
    assert CLI_MODEL_CHOICES["codex_cli"] == [
        "auto",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    ]


def test_requirements_include_openai_backend_dependency():
    requirements = Path("requirements.txt").read_text(encoding="utf-8")
    assert "langchain-openai" in requirements


def test_pyproject_uses_explicit_package_discovery_for_editable_install():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    package_finder = (
        pyproject.get("tool", {})
        .get("setuptools", {})
        .get("packages", {})
        .get("find")
    )

    assert package_finder == {"include": ["app", "app.*"]}


def test_fastapi_and_langgraph_dependencies_are_bounded():
    requirements = Path("requirements.txt").read_text(encoding="utf-8")
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    project_dependencies = pyproject["project"]["dependencies"]

    for dependency in ("fastapi>=0.138,<0.139", "langgraph>=1.2,<1.3"):
        assert dependency in requirements
        assert dependency in project_dependencies
