from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent


def load_config(path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    config_path = Path(path) if path else PROJECT_ROOT / "config.yaml"
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_project_path(relative_path: str) -> Path:
    return PROJECT_ROOT / relative_path
