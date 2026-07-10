from __future__ import annotations

try:
    import torch
    from torch import nn
except Exception:  # pragma: no cover
    torch = None
    nn = None


if nn is not None:
    class ITransformerLite(nn.Module):
        def __init__(self, window_size: int, d_model: int = 128, classes: int = 3):
            super().__init__()
            self.proj = nn.Linear(window_size, d_model)
            layer = nn.TransformerEncoderLayer(d_model=d_model, nhead=4, dim_feedforward=256, dropout=0.1, batch_first=True)
            self.encoder = nn.TransformerEncoder(layer, num_layers=2)
            self.regime = nn.Linear(d_model, classes)
            self.drawdown = nn.Linear(d_model, 3)
            self.volatility = nn.Linear(d_model, 2)

        def forward(self, x):
            x = x.transpose(1, 2)
            h = self.encoder(self.proj(x)).mean(dim=1)
            return {"regime": self.regime(h), "drawdown": self.drawdown(h), "volatility": self.volatility(h)}

