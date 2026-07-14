from enum import Enum


class StringEnum(str, Enum):
    pass


class EntityStatus(StringEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    STALE = "stale"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class DataSourceType(StringEnum):
    REAL = "real"
    SYNTHETIC = "synthetic"
    BACKFILLED = "backfilled"
    MANUAL_OVERRIDE = "manual_override"


class DataMode(StringEnum):
    DEMO = "demo"
    SANDBOX = "sandbox"
    REAL = "real"


class AssetType(StringEnum):
    EQUITY = "equity"
    ETF = "etf"
    CRYPTO = "crypto"
    BOND = "bond"
    FUND = "fund"
    CASH = "cash"
    OTHER = "other"


class RecommendationAction(StringEnum):
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    REDUCE = "reduce"
    AVOID = "avoid"


class JudgeVerdict(StringEnum):
    PASS = "pass"
    WARN = "warn"
    HOLD = "hold"
    BLOCK = "block"


class RiskLevel(StringEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EvidenceType(StringEnum):
    MARKET_DATA = "market_data"
    FILING = "filing"
    NEWS = "news"
    RESEARCH_NOTE = "research_note"
    MODEL_OUTPUT = "model_output"
    MANUAL_NOTE = "manual_note"


class AccessRole(StringEnum):
    OWNER = "owner"
    VIEWER = "viewer"


class ClaimStatus(StringEnum):
    PROPOSED = "proposed"
    VERIFIED = "verified"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ResearchRunState(StringEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"


class ModelLifecycleStatus(StringEnum):
    CANDIDATE = "candidate"
    APPROVED = "approved"
    DEPRECATED = "deprecated"
