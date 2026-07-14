from investment_research.service.analysis_intake import AnalysisProviderSettings
from investment_research.service.catalog import DomainCatalogService


def test_catalog_lists_demo_real_and_sandbox_modes() -> None:
    payload = DomainCatalogService().describe_domain()

    assert payload.data_modes == ["demo", "sandbox", "real"]
    assert payload.mode_policies[1].data_mode == "sandbox"
    assert payload.mode_policies[2].allowed_source_types == ["real", "backfilled", "manual_override"]
    assert payload.analysis_providers[0].provider_name == "persisted-market-data-provider"
    assert payload.analysis_providers[1].provider_version == "1.0.0"
    assert payload.analysis_provider_config.market_data_provider == "persisted_fallback"
    assert "AnalysisRun" in payload.entities


def test_catalog_reflects_provider_settings_configuration() -> None:
    settings = AnalysisProviderSettings()
    settings.market_data_provider = "persisted"
    settings.evidence_provider = "persisted"

    payload = DomainCatalogService(provider_settings=settings).describe_domain()

    assert payload.analysis_provider_config.market_data_provider == "persisted"
    assert payload.analysis_provider_config.evidence_provider == "persisted"
    assert payload.analysis_providers[0].provider_name == "persisted-market-data-provider"


def test_catalog_can_switch_to_stub_provider_configuration() -> None:
    settings = AnalysisProviderSettings()
    settings.market_data_provider = "stub_realtime"
    settings.evidence_provider = "stub"

    payload = DomainCatalogService(provider_settings=settings).describe_domain()

    assert payload.analysis_provider_config.market_data_provider == "stub_realtime"
    assert payload.analysis_provider_config.evidence_provider == "stub"
    assert payload.analysis_providers[0].provider_name == "stub-realtime-market-data-provider"
    assert payload.analysis_providers[1].provider_name == "stub-realtime-evidence-provider"


def test_catalog_can_switch_to_authoritative_bundle_provider_configuration() -> None:
    settings = AnalysisProviderSettings()
    settings.market_data_provider = "bundle_backed"
    settings.evidence_provider = "bundle_backed"

    payload = DomainCatalogService(provider_settings=settings).describe_domain()

    assert payload.analysis_providers[0].provider_name == "authoritative-training-bundle-market-provider"
    assert payload.analysis_providers[1].provider_name == "authoritative-training-bundle-evidence-provider"


def test_demo_run_exposes_traceable_synthetic_provenance() -> None:
    run = DomainCatalogService().build_demo_analysis_run()

    assert run.provenance.source_type == "synthetic"
    assert run.provenance.data_mode == "demo"
    assert run.judge_score_ids
