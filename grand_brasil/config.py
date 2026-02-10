"""Configuration loading — merges config.yaml (thresholds) with .env (secrets)."""

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class AgingThresholds(BaseModel):
    """Configurable day thresholds for aging brackets."""

    green_max_days: int = 30
    yellow_max_days: int = 60
    orange_max_days: int = 90
    # 90+ = red (implicit)


class PriceReductionRule(BaseModel):
    """A single price reduction rule based on days in stock."""

    days_threshold: int
    reduction_percent: float
    min_margin_percent: float


class B2BScoringWeights(BaseModel):
    """Weights and thresholds for B2B candidate scoring."""

    aging_weight: float = 0.4
    concentration_weight: float = 0.4
    margin_weight: float = 0.2
    score_threshold: float = 7.0          # Above this = B2B candidate
    concentration_limit: int = 3          # Same model count to trigger flag


class AppConfig(BaseModel):
    """All business rule configuration loaded from config.yaml."""

    aging: AgingThresholds = AgingThresholds()
    price_reduction_rules: list[PriceReductionRule] = []
    b2b_scoring: B2BScoringWeights = B2BScoringWeights()


class Settings(BaseSettings):
    """Application settings combining YAML config and environment secrets."""

    # Secrets from .env
    dealerup_token: Optional[str] = None

    # Business config from config.yaml
    app: AppConfig = AppConfig()

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


def load_config(
    config_path: Optional[Path] = None,
    project_root: Optional[Path] = None,
) -> Settings:
    """Load YAML config and merge with .env secrets.

    Args:
        config_path: Explicit path to config.yaml. If None, searches in project_root.
        project_root: Project root directory. Defaults to Coding/ directory.

    Returns:
        Fully loaded Settings instance.
    """
    if project_root is None:
        # Walk up from this file to find config.yaml
        project_root = Path(__file__).resolve().parent.parent

    if config_path is None:
        config_path = project_root / "config.yaml"

    app_config = AppConfig()

    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f)

        if yaml_data:
            app_config = AppConfig(**yaml_data)

    return Settings(app=app_config)
