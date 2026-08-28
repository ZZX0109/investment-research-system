#!/usr/bin/env python3
"""BERT feature-extraction sentiment encoder (lightweight transfer learning — NO fine-tune).

Uses pre-trained ``bert-base-chinese`` (frozen) to encode financial text into
[CLS] 768-dim vectors.  Two text sources are encoded and pooled per (symbol, date):

  * sentiment_news  : recent news (title + content)          — recent tail only
  * event_notice    : historical announcement titles (2020+) — full history

For each (symbol, date) the CLS vectors of all texts that day are mean-pooled
into a single 768-dim sentiment vector.  Output parquet (symbol, trade_date,
s_0..s_767) consumed by panel_eval.py via ``--sentiment-vectors``.

This is the user's "轻量档 (feature extraction, 迁移学习但轻)": pretrained
weights used as a feature extractor, no weight updates.  GPU-friendly (RTX 4090).

Usage:
    python3 scripts/encode_news_bert.py --sources news notice --batch-size 64
    python3 scripts/encode_news_bert.py --sources notice --max-length 128
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
OUT = PROJECT / "artifacts/sentiment_vectors/news_bert_cls.parquet"
log = logging.getLogger("bert_encode")


def load_texts(conn: sqlite3.Connection, sources: list[str]) -> pd.DataFrame:
    frames = []
    if "news" in sources:
        try:
            df = pd.read_sql_query(
                "SELECT symbol, published_at, title, content FROM sentiment_news", conn
            )
            if not df.empty:
                df["d"] = pd.to_datetime(df["published_at"], errors="coerce")
                df = df.dropna(subset=["d"])
                df["d"] = df["d"].dt.tz_localize(None).dt.normalize()
                df["text"] = (df["title"].fillna("").astype(str) + "。" + df["content"].fillna("").astype(str).str.slice(0, 480))
                df = df[df["text"].str.len() > 2][["symbol", "d", "text"]]
                frames.append(df)
        except Exception as e:
            log.warning("news load: %s", e)
    if "notice" in sources:
        try:
            df = pd.read_sql_query(
                "SELECT symbol, notice_date, title FROM event_notice", conn
            )
            if not df.empty:
                df["d"] = pd.to_datetime(df["notice_date"], errors="coerce")
                df = df.dropna(subset=["d"])
                df["d"] = df["d"].dt.tz_localize(None).dt.normalize()
                df["text"] = df["title"].fillna("").astype(str)
                df = df[df["text"].str.len() > 2][["symbol", "d", "text"]]
                frames.append(df)
        except Exception as e:
            log.warning("notice load: %s", e)
    if not frames:
        return pd.DataFrame(columns=["symbol", "d", "text"])
    txt = pd.concat(frames, ignore_index=True)
    return txt


class TextDS(Dataset):
    def __init__(self, texts, tok, maxlen):
        self.texts = texts
        self.tok = tok
        self.maxlen = maxlen

    def __len__(self):
        return len(self.texts)

    def __getitem__(self, i):
        e = self.tok(self.texts[i], truncation=True, padding="max_length", max_length=self.maxlen, return_tensors="pt")
        return {k: v.squeeze(0) for k, v in e.items()}


def encode(texts: list[str], model_name: str, batch_size: int, maxlen: int, device: str) -> np.ndarray:
    from transformers import AutoModel, AutoTokenizer
    log.info("loading %s on %s ...", model_name, device)
    tok = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name).to(device).eval()
    ds = TextDS(texts, tok, maxlen)
    dl = DataLoader(ds, batch_size=batch_size, shuffle=False, num_workers=2)
    out = np.zeros((len(texts), 768), dtype=np.float32)
    i = 0
    with torch.no_grad():
        for b in dl:
            b = {k: v.to(device) for k, v in b.items()}
            with torch.amp.autocast("cuda", enabled=(device == "cuda")):
                hs = model(**b).last_hidden_state  # (B, L, H)
            cls = hs[:, 0, :].float().cpu().numpy()  # CLS token
            n = cls.shape[0]
            out[i:i + n] = cls
            i += n
            if i % (batch_size * 20) == 0:
                log.info("encoded %d/%d", i, len(texts))
    return out


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--sources", nargs="+", choices=["news", "notice"], default=["news", "notice"])
    p.add_argument("--model", default="bert-base-chinese")
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--max-length", type=int, default=128)
    p.add_argument("--device", default=None)
    return p.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = parse_args()
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    log.info("device=%s", device)
    conn = sqlite3.connect(str(DB), timeout=60.0)
    txt = load_texts(conn, args.sources)
    conn.close()
    if txt.empty:
        log.error("no texts to encode")
        return 1
    log.info("encoding %d texts across %d symbols", len(txt), txt["symbol"].nunique())
    vecs = encode(txt["text"].tolist(), args.model, args.batch_size, args.max_length, device)
    df = txt[["symbol", "d"]].copy()
    df["d"] = pd.to_datetime(df["d"])
    vcols = ["s_" + str(i) for i in range(768)]
    vdf = pd.DataFrame(vecs, columns=vcols)
    df = pd.concat([df.reset_index(drop=True), vdf.reset_index(drop=True)], axis=1)
    # mean-pool per (symbol, date)
    agg = df.groupby(["symbol", "d"], as_index=False)[vcols].mean()
    agg = agg.rename(columns={"d": "trade_date"})
    agg["trade_date"] = pd.to_datetime(agg["trade_date"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    agg.to_parquet(OUT, index=False)
    log.info("wrote %s: %d (symbol,date) rows", OUT, len(agg))
    print({"status": "ok", "n_texts": len(txt), "n_symbol_date": len(agg), "dim": 768, "out": str(OUT)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
