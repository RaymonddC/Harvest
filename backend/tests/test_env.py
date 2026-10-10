import re
from pathlib import Path

from app import config

ROOT = Path(__file__).resolve().parents[2]
NAME = r'"([A-Z][A-Z0-9_]+)"'


def env_names_read_by_the_app() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "backend" / "app").glob("*.py"):
        text = path.read_text()
        names |= set(re.findall(r"environ\.get\(" + NAME, text))
        names |= set(re.findall(r"_bool\(" + NAME, text))
    return names


def test_every_setting_the_app_reads_is_in_env_example_and_env_md():
    names = env_names_read_by_the_app()
    assert len(names) > 20  # the scan itself works
    example = (ROOT / ".env.example").read_text()
    reference = (ROOT / "ENV.md").read_text()
    for name in sorted(names):
        assert re.search(rf"^#?\s*{name}=", example, re.M), f"{name} is missing from .env.example"
        assert f"`{name}`" in reference, f"{name} is missing from ENV.md"


def test_dotenv_fills_gaps_but_never_overrides(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("HARVEST_T_NEW=from-file\nHARVEST_T_KEPT=from-file\nHARVEST_T_BLANK=\n")
    monkeypatch.setenv("HARVEST_T_KEPT", "from-shell")
    monkeypatch.delenv("HARVEST_T_NEW", raising=False)
    monkeypatch.delenv("HARVEST_T_BLANK", raising=False)
    config._load_dotenv((tmp_path,))
    import os

    assert os.environ["HARVEST_T_NEW"] == "from-file"
    assert os.environ["HARVEST_T_KEPT"] == "from-shell"
    assert "HARVEST_T_BLANK" not in os.environ
    for key in ("HARVEST_T_NEW", "HARVEST_T_BLANK"):
        os.environ.pop(key, None)


def test_a_missing_dotenv_is_fine(tmp_path):
    config._load_dotenv((tmp_path,))
