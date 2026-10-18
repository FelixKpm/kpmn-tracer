"""End-to-end self test that needs no test media (used to verify installed/frozen builds).

Creates a short clip (noisy gradient plus a moving white dot) via FFmpeg, then:
probe -> proxy -> manual shot -> ProRes overlay export (frame count check)
-> person segmentation model load -> text rendering.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

from kpmn_tracer import __version__

log = logging.getLogger(__name__)


def _step(name: str, results: list[tuple[str, bool, str]]):
    class Ctx:
        def __enter__(self):
            self.t = time.time()
            return self

        def __exit__(self, et, ev, tb):
            ok = et is None
            results.append((name, ok, f"{time.time() - self.t:.1f}s" if ok else f"{et.__name__}: {ev}"))
            return True  # keep going, report at the end

    return Ctx()


def run(workdir: Path | None = None) -> bool:
    from kpmn_tracer.io.ffmpeg_bin import SUBPROCESS_FLAGS, ffmpeg, ffprobe

    results: list[tuple[str, bool, str]] = []
    tmp = Path(workdir or tempfile.mkdtemp(prefix="kpmn_selftest_"))
    clip = tmp / "selftest.mp4"
    with _step("ffmpeg/ffprobe", results):
        for exe in (ffmpeg(), ffprobe()):
            subprocess.run([exe, "-version"], capture_output=True, check=True, creationflags=SUBPROCESS_FLAGS)
    with _step("ffmpeg features", results):
        def listing(kind: str) -> str:
            return subprocess.run([ffmpeg(), "-hide_banner", f"-{kind}"], capture_output=True, text=True,
                                  check=True, creationflags=SUBPROCESS_FLAGS).stdout

        enc, flt = listing("encoders"), listing("filters")
        missing = [n for n in ("prores_ks", "libx264", "libx265", "mjpeg", "aac") if f" {n} " not in enc]
        missing += [n for n in ("zscale", "tonemap") if f" {n} " not in flt]
        assert not missing, f"FFmpeg build lacks {', '.join(missing)}"
    with _step("create test clip", results):
        cmd = [ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "640x360",
               "-r", "30", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, creationflags=SUBPROCESS_FLAGS)
        assert proc.stdin is not None
        rng = np.random.default_rng(0)
        bg = np.dstack([np.tile(np.linspace(80, 200, 640, dtype=np.float32), (360, 1))] * 3)
        bg = (bg + rng.normal(0, 8, bg.shape)).clip(0, 255).astype(np.uint8)
        for n in range(60):
            f = bg.copy()
            x, y = int(320 + 3 * n), int(300 - 6 * n + 0.04 * n * n)
            f[max(0, y - 2):y + 2, x - 2:x + 2] = 255
            proc.stdin.write(f.tobytes())
        proc.stdin.close()
        assert proc.wait() == 0
    sess = None
    with _step("probe + proxy", results):
        from kpmn_tracer.session import ClipSession

        sess = ClipSession.open(clip, cache_root=tmp / "cache")
        assert sess.project.frame_count == 60, sess.project.frame_count
    with _step("render + ProRes export", results):
        from kpmn_tracer.io.decode import count_frames
        from kpmn_tracer.io.export import ExportSettings, export
        from kpmn_tracer.trace.model import AnchorKind, Shot

        assert sess is not None
        shot = Shot(impact_frame=5, land_frame=50, text="Selbsttest")
        shot.set_anchor(AnchorKind.START, 322, 302)
        shot.set_anchor(AnchorKind.APEX, 400, 80)
        shot.set_anchor(AnchorKind.LAND, 480, 200)
        sess.project.shots = [shot]
        out = export(sess.project, ExportSettings("prores", tmp / "overlay.mov"))
        assert count_frames(out) == 60
    with _step("person segmentation model", results):
        from kpmn_tracer.segmentation.segmenter import MediaPipeSegmenter

        seg = MediaPipeSegmenter()
        m = seg.segment(np.full((256, 256, 3), 120, np.uint8))
        seg.close()
        assert m.shape == (256, 256)
    if sess is not None:
        sess.close()
    print(f"KPMN Tracer {__version__} self test ({tmp})")
    for name, ok, info in results:
        print(f"  [{'OK' if ok else 'FAIL'}] {name:28s} {info}")
    ok = all(ok for _, ok, _ in results)
    if ok and workdir is None:
        shutil.rmtree(tmp, ignore_errors=True)
    return ok
