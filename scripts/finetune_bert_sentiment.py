#!/usr/bin/env python3
"""Step-3 full transfer learning: fine-tune bert-base-chinese for finance sentiment.

Unlike the lightweight (frozen feature-extraction) step which produced a no-signal
768-dim [CLS] vector, this fine-tunes a 3-class sentiment head with WEAK SUPERVISION
labels = the sign of each text's symbol forward-5d return (price-validated sentiment:
texts preceding price rises => positive).  The trained model then produces a low-dim,
finance-aware sentiment SCORE (P(pos) - P(neg)) per text, aggregated per (symbol, date).

PIT / out-of-sample honesty:
  * Fine-tune is trained ONLY on texts whose date falls in the train-period (the same
    80% time cutoff the panel uses).  Texts in the holdout 20% are encoded by a model
    that never saw holdout-period labels -> the holdout sentiment score is a legitimate
    out-of-sample prediction, no look-ahead.

Output parquet (symbol, trade_date, s_score, s_pos, s_neg, s_neu, s_vol) consumed by
panel_eval.py --sentiment-vectors.

Usage:
    python3 scripts/finetune_bert_sentiment.py --model /root/bert-base-chinese \
        --epochs 2 --batch-size 64 --max-length 128
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, Dataset

PROJECT = Path(__file__).resolve().parent.parent
DB = Path(PROJECT / "var/investment_research.db")
OUT = PROJECT / "artifacts/sentiment_vectors/news_bert_finetune_score.parquet"
log = logging.getLogger("finetune")


def load_texts(conn: sqlite3.Connection) -> pd.DataFrame:
    frames = []
    try:
        df = pd.read_sql_query("SELECT symbol, published_at, title, content FROM sentiment_news", conn)
        if not df.empty:
            df["d"] = pd.to_datetime(df["published_at"], errors="coerce"); df = df.dropna(subset=["d"])
            df["d"] = df["d"].dt.tz_localize(None).dt.normalize()
            df["text"] = df["title"].fillna("").astype(str) + "。" + df["content"].fillna("").astype(str).str.slice(0, 480)
            frames.append(df[df["text"].str.len() > 2][["symbol", "d", "text"]])
    except Exception as e:
        log.warning("news: %s", e)
    try:
        df = pd.read_sql_query("SELECT symbol, notice_date, title FROM event_notice", conn)
        if not df.empty:
            df["d"] = pd.to_datetime(df["notice_date"], errors="coerce"); df = df.dropna(subset=["d"])
            df["d"] = df["d"].dt.tz_localize(None).dt.normalize()
            df["text"] = df["title"].fillna("").astype(str)
            frames.append(df[df["text"].str.len() > 2][["symbol", "d", "text"]])
    except Exception as e:
        log.warning("notice: %s", e)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["symbol", "d", "text"])


def load_fwd_returns(conn: sqlite3.Connection, horizon: int = 5) -> pd.DataFrame:
    bars = pd.read_sql_query(
        """SELECT symbol, trade_date, json_extract(payload_json,'$.close') AS close
           FROM versioned_market_bars WHERE active=1 AND interval='1d' ORDER BY symbol, trade_date""",
        conn,
    )
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars["close"] = pd.to_numeric(bars["close"], errors="coerce")
    bars = bars.dropna(subset=["close"]).sort_values(["symbol", "trade_date"])
    bars["fwd_ret"] = bars.groupby("symbol")["close"].shift(-horizon) / bars["close"] - 1.0
    bars["d"] = bars["trade_date"].dt.normalize()
    return bars[["symbol", "d", "fwd_ret"]]


class TextDS(Dataset):
    def __init__(self, texts, labels, tok, maxlen):
        self.texts, self.labels, self.tok, self.maxlen = texts, labels, tok, maxlen

    def __len__(self):
        return len(self.texts)

    def __getitem__(self, i):
        e = self.tok(self.texts[i], truncation=True, padding="max_length", max_length=self.maxlen, return_tensors="pt")
        return {k: v.squeeze(0) for k, v in e.items()}, int(self.labels[i])


def label_from_ret(ret, pos_thr=0.02, neg_thr=-0.02):
    if pd.isna(ret):
        return 1  # neutral
    if ret > pos_thr:
        return 2  # positive
    if ret < neg_thr:
        return 0  # negative
    return 1  # neutral


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="/root/bert-base-chinese")
    p.add_argument("--epochs", type=int, default=2)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--max-length", type=int, default=128)
    p.add_argument("--lr", type=float, default=2e-5)
    p.add_argument("--horizon", type=int, default=5)
    p.add_argument("--device", default=None)
    p.add_argument("--max-train", type=int, default=20000, help="cap train texts for speed")
    return p.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = parse_args()
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    log.info("device=%s", device)
    conn = sqlite3.connect(str(DB), timeout=60.0)
    txt = load_texts(conn)
    fwd = load_fwd_returns(conn, args.horizon)
    conn.close()
    if txt.empty:
        log.error("no texts"); return 1
    # attach forward return to each text (per-symbol asof: text date -> latest bar at/ before text date)
    txt = txt.sort_values(["symbol", "d"])
    fwd = fwd.sort_values(["symbol", "d"])
    parts = []
    for s, sub in txt.groupby("symbol", sort=False):
        fsub = fwd[fwd["symbol"] == s].drop(columns=["symbol"])
        if fsub.empty:
            parts.append(sub.assign(fwd_ret=np.nan)); continue
        parts.append(pd.merge_asof(sub, fsub, on="d", direction="backward"))
    txt = pd.concat(parts, ignore_index=True)
    txt["label"] = txt["fwd_ret"].apply(label_from_ret)
    log.info("label dist: %s", txt["label"].value_counts().to_dict())
    # time split: 80% by date (cutoff on text date)
    cut_date = txt["d"].quantile(0.8)
    train = txt[txt["d"] <= cut_date].copy()
    hold = txt[txt["d"] > cut_date].copy()
    if args.max_train and len(train) > args.max_train:
        train = train.sample(args.max_train, random_state=42)
    log.info("train=%d (cut=%s) hold=%d", len(train), cut_date, len(hold))

    from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup
    tok = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(args.model, num_labels=3).to(device)
    # class-balanced loss weights (neutral dominates)
    counts = train["label"].value_counts().to_dict()
    w = torch.tensor([1.0 / max(counts.get(i, 1), 1) for i in range(3)], dtype=torch.float, device=device)
    w = w / w.sum()
    loss_fn = torch.nn.CrossEntropyLoss(weight=w)
    ds = TextDS(train["text"].tolist(), train["label"].tolist(), tok, args.max_length)
    dl = DataLoader(ds, batch_size=args.batch_size, shuffle=True, num_workers=2)
    total = len(dl) * args.epochs
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
    sched = get_linear_schedule_with_warmup(opt, int(0.1 * total), total)
    scaler = torch.amp.GradScaler("cuda", enabled=(device == "cuda"))
    model.train()
    step = 0
    for ep in range(args.epochs):
        for b in dl:
            b_in, b_lab = b
            b_in = {k: v.to(device) for k, v in b_in.items()}
            b_lab = b_lab.to(device)
            opt.zero_grad()
            with torch.amp.autocast("cuda", enabled=(device == "cuda")):
                out = model(**b_in).logits
                loss = loss_fn(out, b_lab)
            scaler.scale(loss).backward(); scaler.step(opt); scaler.update(); sched.step()
            step += 1
            if step % 50 == 0:
                log.info("ep %d step %d/%d loss=%.4f", ep, step, total, loss.item())
    # predict sentiment probs for ALL texts
    model.eval()
    all_texts = txt["text"].tolist()
    probs = np.zeros((len(all_texts), 3), dtype=np.float32)
    inf_ds = TextDS(all_texts, [0] * len(all_texts), tok, args.max_length)
    inf_dl = DataLoader(inf_ds, batch_size=args.batch_size, shuffle=False, num_workers=2)
    i = 0
    with torch.no_grad():
        for b in inf_dl:
            b_in, _ = b
            b_in = {k: v.to(device) for k, v in b_in.items()}
            with torch.amp.autocast("cuda", enabled=(device == "cuda")):
                lg = model(**b_in).logits
            p = torch.softmax(lg.float(), dim=-1).cpu().numpy()
            n = p.shape[0]
            probs[i:i + n] = p; i += n
            if i % (args.batch_size * 20) == 0:
                log.info("inferred %d/%d", i, len(all_texts))
    df = txt[["symbol", "d"]].copy()
    df["pred"] = probs.argmax(axis=1)
    df["s_pos"] = probs[:, 2]; df["s_neg"] = probs[:, 0]; df["s_neu"] = probs[:, 1]
    df["s_score"] = df["s_pos"] - df["s_neg"]
    df["s_vol"] = 1.0
    # label-accuracy sanity (train-period = in-sample-ish; hold = out-of-sample)
    is_train = txt["d"].values <= np.datetime64(cut_date)
    lab = txt["label"].values
    tr_acc = float((df["pred"].values[is_train] == lab[is_train]).mean()) if is_train.any() else float("nan")
    ho_acc = float((df["pred"].values[~is_train] == lab[~is_train]).mean()) if (~is_train).any() else float("nan")
    log.info("label-acc train(in-sample)=%.3f hold(out-of-sample)=%.3f", tr_acc, ho_acc)
    # aggregate per (symbol, date): mean score/probs + count
    agg = df.groupby(["symbol", "d"], as_index=False).agg(
        s_score=("s_score", "mean"), s_pos=("s_pos", "mean"), s_neg=("s_neg", "mean"),
        s_neu=("s_neu", "mean"), s_vol=("s_vol", "sum"))
    agg = agg.rename(columns={"d": "trade_date"})
    agg["trade_date"] = pd.to_datetime(agg["trade_date"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    agg.to_parquet(OUT, index=False)
    log.info("wrote %s: %d (symbol,date) rows, cols=%s", OUT, len(agg), list(agg.columns))
    print({"status": "ok", "n_texts": len(txt), "n_train": len(train), "n_hold": len(hold),
           "n_symbol_date": len(agg), "out": str(OUT), "label_dist": counts,
           "train_acc": round(tr_acc, 3), "hold_acc": round(ho_acc, 3)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
