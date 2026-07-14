from pydantic import BaseModel

from investment_research.domain.models import ResearchReport
from investment_research.pipeline.models import AnalysisBundle


class GeneratedReportResponse(BaseModel):
    report: ResearchReport
    bundle: AnalysisBundle
