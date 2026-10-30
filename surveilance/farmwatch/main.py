"""Entry point: python -m farmwatch.main --config config.yaml [--dry-run] [--dashboard]"""
import argparse
import logging
import os
import sys
import time

import yaml
from dotenv import load_dotenv

from .alarm import Alarm
from .pipeline import CameraPipeline
from .storage import Storage
from .vision import VisionClient


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Sheep farm camera surveillance")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--dry-run", action="store_true", help="no cloud vision calls, no Telegram; log only")
    p.add_argument("--dashboard", action="store_true", help="also serve the web dashboard")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--camera", action="append", help="only run these camera names (repeatable)")
    p.add_argument("--source", help="override the source of the (single) selected camera, e.g. a video file")
    p.add_argument("--speed", type=float, default=1.0, help="file replay: time multiplier for behaviour clocks")
    p.add_argument("--max-frames", type=int, default=0, help="stop after N sampled frames (testing)")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("farmwatch")
    load_dotenv()
    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    st = cfg.get("storage", {})
    storage = Storage(st.get("db_path", "data/events.sqlite"), st.get("snapshot_dir", "data/snapshots"))
    vc = cfg.get("vision", {})
    vision = VisionClient(os.environ.get("TYPESAFE_API_KEY", ""), vc.get("model", "jev-latest"),
                          float(vc.get("timeout_seconds", 60)), int(vc.get("daily_budget", 2000)),
                          dry_run=args.dry_run)
    alarm = Alarm(os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", ""),
                  dry_run=args.dry_run)
    if args.dry_run:
        log.warning("DRY RUN: vision and Telegram disabled")

    cams = cfg.get("cameras", [])
    if args.camera:
        cams = [c for c in cams if c["name"] in args.camera]
    if args.source:
        if len(cams) != 1:
            log.error("--source needs exactly one selected camera (use --camera)")
            return 2
        cams[0] = dict(cams[0], source=args.source)
    if not cams:
        log.error("no cameras configured")
        return 2

    pipelines = [CameraPipeline(c, cfg, vision, alarm, storage, args.speed, args.max_frames) for c in cams]
    for pl in pipelines:
        pl.start()

    if args.dashboard:
        from .dashboard import serve
        import threading
        threading.Thread(target=serve, args=(storage, vision, args.port), daemon=True).start()

    try:
        while any(pl.is_alive() for pl in pipelines):
            time.sleep(1)
    except KeyboardInterrupt:
        for pl in pipelines:
            pl.stopped = True
    log.info("vision usage today: %s", vision.usage())
    return 0


if __name__ == "__main__":
    sys.exit(main())
