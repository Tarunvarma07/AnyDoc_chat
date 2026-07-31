import re
import logging
from typing import List
from better_profanity import profanity
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

# Loads better_profanity's maintained, whole-word-matched default wordlist
# once at import time instead of hand-rolling and maintaining our own list.
profanity.load_censor_words()

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
    Scans text for profanity using better_profanity's maintained wordlist
    (whole-word matched, so it doesn't flag substrings like "assessment").
    Returns True if profanity is detected, False otherwise.
    """
    if not text:
        return False

    if profanity.contains_profanity(text):
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
