#!/usr/bin/env python3
"""Train date-batched StockMixer/MASTER-style research challengers.

This is intentionally a separate runner from the single-stock sequence
runner.  Each optimization batch contains several decision dates and every
date is padded to the frozen stock universe, so the stock-mixing and
stock-attention layers genuinely see cross-sectional context.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

import numpy as np
import torch
from torch import nn

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "scripts"))

from investment_research.domain.data_tier import DataTier
from investment_research.service.object_store import LocalObjectStore
from investment_research.training.models import TrainingSample
from investment_research.training.parquet_store import PITParquetStore
from investment_research.training.sequence_dataset import SequenceExample, build_sequence_examples
from investment_research.training.sequence_experiment import evaluate_predictions
from investment_research.training.sequence_models import _matrix, fit_sequence_stats
from investment_research.training.validation import build_walk_forward_folds
from investment_research.training.active_snapshot_guard import (
    ActiveSnapshotInputError,
    assert_manifest_binding,
    require_active_snapshot,
    require_training_snapshot_gate,
)
from investment_research.training.long_term_config import load_long_term_training_config
from investment_research.training.snapshot_landing import SnapshotGateConfig
from run_sequence_research_training import (
    _load_sequence_cache, _prune_constant_features, _sample_manifest_paths,
    _save_sequence_cache, _sequence_cache_key, _target,
)


TASKS = (
    "excess_return_5d", "excess_return_20d",
    "excess_return_120d", "excess_return_240d",
    "future_max_drawdown_120d", "future_max_drawdown_240d",
)
ARCHITECTURES = ("stockmixer", "master")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-manifest-file", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=PROJECT / "var/cn-research")
    parser.add_argument(
        "--long-term-config", type=Path,
        default=PROJECT / "config/long_term_training.yaml",
        help="data-gate contract used before formal training starts",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--task", choices=TASKS, required=True)
    parser.add_argument("--architecture", choices=ARCHITECTURES, required=True)
    parser.add_argument("--cohort", default="cn_equity_core")
    parser.add_argument("--window", type=int, default=60)
    parser.add_argument("--maximum-dates", type=int, default=1260)
    parser.add_argument("--evaluation-end-offset", type=int, default=0,
                        help="exclude this many latest decision dates for an earlier independent holdout")
    parser.add_argument("--holdout-sessions", type=int, default=252,
                        help="final independent evaluation sessions; must leave room for purged development folds")
    parser.add_argument("--batch-dates", type=int, default=8)
    parser.add_argument("--max-epochs", type=int, default=6)
    parser.add_argument("--hidden-size", type=int, default=32)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--early-stop-patience", type=int, default=2)
    parser.add_argument("--training-run-id", default=None)
    parser.add_argument("--variant", default="default", help="isolates hyperparameter trials without overwriting artifacts")
    parser.add_argument("--allow-research-only", action="store_true")
    parser.add_argument("--rebuild-index", type=Path, default=None)
    parser.add_argument("--sequence-cache", type=Path, default=None)
    parser.add_argument("--init-checkpoint", type=Path, default=None, help="compatible panel checkpoint used as a warm-start only")
    parser.add_argument("--warmup-epochs", type=int, default=0, help="initial epochs that train only the output head after warm-start")
    parser.add_argument("--warm-start-mode", choices=("compatible", "backbone"), default="compatible")
    parser.add_argument("--exclude-feature-prefix", action="append", default=[],
                        help="repeatable feature prefix exclusion used only for controlled ablations")
    return parser.parse_args()


def _device() -> torch.device:
    requested = os.getenv("INVESTMENT_RESEARCH_TORCH_DEVICE", "cuda")
    if requested == "cuda" and torch.cuda.is_available():
        try:
            fraction = float(os.getenv("INVESTMENT_RESEARCH_GPU_MEMORY_FRACTION", "0.80"))
            torch.cuda.set_per_process_memory_fraction(fraction, device=0)
        except (ValueError, RuntimeError):
            pass
        return torch.device("cuda")
    return torch.device("cpu")


class _StockMixer(nn.Module):
    def __init__(self, width: int, universe_size: int, hidden: int):
        super().__init__()
        self.temporal = nn.Sequential(
            nn.Conv1d(width, hidden, kernel_size=3, padding=1), nn.GELU(),
            nn.Conv1d(hidden, hidden, kernel_size=5, padding=2), nn.GELU(),
        )
        self.stock_mix = nn.Linear(universe_size, universe_size)
        self.channel_mix = nn.Sequential(nn.LayerNorm(hidden), nn.Linear(hidden, hidden * 2), nn.GELU(), nn.Linear(hidden * 2, hidden))
        self.head = nn.Sequential(nn.LayerNorm(hidden), nn.Linear(hidden, 3))

    def forward(self, values: torch.Tensor, valid: torch.Tensor) -> torch.Tensor:
        batch, stocks, steps, width = values.shape
        encoded = self.temporal(values.reshape(batch * stocks, steps, width).transpose(1, 2)).mean(dim=2)
        encoded = encoded.reshape(batch, stocks, -1)
        encoded = encoded + self.stock_mix(encoded.transpose(1, 2)).transpose(1, 2)
        encoded = encoded + self.channel_mix(encoded)
        encoded = encoded.masked_fill(~valid.unsqueeze(-1), 0.0)
        return self.head(encoded)


class _MASTER(nn.Module):
    def __init__(self, width: int, universe_size: int, hidden: int):
        super().__init__()
        heads = 4 if hidden % 4 == 0 else 1
        self.input = nn.Linear(width, hidden)
        layer = nn.TransformerEncoderLayer(hidden, heads, hidden * 2, 0.1, batch_first=True)
        self.temporal = nn.TransformerEncoder(layer, 2, enable_nested_tensor=False)
        self.market_gate = nn.Sequential(nn.Linear(hidden * 2, hidden), nn.Sigmoid())
        self.stock_attention = nn.MultiheadAttention(hidden, heads, dropout=0.1, batch_first=True)
        self.head = nn.Sequential(nn.LayerNorm(hidden), nn.Linear(hidden, 3))

    def forward(self, values: torch.Tensor, valid: torch.Tensor) -> torch.Tensor:
        batch, stocks, steps, width = values.shape
        tokens = self.input(values.reshape(batch * stocks, steps, width))
        encoded = self.temporal(tokens)[:, -1].reshape(batch, stocks, -1)
        denominator = valid.sum(dim=1, keepdim=True).clamp_min(1).to(encoded.dtype)
        market = (encoded * valid.unsqueeze(-1)).sum(dim=1, keepdim=True) / denominator.unsqueeze(-1)
        market = market.expand(-1, stocks, -1)
        encoded = encoded * self.market_gate(torch.cat((encoded, market), dim=-1))
        attended, _ = self.stock_attention(encoded, encoded, encoded, key_padding_mask=~valid)
        encoded = encoded + attended
        encoded = encoded.masked_fill(~valid.unsqueeze(-1), 0.0)
        return self.head(encoded)


def _network(name: str, width: int, universe_size: int, hidden: int) -> nn.Module:
    return (_StockMixer if name == "stockmixer" else _MASTER)(width, universe_size, hidden)


def _load_examples(args: argparse.Namespace) -> list[SequenceExample]:
    active = None
    try:
        active = require_active_snapshot(args.data_root)
    except ActiveSnapshotInputError as exc:
        if not args.allow_research_only or args.rebuild_index is None:
            raise SystemExit(str(exc)) from exc
    if active is not None:
        contract = load_long_term_training_config(args.long_term_config)
        try:
            require_training_snapshot_gate(
                active,
                config=SnapshotGateConfig(
                    required_datasets=set(contract.required_snapshot_datasets),
                    minimum_financial_coverage=contract.minimum_financial_coverage,
                ),
                labels_mature=True,
                allow_research_only=args.allow_research_only,
            )
        except ActiveSnapshotInputError as exc:
            raise SystemExit(str(exc)) from exc
    manifest_paths = _sample_manifest_paths([], [args.sample_manifest_file])
    manifest_paths = [path for path in manifest_paths if path.parent.parent.name == args.cohort]
    if not manifest_paths:
        raise SystemExit(f"no manifests found for panel cohort:{args.cohort}")
    if args.maximum_dates > 0:
        years = sorted({int(path.name.split("-", 1)[0]) for path in manifest_paths if path.name.split("-", 1)[0].isdigit()})
        keep = set(years[-max(2, args.maximum_dates // 200 + 2):])
        manifest_paths = [path for path in manifest_paths if not path.name.split("-", 1)[0].isdigit() or int(path.name.split("-", 1)[0]) in keep]
    manifests = [json.loads(path.read_text(encoding="utf-8")) for path in manifest_paths]
    if not manifests or any(item.get("data_tier") != DataTier.RESEARCH_PIT.value for item in manifests):
        raise SystemExit("panel training requires research_pit manifests")
    if active is not None:
        for item in manifests:
            try:
                assert_manifest_binding(active, item)
            except ActiveSnapshotInputError as exc:
                raise SystemExit(str(exc)) from exc
    store = PITParquetStore(LocalObjectStore(args.object_store))
    rows: list[TrainingSample] = []
    snapshots = set()
    for manifest in manifests:
        snapshot = (manifest.get("market_snapshot_id"), manifest.get("market_snapshot_hash"))
        snapshots.add(snapshot)
        for row in store.read_partition(
            manifest["sample_parquet_ref"],
            expected_payload_hash=manifest.get("payload_hash"),
        ):
            value = dict(row)
            for key in ("features", "labels", "data_quality_mask", "event_missing_mask"):
                if isinstance(value.get(key), str):
                    value[key] = json.loads(value[key])
            sample = TrainingSample.model_validate(value)
            if (sample.market_snapshot_id, sample.market_snapshot_hash) != snapshot:
                raise SystemExit("panel sample snapshot mismatch")
            rows.append(sample)
    if len(snapshots) != 1:
        raise SystemExit("panel training cannot mix market snapshots")
    if args.maximum_dates > 0:
        dates = sorted({item.as_of_date for item in rows})
        keep_dates = set(dates[-args.maximum_dates:])
        rows = [item for item in rows if item.as_of_date in keep_dates]
    cache_key = _sequence_cache_key(manifests, target_name=_target(args.task), window=args.window)
    examples = _load_sequence_cache(args.sequence_cache, cache_key)
    if examples is None:
        examples = build_sequence_examples(rows, target_name=_target(args.task), window_sessions=args.window)
        _save_sequence_cache(args.sequence_cache, cache_key, examples)
    else:
        print(f"SEQUENCE_CACHE_HIT {len(examples)}", flush=True)
    if not examples:
        raise SystemExit("panel scope has no valid windows")
    examples, pruning = _prune_constant_features(examples)
    excluded_prefixes = tuple(args.exclude_feature_prefix)
    if excluded_prefixes:
        kept = [name for name in examples[0].feature_order if not name.startswith(excluded_prefixes)]
        if not kept:
            raise SystemExit("feature ablation excluded every feature")
        positions = [examples[0].feature_order.index(name) for name in kept]
        examples = [item.model_copy(update={
            "feature_order": kept,
            "values": item.values[:, positions],
            "missing_mask": item.missing_mask[:, positions],
        }) for item in examples]
        pruning["ablation_excluded_prefixes"] = list(excluded_prefixes)
        pruning["retained_feature_count"] = len(kept)
    print(
        f"FEATURE_PRUNING {pruning['original_feature_count']} "
        f"{pruning['retained_feature_count']} dropped={pruning['dropped_feature_count']}",
        flush=True,
    )
    feature_order = list(examples[0].feature_order)
    incompatible = [item for item in examples if item.feature_order != feature_order]
    if incompatible:
        raise SystemExit(f"panel feature order drift:{len(incompatible)}")
    return examples


def _groups(examples: list[SequenceExample]) -> tuple[list[str], dict[str, list[SequenceExample]]]:
    symbols = sorted({item.symbol for item in examples})
    grouped: dict[str, list[SequenceExample]] = {}
    for item in examples:
        grouped.setdefault(item.decision_time[:10], []).append(item)
    grouped = {day: sorted(items, key=lambda item: item.symbol) for day, items in grouped.items() if len(items) >= 5}
    return symbols, grouped


def _batch_tensor(days: list[str], grouped: dict[str, list[SequenceExample]], symbols: list[str], stats, device: torch.device):
    first = next(iter(grouped.values()))[0]
    width = len(first.feature_order) * 2 + 9
    batch = np.zeros((len(days), len(symbols), first.window_sessions, width), dtype=np.float32)
    valid = np.zeros((len(days), len(symbols)), dtype=bool)
    targets = np.zeros((len(days), len(symbols)), dtype=np.float32)
    index = {symbol: pos for pos, symbol in enumerate(symbols)}
    for row, day in enumerate(days):
        items = grouped[day]
        matrix = _matrix(items, stats, validate=False).numpy()
        for item_index, item in enumerate(items):
            pos = index[item.symbol]
            batch[row, pos] = matrix[item_index]
            valid[row, pos] = True
            targets[row, pos] = float(item.target)
    return (torch.from_numpy(batch).to(device), torch.from_numpy(valid).to(device), torch.from_numpy(targets).to(device))


def _loss(prediction, target, valid):
    taus = torch.tensor([0.1, 0.5, 0.9], device=prediction.device)
    error = target.unsqueeze(-1) - prediction
    loss = torch.maximum(taus * error, (taus - 1) * error)
    return loss.masked_select(valid.unsqueeze(-1)).mean()


def _warm_start(model: nn.Module, *, architecture: str, feature_order: list[str], symbols: list[str], args) -> dict:
    """Load only shape-compatible weights; a changed head can be deliberately reset."""
    info = {"enabled": False, "mode": args.warm_start_mode, "source": None, "loaded_keys": 0, "skipped_keys": 0}
    if args.init_checkpoint is None:
        return info
    path = args.init_checkpoint.expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"warm-start checkpoint missing:{path}")
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if payload.get("architecture") != architecture:
        raise SystemExit(f"warm-start architecture mismatch:{payload.get('architecture')} != {architecture}")
    if payload.get("feature_order") != feature_order or payload.get("symbols") != symbols:
        raise SystemExit("warm-start feature or universe mismatch")
    source = payload.get("state_dict")
    if not isinstance(source, dict):
        raise SystemExit("warm-start checkpoint missing state_dict")
    target = model.state_dict()
    compatible = {
        key: value for key, value in source.items()
        if key in target and target[key].shape == value.shape and (args.warm_start_mode != "backbone" or not key.startswith("head."))
    }
    if not compatible:
        raise SystemExit("warm-start checkpoint has no compatible weights")
    model.load_state_dict(compatible, strict=False)
    info.update({"enabled": True, "source": str(path), "loaded_keys": len(compatible), "skipped_keys": len(source) - len(compatible)})
    return info


def _atomic_torch_save(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temporary)
    temporary.replace(path)


def _fit(architecture, train_days, valid_days, grouped, symbols, stats, args, device, checkpoint_path: Path | None = None):
    torch.manual_seed(args.seed)
    model = _network(architecture, len(next(iter(grouped.values()))[0].feature_order) * 2 + 9, len(symbols), args.hidden_size).to(device)
    warm_start = _warm_start(model, architecture=architecture, feature_order=list(next(iter(grouped.values()))[0].feature_order), symbols=symbols, args=args)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    best, best_loss, stale = None, float("inf"), 0
    start_epoch = 0
    if checkpoint_path is not None and checkpoint_path.is_file():
        checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
        if checkpoint.get("architecture") == architecture and checkpoint.get("seed") == args.seed:
            model.load_state_dict(checkpoint["model"])
            optimizer.load_state_dict(checkpoint["optimizer"])
            best = checkpoint.get("best")
            best_loss = float(checkpoint.get("best_loss", best_loss))
            stale = int(checkpoint.get("stale", stale))
            start_epoch = int(checkpoint.get("next_epoch", 0))
            warm_start["resumed_checkpoint"] = str(checkpoint_path)
    for epoch in range(start_epoch, args.max_epochs):
        freeze_backbone = warm_start["enabled"] and epoch < args.warmup_epochs
        for name, parameter in model.named_parameters():
            parameter.requires_grad = not freeze_backbone or name.startswith("head.")
        model.train()
        order = list(train_days)
        rng = np.random.default_rng(args.seed + epoch)
        rng.shuffle(order)
        for offset in range(0, len(order), args.batch_dates):
            x, valid, target = _batch_tensor(order[offset:offset + args.batch_dates], grouped, symbols, stats, device)
            optimizer.zero_grad(set_to_none=True)
            loss = _loss(model(x, valid), target, valid)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        model.eval()
        with torch.no_grad():
            losses = []
            for offset in range(0, len(valid_days), args.batch_dates):
                x, valid, target = _batch_tensor(valid_days[offset:offset + args.batch_dates], grouped, symbols, stats, device)
                losses.append(float(_loss(model(x, valid), target, valid).item()))
        validation_loss = float(np.mean(losses)) if losses else 0.0
        if validation_loss < best_loss:
            best_loss, stale = validation_loss, 0
            best = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
        else:
            stale += 1
        if checkpoint_path is not None:
            _atomic_torch_save({"architecture": architecture, "seed": args.seed, "next_epoch": epoch + 1,
                                "model": model.state_dict(), "optimizer": optimizer.state_dict(), "best": best,
                                "best_loss": best_loss, "stale": stale}, checkpoint_path)
        if stale >= args.early_stop_patience:
            break
    if best is not None:
        model.load_state_dict(best)
    for parameter in model.parameters():
        parameter.requires_grad = True
    return model.eval(), warm_start


def _predict(model, days, grouped, symbols, stats, args, device):
    predictions, targets, decision_dates, industries = [], [], [], []
    index = {symbol: pos for pos, symbol in enumerate(symbols)}
    with torch.no_grad():
        for offset in range(0, len(days), args.batch_dates):
            batch_days = days[offset:offset + args.batch_dates]
            x, valid, target = _batch_tensor(batch_days, grouped, symbols, stats, device)
            output = model(x, valid).detach().cpu().numpy()
            target_np = target.detach().cpu().numpy()
            valid_np = valid.detach().cpu().numpy()
            for row, day in enumerate(batch_days):
                for pos, symbol in enumerate(symbols):
                    if valid_np[row, pos]:
                        predictions.append(output[row, pos].tolist())
                        targets.append(float(target_np[row, pos]))
                        decision_dates.append(day)
                        industries.append(next((getattr(item, "industry_key", None) or "unknown" for item in grouped[day] if item.symbol == symbol), "unknown"))
    return predictions, targets, decision_dates, industries


def main() -> int:
    args = _args()
    active = None
    output_root = args.output_root if args.output_root.is_absolute() else PROJECT / args.output_root
    scope = output_root / "cn" / "close_confirmed" / args.cohort / args.task / "panel" / args.architecture
    if args.variant != "default":
        scope = scope / "variants" / args.variant
    checkpoint_root = scope / "checkpoints"
    required = [scope / name for name in ("sequence_evaluation.json", "sequence_manifest.json", "model.pt")]
    if all(path.is_file() and path.stat().st_size > 0 for path in required):
        # Existing artifacts must not bypass the current snapshot gate.  A
        # stale output is only reusable after the same immutable input check
        # that would precede a fresh panel fit.
        try:
            active = require_active_snapshot(args.data_root)
        except ActiveSnapshotInputError as exc:
            if not args.allow_research_only or args.rebuild_index is None:
                raise SystemExit(str(exc)) from exc
        if active is not None:
            contract = load_long_term_training_config(args.long_term_config)
            try:
                require_training_snapshot_gate(
                    active,
                    config=SnapshotGateConfig(
                        required_datasets=set(contract.required_snapshot_datasets),
                        minimum_financial_coverage=contract.minimum_financial_coverage,
                    ),
                    labels_mature=True,
                    allow_research_only=args.allow_research_only,
                )
            except ActiveSnapshotInputError as exc:
                raise SystemExit(str(exc)) from exc
        print(required[0], flush=True)
        return 0
    np.random.seed(args.seed)
    examples = _load_examples(args)
    symbols, grouped = _groups(examples)
    dates = sorted(grouped)
    if args.evaluation_end_offset:
        if args.evaluation_end_offset >= len(dates):
            raise SystemExit("evaluation end offset excludes every decision date")
        dates = dates[:-args.evaluation_end_offset]
    if len(dates) <= args.holdout_sessions:
        raise SystemExit("panel experiment requires more dates than its holdout")
    holdout_start = dates[-args.holdout_sessions]
    stress_start = dates[-min(126, args.holdout_sessions)]
    development = [day for day in dates if day < holdout_start]
    holdout = [day for day in dates if day >= holdout_start]
    stress = [day for day in holdout if day >= stress_start]
    fold_defs = build_walk_forward_folds(
        dates=[date.fromisoformat(day) for day in development], train_window_days=504,
        validation_window_days=126, prediction_horizon_days=_horizon(args.task),
        embargo_days=_horizon(args.task),
    )
    stats = fit_sequence_stats([item for day in development for item in grouped[day]])
    folds = []
    for fold in fold_defs:
        train_days = [day for day in development if fold.train_start <= date.fromisoformat(day) <= fold.train_end and all(date.fromisoformat(item.label_end[:10]) < fold.validation_start for item in grouped[day] if item.label_end)]
        validation_days = [day for day in development if fold.validation_start <= date.fromisoformat(day) <= fold.validation_end]
        if train_days and validation_days:
            folds.append((train_days, validation_days, fold.fold_id))
    if not folds:
        raise SystemExit("panel experiment has no valid purged folds")
    device = _device()
    oof_predictions, oof_targets, oof_dates = [], [], []
    warm_starts = []
    for train_days, validation_days, fold_id in folds:
        model, warm_start = _fit(args.architecture, train_days, validation_days, grouped, symbols, stats, args, device, checkpoint_root / f"{fold_id}.pt")
        warm_starts.append(warm_start)
        predictions, targets, decision_dates, _industries = _predict(model, validation_days, grouped, symbols, stats, args, device)
        oof_predictions.extend(predictions); oof_targets.extend(targets); oof_dates.extend(decision_dates)
    development_dates = development[-126:]
    final_train_days = development[:-126] or development
    model, final_warm_start = _fit(args.architecture, final_train_days, development_dates, grouped, symbols, stats, args, device, checkpoint_root / "final.pt")
    holdout_predictions, holdout_targets, holdout_dates, holdout_industries = _predict(model, holdout, grouped, symbols, stats, args, device)
    stress_predictions, stress_targets, stress_dates, _stress_industries = _predict(model, stress, grouped, symbols, stats, args, device)
    industry_metrics = {}
    for industry in sorted(set(holdout_industries)):
        indices = [index for index, value in enumerate(holdout_industries) if value == industry]
        if len(indices) < 30:
            continue
        industry_metrics[industry] = evaluate_predictions(
            args.task, [holdout_predictions[index] for index in indices], [holdout_targets[index] for index in indices],
            decision_dates=[holdout_dates[index] for index in indices],
        )
    result = {
        "task": args.task, "architecture": args.architecture, "variant": args.variant, "window_sessions": args.window,
        "evaluation_end_offset": args.evaluation_end_offset,
        "holdout_sessions": args.holdout_sessions,
        "fold_count": len(folds), "seed": args.seed,
        "oof_metrics": evaluate_predictions(args.task, oof_predictions, oof_targets, decision_dates=oof_dates),
        "holdout_metrics": evaluate_predictions(args.task, holdout_predictions, holdout_targets, decision_dates=holdout_dates),
        "stress_metrics": evaluate_predictions(args.task, stress_predictions, stress_targets, decision_dates=stress_dates),
        "holdout_industry_metrics": industry_metrics,
        "panel_contract": {"decision_date_batch": True, "universe_size": len(symbols), "symbols": symbols, "padding_mask": True, "stock_attention": args.architecture == "master"},
        "warm_start": {"folds": warm_starts, "final": final_warm_start, "warmup_epochs": args.warmup_epochs},
        "feature_ablation": {"excluded_prefixes": list(args.exclude_feature_prefix)},
    }
    scope.mkdir(parents=True, exist_ok=True)
    model_path = scope / "model.pt"
    torch.save({"state_dict": model.state_dict(), "task": args.task, "architecture": args.architecture, "feature_order": list(examples[0].feature_order), "stats": stats, "symbols": symbols, "window": args.window, "seed": args.seed}, model_path)
    payload = {"schema_version": "cn-panel-sequence-evaluation-v1", "status": "research_only", "deployment_ready": False, "training_run_id": args.training_run_id or f"panel-{args.task}-{args.architecture}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}", "task": args.task, "architecture": args.architecture, "training_symbol_count": len(symbols), "training_date_count": len(dates), "result": result, "model_hash": sha256(model_path.read_bytes()).hexdigest()}
    report = scope / "sequence_evaluation.json"
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    summary = {"task": args.task, "architecture": args.architecture, "status": "research_only", "panel_contract": result["panel_contract"], "artifact_ref": str(model_path), "report_ref": str(report), "report_hash": sha256(report.read_bytes()).hexdigest()}
    (scope / "sequence_manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report, flush=True)
    return 0


def _horizon(task: str) -> int:
    if task.endswith("120d"):
        return 120
    if task.endswith("240d"):
        return 240
    return 5 if task.endswith("5d") else 20


if __name__ == "__main__":
    raise SystemExit(main())
