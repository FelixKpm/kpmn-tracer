"""Train the optional YOLO ball detector on CPU (or GPU if available).

    pip install -r requirements-ml.txt
    python tools/train_yolo.py dataset_dir/dataset.yaml [--epochs 80] [--model yolo11n.pt]

The best weights end up in ``runs/detect/<name>/weights/best.pt``; set that path in the
project settings (``yolo_model``) or pass ``--yolo-model`` to the CLI to use it.
Note: Ultralytics is AGPL-3.0 licensed (see DECISIONS.md).
"""

from __future__ import annotations

import argparse

from kpmn_tracer.ball.ml_detector import pick_device


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data")
    ap.add_argument("--model", default="yolo11n.pt")
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--imgsz", type=int, default=320)
    ap.add_argument("--name", default="kpmn_ball")
    a = ap.parse_args()
    from ultralytics import YOLO

    YOLO(a.model).train(data=a.data, epochs=a.epochs, imgsz=a.imgsz, device=pick_device("auto"),
                        name=a.name, mosaic=0.5, scale=0.3, fliplr=0.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
