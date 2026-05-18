from pathlib import Path

import yaml

from app.agents import load_agents_yaml
from app.config import PROJECT_ROOT


def test_agents_yaml_parses():
    path = PROJECT_ROOT / "agents_config.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "experts" in raw
    assert len(raw["experts"]) == 3


def test_load_agents_yaml_returns_experts():
    agents, synthesis = load_agents_yaml()
    assert len(agents) == 3
    assert synthesis is not None
    assert agents[0].display_name
    assert agents[0].description
