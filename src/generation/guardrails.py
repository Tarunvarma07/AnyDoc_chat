import re
import logging
from typing import List
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

# Basic V1 Prompt Injection Patterns
INJECTION_PATTERNS = [
    r"ignore.{0,20}previous.{0,20}(instructions|prompts)",
    r"system.{0,20}prompt",
    r"you.{0,20}are.{0,20}now",
    r"forget.{0,20}all.{0,20}(instructions|commands)",
    r"disregard.{0,20}previous",
    r"base.{0,20}prompt",
    r"bypass",
    r"jailbreak"
]

# Profanity blocklist, matched with strict \b...\b word boundaries against
# the literal text only - no leetspeak/spacing normalization.
#
# We tried `better_profanity` first (a maintained library) instead of a
# hand-rolled list, on the theory that a real maintained wordlist beats
# reinventing one. In production that backfired: its fuzzy matching (built
# to catch spaced-out evasion like "t e s t") strips whitespace before
# matching, so two completely innocuous ADJACENT words can concatenate into
# a flagged term - e.g. "...this test is grounded..." got censored because
# "test" + "is" collapses to "testis". That's a worse failure mode than the
# placeholder list it replaced: it silently blocked a correct, grounded
# answer rather than just failing to catch anything. Strict per-word regex
# matching against the literal text can't do that, at the cost of not
# catching deliberately spaced-out evasion - an acceptable trade for a
# demo-scale guardrail; a real moderation API is the right tool if that
# matters.
PROFANITY_WORDS = [
    "fuck", "shit", "bitch", "asshole", "bastard", "dick", "cunt",
    "piss", "slut", "whore", "damn", "crap",
]
_PROFANITY_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in PROFANITY_WORDS) + r")\b",
    re.IGNORECASE,
)

def check_prompt_injection(text: str) -> bool:
    """
    Scans text for common prompt injection phrases.
    Returns True if an injection pattern is detected, False otherwise.
    """
    if not text:
        return False
        
    text_lower = text.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text_lower):
            logger.warning(f"Guardrail triggered: Prompt injection pattern detected - '{pattern}'")
            return True
            
    return False

def check_profanity(text: str) -> bool:
    """
    Scans text for profanity using strict whole-word regex matching against
    the literal text (see PROFANITY_WORDS above for why this isn't backed by
    a fuzzy-matching library). Word-boundary matched, so it doesn't flag
    substrings like "assessment", and doesn't concatenate adjacent words.
    Returns True if profanity is detected, False otherwise.
    """
    if not text:
        return False

    if _PROFANITY_PATTERN.search(text):
        logger.warning("Guardrail triggered: Profanity detected")
        return True

    return False

def verify_citations(answer: str, context_docs: List[Document]) -> bool:
    """
    Verifies that any citations in the answer (e.g., [1], [2]) map to actual provided documents.
    Returns True if citations are valid or none exist, False if a citation is hallucinated.
    """
    # Find all citations in the format [1], [2], etc.
    citations = re.findall(r'\[(\d+)\]', answer)
    if not citations:
        return True # No citations to verify
        
    num_docs = len(context_docs)
    for cit in citations:
        try:
            cit_idx = int(cit)
            # If the citation index is greater than the number of provided docs, it's hallucinated
            if cit_idx > num_docs or cit_idx < 1:
                logger.warning(f"Guardrail triggered: Hallucinated citation [{cit_idx}] detected.")
                return False
        except ValueError:
            pass
            
    return True
