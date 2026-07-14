import type {
  AnalysisBundle,
  Asset,
  AuditRecord,
  AuthResponse,
  DomainCatalog,
  Evidence,
  Position,
  PriceSeries,
  User,
  Watchlist
} from "../types";

import {
  getDemoAssets,
  getDemoAuditRecords,
  getDemoBundle,
  getDemoCatalog,
  getDemoEvidence,
  getDemoPositions,
  getDemoPriceSeries,
  getDemoSession,
  getDemoWatchlists,
  getDemoAnalysisRuns
} from "./investmentDemo";

const demoUser = getDemoSession().user;
const demoAsset = getDemoAssets()[0];
const demoPosition = getDemoPositions()[0];
const demoWatchlist = getDemoWatchlists()[0];
const demoPriceSeries = getDemoPriceSeries(demoAsset.id)[0];
const demoEvidence = getDemoEvidence(demoAsset.id);
const demoBundle = getDemoBundle();
const demoHistoricalRunId = getDemoAnalysisRuns(demoAsset.id).find((run) => run.id !== demoBundle.run.id)?.id;
const demoHistoricalBundle = getDemoBundle(undefined, demoHistoricalRunId);

const sandboxUser: User = {
  ...demoUser,
  email: "sandbox@investment-research.local",
  display_name: "Sandbox Analyst",
  auth_subject: "user:sandbox-analyst",
  provenance: {
    ...demoUser.provenance,
    data_mode: "sandbox",
    source_name: "sandbox-mode"
  }
};

const sandboxAsset: Asset = {
  ...demoAsset,
  ticker: "AMD",
  name: "Advanced Micro Devices",
  provenance: {
    ...demoAsset.provenance,
    data_mode: "sandbox",
    source_name: "sandbox-seed-v1",
    confidence: 0.9
  }
};

const sandboxPosition: Position = {
  ...demoPosition,
  user_id: sandboxUser.id,
  asset_id: sandboxAsset.id,
  quantity: 42,
  cost_basis: 132.15,
  provenance: {
    ...demoPosition.provenance,
    data_mode: "sandbox",
    source_name: "sandbox-portfolio"
  }
};

const sandboxWatchlist: Watchlist = {
  ...demoWatchlist,
  user_id: sandboxUser.id,
  name: "Sandbox Semis",
  asset_ids: [sandboxAsset.id],
  provenance: {
    ...demoWatchlist.provenance,
    data_mode: "sandbox",
    source_name: "sandbox-seed-v1"
  }
};

const sandboxPriceSeries: PriceSeries = {
  ...demoPriceSeries,
  asset_id: sandboxAsset.id,
  provenance: {
    ...demoPriceSeries.provenance,
    data_mode: "sandbox",
    source_name: "sandbox-prices-v1",
    confidence: 0.91
  },
  points: demoPriceSeries.points.map((point, index) => ({
    ...point,
    asset_id: sandboxAsset.id,
    open: index === 0 ? 158.4 : 161.8,
    high: index === 0 ? 163.2 : 166.1,
    low: index === 0 ? 157.2 : 160.9,
    close: index === 0 ? 162.7 : 165.4,
    volume: index === 0 ? 2450000 : 2710000,
    provenance: {
      ...point.provenance,
      data_mode: "sandbox",
      source_name: "sandbox-prices-v1",
      confidence: 0.91
    }
  }))
};

const sandboxEvidence: Evidence[] = [
  {
    ...demoEvidence[0],
    asset_id: sandboxAsset.id,
    title: "Channel checks support accelerator demand",
    summary: "Sandbox analyst scenario keeps datacenter and PC recovery assumptions explicit for testing gating behavior.",
    source_url: "https://sandbox.investment-research.local/evidence/amd-demand",
    provenance: {
      ...demoEvidence[0].provenance,
      data_mode: "sandbox",
      source_name: "sandbox-analyst",
      confidence: 0.79
    }
  },
  {
    ...demoEvidence[1],
    asset_id: sandboxAsset.id,
    title: "Synthetic price path remains constructive",
    summary: "Backfilled sandbox path shows improving participation while remaining clearly marked as non-production data.",
    provenance: {
      ...demoEvidence[1].provenance,
      data_mode: "sandbox",
      source_name: "sandbox-prices-v1",
      confidence: 0.88
    }
  }
];

