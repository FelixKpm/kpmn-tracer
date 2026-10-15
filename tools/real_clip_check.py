"""Plausibility check on a real, freely licensed range clip (not part of the test suite).

Clip: "Suvichaya Vinijchaitham Golf Swing Slow Mo 2026.webm", Wikimedia Commons, CC0
https://commons.wikimedia.org/wiki/File:Suvichaya_Vinijchaitham_Golf_Swing_Slow_Mo_2026.webm

    python tools/real_clip_check.py <dir>      # downloads the clip into <dir> if missing

Prints the impact candidates and tracks the ball of the shot at frame 281
(ball resting at ~(712, 1224) in the 1080x1920 frame), then writes a contact
sheet with the rendered tracer.
"""

from __future__ import annotations

import logging
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from kpmn_tracer.analysis import AnalysisOptions, analyze_shot
from kpmn_tracer.ball.impact import detect_impacts
from kpmn_tracer.render.tracer import TracerRenderer, composite_over
from kpmn_tracer.session import ClipSession
from kpmn_tracer.trace.model import AnchorKind, Shot

URL = ("https://upload.wikimedia.org/wikipedia/commons/9/9e/"
       "Suvichaya_Vinijchaitham_Golf_Swing_Slow_Mo_2026.webm")
BALL = (711.75, 1223.8)
IMPACT = 281


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "test_output/real")
    out.mkdir(parents=True, exist_ok=True)
    clip = out / "suvichaya.webm"
    if not clip.exists():
        req = urllib.request.Request(URL, headers={"User-Agent": "KPMN-Tracer-dev/0.1"})
        with urllib.request.urlopen(req) as r, open(clip, "wb") as f:  # noqa: S310 - fixed URL
            f.write(r.read())
    sess = ClipSession.open(clip, cache_root=out / "cache")
    cands = detect_impacts(sess, BALL, 0)
    print("impact candidates:", [(c.frame, "+".join(c.sources), round(c.confidence, 2)) for c in cands])
    shot = Shot(impact_frame=IMPACT)
    shot.set_anchor(AnchorKind.START, *BALL)
    res = analyze_shot(sess, shot, AnalysisOptions())
    print(f"ball tracking: confidence {shot.confidence:.2f}, detections {res.n_detections if res else 0}")
    r = TracerRenderer(sess.project.width, sess.project.height, sess.project.fps, sess.project.style)
    tiles = []
    for f in (284, 290, 300, 320, 345, 380):
        im = composite_over(sess.reader.read(f), r.render([shot], f))
        tiles.append(cv2.resize(im, (270, 480)))
    cv2.imwrite(str(out / "real_tracer.jpg"), np.hstack(tiles))
    print("sheet:", out / "real_tracer.jpg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
