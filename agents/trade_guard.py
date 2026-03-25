"""
Trade data guard utilities.

Centralizes deterministic checks used by router/graph/SQL agent so trade-data
queries only run when explicitly requested and for configured HS-code scope.
"""

from dataclasses import dataclass
import re
from typing import Iterable, Optional, List

from config import Config


_TRADE_TERMS = (
    "trade data",
    "export data",
    "trade statistics",
    "export statistics",
    "trade stats",
    "export stats",
    "export value",
    "export values",
    "trade value",
    "trade values",
    "monthly exports",
    "monthly export",
    "quarterly exports",
    "quarterly export",
    "ytd exports",
    "historical exports",
    "past exports",
)

_TRADE_PATTERN = re.compile(
    r"\b(export|trade)\b.{0,30}\b(data|stats?|statistics|value|values|trend|trends|monthly|quarterly|growth|ytd|historical|past)\b",
    re.IGNORECASE,
)
_TRADE_PATTERN_REVERSE = re.compile(
    r"\b(data|stats?|statistics|value|values|trend|trends|monthly|quarterly|growth|ytd|historical|past)\b.{0,30}\b(export|trade)\b",
    re.IGNORECASE,
)
_HOW_MUCH_EXPORTED_PATTERN = re.compile(
    r"\b(how\s+much|total|compare|show|give|provide|fetch|get|display|list)\b.{0,35}\b(export|trade)\b",
    re.IGNORECASE,
)

_DGFT_FTP_CONTEXT_TERMS = (
    "dgft",
    "foreign trade policy",
    "ftp",
    "handbook of procedures",
    "hbp",
)
_POLICY_REFERENCE_PATTERN = re.compile(
    r"\b(article|section|clause|paragraph|para|chapter)\b|\b\d+\.\d{2,}\b",
    re.IGNORECASE,
)


@dataclass
class TradeValidationResult:
    status: str
    message: str
    hs_code_6: Optional[str] = None
    matched_input: Optional[str] = None


def normalize_hs_digits(hs_text: Optional[str]) -> str:
    """Normalize HS-like token to digit-only code (max 8 digits)."""
    if hs_text is None:
        return ""

    digits = re.sub(r"\D", "", str(hs_text))
    if not digits:
        return ""

    if len(digits) in (1, 3, 5, 7):
        digits = digits.zfill(len(digits) + 1)

    if len(digits) > 8:
        digits = digits[:8]

    return digits


def extract_digit_tokens(query: str) -> List[str]:
    """Extract numeric tokens that could be HS-like inputs (1 to 8 digits)."""
    if not query:
        return []
    return re.findall(r"\b\d{1,8}\b", query)


def is_explicit_trade_data_request(query: str) -> bool:
    """Return True only when user explicitly asks for trade/export data/statistics."""
    if not query:
        return False

    q = query.lower()
    if any(term in q for term in _TRADE_TERMS):
        return True

    if _TRADE_PATTERN.search(q) or _TRADE_PATTERN_REVERSE.search(q):
        return True

    if _HOW_MUCH_EXPORTED_PATTERN.search(q) and (
        "data" in q
        or "stats" in q
        or "statistics" in q
        or "value" in q
        or "values" in q
        or "trend" in q
        or "monthly" in q
        or "quarterly" in q
    ):
        return True

    return False


def is_ftp_policy_reference_query(query: str) -> bool:
    """
    Detect DGFT FTP document-reference style questions.
    Example: "Explain DGFT FTP article 8.04".
    """
    if not query:
        return False

    q = query.lower()
    has_ftp_context = any(term in q for term in _DGFT_FTP_CONTEXT_TERMS)
    if not has_ftp_context:
        return False

    return bool(_POLICY_REFERENCE_PATTERN.search(q))


def validate_trade_hs_request(
    query: str,
    state_hs_code: Optional[str] = None,
    allowed_hs6: Optional[Iterable[str]] = None,
) -> TradeValidationResult:
    """
    Validate HS-code scope for trade-data queries.

    Rules:
    - Trade data allowed only for explicit 6-digit HS codes from allowlist, or
      8-digit codes whose first 6 digits are in allowlist.
    - If input has fewer than 6 digits and prefix matches allowlist, ask user to
      provide 6-8 digit HS code.
    """
    allowed_list = sorted(set(allowed_hs6 or Config.FOCUS_HS_CODES))
    allowed_set = set(allowed_list)

    raw_tokens = extract_digit_tokens(query)
    normalized_tokens = []
    for token in raw_tokens:
        normalized = normalize_hs_digits(token)
        if normalized:
            normalized_tokens.append(normalized)

    for token in normalized_tokens:
        if len(token) >= 6:
            hs6 = token[:6]
            if hs6 in allowed_set:
                return TradeValidationResult(
                    status="ok",
                    message="Trade data request validated.",
                    hs_code_6=hs6,
                    matched_input=token,
                )

    long_tokens = [t for t in normalized_tokens if len(t) >= 6]
    if long_tokens:
        requested = long_tokens[0][:6]
        return TradeValidationResult(
            status="not_allowed",
            message=(
                f"Trade data is not available for HS {requested}. "
                f"Supported HS-6 codes are: {', '.join(allowed_list)}."
            ),
            hs_code_6=None,
            matched_input=long_tokens[0],
        )

    short_tokens = [t for t in normalized_tokens if 0 < len(t) < 6]
    if short_tokens:
        for token in short_tokens:
            matches = [code for code in allowed_list if code.startswith(token)]
            if matches:
                preview = ", ".join(matches[:5])
                if len(matches) > 5:
                    preview += ", ..."
                return TradeValidationResult(
                    status="needs_6_to_8_digit",
                    message=(
                        f"The prefix '{token}' matches tracked HS codes ({preview}). "
                        "Please provide a 6 to 8 digit HS code."
                    ),
                    hs_code_6=None,
                    matched_input=token,
                )

        return TradeValidationResult(
            status="not_allowed",
            message=(
                f"Trade data is not available for prefix '{short_tokens[0]}'. "
                f"Supported HS-6 codes are: {', '.join(allowed_list)}."
            ),
            hs_code_6=None,
            matched_input=short_tokens[0],
        )

    normalized_state_hs = normalize_hs_digits(state_hs_code)
    if len(normalized_state_hs) >= 6 and normalized_state_hs[:6] in allowed_set:
        return TradeValidationResult(
            status="ok",
            message="Using HS code from conversation context.",
            hs_code_6=normalized_state_hs[:6],
            matched_input=normalized_state_hs,
        )

    return TradeValidationResult(
        status="missing_hs",
        message=(
            "Please provide a 6 to 8 digit HS code for trade data. "
            f"Supported HS-6 codes are: {', '.join(allowed_list)}."
        ),
        hs_code_6=None,
        matched_input=None,
    )
