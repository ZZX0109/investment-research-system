"""Composition helpers for application and worker entry points.

The container is intentionally small: services receive an explicit unit of
work, which keeps commands testable and prevents route handlers from building
their own dependency graphs.
"""

from __future__ import annotations

from investment_research.repository.sqlite import SQLiteUnitOfWork, create_unit_of_work
from investment_research.service.long_term_domain import LongTermDomainService
from investment_research.service.outbox import OutboxService
from investment_research.service.portfolio_research import PortfolioResearchService


def open_unit_of_work() -> SQLiteUnitOfWork:
    return create_unit_of_work()


def build_portfolio_research_service(uow: SQLiteUnitOfWork) -> PortfolioResearchService:
    return PortfolioResearchService(uow)


def build_long_term_domain_service(uow: SQLiteUnitOfWork) -> LongTermDomainService:
    return LongTermDomainService(uow)


def build_outbox_service(uow: SQLiteUnitOfWork) -> OutboxService:
    return OutboxService(uow)
