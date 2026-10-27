"""Configuration: config.yaml (optional) < environment variables."""
import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Config:
    database_url: str = "sqlite:///iris_local.db"  # local default; Docker uses Postgres
    schema: str = "iris_staging"                    # the ONLY schema we may write to
    log_level: str = "INFO"
    portal_max_requests_per_hour: int = 60          # portal terms of use


def load_config(path: str | None = None) -> Config:
    cfg = Config()
    p = Path(path or "config.yaml")
    if p.exists():                                  # file values override defaults
        for key, value in (yaml.safe_load(p.read_text()) or {}).items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
    # Environment wins: this is how Docker injects the DB URL (no secrets in files).
    cfg.database_url = os.environ.get("DATABASE_URL", cfg.database_url)
    cfg.log_level = os.environ.get("LOG_LEVEL", cfg.log_level)
    return cfg
