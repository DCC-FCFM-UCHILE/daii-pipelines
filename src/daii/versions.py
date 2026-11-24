"""Candidatos Silver y publicaciones Gold identificados por un manifiesto."""

import hashlib
import json
import shutil
import sqlite3
import subprocess
import tempfile
from collections import Counter
from datetime import UTC, datetime
from fcntl import LOCK_EX, flock
from pathlib import Path
from uuid import uuid4

from daii.config import BRONZE, DATA, GOLD_DB, ROOT
from daii.gold import load
from daii.log import archivo, logger
from daii.silver import transform

VERSIONS = DATA / "versions"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def config_hashes() -> dict[str, str]:
    return {p.name: digest(p) for p in sorted((ROOT / "config").glob("*.yaml"))}


def parquet_hashes(directory: Path) -> dict[str, str]:
    return {p.name: digest(p) for p in sorted(directory.glob("*.parquet"))}


def code_provenance() -> dict:
    # Fuera de un checkout (contenedor, wheel) no hay git: la procedencia queda incompleta pero se publica igual.
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT))
    except OSError, subprocess.CalledProcessError:
        commit, dirty = None, None
    lockfile = ROOT / "uv.lock"
    return {"commit": commit, "dirty": dirty, "lockfile": digest(lockfile) if lockfile.exists() else None}


# shortcut: cada versión (~8 MB) y cada candidato sin publicar se guardan para siempre; agregar un `prune`
# cuando data/versions pese.
def prepare() -> str:
    VERSIONS.mkdir(parents=True, exist_ok=True)
    build_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
    runs = load.run_manifest()
    selected = [BRONZE / row["spider"] / row["run_en_uso"] for row in runs if row["run_en_uso"]]
    if not selected:
        raise ValueError("No hay corridas completas para preparar Silver")
    inputs = {str(p.relative_to(DATA)): digest(p) for r in selected if (p := r / "items.jsonl").is_file()}
    manifest = {
        "build_id": build_id,
        "schema_version": 1,
        **code_provenance(),
        "config": config_hashes(),
        "runs": runs,
        "inputs": inputs,
    }
    with tempfile.TemporaryDirectory(dir=VERSIONS) as temporary:
        candidate = Path(temporary) / "candidate"
        with logger.contextualize(componente="silver", build_id=build_id), archivo(candidate / "log.jsonl"):
            transform.build(candidate / "silver", selected)
            if any(digest(DATA / name) != expected for name, expected in inputs.items()):
                raise ValueError("Bronze cambió durante Silver")
            manifest["silver"] = parquet_hashes(candidate / "silver")
            (candidate / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
            fijadas = ", ".join(f"{r['spider']}={r['run_en_uso']}" for r in runs if r["run_en_uso"])
            logger.bind(evento="silver_preparado").info(f"corridas fijadas: {fijadas}")
        candidate.rename(VERSIONS / build_id)
    return build_id


def _version(build_id: str) -> Path:
    if not build_id or Path(build_id).name != build_id or build_id in (".", ".."):
        raise ValueError("Identificador de versión inválido")
    return VERSIONS / build_id


def versions() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(VERSIONS.glob("*/manifest.json"))]


def publish(build_id: str | None = None) -> dict[str, int]:
    candidates = versions()
    if not candidates:
        raise ValueError("Ejecute daii silver para generar un candidato")
    directory = _version(build_id or candidates[-1]["build_id"])
    with logger.contextualize(componente="gold", build_id=directory.name), archivo(directory / "log.jsonl"):
        return _publish(directory)


