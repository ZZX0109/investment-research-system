from __future__ import annotations

import sqlite3
from typing import Any, Callable

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse


def build_research_router(
    *,
    get_current_user: Callable[..., sqlite3.Row],
    research_payload: Callable[[str, str, int | None], dict[str, Any]],
    analyze_document_content: Callable[[str, str, bytes], dict[str, Any]],
    markdown_report: Callable[[str, str, int | None], str],
    get_analysis_run: Callable[[str], dict[str, Any] | None],
    recent_runs: Callable[[str], list[dict[str, Any]]],
    get_report_snapshot: Callable[[str], dict[str, Any] | None],
    data_mode_status: Callable[[], dict[str, Any]],
) -> APIRouter:
    router = APIRouter(tags=["research"])

    @router.get("/api/research/{symbol}")
    def research(symbol: str, preference: str = Query(default="balanced"), user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
        payload = research_payload(symbol, preference, int(user["id"]))
        return {**payload, "dataMode": data_mode_status()}

    @router.post("/api/documents/{symbol}/analyze")
    async def analyze_document(symbol: str, file: UploadFile = File(...), user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
        content = await file.read()
        result = analyze_document_content(symbol.upper(), file.filename or "uploaded-report", content)
        return {"ok": True, "symbol": symbol.upper(), "documentAnalysis": result, "dataMode": data_mode_status(), "sourceMeta": result.get("sourceMeta")}

    @router.get("/api/reports/{symbol}.md", response_class=PlainTextResponse)
    def report_markdown(
        symbol: str,
        preference: str = Query(default="balanced"),
        run_id: str | None = Query(default=None),
        user: sqlite3.Row = Depends(get_current_user),
    ) -> str:
        if not run_id:
            latest_runs = recent_runs(symbol.upper())
            if not latest_runs:
                raise HTTPException(status_code=404, detail="No analysis run exists for this symbol. Generate an analysis run first, then open the bound report snapshot.")
            run_id = str(latest_runs[0]["runId"])
        run = get_analysis_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Analysis run '{run_id}' was not found.")
        if not run.get("inputSnapshotHash") or not run.get("inputSnapshot"):
            raise HTTPException(status_code=409, detail=f"Analysis run '{run_id}' is missing its frozen input snapshot.")
        source_meta = run.get("sourceMeta") or {}
        required_source_keys = {"mode", "provider", "as_of", "overrides", "synthetic_ratio"}
        if not required_source_keys.issubset(source_meta):
            raise HTTPException(status_code=409, detail=f"Analysis run '{run_id}' is missing source metadata.")
        snapshot = get_report_snapshot(run_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail=f"Report snapshot for run_id '{run_id}' was not found.")
        return str(snapshot["markdown"])

    return router
