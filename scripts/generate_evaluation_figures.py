from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "thesis" / "evaluation_data.json"
OUTPUT_DIR = ROOT / "thesis" / "figures"


def label_bars(axis, bars, fmt="{:.1f}", padding=3):
    axis.bar_label(bars, labels=[fmt.format(bar.get_height()) for bar in bars], padding=padding, fontsize=8)


def save(figure, name: str) -> None:
    figure.tight_layout()
    for suffix in ("pdf", "png"):
        figure.savefig(OUTPUT_DIR / f"{name}.{suffix}", dpi=220, bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    participants = data["participants"]
    tasks = data["tasks"]

    plt.rcParams.update({
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.labelsize": 9,
        "figure.titlesize": 11,
    })

    task_ids = [task["id"] for task in tasks]
    medians = [float(np.median(task["durations_seconds"])) for task in tasks]
    means_seq = [float(np.mean(task["seq"])) for task in tasks]
    full_success = [100 * task["outcomes"].count("success") / len(task["outcomes"]) for task in tasks]
    partial = [100 * task["outcomes"].count("partial") / len(task["outcomes"]) for task in tasks]
    friction = [sum(task["friction"]) for task in tasks]

    figure, axes = plt.subplots(1, 3, figsize=(13.2, 3.7))
    bars = axes[0].bar(task_ids, medians, color="#2563eb")
    label_bars(axes[0], bars, "{:.1f}")
    axes[0].set(title="Median task time", xlabel="Task", ylabel="Time (seconds)", ylim=(0, max(medians) * 1.25))

    bars = axes[1].bar(task_ids, means_seq, color="#0f766e")
    label_bars(axes[1], bars, "{:.2f}")
    axes[1].set(title="Mean SEQ rating", xlabel="Task", ylabel="Ease rating (1 to 7)", ylim=(0, 7.8))

    full_bars = axes[2].bar(task_ids, full_success, label="Full success", color="#16a34a")
    partial_bars = axes[2].bar(task_ids, partial, bottom=full_success, label="Partial success", color="#f59e0b")
    for bars_group, values in ((full_bars, full_success), (partial_bars, partial)):
        for bar, value in zip(bars_group, values):
            if value:
                axes[2].text(bar.get_x() + bar.get_width() / 2, bar.get_y() + bar.get_height() / 2, f"{value:.0f}%", ha="center", va="center", fontsize=8)
    axes[2].set(title="Task outcomes", xlabel="Task", ylabel="Participants (%)", ylim=(0, 108))
    axes[2].legend(loc="lower right", fontsize=8)
    figure.suptitle("Observed task performance, N = 4")
    save(figure, "task_performance")

    ids = [row["id"] for row in participants]
    sus = [row["sus"] for row in participants]
    session_minutes = [row["session_seconds"] / 60 for row in participants]
    coverage = [100 * row["video_seconds"] / row["session_seconds"] for row in participants]

    figure, axes = plt.subplots(1, 3, figsize=(13.2, 3.7))
    bars = axes[0].bar(ids, sus, color="#7c3aed")
    label_bars(axes[0], bars, "{:.1f}")
    axes[0].axhline(68, color="#475569", linestyle=":", linewidth=1, label="68 reference")
    axes[0].set(title="SUS score", xlabel="Participant", ylabel="SUS (0 to 100)", ylim=(0, 108))
    axes[0].legend(fontsize=8)

    bars = axes[1].bar(ids, session_minutes, color="#2563eb")
    label_bars(axes[1], bars, "{:.2f}")
    axes[1].set(title="Session duration", xlabel="Participant", ylabel="Minutes", ylim=(0, max(session_minutes) * 1.2))

    bars = axes[2].bar(ids, coverage, color="#0891b2")
    label_bars(axes[2], bars, "{:.1f}%")
    axes[2].set(title="Video duration coverage", xlabel="Participant", ylabel="Video / session (%)", ylim=(0, 108))
    figure.suptitle("Participant-level usability and recording outcomes")
    save(figure, "participant_outcomes")

    quality = [row["gaze_quality"] for row in participants]
    availability = [100 * row["gaze_availability"] for row in participants]
    sample_rate = [row["gaze_hz"] for row in participants]
    distances = [row["gaze_cursor_px"] for row in participants]

    figure, axes = plt.subplots(2, 2, figsize=(8.8, 6.3))
    values = [quality, availability, sample_rate, distances]
    titles = ["Gaze quality score", "Gaze availability", "Valid gaze sample rate", "Mean gaze to cursor distance"]
    ylabels = ["Score (0 to 1)", "Available samples (%)", "Samples per second (Hz)", "Distance (pixels)"]
    formats = ["{:.3f}", "{:.1f}%", "{:.2f}", "{:.1f}"]
    limits = [(0, 1.08), (0, 108), (0, max(sample_rate) * 1.25), (0, max(distances) * 1.2)]
    colors = ["#0f766e", "#0891b2", "#2563eb", "#dc2626"]
    for axis, value, title, ylabel, fmt, limit, color in zip(axes.flat, values, titles, ylabels, formats, limits, colors):
        bars = axis.bar(ids, value, color=color)
        label_bars(axis, bars, fmt)
        axis.set(title=title, xlabel="Participant", ylabel=ylabel, ylim=limit)
        for index, row in enumerate(participants):
            axis.text(index, limit[1] * 0.03, row["camera"], ha="center", va="bottom", fontsize=7, rotation=90, color="#334155")
    figure.suptitle("Operational webcam gaze quality by participant")
    save(figure, "gaze_quality")

    print(f"Generated figures in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
