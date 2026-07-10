from __future__ import annotations

try:
    import torch
    from torch import nn
except Exception:  # pragma: no cover
    torch = None
    nn = None


if nn is not None:
    class PatchTSTLite(nn.Module):
        def __init__(self, feature_dim: int, patch_len: int = 16, stride: int = 8, d_model: int = 128, classes: int = 3):
            super().__init__()
            self.patch_len = patch_len
            self.stride = stride
            self.proj = nn.Linear(feature_dim * patch_len, d_model)
            layer = nn.TransformerEncoderLayer(d_model=d_model, nhead=4, dim_feedforward=256, dropout=0.1, batch_first=True)
            self.encoder = nn.TransformerEncoder(layer, num_layers=3)
            self.regime = nn.Linear(d_model, classes)
            self.drawdown = nn.Linear(d_model, 3)
            self.volatility = nn.Linear(d_model, 2)

        def patches(self, x):
            chunks = []
            for start in range(0, x.shape[1] - self.patch_len + 1, self.stride):
                chunks.append(x[:, start : start + self.patch_len, :].reshape(x.shape[0], -1))
            return torch.stack(chunks, dim=1)

        def forward(self, x):
            h = self.proj(self.patches(x))
            h = self.encoder(h).mean(dim=1)
            return {"regime": self.regime(h), "drawdown": self.drawdown(h), "volatility": self.volatility(h)}