const sandboxBundle: AnalysisBundle = {
  ...demoBundle,
  asset: sandboxAsset,
  run: {
    ...demoBundle.run,
    asset_id: sandboxAsset.id,
    triggered_by: sandboxUser.auth_subject,
    data_mode: "sandbox",
    provider: "sandbox-seed-market-provider@1.0.0 | sandbox-seed-evidence-provider@1.0.0",
    as_of: "2026-07-03T00:00:00.000Z",
    overrides: ["Sandbox mode is intended for testing and training, not real-money recommendations."],
    synthetic_ratio: 0.34,
    provenance: {
      ...demoBundle.run.provenance,
      data_mode: "sandbox",
      source_name: "analysis-pipeline-sandbox",
      confidence: 0.82
    }
  },
  snapshot: {
    ...demoBundle.snapshot,
    asset_id: sandboxAsset.id,
    mode: "sandbox",
    provider: "sandbox-seed-market-provider@1.0.0 | sandbox-seed-evidence-provider@1.0.0",
    as_of: "2026-07-03T00:00:00.000Z",
    overrides: ["Sandbox mode is intended for testing and training, not real-money recommendations."],
    synthetic_ratio: 0.34,
    data_modes: ["sandbox"],
    intake_strategy: "seeded_sandbox_bundle",
    price_provider_name: "sandbox-seed-market-provider",
    price_provider_version: "1.0.0",
    price_provider_status: "seeded",
    evidence_provider_name: "sandbox-seed-evidence-provider",
    evidence_provider_version: "1.0.0",
    evidence_provider_status: "seeded",
    fallback_reasons: ["Sandbox mode is intended for testing and training, not real-money recommendations."],
    latest_close: 165.4,
    latest_price_timestamp: "2026-07-03T00:00:00.000Z",
    price_freshness_status: "fresh",
    evidence_freshness_status: "fresh",
    refresh_recommendation: "fresh_enough_for_current_mode",
    stale_reasons: [],
    evidence_citation_ids: sandboxEvidence.map((entry) => entry.id),
    evidence_ids: sandboxEvidence.map((entry) => entry.id),
    synthetic_share: 0.34,
    real_share: 0,
    source_meta: {
      mode: "sandbox",
      provider: "sandbox-seed-market-provider@1.0.0 | sandbox-seed-evidence-provider@1.0.0",
      as_of: "2026-07-03T00:00:00.000Z",
      overrides: ["Sandbox mode is intended for testing and training, not real-money recommendations."],
      synthetic_ratio: 0.34
    }
  },
  source_meta: {
    mode: "sandbox",
    provider: "sandbox-seed-market-provider@1.0.0 | sandbox-seed-evidence-provider@1.0.0",
    as_of: "2026-07-03T00:00:00.000Z",
    overrides: ["Sandbox mode is intended for testing and training, not real-money recommendations."],
    synthetic_ratio: 0.34
  },
  evidence: sandboxEvidence,
  predictions: demoBundle.predictions.map((prediction) => ({
    ...prediction,
    asset_id: sandboxAsset.id,
    confidence: 0.71,
    rationale: "Sandbox scenarios keep the trend positive while marking the result as synthetic and regression-safe.",
    risk_probability: 0.43,
    model_status: "sandbox_seed",
    feature_coverage: 0.76,
    missing_features: ["sector_ret_20d", "style_ret_20d"],
    deployment_approved: false,
    manifest_version: "sandbox-seed-v1",
    target_name: "future_max_drawdown_20d",
    inference_warnings: ["Sandbox prediction is regression fixture output and is not approved for deployment."],
    provenance: {
      ...prediction.provenance,
      data_mode: "sandbox",
      source_name: "analysis-pipeline-sandbox",
      confidence: 0.82
    }
  })),
  risk_conclusions: demoBundle.risk_conclusions.map((risk) => ({
    ...risk,
    asset_id: sandboxAsset.id,
    risk_level: "medium",
    summary: "Sandbox data is fresher and denser than demo mode, but it is still unsuitable for capital deployment without real confirmation.",
    evidence_ids: sandboxEvidence.map((entry) => entry.id),
    provenance: {
      ...risk.provenance,
      data_mode: "sandbox",
      source_name: "analysis-pipeline-sandbox",
      confidence: 0.82
    }
  })),
  recommendations: demoBundle.recommendations.map((recommendation) => ({
    ...recommendation,
    asset_id: sandboxAsset.id,
    action: "hold",
    conviction: 0.58,
    reasoning: "Sandbox mode can exercise the full workflow, but the recommendation stays non-actionable until real inputs are attached.",
    guardrails: ["Promote to Real Data Mode before using this run for live decisions."],
    provenance: {
      ...recommendation.provenance,
      data_mode: "sandbox",
      source_name: "analysis-pipeline-sandbox",
      confidence: 0.82
    }
  })),
  judge_scores: demoBundle.judge_scores.map((judge) => ({
    ...judge,
    score: 0.66,
    verdict: "warn",
    gating_reasons: ["Sandbox mode is intended for testing and training, not real-money recommendations."],
    provenance: {
      ...judge.provenance,
      data_mode: "sandbox",
      source_name: "analysis-pipeline-sandbox",
      confidence: 0.82
    }
  })),
  reports: demoBundle.reports.map((report) => ({
    ...report,
    asset_id: sandboxAsset.id,
    title: "AMD Sandbox Analysis Report",
    thesis: "Sandbox mode preserves the run-centric workflow while keeping synthetic assumptions visible end to end.",
    evidence_ids: sandboxEvidence.map((entry) => entry.id),
    body_markdown:
      "# AMD Sandbox Analysis Run\n\n- Data modes: sandbox\n- Gating reasons: Sandbox mode is intended for testing and training, not real-money recommendations",
    provenance: {
      ...report.provenance,
      data_mode: "sandbox",
      source_name: "analysis-pipeline-sandbox",
      confidence: 0.82
    }
  }))
};

