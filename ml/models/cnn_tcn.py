from __future__ import annotations

try:
    import torch
    from torch import nn
except Exception:  # pragma: no cover
    torch = None
    nn = None


if nn is not None:
    class CNNTCNModel(nn.Module):
        def __init__(self, feature_dim: int, classes: int = 3):
            super().__init__()
            self.net = nn.Sequential(
                nn.Conv1d(feature_dim, 64, kernel_size=3, padding=1),
                nn.GELU(),
                nn.Conv1d(64, 128, kernel_size=5, padding=2),
                nn.GELU(),
                nn.Conv1d(128, 128, kernel_size=7, padding=3),
                nn.GELU(),
                nn.AdaptiveAvgPool1d(1),
            )
            self.regime = nn.Linear(128, classes)
            self.drawdown = nn.Linear(128, 3)
            self.volatility = nn.Linear(128, 2)

        def forward(self, x):
            x = x.transpose(1, 2)
            h = self.net(x).squeeze(-1)
            return {"regime": self.regime(h), "drawdown": self.drawdown(h), "volatility": self.volatility(h)}

