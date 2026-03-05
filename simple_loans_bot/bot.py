"""Natural, policy-grounded support bot for Simple Loans."""

from __future__ import annotations

from dataclasses import dataclass
import random
import re
from typing import Optional

from .knowledge import (
    ESCALATION_KEYWORDS,
    FAQ_ANSWERS,
    LATE_AND_HARDSHIP_POLICY,
    LOAN_STATUS_AND_DISBURSEMENT,
    LOAN_TERMS,
    PAYMENT_POLICY,
    STATUS_IDENTIFIER_KEYWORDS,
    VDC_POLICY,
    VEHICLE_AND_TITLE_POLICY,
)


YES_PATTERNS = {
    "yes",
    "y",
    "yep",
    "yeah",
    "correct",
    "that helps",
    "solved",
    "resolved",
}
NO_PATTERNS = {
    "no",
    "n",
    "nope",
    "not really",
    "didn't help",
    "did not help",
    "still need help",
}


@dataclass
class ConversationState:
    greeted: bool = False
    awaiting_status_identifier: bool = False
    awaiting_resolution_confirmation: bool = False
    awaiting_followup_channel: bool = False
    awaiting_followup_time: bool = False
    preferred_channel: Optional[str] = None
    preferred_time: Optional[str] = None
    account_identifier: Optional[str] = None
    failed_payment_mentions: int = 0


