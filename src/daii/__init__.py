"""CLI: `daii run | serve | silver | gold | spiders`."""

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
    sub.add_parser("gold", help="reconstruir gold desde silver")
    sub.add_parser("spiders", help="listar spiders")
    args = p.parse_args()

    from daii.flows.pipeline import all_spiders, pipeline  # import diferido: Prefect tarda en cargar

    match args.cmd:
        case "run":
            pipeline(spiders=args.spiders.split(",") if args.spiders else None)
        case "serve":
            pipeline.serve(name="semanal", cron=args.cron)
        case "silver":
            from daii.silver.transform import build

            print(build())
        case "gold":
            from daii.gold.load import build

            print(build())
        case "spiders":
            print("\n".join(all_spiders()))
