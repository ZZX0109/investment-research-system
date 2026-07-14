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

import { now, version } from "./shared";

const demoUser: User = {
  id: "d0a1f17f-8d70-4a9d-8f05-6d6d1cfca001",
  email: "demo@investment-research.local",
  display_name: "Demo Investor",
  auth_subject: "user:demo-investor",
  status: "active",
  version,
  provenance: {
    data_mode: "demo",
    source_type: "synthetic",
    source_name: "demo-mode",
    observed_at: now,
    confidence: 1
  },
  created_at: now,
  updated_at: now
};

const demoAsset: Asset = {
  id: "c2d1e17b-fb31-4f4f-b5fa-c72dbcf93001",
  ticker: "NVDA",
  name: "NVIDIA Corporation",
  asset_type: "equity",
  currency: "USD",
  exchange: "NASDAQ",
  status: "active",
  version,
  provenance: {
    data_mode: "demo",
    source_type: "synthetic",
    source_name: "demo-seed-v2",
    observed_at: now,
    confidence: 0.84
  },
  created_at: now,
  updated_at: now
};

const demoPosition: Position = {
  id: "83d61a62-98c7-438e-bf0f-65b4058b6001",
  user_id: demoUser.id,
  asset_id: demoAsset.id,
  quantity: 24,
  cost_basis: 119.4,
  opened_at: "2026-06-01T00:00:00.000Z",
  status: "active",
  version,
  provenance: {
    data_mode: "demo",
    source_type: "manual_override",
    source_name: "portfolio-seed",
    observed_at: now,
    confidence: 1
  },
  created_at: now,
  updated_at: now
};

const demoWatchlist: Watchlist = {
  id: "c6ecb4b0-4fe5-48fd-b465-81fe1e1eb001",
  user_id: demoUser.id,
  name: "AI Compounders",
  asset_ids: [demoAsset.id],
  status: "active",
  version,
  provenance: {
    data_mode: "demo",
    source_type: "synthetic",
    source_name: "demo-seed-v2",
    observed_at: now,
    confidence: 1
  },
  created_at: now,
  updated_at: now
};

const demoPriceSeries: PriceSeries = {
  id: "88a3d72f-92d4-4d87-95af-60b6c21b3001",
  asset_id: demoAsset.id,
  interval: "1d",
  status: "active",
  version,
  provenance: {
    data_mode: "demo",
    source_type: "backfilled",
    source_name: "demo-prices-v2",
    observed_at: now,
    confidence: 0.86
  },
  created_at: now,
  updated_at: now,
  points: [
    {
      id: "4fbe4fbb-9691-48bf-840f-2e517cd4e001",
      asset_id: demoAsset.id,
      timestamp: "2026-07-01T00:00:00.000Z",
      open: 141.2,
      high: 144.7,
      low: 139.8,
      close: 143.9,
      volume: 1810000,
      status: "active",
      version,
      provenance: {
        data_mode: "demo",
        source_type: "backfilled",
        source_name: "demo-prices-v2",
        observed_at: "2026-07-01T00:00:00.000Z",
        confidence: 0.86
      },
      created_at: now,
      updated_at: now
    },
    {
      id: "b849a570-8c2c-4094-a4de-6b22d22f9001",
      asset_id: demoAsset.id,
      timestamp: "2026-07-02T00:00:00.000Z",
      open: 144.1,
      high: 147.6,
      low: 143.2,
      close: 146.8,
      volume: 2190000,
      status: "active",
      version,
      provenance: {
        data_mode: "demo",
        source_type: "backfilled",
        source_name: "demo-prices-v2",
        observed_at: "2026-07-02T00:00:00.000Z",
        confidence: 0.86
      },
      created_at: now,
      updated_at: now
    }
  ]
};