def _publish(directory: Path) -> dict[str, int]:
    GOLD_DB.parent.mkdir(parents=True, exist_ok=True)
    with (GOLD_DB.parent / ".publish.lock").open("a") as lock:
        flock(lock, LOCK_EX)
        manifest = json.loads((directory / "manifest.json").read_text())
        snapshot = directory / "daii.sqlite"
        restored = snapshot.exists()
        # Volver a una versión anterior solo con su SQLite ya publicada; reconstruirla mezclaría código nuevo.
        if GOLD_DB.exists() and not snapshot.exists():
            with sqlite3.connect(GOLD_DB) as current:
                has_version = current.execute("SELECT 1 FROM sqlite_master WHERE name='datarelease'").fetchone()
                active = current.execute("SELECT build_id FROM datarelease").fetchone() if has_version else None
                if active and active[0] > manifest["build_id"]:
                    raise ValueError("El candidato es anterior a la versión vigente y nunca se publicó")
        if not snapshot.exists() and config_hashes() != manifest["config"]:
            raise ValueError("La configuración cambió; vuelva a generar Silver")
        if not snapshot.exists() and parquet_hashes(directory / "silver") != manifest["silver"]:
            raise ValueError("El candidato Silver cambió")
        with tempfile.TemporaryDirectory(dir=GOLD_DB.parent) as temporary:
            db = Path(temporary) / "daii.sqlite"
            if snapshot.exists():
                if digest(snapshot) != manifest.get("gold_sha256"):
                    raise ValueError("La SQLite histórica cambió o su publicación quedó incompleta")
                shutil.copyfile(snapshot, db)
                with sqlite3.connect(db) as connection:
                    try:
                        schema = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                    except sqlite3.OperationalError:  # publicada antes de Alembic
                        schema = None
                if schema != load.head():
                    raise ValueError(f"La versión usa el esquema {schema}, distinto de {load.head()}; regenérela")
                counts = manifest["counts"]
                published_at = manifest["published_at"]
            else:
                counts = load.build(directory / "silver", db, manifest["runs"])
                published_at = datetime.now(UTC).isoformat()
                with sqlite3.connect(db) as connection:
                    connection.execute("INSERT INTO datarelease VALUES (?, ?)", (manifest["build_id"], published_at))
                    if (
                        connection.execute("PRAGMA integrity_check").fetchone() != ("ok",)
                        or connection.execute("PRAGMA foreign_key_check").fetchone()
                    ):
                        raise ValueError("La SQLite candidata no pasó la validación")
                manifest |= {"gold_code": code_provenance(), "counts": counts}
            manifest |= {"published_at": published_at, "gold_sha256": digest(db)}
            sidecar = directory / "manifest.tmp"
            sidecar.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
            sidecar.replace(directory / "manifest.json")
            if not snapshot.exists():
                staged = directory / "daii.sqlite.tmp"
                shutil.copyfile(db, staged)
                staged.replace(snapshot)
            db.replace(GOLD_DB)
    if restored:
        logger.bind(evento="gold_rollback").warning(f"se volvió a la versión publicada el {published_at}")
    else:
        logger.bind(evento="gold_publicado").info(f"{sum(counts.values())} filas: {counts}")
    return counts


def diff(before: str, after: str) -> dict:
    def read(build_id: str) -> tuple[dict, dict[str, Counter]]:
        directory = _version(build_id)
        if not (directory / "daii.sqlite").exists():
            raise ValueError(f"La versión {build_id} no existe o nunca se publicó")
        manifest = json.loads((directory / "manifest.json").read_text())
        with sqlite3.connect((directory / "daii.sqlite").resolve().as_uri() + "?mode=ro", uri=True) as db:
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            data = {}
            for (table,) in tables:
                if table in ("datarelease", "alembic_version"):
                    continue
                columns = [
                    r[1] for r in db.execute(f'PRAGMA table_info("{table}")') if (r[1], r[2]) != ("id", "INTEGER")
                ]
                projection = ", ".join(f'"{c}"' for c in columns)
                data[table] = Counter(
                    json.dumps(dict(zip(columns, row, strict=True)), ensure_ascii=False)
                    for row in db.execute(f'SELECT {projection} FROM "{table}"')
                )
        return manifest, data

    a, old = read(before)
    b, new = read(after)
    changes = {}
    for table in sorted(old.keys() | new.keys()):
        left, right = old.get(table, Counter()), new.get(table, Counter())
        if left != right:
            changes[table] = {
                "observaciones_anteriores": [json.loads(x) for x in (left - right).elements()],
                "observaciones_posteriores": [json.loads(x) for x in (right - left).elements()],
            }
    return {"anterior": a, "posterior": b, "cambios": changes}
