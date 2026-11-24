"""Rutas y semillas compartidas por todas las capas."""

import os
from functools import cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("DAII_DATA", ROOT / "data"))
BRONZE, SILVER, GOLD = DATA / "bronze", DATA / "silver", DATA / "gold"
GOLD_DB = GOLD / "daii.sqlite"


@cache
def academicos() -> list[dict]:
    return yaml.safe_load((ROOT / "config" / "academicos.yaml").read_text())


def catalogos() -> dict[str, dict[str, str]]:
    """`<tabla>.<columna>` → código → nombre legible (config/catalogos.yaml). Sin caché: `daii serve` corre días y
    un nombre editado debe verse en la siguiente publicación."""
    return yaml.safe_load((ROOT / "config" / "catalogos.yaml").read_text())


@cache
def whitelist() -> list[str]:
    return yaml.safe_load((ROOT / "config" / "whitelist.yaml").read_text())["dominios"]


def academico(slug: str) -> dict:
    return next(a for a in academicos() if a["slug"] == slug)


def con_perfil(plataforma: str) -> list[dict]:
    return [a for a in academicos() if plataforma in a.get("perfiles", {})]