const demoEvidence: Evidence[] = [
  {
    id: "b3b5a652-b2c8-4ac2-bb10-72b2981ca001",
    asset_id: demoAsset.id,
    evidence_type: "research_note",
    title: "Demand stack remains full",
    summary: "Demo analyst note says hyperscaler orders remain resilient into the next two quarters.",
    source_url: "https://demo.investment-research.local/evidence/nvda-demand",
    collected_at: now,
    related_ids: [],
    status: "active",
    version,
    provenance: {
      data_mode: "demo",
      source_type: "synthetic",
      source_name: "sandbox-analyst",
      observed_at: now,
      confidence: 0.74
    },
    created_at: now,
    updated_at: now
  },
  {
    id: "762d9830-45ec-44ac-8f89-6d79b8d43001",
    asset_id: demoAsset.id,
    evidence_type: "market_data",
    title: "Price momentum still positive",
    summary: "Backfilled path shows higher highs and stable volume participation.",
    source_url: null,
    collected_at: now,
    related_ids: [],
    status: "active",
    version,
    provenance: {
      data_mode: "demo",
      source_type: "backfilled",
      source_name: "demo-prices-v2",
      observed_at: now,
      confidence: 0.81
    },
    created_at: now,
    updated_at: now
  }
];

const demoBundle: AnalysisBundle = {
  asset: demoAsset,
  run: {
    id: "fe8a98f4-1a46-4aa3-9264-f4378a650001",
    asset_id: demoAsset.id,
    triggered_by: demoUser.auth_subject,
    input_snapshot_ref: "sqlite://analysis-snapshots/fe8a98f4-1a46-4aa3-9264-f4378a650001",
    input_snapshot_hash: "demo-run-snapshot-hash",
    model_version: "heuristic-trend-ensemble@2026.07.0",
    reasoning_steps: [
      "resolve_intake_sources",
      "freeze_snapshot",
      "score_prediction",
      "evaluate_risk",
      "apply_judge_gate",
      "emit_recommendation"
    ],
    data_mode: "demo",
    provider: "demo-seed-market-provider@1.0.0 | demo-seed-evidence-provider@1.0.0",
    as_of: "2026-07-02T00:00:00.000Z",
    overrides: ["Demo mode is presentation-only and should not produce live investment advice."],
    synthetic_ratio: 0.67,
    report_version: "auto-1.0.0",
    evidence_ids: demoEvidence.map((entry) => entry.id),
    prediction_ids: ["f5ef7b88-40e8-4e8b-85d6-4c61f8fc8001"],
    risk_conclusion_ids: ["0234b0d6-5c91-4742-aa33-d9d58fd9f001"],
    recommendation_ids: ["4264db29-6fab-4603-b356-e167e3fa1001"],
    report_ids: ["13b3e6a9-d3de-477f-a38a-0145bf4ef001"],
    judge_score_ids: ["d0f48ad3-5d72-4d7c-a29f-a3c6ee5da001"],
    status: "active",
    version,
    provenance: {
      data_mode: "demo",
      source_type: "synthetic",
      source_name: "analysis-pipeline-demo",
      observed_at: now,
      confidence: 0.78
    },
    created_at: now,
    updated_at: now
  },
  snapshot: {
    asset_id: demoAsset.id,
    captured_at: now,
    mode: "demo",
    provider: "demo-seed-market-provider@1.0.0 | demo-seed-evidence-provider@1.0.0",
    as_of: "2026-07-02T00:00:00.000Z",
    overrides: ["Demo mode is presentation-only and should not produce live investment advice."],
    synthetic_ratio: 0.67,
    data_modes: ["demo"],
    source_types: ["backfilled", "synthetic"],
    intake_strategy: "seeded_demo_bundle",
    price_provider_name: "demo-seed-market-provider",
    price_provider_version: "1.0.0",
    price_provider_status: "seeded",
    evidence_provider_name: "demo-seed-evidence-provider",
    evidence_provider_version: "1.0.0",
    evidence_provider_status: "seeded",
    fallback_reasons: ["Demo mode is presentation-only and should not produce live investment advice."],
    latest_close: 146.8,
    latest_price_timestamp: "2026-07-02T00:00:00.000Z",
    price_freshness_status: "fresh",
    evidence_freshness_status: "fresh",
    refresh_recommendation: "fresh_enough_for_current_mode",
    stale_reasons: [],
    evidence_citation_ids: demoEvidence.map((entry) => entry.id),
    evidence_ids: demoEvidence.map((entry) => entry.id),
    synthetic_share: 0.67,
    real_share: 0,
    source_meta: {
      mode: "demo",
      provider: "demo-seed-market-provider@1.0.0 | demo-seed-evidence-provider@1.0.0",
      as_of: "2026-07-02T00:00:00.000Z",
      overrides: ["Demo mode is presentation-only and should not produce live investment advice."],
      synthetic_ratio: 0.67
    }
  },
  source_meta: {
    mode: "demo",
    provider: "demo-seed-market-provider@1.0.0 | demo-seed-evidence-provider@1.0.0",
    as_of: "2026-07-02T00:00:00.000Z",
    overrides: ["Demo mode is presentation-only and should not produce live investment advice."],
    synthetic_ratio: 0.67
  },
  evidence: demoEvidence,
  predictions: [
    {
      id: "f5ef7b88-40e8-4e8b-85d6-4c61f8fc8001",
      asset_id: demoAsset.id,
      analysis_run_id: "fe8a98f4-1a46-4aa3-9264-f4378a650001",
      model_name: "heuristic-trend-ensemble",
      model_version: "2026.07.0",
      horizon: "90d",
      signal: "outperform",
      confidence: 0.63,
      rationale: "Improving price path is visible, but confidence is capped by synthetic-data dominance.",
      risk_probability: 0.58,
      model_status: "demo_seed",
      feature_coverage: 0.62,
      missing_features: ["benchmark_ret_20d", "sector_ret_20d", "style_ret_20d"],
      deployment_approved: false,
      manifest_version: "demo-seed-v1",
      target_name: "future_max_drawdown_20d",
      inference_warnings: ["Demo prediction is seeded synthetic output and is not approved for deployment."],
      status: "active",
      version,
      provenance: {
        data_mode: "demo",
        source_type: "synthetic",
        source_name: "analysis-pipeline-demo",
        observed_at: now,
        confidence: 0.78
      },
      created_at: now,
      updated_at: now
    }
  ],
  risk_conclusions: [
    {
      id: "0234b0d6-5c91-4742-aa33-d9d58fd9f001",
      asset_id: demoAsset.id,
      analysis_run_id: "fe8a98f4-1a46-4aa3-9264-f4378a650001",
      risk_level: "high",
      summary: "Synthetic share remains above the gate, so this run is suitable for demoing flow, not for real capital decisions.",
      evidence_ids: demoEvidence.map((entry) => entry.id),
      stale_after: "2026-07-09T00:00:00.000Z",
      status: "active",
      version,
      provenance: {
        data_mode: "demo",
        source_type: "synthetic",
        source_name: "analysis-pipeline-demo",
        observed_at: now,
        confidence: 0.78
      },
      created_at: now,
      updated_at: now
    }
  ],
  recommendations: [
    {
      id: "4264db29-6fab-4603-b356-e167e3fa1001",
      asset_id: demoAsset.id,
      analysis_run_id: "fe8a98f4-1a46-4aa3-9264-f4378a650001",
      action: "hold",
      conviction: 0.51,
      reasoning: "Judge gate prevents stronger action because the evidence stack is still mostly synthetic.",
      guardrails: ["Require live market confirmation before upgrading to buy."],
      status: "active",
      version,
      provenance: {
        data_mode: "demo",
        source_type: "synthetic",
        source_name: "analysis-pipeline-demo",
        observed_at: now,
        confidence: 0.78
      },
      created_at: now,
      updated_at: now
    }
  ],
  judge_scores: [
    {
      id: "d0f48ad3-5d72-4d7c-a29f-a3c6ee5da001",
      analysis_run_id: "fe8a98f4-1a46-4aa3-9264-f4378a650001",
      score: 0.58,
      verdict: "warn",
      gating_reasons: ["Synthetic data share exceeds 50%", "No real-market confirmation attached"],
      status: "active",
      version,
      provenance: {
        data_mode: "demo",
        source_type: "synthetic",
        source_name: "analysis-pipeline-demo",
        observed_at: now,
        confidence: 0.78
      },
      created_at: now,
      updated_at: now
    }
  ],
  reports: [
    {
      id: "13b3e6a9-d3de-477f-a38a-0145bf4ef001",
      asset_id: demoAsset.id,
      analysis_run_id: "fe8a98f4-1a46-4aa3-9264-f4378a650001",
      title: "NVDA Demo Analysis Report",
      thesis: "The system can narrate upside and caveats from a fixed run without hiding synthetic support.",
      evidence_ids: demoEvidence.map((entry) => entry.id),
      report_version: "auto-1.0.0",
      body_markdown:
        "# NVDA Analysis Run\n\n- Run ID: `fe8a98f4-1a46-4aa3-9264-f4378a650001`\n- Data modes: demo\n- Gating reasons: Synthetic data share exceeds 50%, No real-market confirmation attached",
      status: "active",
      version,
      provenance: {
        data_mode: "demo",
        source_type: "synthetic",
        source_name: "analysis-pipeline-demo",
        observed_at: now,
        confidence: 0.78
      },
      created_at: now,
      updated_at: now
    }
  ]
};

