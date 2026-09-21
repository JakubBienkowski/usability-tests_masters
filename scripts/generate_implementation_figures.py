from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "thesis" / "figures"


def box(axis, xy, width, height, title, body, color, title_size=9, body_size=7.5):
    patch = FancyBboxPatch(
        xy,
        width,
        height,
        boxstyle="round,pad=0.02,rounding_size=0.025",
        linewidth=1.3,
        edgecolor=color,
        facecolor=f"{color}18",
    )
    axis.add_patch(patch)
    axis.text(xy[0] + width / 2, xy[1] + height * 0.70, title, ha="center", va="center", weight="bold", fontsize=title_size, color=color)
    axis.text(xy[0] + width / 2, xy[1] + height * 0.35, body, ha="center", va="center", fontsize=body_size, linespacing=1.25)
    return patch


def arrow(axis, start, end, label, color="#334155", curve=0.0, label_offset=(0, 0)):
    patch = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=12,
        linewidth=1.25,
        color=color,
        connectionstyle=f"arc3,rad={curve}",
    )
    axis.add_patch(patch)
    midpoint = ((start[0] + end[0]) / 2 + label_offset[0], (start[1] + end[1]) / 2 + label_offset[1])
    axis.text(*midpoint, label, ha="center", va="center", fontsize=7, color=color, bbox={"facecolor": "white", "edgecolor": "none", "pad": 1.5})


def save(figure, name):
    figure.tight_layout()
    for suffix in ("pdf", "png"):
        figure.savefig(OUTPUT_DIR / f"{name}.{suffix}", dpi=240, bbox_inches="tight")
    plt.close(figure)


def runtime_architecture():
    figure, axis = plt.subplots(figsize=(12.5, 7.2))
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")

    box(axis, (0.03, 0.66), 0.22, 0.22, "Chrome extension", "Popup controls\nContent instrumentation\nrrweb and task markers", "#2563eb")
    box(axis, (0.03, 0.19), 0.22, 0.26, "Desktop agent", "Screen recorder\nInput and active window\nETH-XGaze provider", "#0f766e")
    box(axis, (0.31, 0.40), 0.18, 0.20, "Loopback bridge", "127.0.0.1:8790\nSession join and leave\nLive gaze stream", "#0891b2")
    box(axis, (0.56, 0.67), 0.17, 0.19, "FastAPI", "Session lifecycle\nEvent ingestion\nRecording upload", "#7c3aed")
    box(axis, (0.56, 0.36), 0.17, 0.17, "RabbitMQ", "Durable ux_events queue\nAsynchronous delivery", "#d97706")
    box(axis, (0.56, 0.08), 0.17, 0.17, "Worker", "Persistence\nFriction markers\nDerived evidence", "#dc2626")
    box(axis, (0.80, 0.52), 0.17, 0.22, "Evidence stores", "JSONL and rrweb\nPostgreSQL aggregates\nH.264 MP4", "#475569")
    box(axis, (0.80, 0.12), 0.17, 0.20, "Report and replay", "Metrics and task table\nSUS and gaze quality\nVideo and timeline", "#16a34a")

    arrow(axis, (0.25, 0.76), (0.56, 0.76), "REST event batches")
    arrow(axis, (0.25, 0.30), (0.56, 0.70), "REST events and MP4 chunks", curve=-0.42, label_offset=(0.015, 0.115))
    arrow(axis, (0.25, 0.73), (0.31, 0.55), "join and gaze", curve=0.08, label_offset=(0.01, 0.01))
    arrow(axis, (0.31, 0.44), (0.25, 0.35), "control", curve=0.08, label_offset=(-0.01, 0))
    arrow(axis, (0.645, 0.67), (0.645, 0.53), "publish")
    arrow(axis, (0.645, 0.36), (0.645, 0.25), "consume")
    arrow(axis, (0.73, 0.17), (0.80, 0.57), "persist", curve=-0.15, label_offset=(0.035, 0))
    arrow(axis, (0.73, 0.76), (0.80, 0.66), "metadata and video")
    arrow(axis, (0.885, 0.52), (0.885, 0.32), "read evidence")

    axis.text(0.50, 0.95, "Runtime architecture and data flow", ha="center", va="center", fontsize=14, weight="bold")
    axis.text(0.50, 0.90, "All producers and artifacts share one session_id and run_id", ha="center", va="center", fontsize=9, color="#334155")
    save(figure, "implementation_runtime_architecture")


