"""The only way a request reaches a model: through this guard.

`bills.ai.client.get_llm_client()` always wraps the configured client in
`PrivacyGuardedClient`, whatever the provider (fake, local, hosted). Before
anything is sent, the guard re-verifies the payload on its own:

1. no image, ever: an image can't be checked for personal information;
2. every token of every text part passes the allowlist (`unsafe_tokens`);
3. none of the personal information we already know for this bill appears,
   whatever the case, accents or digit grouping.

Any failure raises `PersonalInfoEgressError`; nothing is sent. The guarantee
therefore doesn't depend on where the model runs, nor on the redaction code
being bug-free: a regression there is caught here (and by the tests).
"""

from __future__ import annotations

import logging
import re

from bills.ai.client import ImagePart, LLMClient, LLMRequest, TextPart

from .redact import unsafe_tokens
from .vocabulary import VOCABULARY, fold

logger = logging.getLogger(__name__)


class PersonalInfoEgressError(Exception):
    """A request would have sent personal information out. Nothing was sent."""


def known_info_found(text: str, known: list[str]) -> list[str]:
    """Which of the known personal values (or their distinctive parts) are in text."""
    folded, digits = fold(text), re.sub(r"\D", "", text)
    found = []
    for value in known:
        value_digits = re.sub(r"\D", "", value)
        if len(value_digits) >= 6 and value_digits in digits:
            found.append(value)
            continue
        if re.search(rf"(?<!\w){re.escape(fold(value.strip()))}(?!\w)", folded):
            found.append(value)
            continue
        for part in re.split(r"[\s,]+", value):
            if len(part) >= 3 and not part.isdigit() and fold(part) not in VOCABULARY:
                if re.search(rf"(?<!\w){re.escape(fold(part))}(?!\w)", folded):
                    found.append(value)
                    break
    print("Found known information:", found)
    return found


class PrivacyGuardedClient(LLMClient):
    def __init__(self, inner: LLMClient):
        self.inner = inner

    def complete(self, request: LLMRequest, known_personal_info: list[str] | None = None) -> str:
        self.verify(request, known_personal_info or [])
        print("Request passed privacy guard; sending to model:", request)
        return self.inner.complete(request)

    @staticmethod
    def verify(request: LLMRequest, known: list[str]) -> None:
        problems = []
        print("Verifying request with known personal info:", known)
        for part in request.parts:
            print("Verifying part:", type(part).__name__)
            if isinstance(part, ImagePart):
                problems.append("image part")
            elif isinstance(part, TextPart):
                print("Verifying part text:", part.text)
                if bad := unsafe_tokens(part.text):
                    problems.append(f"{len(bad)} token(s) outside the allowlist")
                if known_info_found(part.text, known):
                    problems.append("known personal information")
            else:
                problems.append(f"unknown part {type(part).__name__}")
        if problems:
            # Say what kind of problem, never the offending text: logs are not
            # a place for personal information either.
            logger.error("Blocked a model request: %s", "; ".join(problems))
            raise PersonalInfoEgressError("; ".join(problems))
