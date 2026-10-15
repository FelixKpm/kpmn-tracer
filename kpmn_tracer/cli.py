"""Command line interface.

Examples::

    kpmn-tracer gui [clip]
    kpmn-tracer probe clip.mov
    kpmn-tracer export clip.mov.kpmntrace.json --format prores
    kpmn-tracer analyze clip.mov --ball 960 1500
    kpmn-tracer batch D:/Range/2026-10-15 --auto-confirm 0.8 --export prores
    kpmn-tracer batch-export D:/Range/2026-10-15
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


def _options(a: argparse.Namespace):
    from kpmn_tracer.analysis import AnalysisOptions
    from kpmn_tracer.project.presets import PresetStore

    d = PresetStore().load_defaults()
    return AnalysisOptions(use_person_mask=not a.no_mask and d.use_person_mask,
                           detector=a.detector or d.detector, yolo_model=a.yolo_model or d.yolo_model)


def cmd_analyze(a: argparse.Namespace) -> int:
    from kpmn_tracer.analysis import analyze_clip
    from kpmn_tracer.batch import find_hint_frame
    from kpmn_tracer.session import ClipSession

    sess = ClipSession.open(a.clip)
    try:
        hint = tuple(a.ball) if a.ball else sess.project.ball_start_hint
        frame = a.frame if a.frame is not None else (find_hint_frame(sess, hint) if hint else None)
        new = analyze_clip(sess, hint if frame is not None else None, frame, _options(a),
                           progress=_progress_printer("analyse"))
        path = sess.save()
    finally:
        sess.close()
    for i, s in enumerate(new):
        print(f"shot {i + 1}: impact frame {s.impact_frame}, confidence {s.confidence or 0:.0%}, {s.label}")
    print(path)
    return 0


def cmd_batch(a: argparse.Namespace) -> int:
    from kpmn_tracer.batch import analyze_folder, export_confirmed, write_summary
    from kpmn_tracer.project.presets import PositionPreset, PresetStore

    preset = PositionPreset(tuple(a.ball_norm)) if a.ball_norm else PresetStore().load_position()
    if preset is None:
        log.warning("No ball position preset - impacts are detected from audio only "
                    "(set one in the GUI or pass --ball-norm X Y)")
    results = analyze_folder(a.folder, preset, _options(a), a.auto_confirm, a.reanalyze,
                             _progress_printer("batch"))
    summary = write_summary(results, Path(a.folder) / "kpmn_batch_summary.csv")
    for r in results:
        status = r.error or ", ".join(f"{s.impact_frame}:{s.confidence:.0%}{'✔' if s.confirmed else ''}"
                                      for s in r.shots) or "keine Schläge"
        print(f"{Path(r.clip).name}: {status}")
    print(summary)
    if a.export:
        for out in export_confirmed(a.folder, a.export, _progress_printer("export")):
            print(out)
    return 0


def cmd_batch_export(a: argparse.Namespace) -> int:
    from kpmn_tracer.batch import export_confirmed

    outs = export_confirmed(a.folder, a.format, _progress_printer("export"))
    for o in outs:
        print(o)
    if not outs:
        print("nothing confirmed - confirm shots in the GUI review or use 'batch --auto-confirm'")
    return 0


def _analysis_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--no-mask", action="store_true", help="skip person segmentation")
    p.add_argument("--detector", choices=["classic", "yolo", "both"])
    p.add_argument("--yolo-model")


def cmd_selftest(a: argparse.Namespace) -> int:
    from kpmn_tracer.selftest import run

    return 0 if run() else 1


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
    p = sub.add_parser("analyze", help="find all impacts in a clip and track every shot")
    p.add_argument("clip")
    p.add_argument("--ball", nargs=2, type=float, metavar=("X", "Y"), help="resting ball (source px)")
    p.add_argument("--frame", type=int, help="frame in which the ball rests at --ball")
    _analysis_args(p)
    p.set_defaults(fn=cmd_analyze)
    p = sub.add_parser("batch", help="analyse all clips of a folder (range session)")
    p.add_argument("folder")
    p.add_argument("--ball-norm", nargs=2, type=float, metavar=("X", "Y"),
                   help="ball position as fraction of width/height (default: saved position preset)")
    p.add_argument("--auto-confirm", type=float, metavar="CONF", help="confirm shots with confidence >= CONF")
    p.add_argument("--reanalyze", action="store_true", help="re-run clips that already have shots")
    p.add_argument("--export", choices=["prores", "png", "h264", "h265"], help="export confirmed shots afterwards")
    _analysis_args(p)
    p.set_defaults(fn=cmd_batch)
    p = sub.add_parser("selftest", help="check the installation (FFmpeg, models, export)")
    p.set_defaults(fn=cmd_selftest)
    p = sub.add_parser("batch-export", help="export all confirmed shots of a folder")
    p.add_argument("folder")
    p.add_argument("--format", default="prores", choices=["prores", "png", "h264", "h265"])
    p.set_defaults(fn=cmd_batch_export)
    return ap


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.cmd is None:
        return cmd_gui(argparse.Namespace(clip=None))
    setup_logging("DEBUG" if a.verbose else ("WARNING" if a.cmd == "selftest" else "INFO"))
    return int(a.fn(a))


if __name__ == "__main__":
    raise SystemExit(main())