def synchronized_timeline():
    figure, axis = plt.subplots(figsize=(12.5, 5.5))
    channels = ["Lifecycle", "Task", "Browser", "Desktop", "Gaze", "Recording", "Questionnaire"]
    y_positions = list(range(len(channels), 0, -1))
    axis.set_xlim(0, 453)
    axis.set_ylim(0.3, len(channels) + 0.7)
    axis.set_yticks(y_positions, channels)
    axis.set_xlabel("Seconds from session start, example retained session P4")
    axis.set_title("Canonical event envelope mapped to one synchronized session timeline", pad=12)
    axis.grid(axis="x", linestyle=":", alpha=0.45)

    for y in y_positions:
        axis.hlines(y, 0, 453, color="#cbd5e1", linewidth=1)

    lifecycle_y, task_y, browser_y, desktop_y, gaze_y, recording_y, questionnaire_y = y_positions
    axis.scatter([0, 452.6], [lifecycle_y, lifecycle_y], s=55, color="#7c3aed", zorder=3)
    axis.text(0, lifecycle_y + 0.18, "session_started\n00:00", fontsize=7, ha="left")
    axis.text(452.6, lifecycle_y + 0.18, "session_stopped\n07:33", fontsize=7, ha="right")

    tasks = [(9.6, 101.2, "T1"), (107.6, 172.6, "T2"), (179.4, 300.1, "T3"), (305.0, 395.9, "T4")]
    task_colors = ["#2563eb", "#0891b2", "#0f766e", "#d97706"]
    for (start, end, name), color in zip(tasks, task_colors):
        axis.barh(task_y, end - start, left=start, height=0.35, color=color, alpha=0.9)
        axis.text((start + end) / 2, task_y, f"{name}\n{end-start:.1f}s", ha="center", va="center", fontsize=7, color="white", weight="bold")

    browser_times = [17, 52, 113, 151, 320, 366]
    axis.scatter(browser_times, [browser_y] * len(browser_times), marker="D", s=32, color="#2563eb", label="navigation or interaction")
    desktop_times = [181, 205, 233, 271, 307, 352, 389]
    axis.scatter(desktop_times, [desktop_y] * len(desktop_times), marker="s", s=30, color="#0f766e", label="active-window or desktop input")
    gaze_times = list(range(8, 448, 14))
    axis.scatter(gaze_times, [gaze_y] * len(gaze_times), marker=".", s=18, color="#dc2626", label="gaze sample stream")
    axis.barh(recording_y, 433.6, left=0.8, height=0.30, color="#475569")
    axis.text(217.6, recording_y, "H.264 screen recording, encoded duration 433.6s", ha="center", va="center", fontsize=7, color="white")
    axis.scatter([417, 424, 431, 438, 445], [questionnaire_y] * 5, marker="o", s=26, color="#7c3aed")
    axis.text(430, questionnaire_y + 0.22, "SEQ and SUS responses", ha="center", fontsize=7)

    axis.legend(loc="lower center", bbox_to_anchor=(0.5, -0.28), ncol=3, frameon=False, fontsize=8)
    save(figure, "implementation_synchronized_timeline")


def report_replay_schematic():
    figure, axis = plt.subplots(figsize=(12.5, 7.2))
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")
    axis.text(0.5, 0.96, "Session report and replay evidence layout", ha="center", fontsize=14, weight="bold")
    axis.text(0.5, 0.915, "Schematic populated with retained session P4 values", ha="center", fontsize=9, color="#475569")

    cards = [
        (0.03, "Lifecycle", "Completed\n07:33"),
        (0.22, "Tasks", "4 completed\n2 full, 2 partial"),
        (0.41, "SUS", "55.0 / 100"),
        (0.60, "Gaze quality", "0.879, green\n3.65 Hz"),
        (0.79, "Evidence", "14,824 events\nMP4 available"),
    ]
    for x, title, body in cards:
        box(axis, (x, 0.75), 0.16, 0.12, title, body, "#2563eb", title_size=8.5, body_size=7.5)

    box(axis, (0.03, 0.36), 0.45, 0.32, "Synchronized video and replay", "Desktop MP4 player\nrrweb DOM reconstruction\nShared UTC and sequence navigation\nJump to task, friction, error, or note", "#0f766e", title_size=10, body_size=8.5)
    box(axis, (0.52, 0.36), 0.45, 0.32, "Task and metric evidence", "T1  91.6s  partial  SEQ 2\nT2  64.9s  success  SEQ 7\nT3 120.6s  success  SEQ 6\nT4  90.9s  partial  SEQ 3\nGaze, clicks, scroll, routes, friction", "#7c3aed", title_size=10, body_size=8.2)

    axis.add_patch(Rectangle((0.03, 0.10), 0.94, 0.17, facecolor="#f8fafc", edgecolor="#475569", linewidth=1.2))
    axis.text(0.05, 0.245, "Evidence timeline", fontsize=9, weight="bold", color="#334155")
    axis.hlines(0.17, 0.07, 0.93, color="#94a3b8", linewidth=2)
    markers = [(0.10, "start", "#7c3aed"), (0.27, "T1", "#2563eb"), (0.43, "T2", "#0891b2"), (0.59, "T3", "#0f766e"), (0.75, "T4", "#d97706"), (0.90, "SUS", "#7c3aed")]
    for x, label, color in markers:
        axis.scatter([x], [0.17], s=70, color=color, zorder=3)
        axis.text(x, 0.125, label, ha="center", fontsize=7.5)
    axis.text(0.5, 0.045, "Every aggregate links back to raw events and the corresponding recording interval", ha="center", fontsize=8.5, color="#334155")
    save(figure, "implementation_report_replay")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    runtime_architecture()
    synchronized_timeline()
    report_replay_schematic()
    print(f"Generated implementation figures in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
