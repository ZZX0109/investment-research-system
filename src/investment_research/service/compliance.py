"""Deterministic public-research text compliance checks.

The checker is intentionally rule based: the same text and policy version
always produce the same findings, making it suitable for pre-publication gates
and audit records.  It is a product safeguard, not a substitute for legal
review.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field


ComplianceReasonCode = Literal[
    "DIRECT_BUY_INSTRUCTION",
    "DIRECT_SELL_INSTRUCTION",
    "POSITION_INCREASE_INSTRUCTION",
    "POSITION_REDUCE_INSTRUCTION",
    "HOLD_INSTRUCTION",
    "TARGET_PRICE_GUIDANCE",
    "GUARANTEED_RETURN_CLAIM",
]


class ResearchTextCompliancePolicy(BaseModel):
    policy_version: str = Field(default="cn-public-research-text-v1", min_length=3, max_length=80)
    block_trade_instructions: bool = True
    block_target_prices: bool = True
    block_guaranteed_returns: bool = True


class ComplianceFinding(BaseModel):
    reason_code: ComplianceReasonCode
    matched_text: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    context: str


class ComplianceCheckResult(BaseModel):
    allowed: bool
    policy_version: str
    findings: list[ComplianceFinding] = Field(default_factory=list)

    @property
    def reason_codes(self) -> list[ComplianceReasonCode]:
        return list(dict.fromkeys(item.reason_code for item in self.findings))


class ResearchTextComplianceChecker:
    """Block individual-security instructions while preserving disclaimers."""

    _individual_marker = re.compile(
        r"(?:\b\d{6}(?:\.(?:SH|SZ|BJ))?\b|该股|此股|这只股票|本只股票|个股)",
        flags=re.IGNORECASE,
    )
    _directive_cue = re.compile(
        r"(?:建议|应该|应当|可以|可考虑|宜|最好|立即|现在|请|必须|推荐|值得|继续|坚定|"
        r"不要|请勿|不得|避免|不建议|不应)\s*$"
    )
    _post_directive_cue = re.compile(r"^\s*(?:该股|此股|这只股票|\d{6}|为宜|较合适|更合适|机会|时机)")
    _disclaimer_markers = re.compile(
        r"(?:免责声明|风险提示|不构成|仅供研究|仅供参考|不代表投资建议|系统不会|"
        r"不提供|不会提供|禁止提供|禁止输出|禁止生成|请勿依据|不得据此|不能据此|"
        r"避免将.{0,8}理解为|交易术语|字段示例)"
    )
    _negation = re.compile(r"(?:不|未|无|非|勿|别|莫|无法|不能|不会|不得|禁止|避免)\s*$")

    _trade_terms: tuple[tuple[ComplianceReasonCode, re.Pattern[str]], ...] = (
        ("POSITION_INCREASE_INSTRUCTION", re.compile(r"加仓")),
        ("POSITION_REDUCE_INSTRUCTION", re.compile(r"减仓")),
        ("DIRECT_BUY_INSTRUCTION", re.compile(r"买入")),
        ("DIRECT_SELL_INSTRUCTION", re.compile(r"卖出")),
        (
            "HOLD_INSTRUCTION",
            re.compile(r"(?:继续持有|建议持有|应该持有|可以持有|适合持有|坚定持有|长期持有|持有该股|持有此股|持有这只股票)"),
        ),
    )
    _target_price = re.compile(
        r"(?:目标价(?:格)?|目标点位|上看\s*(?:人民币)?\s*\d+(?:\.\d+)?\s*元|"
        r"看到\s*(?:人民币)?\s*\d+(?:\.\d+)?\s*元)"
    )
    _guaranteed_return = re.compile(
        r"(?:保证.{0,8}收益|收益.{0,8}保证|保本保收益|稳赚不赔|稳赚|必然盈利|一定赚钱|"
        r"无风险收益|确定性收益|必涨|必跌)"
    )

    def __init__(self, policy: ResearchTextCompliancePolicy | None = None) -> None:
        self.policy = policy or ResearchTextCompliancePolicy()

    def check(
        self, text: str, *, subject_symbol: str | None = None,
        subject_name: str | None = None,
    ) -> ComplianceCheckResult:
        findings: list[ComplianceFinding] = []
        individualized = bool(
            subject_symbol or subject_name or self._individual_marker.search(text)
        )

        if self.policy.block_guaranteed_returns:
            for match in self._guaranteed_return.finditer(text):
                if not self._is_negated_claim(text, match.start()):
                    findings.append(self._finding(
                        "GUARANTEED_RETURN_CLAIM", text, match.start(), match.end(),
                    ))

        if self.policy.block_target_prices:
            for match in self._target_price.finditer(text):
                if not self._is_disclaimer_usage(text, match.start(), match.end()):
                    findings.append(self._finding(
                        "TARGET_PRICE_GUIDANCE", text, match.start(), match.end(),
                    ))

        if self.policy.block_trade_instructions and individualized:
            for reason_code, pattern in self._trade_terms:
                for match in pattern.finditer(text):
                    if self._is_disclaimer_usage(text, match.start(), match.end()):
                        continue
                    if reason_code in {
                        "DIRECT_BUY_INSTRUCTION", "DIRECT_SELL_INSTRUCTION"
                    } and not self._looks_directive(
                        text, match.start(), match.end(), subject_symbol, subject_name,
                    ):
                        continue
                    findings.append(self._finding(
                        reason_code, text, match.start(), match.end(),
                    ))

        findings.sort(key=lambda item: (item.start, item.reason_code))
        return ComplianceCheckResult(
            allowed=not findings,
            policy_version=self.policy.policy_version,
            findings=findings,
        )

    def _looks_directive(
        self, text: str, start: int, end: int,
        subject_symbol: str | None, subject_name: str | None,
    ) -> bool:
        left = text[max(0, start - 18):start]
        right = text[end:min(len(text), end + 18)]
        if self._directive_cue.search(left) or self._post_directive_cue.search(right):
            return True
        nearby = text[max(0, start - 18):min(len(text), end + 18)]
        if self._individual_marker.search(nearby):
            return True
        if subject_symbol and subject_symbol.lower() in nearby.lower():
            return True
        if subject_name and subject_name in nearby:
            return True
        sentence_start = max(text.rfind("。", 0, start), text.rfind("！", 0, start), text.rfind("\n", 0, start)) + 1
        return not text[sentence_start:start].strip()

    def _is_disclaimer_usage(self, text: str, start: int, end: int) -> bool:
        left = text[max(0, start - 24):start]
        window = text[max(0, start - 48):min(len(text), end + 48)]
        right = text[end:min(len(text), end + 20)]
        if re.search(r"(?:是|属于|作为).{0,6}(?:交易术语|字段|示例)", right):
            return True
        if re.search(r"(?:交易术语|字段示例|教学示例)", window) and (
            text[max(0, start - 1):start] in {"“", '"', "'", "‘"}
            or text[end:min(len(text), end + 1)] in {"”", '"', "'", "’"}
        ):
            return True
        # "不构成买入或卖出建议" and explicit product-safety statements
        # mention prohibited terms in order to forbid them; they are not advice.
        if self._disclaimer_markers.search(window):
            if self._negation.search(left) or re.search(
                r"(?:不构成|不提供|不会提供|禁止提供|禁止输出|禁止生成|系统不会|避免将).{0,20}$",
                left,
            ) or re.search(r"(?:建议|指令|依据|信号)", text[end:min(len(text), end + 16)]):
                return True
        return False

    def _is_negated_claim(self, text: str, start: int) -> bool:
        left = text[max(0, start - 12):start]
        return bool(self._negation.search(left) or re.search(
            r"(?:无法|不能|不会|不可能|并不|绝不|不承诺|不提供).{0,6}$", left
        ))

    @staticmethod
    def _finding(
        reason_code: ComplianceReasonCode, text: str, start: int, end: int,
    ) -> ComplianceFinding:
        return ComplianceFinding(
            reason_code=reason_code,
            matched_text=text[start:end],
            start=start,
            end=end,
            context=text[max(0, start - 24):min(len(text), end + 24)],
        )