const sandboxHistoricalBundle: AnalysisBundle = {
  ...demoHistoricalBundle,
  asset: sandboxAsset,
  run: {
    ...demoHistoricalBundle.run,
    id: "50fdc0f3-88e4-4ec8-9b85-ec6c103ca001",
    asset_id: sandboxAsset.id,
    triggered_by: sandboxUser.auth_subject,
    input_snapshot_ref: "sqlite://analysis-snapshots/50fdc0f3-88e4-4ec8-9b85-ec6c103ca001",
    input_snapshot_hash: "sandbox-run-snapshot-hash-v0",
    data_mode: "sandbox",
    provider: "sandbox-seed-market-provider@1.0.0 | sandbox-seed-evidence-provider@1.0.0",
    as_of: "2026-07-01T00:00:00.000Z",
    overrides: [
      "Sandbox mode is intended for testing and training, not real-money recommendations.",
      "Older sandbox run retained for report comparison and regression playback."
    ],
    synthetic_ratio: 0.4,
    provenance: {
      ...demoHistoricalBundle.run.provenance,
      data_mode: "sandbox",
      source_name: "analysis-pipeline-sandbox",
      confidence: 0.79
    }
  },
  snapshot: {
    ...demoHistoricalBundle.snapshot,
    asset_id: sandboxAsset.id,
    mode: "sandbox",
    provider: "sandbox-seed-market-provider@1.0.0 | sandbox-seed-evidence-provider@1.0.0",
    as_of: "2026-07-01T00:00:00.000Z",
    overrides: [
      "Sandbox mode is intended for testing and training, not real-money recommendations.",
      "Older sandbox run retained for report comparison and regression playback."
    ],
    synthetic_ratio: 0.4,
    data_modes: ["sandbox"],
    intake_strategy: "seeded_sandbox_bundle_history",
    price_provider_name: "sandbox-seed-market-provider",
    evidence_provider_name: "sandbox-seed-evidence-provider",
    fallback_reasons: [
      "Sandbox mode is intended for testing and training, not real-money recommendations.",
      "Older sandbox run retained for report comparison and regression playback."
    ],
    latest_close: 162.7,
    evidence_ids: sandboxEvidence.map((entry) => entry.id),
    synthetic_share: 0.4,
    source_meta: {
      mode: "sandbox",
      provider: "sandbox-seed-market-provider@1.0.0 | sandbox-seed-evidence-provider@1.0.0",
      as_of: "2026-07-01T00:00:00.000Z",
      overrides: [
        "Sandbox mode is intended for testing and training, not real-money recommendations.",
        "Older sandbox run retained for report comparison and regression playback."
      ],
      synthetic_ratio: 0.4
    }
  },
  source_meta: {
    mode: "sandbox",
    provider: "sandbox-seed-market-provider@1.0.0 | sandbox-seed-evidence-provider@1.0.0",
    as_of: "2026-07-01T00:00:00.000Z",
    overrides: [
      "Sandbox mode is intended for testing and training, not real-money recommendations.",
      "Older sandbox run retained for report comparison and regression playback."
    ],
    synthetic_ratio: 0.4
  },
  evidence: sandboxEvidence,
  predictions: demoHistoricalBundle.predictions.map((prediction) => ({
    ...prediction,
    asset_id: sandboxAsset.id,
    analysis_run_id: "50fdc0f3-88e4-4ec8-9b85-ec6c103ca001",
    provenance: {
      ...prediction.provenance,
      data_mode: "sandbox",
      source_name: "analysis-pipeline-sandbox",
      confidence: 0.79
    }
  })),
  risk_conclusions: demoHistoricalBundle.risk_conclusions.map((risk) => ({
    ...risk,
    asset_id: sandboxAsset.id,
    analysis_run_id: "50fdc0f3-88e4-4ec8-9b85-ec6c103ca001",
    provenance: {
      ...risk.provenance,
      data_mode: "sandbox",
      source_name: "analysis-pipeline-sandbox",
      confidence: 0.79
    }
  })),
  recommendations: demoHistoricalBundle.recommendations.map((recommendation) => ({
    ...recommendation,
    asset_id: sandboxAsset.id,
    analysis_run_id: "50fdc0f3-88e4-4ec8-9b85-ec6c103ca001",
    reasoning: "Older sandbox run remains preserved so the workflow can compare fixed outputs over time.",
    provenance: {
      ...recommendation.provenance,
      data_mode: "sandbox",
      source_name: "analysis-pipeline-sandbox",
      confidence: 0.79
    }
  })),
  judge_scores: demoHistoricalBundle.judge_scores.map((judge) => ({
    ...judge,
    analysis_run_id: "50fdc0f3-88e4-4ec8-9b85-ec6c103ca001",
    gating_reasons: ["Sandbox mode is intended for testing and training, not real-money recommendations."],
    provenance: {
      ...judge.provenance,
      data_mode: "sandbox",
      source_name: "analysis-pipeline-sandbox",
      confidence: 0.79
    }
  })),
  reports: demoHistoricalBundle.reports.map((report) => ({
    ...report,
    asset_id: sandboxAsset.id,
    analysis_run_id: "50fdc0f3-88e4-4ec8-9b85-ec6c103ca001",
    title: "AMD Sandbox Analysis Report v0",
    thesis: "Earlier sandbox report stays fixed so model and judge changes can be compared without mutating history.",
    provenance: {
      ...report.provenance,
      data_mode: "sandbox",
      source_name: "analysis-pipeline-sandbox",
      confidence: 0.79
    }
  }))
};

