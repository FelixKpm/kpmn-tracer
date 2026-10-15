"""Build a YOLO training set from your own analysed clips (see kpmn_tracer.ball.dataset).

    python tools/make_ball_dataset.py out_dir clip1.mov clip2.mov ...   (clips need a .kpmntrace.json)

Every 5th shot goes to the validation split. Afterwards check the labels with
``tools/label_balls.py out_dir/images/train`` and train with ``tools/train_yolo.py``.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from kpmn_tracer.ball.dataset import DatasetParams, export_shot, usable_shots, write_yaml
from kpmn_tracer.session import ClipSession


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--tile", type=int, default=320)
    ap.add_argument("--min-conf", type=float, default=0.6)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    out = Path(a.out)
    k = 0
    for clip in a.clips:
        sess = ClipSession.open(clip)
        for shot in usable_shots(sess, a.min_conf):
            export_shot(sess, shot, out, "val" if k % 5 == 4 else "train", DatasetParams(tile=a.tile))
            k += 1
        sess.close()
    print(f"{k} shots exported -> {write_yaml(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