const demoHistoricalBundle: AnalysisBundle = {
  ...demoBundle,
  run: {
    ...demoBundle.run,
    id: "09c5233b-a4dc-4d8d-908f-cd7c7c9b2001",
    input_snapshot_ref: "sqlite://analysis-snapshots/09c5233b-a4dc-4d8d-908f-cd7c7c9b2001",
    input_snapshot_hash: "demo-run-snapshot-hash-v0",
    prediction_ids: ["4dcf1ff8-3a9e-4881-8b6c-86e0ae6da001"],
    risk_conclusion_ids: ["3f13b499-4c86-41bd-80ce-2802dd1e2001"],
    recommendation_ids: ["8cd65632-d8df-4722-a6c0-d9265d95d001"],
    report_ids: ["cc0f7d1a-2811-423f-97f4-e5e7c8a29001"],
    judge_score_ids: ["f16c3d07-1550-485c-b1c4-0c4b3b2e5001"],
    provenance: {
      ...demoBundle.run.provenance,
      observed_at: "2026-06-28T10:00:00.000Z",
      confidence: 0.74
    },
    as_of: "2026-07-01T00:00:00.000Z",
    overrides: [
      "Demo mode is presentation-only and should not produce live investment advice.",
      "Older seeded run preserved for report comparison and workflow playback."
    ],
    synthetic_ratio: 0.72,
    report_version: "auto-0.9.0",
    created_at: "2026-06-28T10:00:00.000Z",
    updated_at: "2026-06-28T10:00:00.000Z"
  },
  snapshot: {
    ...demoBundle.snapshot,
    captured_at: "2026-06-28T10:00:00.000Z",
    as_of: "2026-07-01T00:00:00.000Z",
    overrides: [
      "Demo mode is presentation-only and should not produce live investment advice.",
      "Older seeded run preserved for report comparison and workflow playback."
    ],
    synthetic_ratio: 0.72,
    fallback_reasons: [
      "Demo mode is presentation-only and should not produce live investment advice.",
      "Older seeded run preserved for report comparison and workflow playback."
    ],
    latest_close: 143.9,
    latest_price_timestamp: "2026-07-01T00:00:00.000Z",
    synthetic_share: 0.72,
    real_share: 0,
    source_meta: {
      mode: "demo",
      provider: "demo-seed-market-provider@1.0.0 | demo-seed-evidence-provider@1.0.0",
      as_of: "2026-07-01T00:00:00.000Z",
      overrides: [
        "Demo mode is presentation-only and should not produce live investment advice.",
        "Older seeded run preserved for report comparison and workflow playback."
      ],
      synthetic_ratio: 0.72
    }
  },
  source_meta: {
    mode: "demo",
    provider: "demo-seed-market-provider@1.0.0 | demo-seed-evidence-provider@1.0.0",
    as_of: "2026-07-01T00:00:00.000Z",
    overrides: [
      "Demo mode is presentation-only and should not produce live investment advice.",
      "Older seeded run preserved for report comparison and workflow playback."
    ],
    synthetic_ratio: 0.72
  },
  predictions: demoBundle.predictions.map((prediction) => ({
    ...prediction,
    id: "4dcf1ff8-3a9e-4881-8b6c-86e0ae6da001",
    analysis_run_id: "09c5233b-a4dc-4d8d-908f-cd7c7c9b2001",
    model_version: "2026.06.4",
    signal: "hold",
    confidence: 0.57,
    rationale: "Earlier seeded run carried the same synthetic caveat with slightly weaker price momentum.",
    risk_probability: 0.61,
    feature_coverage: 0.58,
    inference_warnings: [
      "Historical demo prediction is frozen synthetic output and is not approved for deployment."
    ],
    provenance: {
      ...prediction.provenance,
      observed_at: "2026-06-28T10:00:00.000Z",
      confidence: 0.74
    },
    created_at: "2026-06-28T10:00:00.000Z",
    updated_at: "2026-06-28T10:00:00.000Z"
  })),
  risk_conclusions: demoBundle.risk_conclusions.map((risk) => ({
    ...risk,
    id: "3f13b499-4c86-41bd-80ce-2802dd1e2001",
    analysis_run_id: "09c5233b-a4dc-4d8d-908f-cd7c7c9b2001",
    summary: "Historical demo run kept the same synthetic gate and a slightly lower confidence ceiling.",
    stale_after: "2026-07-05T00:00:00.000Z",
    provenance: {
      ...risk.provenance,
      observed_at: "2026-06-28T10:00:00.000Z",
      confidence: 0.74
    },
    created_at: "2026-06-28T10:00:00.000Z",
    updated_at: "2026-06-28T10:00:00.000Z"
  })),
  recommendations: demoBundle.recommendations.map((recommendation) => ({
    ...recommendation,
    id: "8cd65632-d8df-4722-a6c0-d9265d95d001",
    analysis_run_id: "09c5233b-a4dc-4d8d-908f-cd7c7c9b2001",
    conviction: 0.46,
    reasoning: "Earlier run remained a guarded hold because the demonstration bundle leaned even more heavily on synthetic support.",
    provenance: {
      ...recommendation.provenance,
      observed_at: "2026-06-28T10:00:00.000Z",
      confidence: 0.74
    },
    created_at: "2026-06-28T10:00:00.000Z",
    updated_at: "2026-06-28T10:00:00.000Z"
  })),
  judge_scores: demoBundle.judge_scores.map((judge) => ({
    ...judge,
    id: "f16c3d07-1550-485c-b1c4-0c4b3b2e5001",
    analysis_run_id: "09c5233b-a4dc-4d8d-908f-cd7c7c9b2001",
    score: 0.52,
    verdict: "warn",
    gating_reasons: ["Synthetic data share exceeds 50%", "Historical demo run retained for lineage playback"],
    provenance: {
      ...judge.provenance,
      observed_at: "2026-06-28T10:00:00.000Z",
      confidence: 0.74
    },
    created_at: "2026-06-28T10:00:00.000Z",
    updated_at: "2026-06-28T10:00:00.000Z"
  })),
  reports: demoBundle.reports.map((report) => ({
    ...report,
    id: "cc0f7d1a-2811-423f-97f4-e5e7c8a29001",
    analysis_run_id: "09c5233b-a4dc-4d8d-908f-cd7c7c9b2001",
    title: "NVDA Demo Analysis Report v0",
    report_version: "auto-0.9.0",
    thesis: "A prior immutable run keeps the same thesis family but with a weaker confidence profile for comparison.",
    body_markdown:
      "# NVDA Historical Analysis Run\n\n- Run ID: `09c5233b-a4dc-4d8d-908f-cd7c7c9b2001`\n- Data modes: demo\n- Note: older seeded run retained for fixed-run comparison",
    provenance: {
      ...report.provenance,
      observed_at: "2026-06-28T10:00:00.000Z",
      confidence: 0.74
    },
    created_at: "2026-06-28T10:00:00.000Z",
    updated_at: "2026-06-28T10:00:00.000Z"
  }))
};

