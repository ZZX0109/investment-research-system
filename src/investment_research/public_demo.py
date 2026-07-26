"""Guards for the shared, read-only public research demonstration.

The public deployment is intentionally different from a locally run research
workspace: visitors must never be asked to place API keys in a shared service
or trigger paid LLM calls with somebody else's configuration.
"""

from fastapi import HTTPException, status

from investment_research.config import env_flag


def public_demo_enabled() -> bool:
    return env_flag("INVESTMENT_RESEARCH_PUBLIC_DEMO", False)


def require_private_research_workspace() -> None:
    """Reject stateful LLM/key operations in a shared public deployment."""
    if public_demo_enabled():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "The public demo is read-only and does not accept API keys or "
                "run user-configured LLM requests. Run the project locally to "
                "configure a private research assistant."
            ),
        )
