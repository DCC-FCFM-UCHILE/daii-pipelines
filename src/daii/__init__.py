"""CLI: `daii run | serve | silver | gold | spiders | explorar`."""

import argparse
from pathlib import Path

from dotenv import load_dotenv

# Antes de cualquier import de daii.config: DAII_DATA (y el resto) deben verse igual en el CLI, Prefect y scrapy.
# No pisa variables ya definidas en el entorno.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def main() -> None:
    p = argparse.ArgumentParser(prog="daii")
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="pipeline completo (bronze → quality → silver → gold)")
    run.add_argument("--spiders", help="lista separada por comas (por defecto: todos)")
    serve = sub.add_parser("serve", help="deployment programado en Prefect")
    serve.add_argument("--cron", default="0 6 * * 1", help="cron (default: lunes 06:00)")
    sub.add_parser("silver", help="reconstruir silver desde bronze")
    gold = sub.add_parser("gold", help="publicar un candidato Silver")
    gold.add_argument("--build-id")
    sub.add_parser("versions", help="listar versiones de datos")
    diff = sub.add_parser("diff", help="comparar versiones de datos")
    diff.add_argument("anterior")
    diff.add_argument("posterior")
    sub.add_parser("spiders", help="listar spiders")
    sub.add_parser("explorar", help="app local para explorar bronze, silver y gold (Streamlit)")
    accept = sub.add_parser("aceptar", help="aceptar un run en warn revisado a mano (caída legítima)")
    accept.add_argument("spider")
    accept.add_argument("run_id")
    logs = sub.add_parser("logs", help="consultar data/logs.sqlite")
    logs.add_argument("--run-id")
    logs.add_argument("--spider")
    logs.add_argument("--nivel", default="INFO", help="mínimo (default: INFO)")
    logs.add_argument("--desde", help="fecha ISO en UTC, p. ej. 2026-11-01")
    logs.add_argument("--limite", type=int, default=200)
    args = p.parse_args()

    if args.cmd == "explorar":  # antes de importar Prefect: la app no lo necesita
        import os
        import sys

        from daii.config import ROOT

        app = Path(__file__).parent / "explorar" / "app.py"
        os.chdir(ROOT)  # Streamlit lee .streamlit/config.toml del directorio actual
        os.execv(sys.executable, [sys.executable, "-m", "streamlit", "run", str(app)])  # Ctrl+C lo maneja Streamlit

    from daii.flows.pipeline import all_spiders, pipeline  # import diferido: Prefect tarda en cargar
    from daii.log import setup

    setup("cli", db=args.cmd != "logs")  # después de importar Prefect, que configura `logging` al cargar

    match args.cmd:
        case "run":
            pipeline(spiders=args.spiders.split(",") if args.spiders else None)
        case "serve":
            pipeline.serve(name="semanal", cron=args.cron)
        case "silver":
            from daii.versions import prepare

            print(prepare())
        case "gold":
            from daii.versions import publish

            print(publish(args.build_id))
        case "versions" | "diff":
            import json

            from daii import versions

            result = versions.versions() if args.cmd == "versions" else versions.diff(args.anterior, args.posterior)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        case "spiders":
            print("\n".join(all_spiders()))
        case "aceptar":
            from daii.quality.checks import aceptar

            print(aceptar(args.spider, args.run_id)["status"])
        case "logs":
            from daii.log import consultar

            print("\n".join(consultar(**{k: v for k, v in vars(args).items() if k != "cmd"})))