class SimpleLoansSupportBot:
    """Stateful conversational bot that keeps responses natural and concise."""

    def __init__(self, agent_name: str = "Mia", seed: int = 7) -> None:
        self.agent_name = agent_name
        self.state = ConversationState()
        self._rng = random.Random(seed)

    def respond(self, user_message: str) -> str:
        text = user_message.strip()
        normalized = _normalize(text)

        if "failed payment" in normalized or "payment failed" in normalized:
            self.state.failed_payment_mentions += 1

        greeting = ""
        if not self.state.greeted:
            greeting = (
                f"Hi, I am {self.agent_name}, a virtual support assistant for Simple Loans. "
            )
            self.state.greeted = True

        if self._requires_immediate_escalation(normalized):
            return greeting + self._escalation_message()

        if self.state.awaiting_followup_channel:
            self.state.preferred_channel = text
            self.state.awaiting_followup_channel = False
            self.state.awaiting_followup_time = True
            return (
                greeting
                + "Thanks, I noted that. What time works best for a follow-up?"
            )

        if self.state.awaiting_followup_time:
            self.state.preferred_time = text
            self.state.awaiting_followup_time = False
            self.state.awaiting_resolution_confirmation = False
            channel = self.state.preferred_channel or "your preferred channel"
            when = self.state.preferred_time or "your preferred time"
            return (
                greeting
                + f"Perfect, I have noted a follow-up via {channel} around {when}. "
                + "A human specialist will continue from here."
            )

        if self.state.awaiting_status_identifier:
            if _looks_like_identifier(text):
                self.state.account_identifier = text
                self.state.awaiting_status_identifier = False
                return (
                    greeting
                    + "Thank you. "
                    + LOAN_STATUS_AND_DISBURSEMENT
                    + " "
                    + self._resolution_question()
                )
            return (
                greeting
                + "I still need your account identifier to check status flow. "
                + "Please share it when ready."
            )

        if self.state.awaiting_resolution_confirmation:
            if _is_yes(normalized):
                self.state.awaiting_resolution_confirmation = False
                return greeting + self._closing_message()
            if _is_no(normalized):
                self.state.awaiting_resolution_confirmation = False
                self.state.awaiting_followup_channel = True
                return (
                    greeting
                    + "Understood. I can arrange a follow-up with a specialist. "
                    + "Which contact channel do you prefer?"
                )

        intent = self._detect_intent(normalized)
        response = self._intent_response(intent)
        return greeting + response

    def _requires_immediate_escalation(self, normalized_message: str) -> bool:
        if any(keyword in normalized_message for keyword in ESCALATION_KEYWORDS):
            return True
        if self.state.failed_payment_mentions >= 2:
            return True
        if "policy exception" in normalized_message or "make an exception" in normalized_message:
            return True
        return False

    def _escalation_message(self) -> str:
        self.state.awaiting_resolution_confirmation = False
        self.state.awaiting_status_identifier = False
        return (
            "Thank you for flagging this. I am escalating your case now to a human "
            "specialist for priority handling."
        )

    def _detect_intent(self, normalized_message: str) -> str:
        message = normalized_message

        if _has_greeting(message):
            return "greeting"
        if any(
            word in message
            for word in (
                "same day funding",
                "same-day funding",
                "funds arrive",
                "disbursement time",
            )
        ):
            return "disbursement_timeline"
        if any(
            word in message
            for word in (
                "status",
                "where is my loan",
                "check my loan",
                "my application",
                "pending",
            )
        ):
            return "status"
        if any(word in message for word in ("payment", "due date", "prepayment", "pay early", "partial payment", "bank holiday")):
            return "payments"
        if any(word in message for word in ("late", "hardship", "struggling", "can't pay", "cannot pay")):
            return "late_hardship"
        if "vdc" in message or "debt cancellation" in message or "dca" in message:
            return "vdc"
        if any(word in message for word in ("title", "vehicle inspection", "government id", "proof of address", "lienholder")):
            return "vehicle_docs"
        if any(word in message for word in ("apr", "fee", "terms", "doc stamp", "registration fee", "repayment schedule")):
            return "terms"

        if "auto equity" in message or "title loan" in message or "car equity" in message:
            return "auto_equity_loan"
        if "different" in message and "simple loans" in message:
            return "what_makes_simple_loans_different"
        if "credit" in message and ("run" in message or "check" in message or "report" in message):
            return "credit_check"
        if "job" in message or "employed" in message or "employment" in message:
            return "job_requirement"
        if "how long" in message or "30 minutes" in message or "process" in message:
            return "process_time"
        if any(word in message for word in ("zelle", "paypal", "moneygram", "ach", "wire", "debit card")):
            return "funding_methods"
        if "how much" in message or "$25,000" in message or "25000" in message or "max" in message:
            return "max_loan_amount"
        if "online" in message or "office" in message:
            return "fully_online"

        if any(keyword in message for keyword in STATUS_IDENTIFIER_KEYWORDS):
            return "status"
        return "unknown"

    def _intent_response(self, intent: str) -> str:
        if intent == "greeting":
            return "How can I help you today?"

        if intent == "status":
            self.state.awaiting_status_identifier = True
            self.state.awaiting_resolution_confirmation = False
            return (
                "I can help with your loan status. Please share your account identifier."
            )

        if intent == "disbursement_timeline":
            return LOAN_STATUS_AND_DISBURSEMENT + " " + self._resolution_question()

        if intent == "payments":
            return PAYMENT_POLICY + " " + self._resolution_question()

        if intent == "late_hardship":
            return LATE_AND_HARDSHIP_POLICY + " " + self._resolution_question()

        if intent == "vdc":
            return VDC_POLICY + " " + self._resolution_question()

        if intent == "vehicle_docs":
            return VEHICLE_AND_TITLE_POLICY + " " + self._resolution_question()

        if intent == "terms":
            return LOAN_TERMS + " " + self._resolution_question()

        if intent in FAQ_ANSWERS:
            return FAQ_ANSWERS[intent] + " " + self._resolution_question()

        return (
            "I want to make sure I guide you correctly. Are you asking about loan "
            "status, payments, documentation, terms, or VDC?"
        )

    def _resolution_question(self) -> str:
        self.state.awaiting_resolution_confirmation = True
        options = [
            "Did this answer your question?",
            "Did that clear things up for you?",
            "Does this resolve what you needed?",
        ]
        return self._rng.choice(options)

    def _closing_message(self) -> str:
        closings = [
            "Great, happy to help. If anything else comes up, I am here.",
            "Glad that helped. Reach out anytime if you need more support.",
            "Perfect. If you need anything else, I can help.",
        ]
        return self._rng.choice(closings)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def _is_yes(normalized_value: str) -> bool:
    return _starts_with_or_equals(normalized_value, YES_PATTERNS)


def _is_no(normalized_value: str) -> bool:
    return _starts_with_or_equals(normalized_value, NO_PATTERNS)


def _starts_with_or_equals(normalized_value: str, candidates: set[str]) -> bool:
    for candidate in candidates:
        if normalized_value == candidate or normalized_value.startswith(f"{candidate} "):
            return True
    return False


def _has_greeting(normalized_value: str) -> bool:
    return bool(re.search(r"\b(hello|hi|hey)\b", normalized_value))


def _looks_like_identifier(value: str) -> bool:
    compact = value.strip()
    return bool(re.search(r"[a-zA-Z]", compact) and re.search(r"\d", compact) and len(compact) >= 5)
