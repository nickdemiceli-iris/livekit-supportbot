"""Prompt and response phrasing helpers for natural support tone."""

from __future__ import annotations

import random


def opening_disclosure(agent_name: str) -> str:
    return f"Hi, I am {agent_name}, a virtual support assistant for Simple Loans. "


def resolution_question(rng: random.Random) -> str:
    options = [
        "Did this answer your question?",
        "Did that clear things up for you?",
        "Does this resolve what you needed?",
    ]
    return rng.choice(options)


def closing_message(rng: random.Random) -> str:
    options = [
        "Great, happy to help. If anything else comes up, I am here.",
        "Glad that helped. Reach out anytime if you need more support.",
        "Perfect. If you need anything else, I can help.",
    ]
    return rng.choice(options)


ESCALATION_MESSAGE = (
    "Thank you for flagging this. I am escalating your case now to a human "
    "specialist for priority handling."
)

FOLLOWUP_CHANNEL_QUESTION = (
    "Understood. I can arrange a follow-up with a specialist. "
    "Which contact channel do you prefer?"
)

FOLLOWUP_TIME_QUESTION = "Thanks, I noted that. What time works best for a follow-up?"

FOLLOWUP_CONFIRM_TEMPLATE = (
    "Perfect, I have noted a follow-up via {channel} around {when}. "
    "A human specialist will continue from here."
)