const demoBundles: AnalysisBundle[] = [demoBundle, demoHistoricalBundle];

const demoAudit: AuditRecord[] = [
  {
    id: "6687208d-75fa-474c-90fb-dc793f690001",
    actor: demoUser.auth_subject,
    action: "analysis-run.created",
    target_type: "analysis_run",
    target_id: demoBundle.run.id,
    details: { asset_id: demoAsset.id, evidence_count: String(demoEvidence.length) },
    status: "active",
    version,
    provenance: {
      data_mode: "demo",
      source_type: "manual_override",
      source_name: "audit-log",
      observed_at: now,
      confidence: 1
    },
    created_at: now,
    updated_at: now
  },
  {
    id: "c90d597e-d553-42ce-9895-5b9af3519001",
    actor: demoUser.auth_subject,
    action: "report.generated",
    target_type: "research_report",
    target_id: demoBundle.reports[0].id,
    details: { asset_id: demoAsset.id, analysis_run_id: demoBundle.run.id },
    status: "active",
    version,
    provenance: {
      data_mode: "demo",
      source_type: "manual_override",
      source_name: "audit-log",
      observed_at: now,
      confidence: 1
    },
    created_at: now,
    updated_at: now
  },
  {
    id: "c5e1a9de-0898-4fbb-b66f-7f79190e1001",
    actor: demoUser.auth_subject,
    action: "analysis-run.created",
    target_type: "analysis_run",
    target_id: demoHistoricalBundle.run.id,
    details: { asset_id: demoAsset.id, evidence_count: String(demoEvidence.length) },
    status: "active",
    version,
    provenance: {
      data_mode: "demo",
      source_type: "manual_override",
      source_name: "audit-log",
      observed_at: "2026-06-28T10:00:00.000Z",
      confidence: 1
    },
    created_at: "2026-06-28T10:00:00.000Z",
    updated_at: "2026-06-28T10:00:00.000Z"
  }
];

