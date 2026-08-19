from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split

from ai.generate_training_data import NoiseConfig, generate_rows, write_csv


FEATURE_COLUMNS = ["packet_size", "interarrival_ms", "src_port", "dst_port", "service_port"]


def train(
    data_path: Path,
    model_path: Path,
    report_path: Path,
    seed: int = 7,
    regenerate_data: bool = False,
) -> dict[str, object]:
    noise = NoiseConfig()
    if regenerate_data or not data_path.exists():
        write_csv(data_path, generate_rows(samples_per_class=1200, seed=seed, noise=noise))

    data = pd.read_csv(data_path)
    x_train, x_test, y_train, y_test = train_test_split(
        data[FEATURE_COLUMNS],
        data["label"],
        test_size=0.25,
        random_state=seed,
        stratify=data["label"],
    )
    model = RandomForestClassifier(
        n_estimators=160,
        max_depth=12,
        min_samples_leaf=2,
        class_weight="balanced",
        random_state=seed,
        n_jobs=-1,
    )
    model.fit(x_train, y_train)
    predictions = model.predict(x_test)
    labels = sorted(data["label"].unique().tolist())
    report = {
        "accuracy": accuracy_score(y_test, predictions),
        "classification_report": classification_report(y_test, predictions, output_dict=True),
        "confusion_matrix": {
            "labels": labels,
            "values": confusion_matrix(y_test, predictions, labels=labels).tolist(),
        },
        "features": FEATURE_COLUMNS,
        "training_noise": {
            "shared_port_probability": noise.shared_port_probability,
            "packet_size_jitter": noise.packet_size_jitter,
            "interarrival_jitter": noise.interarrival_jitter,
            "burst_probability": noise.burst_probability,
        },
    }

    model_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "features": FEATURE_COLUMNS}, model_path)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Random Forest traffic classifier.")
    parser.add_argument("--data", type=Path, default=Path("data/training_flows.csv"))
    parser.add_argument("--model", type=Path, default=Path("models/traffic_rf.joblib"))
    parser.add_argument("--report", type=Path, default=Path("results/model_report.json"))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--regenerate-data", action="store_true")
    args = parser.parse_args()
    report = train(args.data, args.model, args.report, args.seed, args.regenerate_data)
    print(f"Saved model to {args.model}")
    print(f"Accuracy: {report['accuracy']:.3f}")


if __name__ == "__main__":
    main()
