from pathlib import Path

import pandas as pd

from ml.train_mwdet import train


def test_training_pipeline_keeps_participants_as_groups(tmp_path: Path):
    rows = []
    for participant in range(6):
        for sample in range(6):
            label = (participant + sample) % 2
            rows.append({
                "id": f"p{participant}",
                "label": label,
                "fixationduration_mean": 100 + 30 * label + sample,
                "saccade_num": 5 + 4 * label + sample / 10,
                "duration_fixation_aoi_out": 0.1 + 0.5 * label,
            })
    data = tmp_path / "fixture.csv"
    pd.DataFrame(rows).to_csv(data, index=False)

    report = train(data, tmp_path / "output", seed=7)

    assert report["dataset"]["participants"] == 6
    assert report["validation"]["scheme"] == "leave-one-participant-out"
    assert len(report["experiments"]) == 8
    assert (tmp_path / "output" / "mwdet_baseline.joblib").exists()

