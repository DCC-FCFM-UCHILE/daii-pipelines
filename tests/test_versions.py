import json
import sqlite3

import pytest

from daii import versions
from daii.gold import load
from daii.quality import checks


def test_publica_la_corrida_fijada_y_preserva_historial(tmp_path, monkeypatch):
    bronze = tmp_path / 'bronze'
    gold = tmp_path / 'gold' / 'daii.sqlite'
    for module, field, value in (
        (versions, 'DATA', tmp_path),
        (versions, 'VERSIONS', tmp_path / 'versions'),
        (versions, 'BRONZE', bronze),
        (versions, 'GOLD_DB', gold),
        (load, 'BRONZE', bronze),
        (checks, 'BRONZE', bronze),
    ):
        monkeypatch.setattr(module, field, value)

    def run(name, state):
        directory = bronze / 'orcid' / name
        directory.mkdir(parents=True)
        (directory / 'quality.json').write_text(json.dumps({'status': state}))
        item = {'tipo': 'area', 'persona': 'aidan-hogan', 'spider': 'orcid', 'nombre': name}
        (directory / 'items.jsonl').write_text(json.dumps(item) + '\n')

    run('20261123T175501Z', 'ok')
    first = versions.prepare()
    run('20261123T185212Z', 'warn')
    versions.publish(first)
    second = versions.prepare()
    versions.publish(second)
    with sqlite3.connect(gold) as db:
        assert db.execute('SELECT run_en_uso, estado FROM scraperun').fetchone() == ('20261123T175501Z', 'warn')
        assert db.execute('SELECT build_id FROM datarelease').fetchone() == (second,)
    assert (tmp_path / 'versions' / first / 'daii.sqlite').exists()
    assert 'area' not in versions.diff(first, second)['cambios']

    with monkeypatch.context() as patch:
        patch.setattr(load, 'build', lambda *_: pytest.fail('La republicación debe reutilizar el snapshot'))
        versions.publish(second)
        versions.publish(first)  # rollback a una versión ya publicada
        patch.setattr(load, 'head', lambda: '0002')
        with pytest.raises(ValueError, match='esquema 0001'):
            versions.publish(second)
    with sqlite3.connect(gold) as db:
        assert db.execute('SELECT build_id FROM datarelease').fetchone() == (first,)
        assert db.execute('SELECT version_num FROM alembic_version').fetchone() is not None

    stale, newest = versions.prepare(), versions.prepare()
    versions.publish(newest)
    with pytest.raises(ValueError, match='nunca se publicó'):
        versions.publish(stale)
    with pytest.raises(ValueError, match='nunca se publicó'):
        versions.diff(first, stale)

    tampered = versions.prepare()
    (tmp_path / 'versions' / tampered / 'silver' / 'proyecto.parquet').write_bytes(b'archivo imprevisto')
    with pytest.raises(ValueError, match='Silver cambió'):
        versions.publish(tampered)


def test_procedencia_sin_git(monkeypatch):
    def sin_git(*_, **__):
        raise FileNotFoundError('git')

    monkeypatch.setattr(versions.subprocess, 'check_output', sin_git)
    assert versions.code_provenance()['commit'] is None


def test_migraciones_coinciden_con_los_modelos(tmp_path):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlmodel import SQLModel, create_engine

    engine = create_engine(f'sqlite:///{tmp_path / "g.sqlite"}')
    load.migrate(engine)
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), SQLModel.metadata) == []
