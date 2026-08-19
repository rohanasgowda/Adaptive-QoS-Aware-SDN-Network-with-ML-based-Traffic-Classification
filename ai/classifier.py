from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd

from ai.train_model import FEATURE_COLUMNS
from common.flow_features import feature_vector
from common.traffic_types import TrafficType


class TrafficClassifier:
    def __init__(self, model_path: str | Path = "models/traffic_rf.joblib") -> None:
        bundle = joblib.load(model_path)
        self.model = bundle["model"]
        self.features = bundle.get("features", FEATURE_COLUMNS)

    def predict(
        self,
        packet_size: int,
        interarrival_ms: float,
        src_port: int,
        dst_port: int,
    ) -> TrafficType:
        row = pd.DataFrame(
            [feature_vector(packet_size, interarrival_ms, src_port, dst_port)],
            columns=self.features,
        )
        return TrafficType(self.model.predict(row)[0])