const demoCatalog: DomainCatalog = {
  entities: [
    "User",
    "Asset",
    "Position",
    "Watchlist",
    "PricePoint",
    "PriceSeries",
    "Evidence",
    "ResearchReport",
    "ModelPrediction",
    "RiskConclusion",
    "InvestmentRecommendation",
    "AuditRecord",
    "JudgeScore",
    "AnalysisRun"
  ],
  data_modes: ["demo", "sandbox", "real"],
  data_source_types: ["real", "synthetic", "backfilled", "manual_override"],
  mode_policies: [
    {
      data_mode: "demo",
      allowed_source_types: ["synthetic", "backfilled", "manual_override"],
      description: "Stable presentation mode backed by fixed synthetic and backfilled records.",
      judge_gate_reason: "Demo mode is presentation-only and should not produce live investment advice."
    },
    {
      data_mode: "sandbox",
      allowed_source_types: ["synthetic", "backfilled", "manual_override"],
      description: "Synthetic experimentation mode for testing, training, and regression coverage.",
      judge_gate_reason: "Sandbox mode is intended for testing and training, not real-money recommendations."
    },
    {
      data_mode: "real",
      allowed_source_types: ["real", "backfilled", "manual_override"],
      description: "User-facing mode for real-market workflows with traceable live or operator-managed inputs.",
      judge_gate_reason: null
    }
  ],
  analysis_provider_config: {
    market_data_provider: "persisted_fallback",
    evidence_provider: "persisted_fallback"
  },
  analysis_providers: [
    { provider_name: "demo-seed-market-provider", provider_version: "1.0.0", kind: "market_data" },
    { provider_name: "demo-seed-evidence-provider", provider_version: "1.0.0", kind: "evidence" }
  ],
  principles: [
    "Every domain object carries status, schema version, entity version, and provenance.",
    "Reports are generated from immutable analysis runs rather than mutable current state.",
    "Synthetic and real data remain visible to users across the full chain."
  ]
};

