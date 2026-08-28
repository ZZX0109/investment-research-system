"""Third-party project integration adapters.

Each external project (fortune, xystock, kittenCN) lives under its own
sub-package so its config/dependencies stay isolated from the core pipeline.
Adapters wrap live data fetches (akshare) with graceful degradation: a
network-gated environment degrades to ``status="network_unavailable"`` and
never crashes the research run, while a networked environment gets real data.
"""
