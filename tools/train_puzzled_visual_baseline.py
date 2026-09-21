"""Train a leakage-safe visual baseline on the public PUZZLED webcam dataset.

The model is deliberately a research baseline, not a detector of a person's
mental state. It predicts the PUZZLED behavioural labels from short windows of
MediaPipe face-landmark dynamics and evaluates them leave-one-participant-out.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import joblib
import mediapipe as mp
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    log_loss,
)

LABELS = {1: "OK", 2: "Challenged", 3: "Lost", 4: "Bored"}
FEATURE_NAMES = [
    "ear_left",
    "ear_right",
    "brow_eye_left",
    "brow_eye_right",
    "mouth_aspect",
    "face_center_x",
    "face_center_y",
    "nose_offset_x",
    "nose_offset_y",
    "head_roll",
]


def distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


def frame_features(landmarks) -> np.ndarray:
    xy = np.asarray([(p.x, p.y) for p in landmarks.landmark], dtype=np.float64)
    eye_scale = max(distance(xy[33], xy[263]), 1e-6)

    def ear(indices: tuple[int, int, int, int, int, int]) -> float:
        p1, p2, p3, p4, p5, p6 = (xy[i] for i in indices)
        return (distance(p2, p6) + distance(p3, p5)) / max(
            2.0 * distance(p1, p4), 1e-6
        )

    left_ear = ear((33, 160, 158, 133, 153, 144))
    right_ear = ear((362, 385, 387, 263, 373, 380))
    left_eye_y = float(np.mean(xy[[159, 145], 1]))
    right_eye_y = float(np.mean(xy[[386, 374], 1]))
    brow_left = abs(left_eye_y - float(np.mean(xy[[70, 63, 105], 1]))) / eye_scale
    brow_right = abs(right_eye_y - float(np.mean(xy[[336, 296, 334], 1]))) / eye_scale
    mouth_aspect = distance(xy[13], xy[14]) / max(distance(xy[78], xy[308]), 1e-6)
    face_center = np.mean(xy[[10, 152, 234, 454]], axis=0)
    eye_center = (xy[33] + xy[263]) / 2.0
    nose_offset = (xy[1] - eye_center) / eye_scale
    eye_vector = xy[263] - xy[33]
    head_roll = math.atan2(float(eye_vector[1]), float(eye_vector[0]))
    return np.asarray(
        [
            left_ear,
            right_ear,
            brow_left,
            brow_right,
            mouth_aspect,
            face_center[0],
            face_center[1],
            nose_offset[0],
            nose_offset[1],
            head_roll,
        ],
        dtype=np.float64,
    )


def read_annotations(path: Path) -> dict[int, list[tuple[float, int]]]:
    annotations: dict[int, list[tuple[float, int]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.reader(handle):
            if len(row) < 4:
                continue
            annotations[int(row[1])].append((float(row[2]), int(row[3])))
    for values in annotations.values():
        values.sort()
    return annotations


def label_at(transitions: list[tuple[float, int]], second: float) -> int:
    label = 1
    for start, candidate in transitions:
        if start > second:
            break
        label = candidate
    return label


def consensus_label(annotations: dict[int, list[tuple[float, int]]], second: float) -> int:
    # Researchers are independent post-hoc annotators; use them when available.
    annotators = [a for a in (1, 2, 3) if a in annotations] or list(annotations)
    votes = [label_at(annotations[a], second) for a in annotators]
    counts = Counter(votes)
    # Stable tie-break: prefer the student's concurrent label, then lower severity.
    best_count = max(counts.values())
    tied = {label for label, count in counts.items() if count == best_count}
    student = label_at(annotations[0], second) if 0 in annotations else None
    return student if student in tied else min(tied)


def summarize_window(samples: list[np.ndarray], expected: int) -> np.ndarray:
    array = np.vstack(samples)
    means = np.nanmean(array, axis=0)
    stds = np.nanstd(array, axis=0)
    if len(array) > 1:
        slopes = np.polyfit(np.arange(len(array)), array, 1)[0]
        motion = np.nanmean(np.abs(np.diff(array, axis=0)), axis=0)
    else:
        slopes = np.zeros(array.shape[1])
        motion = np.zeros(array.shape[1])
    detection_ratio = len(samples) / max(expected, 1)
    return np.concatenate([means, stds, slopes, motion, [detection_ratio]])


def extract_video(
    video_path: Path, csv_path: Path, sample_hz: float, window_seconds: float
) -> tuple[list[np.ndarray], list[int]]:
    annotations = read_annotations(csv_path)
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_step = max(1, round(fps / sample_hz))
    expected = max(1, round(sample_hz * window_seconds))
    windows: dict[int, list[np.ndarray]] = defaultdict(list)
    frame_index = 0
    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=False,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    ) as mesh:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_index % frame_step == 0:
                second = frame_index / fps
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = mesh.process(rgb)
                if result.multi_face_landmarks:
                    windows[int(second // window_seconds)].append(
                        frame_features(result.multi_face_landmarks[0])
                    )
            frame_index += 1
    cap.release()

    features: list[np.ndarray] = []
    labels: list[int] = []
    for window_index, samples in sorted(windows.items()):
        if len(samples) < max(2, expected // 3):
            continue
        midpoint = (window_index + 0.5) * window_seconds
        features.append(summarize_window(samples, expected))
        labels.append(consensus_label(annotations, midpoint))
    return features, labels


def model(seed: int) -> RandomForestClassifier:
    return RandomForestClassifier(
        n_estimators=400,
        min_samples_leaf=3,
        class_weight="balanced_subsample",
        random_state=seed,
        # Some managed Windows environments deny creation of joblib worker
        # pipes. A single worker is slower but deterministic and portable.
        n_jobs=1,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path(".datasets/puzzled"))
    parser.add_argument("--output", type=Path, default=Path(".run/ml/puzzled_visual"))
    parser.add_argument("--sample-hz", type=float, default=2.0)
    parser.add_argument("--window-seconds", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cache_directory = args.output / "feature_cache"
    cache_directory.mkdir(parents=True, exist_ok=True)

    rows: list[np.ndarray] = []
    targets: list[int] = []
    groups: list[str] = []
    video_paths = sorted(args.data.glob("*.webm"))
    if len(video_paths) < 2:
        raise SystemExit("At least two complete PUZZLED videos are required.")
    for index, video in enumerate(video_paths, 1):
        annotation = video.with_suffix(".csv")
        if not annotation.exists():
            continue
        cache_path = cache_directory / f"{video.stem}.npz"
        if cache_path.exists():
            cached = np.load(cache_path)
            x_video = [row for row in cached["x"]]
            y_video = cached["y"].astype(int).tolist()
            print(f"[{index}/{len(video_paths)}] cached {video.name}", flush=True)
        else:
            print(f"[{index}/{len(video_paths)}] extracting {video.name}", flush=True)
            x_video, y_video = extract_video(
                video, annotation, args.sample_hz, args.window_seconds
            )
            np.savez_compressed(
                cache_path,
                x=np.vstack(x_video) if x_video else np.empty((0, 41)),
                y=np.asarray(y_video, dtype=int),
            )
        rows.extend(x_video)
        targets.extend(y_video)
        groups.extend([video.stem] * len(y_video))
        print(f"  windows={len(y_video)} labels={dict(Counter(y_video))}", flush=True)

    x = np.vstack(rows)
    y = np.asarray(targets)
    group_array = np.asarray(groups)
    classes = np.asarray(sorted(set(targets)))
    predictions = np.empty_like(y)
    probabilities = np.zeros((len(y), len(classes)), dtype=float)
    folds = []
    for held_out in sorted(set(groups)):
        train = group_array != held_out
        test = ~train
        classifier = model(args.seed)
        classifier.fit(x[train], y[train])
        predictions[test] = classifier.predict(x[test])
        fold_probabilities = classifier.predict_proba(x[test])
        for source_index, label in enumerate(classifier.classes_):
            probabilities[test, int(np.where(classes == label)[0][0])] = (
                fold_probabilities[:, source_index]
            )
        folds.append(
            {
                "participant": held_out,
                "windows": int(test.sum()),
                "balanced_accuracy": float(
                    balanced_accuracy_score(y[test], predictions[test])
                ),
                "macro_f1": float(
                    f1_score(y[test], predictions[test], average="macro")
                ),
            }
        )

    final_model = model(args.seed)
    final_model.fit(x, y)
    artifact = {
        "model": final_model,
        "classes": {int(k): v for k, v in LABELS.items()},
        "feature_names": [
            f"{stat}_{name}"
            for stat in ("mean", "std", "slope", "motion")
            for name in FEATURE_NAMES
        ]
        + ["face_detection_ratio"],
        "sample_hz": args.sample_hz,
        "window_seconds": args.window_seconds,
    }
    joblib.dump(artifact, args.output / "puzzled_visual_baseline.joblib")
    report = {
        "dataset": "PUZZLED",
        "evaluation": "leave-one-participant-out",
        "participants": len(set(groups)),
        "videos_available": len(video_paths),
        "windows": len(y),
        "labels": {LABELS[k]: int((y == k).sum()) for k in classes},
        "balanced_accuracy": float(balanced_accuracy_score(y, predictions)),
        "macro_f1": float(f1_score(y, predictions, average="macro")),
        "multiclass_log_loss": float(log_loss(y, probabilities, labels=classes)),
        "class_order": [LABELS[k] for k in classes],
        "confusion_matrix": confusion_matrix(y, predictions, labels=classes).tolist(),
        "folds": folds,
        "limitations": [
            "Small dataset and only the locally available complete videos were used.",
            "PUZZLED labels describe comfort/challenge/lost/bored, not attention directly.",
            "The student looked at a labelling panel while recording, which affects gaze.",
            "This is a visual proof-of-concept and must not be treated as a psychological diagnosis.",
        ],
    }
    (args.output / "puzzled_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
