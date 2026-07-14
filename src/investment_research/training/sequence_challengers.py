from __future__ import annotations

from hashlib import sha256
import json
from statistics import mean, pstdev

from pydantic import BaseModel, Field

from investment_research.training.models import TrainingSample


CHALLENGER_SEEDS = (42, 2026, 3407)


class SequenceExample(BaseModel):
    symbol: str
    market: str
    decision_context: str
    window_sessions: int = Field(ge=60, le=120)
    feature_order: list[str]
    values: list[list[float]]
    missing_mask: list[list[bool]]
    target: float
    sequence_hash: str


class ChallengerSeedResult(BaseModel):
    seed: int
    metric: float


class ChallengerSummary(BaseModel):
    architecture: str
    seeds: list[int]
    metric_mean: float
    metric_std: float
    baseline_approved: bool
    status: str = "research_only"


def build_sequence_examples(
    samples: list[TrainingSample],
    *,
    target_name: str,
    window_sessions: int,
) -> list[SequenceExample]:
    if window_sessions not in {60, 120}:
        raise ValueError("sequence window must be 60 or 120 sessions")
    grouped: dict[tuple[str, str, str], list[TrainingSample]] = {}
    for sample in samples:
        grouped.setdefault(
            (sample.symbol, sample.market.value, sample.decision_context), []
        ).append(sample)
    output: list[SequenceExample] = []
    for (symbol, market, context), group in grouped.items():
        ordered = sorted(group, key=lambda item: item.as_of_date)
        feature_order = sorted({name for sample in ordered for name in sample.features})
        for end in range(window_sessions - 1, len(ordered)):
            window = ordered[end - window_sessions + 1 : end + 1]
            target = getattr(window[-1].labels, target_name)
            if target is None or not window[-1].labels.label_available:
                continue
            values = [
                [float(sample.features.get(name, 0.0)) for name in feature_order]
                for sample in window
            ]
            missing = [
                [
                    name in sample.missing_features or name not in sample.features
                    for name in feature_order
                ]
                for sample in window
            ]
            payload = {
                "symbol": symbol,
                "market": market,
                "context": context,
                "features": feature_order,
                "values": values,
                "missing": missing,
                "target": target,
            }
            output.append(
                SequenceExample(
                    symbol=symbol,
                    market=market,
                    decision_context=context,
                    window_sessions=window_sessions,
                    feature_order=feature_order,
                    values=values,
                    missing_mask=missing,
                    target=float(target),
                    sequence_hash=sha256(
                        json.dumps(
                            payload, sort_keys=True, separators=(",", ":")
                        ).encode()
                    ).hexdigest(),
                )
            )
    return output


def train_gru_challenger(
    examples: list[SequenceExample],
    *,
    baseline_approved: bool,
    epochs: int = 12,
) -> ChallengerSummary:
    if not baseline_approved:
        raise ValueError(
            "deep challenger cannot start before its traditional baseline is approved"
        )
    if not examples:
        raise ValueError("sequence examples must not be empty")
    import torch
    import torch.nn as nn

    feature_count = len(examples[0].feature_order)
    results: list[float] = []
    for seed in CHALLENGER_SEEDS:
        torch.manual_seed(seed)
        network = _GRUNetwork(feature_count * 2)
        optimizer = torch.optim.AdamW(network.parameters(), lr=0.002, weight_decay=1e-4)
        criterion = nn.MSELoss()
        matrix, targets = _tensorize(examples, torch)
        network.train()
        for _ in range(epochs):
            optimizer.zero_grad()
            prediction = network(matrix)
            loss = criterion(prediction, targets)
            loss.backward()
            nn.utils.clip_grad_norm_(network.parameters(), 1.0)
            optimizer.step()
        network.eval()
        with torch.no_grad():
            mse = float(criterion(network(matrix), targets).item())
        results.append(mse)
    return ChallengerSummary(
        architecture="gru",
        seeds=list(CHALLENGER_SEEDS),
        metric_mean=mean(results),
        metric_std=pstdev(results),
        baseline_approved=True,
    )


def _tensorize(examples, torch):
    rows = []
    for example in examples:
        rows.append(
            [
                [*values, *[1.0 if flag else 0.0 for flag in mask]]
                for values, mask in zip(example.values, example.missing_mask)
            ]
        )
    matrix = torch.tensor(rows, dtype=torch.float32)
    # Per-fold callers must pass training-only examples; statistics never use holdout rows.
    means = matrix.mean(dim=(0, 1), keepdim=True)
    stds = matrix.std(dim=(0, 1), keepdim=True).clamp_min(1e-6)
    feature_count = matrix.shape[-1] // 2
    matrix[:, :, :feature_count] = (
        matrix[:, :, :feature_count] - means[:, :, :feature_count]
    ) / stds[:, :, :feature_count]
    return matrix, torch.tensor([item.target for item in examples], dtype=torch.float32)


class _GRUNetwork:
    def __new__(cls, input_size: int):
        import torch.nn as nn

        class Network(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.gru = nn.GRU(input_size, 48, batch_first=True, dropout=0.0)
                self.dropout = nn.Dropout(0.25)
                self.output = nn.Linear(48, 1)

            def forward(self, value):
                encoded, _ = self.gru(value)
                return self.output(self.dropout(encoded[:, -1])).squeeze(-1)

        return Network()
