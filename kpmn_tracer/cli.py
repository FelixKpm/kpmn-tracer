"""Command line interface.

Examples::

    kpmn-tracer gui [clip]
    kpmn-tracer probe clip.mov
    kpmn-tracer export clip.mov.kpmntrace.json --format prores
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from kpmn_tracer.logging_setup import setup_logging

log = logging.getLogger("kpmn_tracer.cli")


def _progress_printer(label: str):
    last = [-1]

    def cb(f: float) -> None:
        pct = int(f * 100)
        if pct != last[0] and pct % 10 == 0:
            last[0] = pct
            log.info("%s %d%%", label, pct)

    return cb


def cmd_probe(a: argparse.Namespace) -> int:
    from kpmn_tracer.io.probe import probe

    info = probe(a.clip)
    print(json.dumps(info.to_dict(), indent=1))
    print(info.summary())
    return 0


def cmd_export(a: argparse.Namespace) -> int:
    from kpmn_tracer.io.export import ExportSettings, export
    from kpmn_tracer.session import ClipSession

    sess = ClipSession.open(a.project)
    try:
        occl = None
        if any(s.occlude for s in sess.project.shots):
            from kpmn_tracer.segmentation.provider import occlusion_for_session

            occl = occlusion_for_session(sess)
        out = export(sess.project, ExportSettings(a.format, Path(a.out) if a.out else None, a.crf),
                     occl, _progress_printer("export"))
    finally:
        sess.close()
    print(out)
    return 0


def cmd_gui(a: argparse.Namespace) -> int:
    from kpmn_tracer.gui.app import main as gui_main

    return gui_main([sys.argv[0]] + ([a.clip] if a.clip else []))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="kpmn-tracer", description="TV-style ball tracer for golf videos")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("gui", help="start the GUI (default)")
    p.add_argument("clip", nargs="?")
    p.set_defaults(fn=cmd_gui)
    p = sub.add_parser("probe", help="show clip metadata")
    p.add_argument("clip")
    p.set_defaults(fn=cmd_probe)
    p = sub.add_parser("export", help="export the overlay of a clip/project")
    p.add_argument("project", help="clip or .kpmntrace.json")
    p.add_argument("--format", default="prores", choices=["prores", "png", "h264", "h265"])
    p.add_argument("--out")
    p.add_argument("--crf", type=int, default=18)
    p.set_defaults(fn=cmd_export)
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.cmd is None:
        return cmd_gui(argparse.Namespace(clip=None))
    setup_logging("DEBUG" if a.verbose else "INFO")
    return int(a.fn(a))


if __name__ == "__main__":
    raise SystemExit(main())