const sandboxBundles: AnalysisBundle[] = [sandboxBundle, sandboxHistoricalBundle];

const sandboxAudit: AuditRecord[] = getDemoAuditRecords().map((record) => ({
  ...record,
  actor: sandboxUser.auth_subject,
  target_id:
    record.target_id === demoBundle.run.id
      ? sandboxBundle.run.id
      : record.target_id === demoHistoricalBundle.run.id
        ? sandboxHistoricalBundle.run.id
        : record.target_id === demoBundle.reports[0].id
          ? sandboxBundle.reports[0].id
          : record.target_id,
  details: {
    ...record.details,
    asset_id: sandboxAsset.id,
    analysis_run_id:
      record.details.analysis_run_id === demoBundle.run.id
        ? sandboxBundle.run.id
        : record.details.analysis_run_id === demoHistoricalBundle.run.id
          ? sandboxHistoricalBundle.run.id
          : record.details.analysis_run_id,
    evidence_count: String(sandboxEvidence.length),
    mode: "sandbox"
  },
  provenance: {
    ...record.provenance,
    data_mode: "sandbox",
    source_name: "sandbox-audit-log"
  }
}));

const sandboxCatalog: DomainCatalog = {
  ...getDemoCatalog(),
  analysis_provider_config: {
    market_data_provider: "stub_realtime",
    evidence_provider: "stub"
  },
  analysis_providers: [
    { provider_name: "sandbox-seed-market-provider", provider_version: "1.0.0", kind: "market_data" },
    { provider_name: "sandbox-seed-evidence-provider", provider_version: "1.0.0", kind: "evidence" }
  ]
};

export function getSandboxSession(): AuthResponse {
  return {
    user: sandboxUser,
    access_expires_at: "2026-07-04T00:00:00.000Z",
    refresh_expires_at: "2026-07-10T00:00:00.000Z"
  };
}

export function getSandboxAssets(): Asset[] {
  return [sandboxAsset];
}

export function getSandboxPositions(): Position[] {
  return [sandboxPosition];
}

export function getSandboxWatchlists(): Watchlist[] {
  return [sandboxWatchlist];
}

export function getSandboxPriceSeries(assetId: string): PriceSeries[] {
  return assetId === sandboxAsset.id ? [sandboxPriceSeries] : [];
}

export function getSandboxEvidence(assetId: string): Evidence[] {
  return assetId === sandboxAsset.id ? sandboxEvidence : [];
}

export function getSandboxReports(assetId: string) {
  return assetId === sandboxAsset.id ? sandboxBundles.flatMap((bundle) => bundle.reports) : [];
}

export function getSandboxAnalysisRuns(assetId: string) {
  return assetId === sandboxAsset.id ? sandboxBundles.map((bundle) => bundle.run) : [];
}

export function getSandboxBundle(assetId?: string, runId?: string): AnalysisBundle {
  const bundle = runId ? sandboxBundles.find((entry) => entry.run.id === runId) ?? sandboxBundle : sandboxBundle;
  if (!assetId || assetId === sandboxAsset.id) {
    return bundle;
  }
  return {
    ...bundle,
    asset: { ...bundle.asset, id: assetId },
    run: { ...bundle.run, asset_id: assetId },
    snapshot: { ...bundle.snapshot, asset_id: assetId }
  };
}

export function getSandboxAuditRecords() {
  return sandboxAudit;
}

export function getSandboxCatalog(): DomainCatalog {
  return sandboxCatalog;
}
