from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pathlib import Path
from starlette.background import BackgroundTask

from investment_research.api.artifact_security import require_artifact_access
from investment_research.api.artifact_security import require_agent_api_access
from investment_research.api.artifact_security import require_report_access
from investment_research.api.artifact_security import require_project_access
from investment_research.api.artifact_security import require_run_access
from investment_research.api.test_officer_schemas import (
    TestOfficerMissionPreviewRequest,
    TestOfficerMissionPreviewResponse,
    TestOfficerRunRequest,
    TestOfficerRunResponse,
)
from investment_research.service.run_bundle_models import RunBundleAuditRunSummary
from investment_research.service.run_bundle_models import RunBundleAuditRunDetail
from investment_research.service.run_bundle_models import RunBundleAuditStatus
from investment_research.service.run_bundle_models import RunBundleComparisonReport
from investment_research.service.run_bundle_models import RunBundleHistoryIndex
from investment_research.service.run_bundle_models import RunBundleManifest
from investment_research.service.run_bundle_models import RunBundleManifestEvidence
from investment_research.service.run_bundle_models import RunBundleManifestJudgeReport
from investment_research.service.run_bundle_models import RunBundleMissionPackage
from investment_research.service.run_bundle_models import RunBundleOnboardingProtocol
from investment_research.service.run_bundle_models import RunBundleRetentionJobResult
from investment_research.service.run_bundle_models import RunBundleArtifactIntegrityReport
from investment_research.service.run_bundle_models import RunBundleDownloadManifest
from investment_research.service.run_bundle_models import RunBundleRetentionCleanupPlan
from investment_research.service.run_bundle_models import RunBundleRegistryManifest
from investment_research.service.run_bundle_models import RunBundleRegistryFailureAttribution
from investment_research.service.run_bundle_models import RunBundleRegistryResourceRecord
from investment_research.service.run_bundle_models import RunBundleRegistrySourceContext
from investment_research.service.run_bundles import ArtifactDecryptionError, RunBundleService, get_default_runs_root
from investment_research.service.test_officer_preview import (
    MissionPreviewError,
    MissionPreviewService,
)
from investment_research.service.test_officer_runs import MissionRunError, MissionRunService

router = APIRouter(prefix="/api/v1/test-officer", tags=["test-officer"])
RegistryResourceResponse = (
    RunBundleOnboardingProtocol
    | RunBundleMissionPackage
    | RunBundleManifestJudgeReport
    | RunBundleRetentionCleanupPlan
    | list[RunBundleManifestEvidence]
    | list[RunBundleRegistryResourceRecord]
    | list[RunBundleRegistrySourceContext]
    | list[RunBundleRegistryFailureAttribution]
)


def get_run_bundle_service() -> RunBundleService:
    return RunBundleService(get_default_runs_root())


def get_test_officer_preview_service() -> MissionPreviewService:
    return MissionPreviewService()


def get_test_officer_run_service() -> MissionRunService:
    return MissionRunService(runs_root=get_default_runs_root())


@router.get("/history")
def get_run_history(
    request: Request,
    mission_id: str | None = Query(default=None),
    service: RunBundleService = Depends(get_run_bundle_service),
) -> RunBundleHistoryIndex:
    require_agent_api_access(request)
    history = service.get_history()
    if mission_id:
        history = history.model_copy(update={"runs": service.list_runs(mission_id=mission_id)})
    return history


@router.get("/audit/status")
def get_audit_status(
    request: Request,
    service: RunBundleService = Depends(get_run_bundle_service),
) -> RunBundleAuditStatus:
    require_agent_api_access(request)
    return service.get_audit_status()


@router.get("/audit/runs")
def get_audit_runs(
    request: Request,
    project_id: str | None = Query(default=None),
    target_app_id: str | None = Query(default=None),
    mission_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    service: RunBundleService = Depends(get_run_bundle_service),
) -> list[RunBundleAuditRunSummary]:
    if project_id:
        require_project_access(request, project_id, min_role="viewer")
    else:
        require_agent_api_access(request)
    return service.list_audit_runs(
        project_id=project_id,
        target_app_id=target_app_id,
        mission_id=mission_id,
        status=status,
        review_status=review_status,
        limit=limit,
    )


