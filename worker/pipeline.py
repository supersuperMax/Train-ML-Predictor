"""Оркестрация шагов: ingest → normalize → geo → inference → snapshot.

Шаги выполняются по порядку. При ошибке оставшиеся шаги пропускаются, опубликованный snapshot не меняется,
а ошибка записывается в журнал: data/store/runs.jsonl, data/snapshot/LAST_RUN.json и таблицу pipeline_runs.
"""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from worker import db, geo, inference, ingest, normalize, snapshot
from worker.config import Config

log = logging.getLogger("worker")

STEPS = {
    "ingest": ingest.run,
    "normalize": normalize.run,
    "geo": geo.run,
    "inference": inference.run,
}
ORDER = [*STEPS, "snapshot"]


def _write_run(cfg: Config, run: dict) -> None:
    cfg.store_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps(run, ensure_ascii=False, default=str)
    with open(cfg.store_dir / "runs.jsonl", "a", encoding="utf-8") as f:
        f.write(line + "\n")
    cfg.snapshot_dir.mkdir(parents=True, exist_ok=True)
    tmp = cfg.snapshot_dir / "LAST_RUN.json.tmp"
    tmp.write_text(line, encoding="utf-8")
    tmp.replace(cfg.snapshot_dir / "LAST_RUN.json")
    db.log_run(cfg.database_url, run)


def run(cfg: Config, steps: list[str] | None = None) -> dict:
    steps = steps or ORDER
    run_info = {"started_at": datetime.now(timezone.utc).isoformat(), "steps": steps,
                "status": "ok", "details": {}}
    for step in steps:
        t0 = time.perf_counter()
        log.info("шаг %s…", step)
        try:
            if step == "snapshot":
                result = snapshot.run(cfg, run_info["details"])
                run_info["version"] = result["version"]
            else:
                result = STEPS[step](cfg)
        except Exception as e:
            log.exception("шаг %s завершился ошибкой", step)
            run_info.update(status="error", error=f"{step}: {e}")
            break
        result["seconds"] = round(time.perf_counter() - t0, 2)
        run_info["details"][step] = result
        log.info("шаг %s: %s", step, json.dumps(result, ensure_ascii=False, default=str))
    run_info["finished_at"] = datetime.now(timezone.utc).isoformat()
    _write_run(cfg, run_info)
    return run_info


def _fingerprint(cfg: Config) -> tuple:
    """Изменение входов (новые файлы валидаций, модель, справочники, история) запускает внеочередной прогон."""
    def files(folder: Path, recursive=False):
        if not folder.exists():
            return ()
        it = folder.rglob("*") if recursive else folder.iterdir()
        return tuple(sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in it
                            if p.is_file() and "__pycache__" not in p.parts))
    return (files(cfg.incoming_dir), files(cfg.model_dir, recursive=True),
            files(cfg.reference_dir), files(cfg.history_seed_dir))


def loop(cfg: Config) -> None:
    log.info("пайплайн по расписанию: каждые %s мин, проверка входов каждые %s с", cfg.interval_min, cfg.poll_sec)
    last_print, last_run = None, 0.0
    while True:
        fp = _fingerprint(cfg)
        due = time.monotonic() - last_run >= cfg.interval_min * 60
        if due or fp != last_print:
            run(cfg)
            last_run, last_print = time.monotonic(), _fingerprint(cfg)
        time.sleep(cfg.poll_sec)
