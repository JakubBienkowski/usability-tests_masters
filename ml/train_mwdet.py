"""Train a subject-independent mind-wandering baseline on the MWDET dataset.

This model is an offline research baseline.  It is deliberately not loaded by the
runtime MFEM scorer because the public dataset and our live event stream do not yet
share an identical feature extractor.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.calibration import calibration_curve
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    balanced_accuracy_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import LeaveOneGroupOut, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

DEFAULT_DATA = Path(".datasets/mwdet_project/Scripts/features_labels_webgazer.csv")
NON_FEATURES = {
    "label",
    "id",
    "endtime_iso",
    "starttime_iso",
    "endtime_video",
    "starttime_video",
    "video_id",
    "video_order",
    "video_length",
}


@dataclass(frozen=True)
class FeatureSet:
    name: str
    prefixes: tuple[str, ...]


ABLATIONS = (
    FeatureSet("all_gaze_dynamics", ()),
    FeatureSet("fixation_only", ("fixation", "duration_fixation")),
    FeatureSet("saccade_only", ("saccade", "num_saccade")),
    FeatureSet("aoi_transitions_only", ("duration_fixation_aoi", "num_saccade_aoi")),
)


def _select_features(frame: pd.DataFrame, prefixes: Iterable[str] = ()) -> list[str]:
    candidates = [
        name
        for name in frame.columns
        if name not in NON_FEATURES and pd.api.types.is_numeric_dtype(frame[name])
    ]
    prefixes = tuple(prefixes)
    if prefixes:
        candidates = [name for name in candidates if name.startswith(prefixes)]
    if not candidates:
        raise ValueError("No numeric features match the requested ablation.")
    return candidates


def _models(feature_names: list[str], seed: int) -> dict[str, Pipeline]:
    preprocessor = ColumnTransformer(
        [("numeric", Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]), feature_names)],
        remainder="drop",
    )
    return {
        "logistic_regression": Pipeline([
            ("features", clone(preprocessor)),
            ("model", LogisticRegression(
                class_weight="balanced", max_iter=3000, random_state=seed
            )),
        ]),
        "random_forest": Pipeline([
            ("features", clone(preprocessor)),
            ("model", RandomForestClassifier(
                n_estimators=500,
                min_samples_leaf=3,
                class_weight="balanced_subsample",
                random_state=seed,
                n_jobs=1,
            )),
        ]),
    }


def _metrics(y_true: np.ndarray, probability: np.ndarray) -> dict[str, float | list]:
    prediction = (probability >= 0.5).astype(int)
    fraction_positive, mean_predicted = calibration_curve(
        y_true, probability, n_bins=5, strategy="quantile"
    )
    return {
        "balanced_accuracy": float(balanced_accuracy_score(y_true, prediction)),
        "macro_f1": float(f1_score(y_true, prediction, average="macro")),
        "mind_wandering_precision": float(precision_score(
            y_true, prediction, zero_division=0
        )),
        "mind_wandering_recall": float(recall_score(
            y_true, prediction, zero_division=0
        )),
        "roc_auc": float(roc_auc_score(y_true, probability)),
        "brier_score": float(brier_score_loss(y_true, probability)),
        "calibration": [
            {"mean_probability": float(p), "observed_frequency": float(o)}
            for p, o in zip(mean_predicted, fraction_positive)
        ],
    }


def train(data_path: Path, output_dir: Path, seed: int = 42) -> dict:
    frame = pd.read_csv(data_path)
    required = {"id", "label"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Dataset must contain columns: {sorted(required)}")
    frame = frame.dropna(subset=["id", "label"]).copy()
    y = frame["label"].astype(int).to_numpy()
    groups = frame["id"].astype(str).to_numpy()
    if set(np.unique(y)) != {0, 1}:
        raise ValueError("MWDET label must be binary (0=on-task, 1=mind-wandering).")
    if len(np.unique(groups)) < 3:
        raise ValueError("At least three participants are required.")

    logo = LeaveOneGroupOut()
    results: list[dict] = []
    fitted: dict[tuple[str, str], Pipeline] = {}
    for feature_set in ABLATIONS:
        feature_names = _select_features(frame, feature_set.prefixes)
        for model_name, estimator in _models(feature_names, seed).items():
            probability = cross_val_predict(
                estimator,
                frame,
                y,
                groups=groups,
                cv=logo,
                method="predict_proba",
                # A single process is also the most reproducible option on Windows
                # and works in restricted research environments without named pipes.
                n_jobs=1,
            )[:, 1]
            estimator.fit(frame, y)
            fitted[(feature_set.name, model_name)] = estimator
            results.append({
                "feature_set": feature_set.name,
                "model": model_name,
                "feature_count": len(feature_names),
                **_metrics(y, probability),
            })

    best = max(results, key=lambda item: (item["macro_f1"], item["roc_auc"]))
    best_key = (best["feature_set"], best["model"])
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "mwdet_baseline.joblib"
    joblib.dump(fitted[best_key], model_path)

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "name": "MWDET",
            "source": "https://github.com/Yue-ZHAO/MWDET_Project",
            "file": str(data_path),
            "tracker": "WebGazer" if "webgazer" in data_path.name.lower() else "Tobii",
            "rows": int(len(frame)),
            "participants": int(frame["id"].nunique()),
            "mind_wandering_rows": int(y.sum()),
            "on_task_rows": int((1 - y).sum()),
        },
        "validation": {
            "scheme": "leave-one-participant-out",
            "threshold": 0.5,
            "selection_metric": "macro_f1",
            "warning": (
                "External proof-of-concept only. Do not report this as validation "
                "of the full live MFEM system."
            ),
        },
        "experiments": results,
        "selected": best,
        "artifact": str(model_path),
    }
    (output_dir / "mwdet_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, default=Path(".run/ml/mwdet"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    report = train(args.data, args.output, args.seed)
    print(json.dumps(report["selected"], indent=2))
    print(f"Full report: {args.output / 'mwdet_report.json'}")


if __name__ == "__main__":
    main()
