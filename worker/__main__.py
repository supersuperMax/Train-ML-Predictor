"""CLI пайплайна.

    python -m worker run --once               # один полный прогон
    python -m worker run --step ingest        # отдельный шаг (можно несколько: --step geo --step snapshot)
    python -m worker run                      # по расписанию (PIPELINE_INTERVAL_MIN) + при изменении входов
    python -m worker osm                      # выгрузить остановки и трассы из OpenStreetMap в data/reference/
"""
import argparse
import json
import logging
import sys

from worker import config, osm, pipeline


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m worker", description="Пайплайн прогноза пассажиропотока")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="запустить пайплайн")
    run.add_argument("--once", action="store_true", help="один полный прогон и выход")
    run.add_argument("--step", action="append", choices=pipeline.ORDER, help="выполнить только указанный шаг")
    sub.add_parser("osm", help=f"выгрузить остановки и трассы трамваев из OpenStreetMap в data/reference/{osm.FILE_NAME}")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config.load()
    if args.command == "osm":
        print(json.dumps(osm.run(cfg), ensure_ascii=False))
        return 0
    if args.step or args.once:
        steps = [s for s in pipeline.ORDER if s in args.step] if args.step else None
        result = pipeline.run(cfg, steps)
        return 0 if result["status"] == "ok" else 1
    pipeline.loop(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