export function getDemoSession(): AuthResponse {
  return {
    user: demoUser,
    access_expires_at: "2026-07-04T00:00:00.000Z",
    refresh_expires_at: "2026-07-10T00:00:00.000Z"
  };
}

export function getDemoAssets(): Asset[] {
  return [demoAsset];
}

export function getDemoPositions(): Position[] {
  return [demoPosition];
}

export function getDemoWatchlists(): Watchlist[] {
  return [demoWatchlist];
}

export function getDemoPriceSeries(assetId: string): PriceSeries[] {
  return assetId === demoAsset.id ? [demoPriceSeries] : [];
}

export function getDemoEvidence(assetId: string): Evidence[] {
  return assetId === demoAsset.id ? demoEvidence : [];
}

export function getDemoReports(assetId: string) {
  return assetId === demoAsset.id ? demoBundles.flatMap((bundle) => bundle.reports) : [];
}

export function getDemoAnalysisRuns(assetId: string) {
  return assetId === demoAsset.id ? demoBundles.map((bundle) => bundle.run) : [];
}

export function getDemoBundle(assetId?: string, runId?: string): AnalysisBundle {
  const bundle = runId ? demoBundles.find((entry) => entry.run.id === runId) ?? demoBundle : demoBundle;
  if (!assetId || assetId === demoAsset.id) {
    return bundle;
  }
  return {
    ...bundle,
    asset: { ...bundle.asset, id: assetId },
    run: { ...bundle.run, asset_id: assetId },
    snapshot: { ...bundle.snapshot, asset_id: assetId }
  };
}

export function getDemoAuditRecords() {
  return demoAudit;
}

export function getDemoCatalog(): DomainCatalog {
  return demoCatalog;
}
