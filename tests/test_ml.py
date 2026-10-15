"""Phase 6 (optional ML): detector interface, combined detector, dataset bootstrapping, labels.

Ultralytics itself is not required for these tests; a fake model with the same
``predict`` contract stands in for YOLO.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from kpmn_tracer.ball.candidates import Candidate
from kpmn_tracer.ball.ml_detector import CombinedDetector, YoloDetector


class FakeYolo:
    """Finds the brightest pixel in the crop and reports a 6x6 box there."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def predict(self, source, **kw):
        out = []
        for tile in source:  # list of tiles, like ultralytics batch prediction
            self.calls.append((tile.shape, kw))
            g = tile.max(axis=2)
            if g.max() < 200:
                boxes = SimpleNamespace(xyxy=np.zeros((0, 4)), conf=np.zeros(0))
            else:
                y, x = np.unravel_index(int(np.argmax(g)), g.shape)
                boxes = SimpleNamespace(xyxy=np.array([[x - 3, y - 3, x + 3, y + 3]], float), conf=np.array([0.8]))
            out.append(SimpleNamespace(boxes=boxes))
        return out


def test_yolo_detector_returns_reference_coordinates() -> None:
    frame = np.zeros((200, 300, 3), np.uint8)
    frame[120, 210] = 255
    shift = np.array([[1, 0, 5], [0, 1, -4], [0, 0, 1]], float)  # frame -> reference
    model = FakeYolo()
    det = YoloDetector(lambda f: frame, lambda f: shift, (300, 200), 10, model, device="cpu", imgsz=64, overlap=16)
    c = det.detect(3, (150, 80, 260, 160))
    assert len(model.calls) > 1 and all(s[0] <= 64 and s[1] <= 64 for s, _ in model.calls)  # tiled
    assert len(c) == 1
    assert (c[0].x, c[0].y) == (215.0, 116.0)  # 210+5, 120-4
    assert c[0].score > 5 and model.calls[0][1]["device"] == "cpu"


def test_combined_detector_merges_duplicates() -> None:
    class D:
        def __init__(self, cands):
            self.cands = cands

        def detect(self, frame, roi, r=2.0, gap=2):
            return self.cands

    a = D([Candidate(1, 10.0, 10.0, 3.0, 4, 1), Candidate(1, 50.0, 50.0, 2.0, 4, 1)])
    b = D([Candidate(1, 11.0, 10.5, 8.0, 4, 0)])
    out = CombinedDetector([a, b]).detect(1, (0, 0, 100, 100))
    assert len(out) == 2 and out[0].score == 8.0


def test_dataset_export_labels_match_ball(media_dir: Path, tmp_path: Path) -> None:
    from synth import ShotSpec, SynthConfig, generate

    from kpmn_tracer.analysis import AnalysisOptions, analyze_shot
    from kpmn_tracer.ball.dataset import export_shot, usable_shots, write_yaml
    from kpmn_tracer.session import ClipSession
    from kpmn_tracer.trace.model import AnchorKind, Shot

    cfg = SynthConfig(width=640, height=360, fps=30, n_frames=110, shots=[ShotSpec(impact_frame=40)],
                      ref_frame=40, crf=14)
    truth = generate(cfg, media_dir, "ml_ds")
    sess = ClipSession.open(media_dir / "ml_ds.mp4", cache_root=tmp_path / "c")
    shot = Shot(impact_frame=40)
    shot.set_anchor(AnchorKind.START, *truth["frames"][40]["balls"][0]["frame"])
    analyze_shot(sess, shot, AnalysisOptions(use_person_mask=False))
    sess.project.shots = [shot]
    assert usable_shots(sess) == [shot]
    out = tmp_path / "ds"
    n = export_shot(sess, shot, out)
    assert n > 10
    write_yaml(out)
    labels = sorted((out / "labels" / "train").glob("*.txt"))
    pos = [p for p in labels if p.read_text().strip()]
    neg = [p for p in labels if not p.read_text().strip()]
    assert len(pos) == n and len(neg) > 0
    # verify one label against the ground truth: the labelled pixel is the ball's position
    import cv2

    img = cv2.imread(str(out / "images" / "train" / (pos[3].stem + ".jpg")))
    _, cx, cy, w, h = map(float, pos[3].read_text().split())
    x, y = cx * img.shape[1], cy * img.shape[0]
    f = int(pos[3].stem.split("_")[-1])
    ball = truth["frames"][f]["balls"][0]
    patch = img[int(y) - 2:int(y) + 3, int(x) - 2:int(x) + 3].mean()
    assert ball["visible"] and patch > img.mean() + 15  # bright ball under the label
    assert "names" in (out / "dataset.yaml").read_text()


def test_label_tool_roundtrip(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, "tools")
    from label_balls import label_path, read_label, write_label

    img = tmp_path / "ds" / "images" / "train" / "a.jpg"
    lp = label_path(img)
    assert lp == tmp_path / "ds" / "labels" / "train" / "a.txt"
    write_label(lp, (0.5, 0.25, 0.05))
    assert read_label(lp) == (0.5, 0.25, 0.05)
    write_label(lp, None)
    assert read_label(lp) is None