@router.get("/audit/runs/{run_id}")
def get_audit_run_detail(
    request: Request,
    run_id: str,
    service: RunBundleService = Depends(get_run_bundle_service),
) -> RunBundleAuditRunDetail:
    try:
        require_project_access(request, service.get_audit_run_project_id(run_id), min_role="viewer")
        return service.get_audit_run_detail(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/latest/manifest")
def get_latest_run_manifest(
    request: Request,
    mission_id: str | None = Query(default=None),
    service: RunBundleService = Depends(get_run_bundle_service),
) -> RunBundleManifest:
    require_agent_api_access(request)
    try:
        return service.get_latest_manifest(mission_id=mission_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/manifest")
def get_run_manifest(
    request: Request,
    run_id: str,
    service: RunBundleService = Depends(get_run_bundle_service),
) -> RunBundleManifest:
    require_run_access(request, run_id)
    try:
        return service.get_manifest(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/comparison")
def get_run_comparison(
    request: Request,
    run_id: str,
    service: RunBundleService = Depends(get_run_bundle_service),
) -> RunBundleComparisonReport:
    require_run_access(request, run_id)
    comparison = service.get_comparison(run_id)
    if comparison is None:
        raise HTTPException(status_code=404, detail="Comparison report not found")
    return comparison


@router.get("/runs/{run_id}/registry")
def get_run_registry_manifest(
    request: Request,
    run_id: str,
    service: RunBundleService = Depends(get_run_bundle_service),
) -> RunBundleRegistryManifest:
    require_run_access(request, run_id)
    try:
        return service.get_registry_manifest(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/registry/{resource_name}", response_model=RegistryResourceResponse)
def get_run_registry_resource(
    request: Request,
    run_id: str,
    resource_name: str,
    service: RunBundleService = Depends(get_run_bundle_service),
) -> RegistryResourceResponse:
    require_run_access(request, run_id)
    try:
        return service.get_registry_resource(run_id, resource_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/mission-preview", response_model=TestOfficerMissionPreviewResponse)
def post_mission_preview(
    request: Request,
    payload: TestOfficerMissionPreviewRequest,
    service: MissionPreviewService = Depends(get_test_officer_preview_service),
) -> TestOfficerMissionPreviewResponse:
    require_agent_api_access(request)
    try:
        return service.preview_mission(payload)
    except MissionPreviewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs", response_model=TestOfficerRunResponse)
def post_test_officer_run(
    request: Request,
    payload: TestOfficerRunRequest,
    service: MissionRunService = Depends(get_test_officer_run_service),
) -> TestOfficerRunResponse:
    require_agent_api_access(request)
    try:
        return service.create_run(payload)
    except MissionRunError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/{run_id}/retention-job", response_model=RunBundleRetentionJobResult)
def post_run_retention_job(
    request: Request,
    run_id: str,
    apply: bool = Query(default=False),
    now: str | None = Query(default=None),
    service: RunBundleService = Depends(get_run_bundle_service),
) -> RunBundleRetentionJobResult:
    try:
        require_project_access(request, service.get_manifest(run_id).project.id, min_role="operator")
        return service.execute_retention_job(run_id, apply=apply, now=now)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/integrity", response_model=RunBundleArtifactIntegrityReport)
def post_run_integrity_report(
    request: Request,
    run_id: str,
    service: RunBundleService = Depends(get_run_bundle_service),
) -> RunBundleArtifactIntegrityReport:
    try:
        require_project_access(request, service.get_manifest(run_id).project.id, min_role="operator")
        return service.verify_artifact_integrity(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/download-bundle", response_model=RunBundleDownloadManifest)
def post_run_download_bundle_manifest(
    request: Request,
    run_id: str,
    service: RunBundleService = Depends(get_run_bundle_service),
) -> RunBundleDownloadManifest:
    try:
        require_project_access(request, service.get_manifest(run_id).project.id, min_role="operator")
        return service.create_download_bundle(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/download-bundle")
def get_run_download_bundle(
    request: Request,
    run_id: str,
    service: RunBundleService = Depends(get_run_bundle_service),
) -> FileResponse:
    require_run_access(request, run_id)
    try:
        manifest = service.create_download_bundle(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(manifest.bundlePath, media_type="application/zip", filename=f"{run_id}-bundle.zip")


@router.get("/runs/{run_id}/artifacts/{artifact_name:path}")
def get_run_artifact(
    request: Request,
    run_id: str,
    artifact_name: str,
    service: RunBundleService = Depends(get_run_bundle_service),
) -> FileResponse:
    require_artifact_access(request, run_id=run_id)
    try:
        delivery = service.get_artifact_delivery(run_id, artifact_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ArtifactDecryptionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    background = BackgroundTask(_delete_temporary_file, delivery.path) if delivery.temporary else None
    return FileResponse(delivery.path, media_type=delivery.media_type, background=background)


@router.get("/runs/{run_id}/reports/{report_name:path}")
def get_run_report(
    request: Request,
    run_id: str,
    report_name: str,
    service: RunBundleService = Depends(get_run_bundle_service),
) -> FileResponse:
    require_report_access(request, report_name, run_id)
    try:
        report_path = service.get_report_path(run_id, report_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(report_path)


def _delete_temporary_file(path: Path) -> None:
    path.unlink(missing_ok=True)
