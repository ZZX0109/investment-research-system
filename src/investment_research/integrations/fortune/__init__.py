"""fortune integration adapter package.

Mirrors wonglaitung/fortune ``data_services/`` (financial reports, northbound
flow, margin, dragon-tiger, regime) backed by akshare with graceful
degradation.  Adapters normalize to plain dicts the core pipeline
(``training/dataset.py`` fundamental_*, ``repository/market_observation``)
can consume directly.
"""
