"""LiveKit voice agent for Simple Loans support with strict KB grounding."""

from __future__ import annotations

from collections.abc import AsyncIterable
from dataclasses import dataclass
import os
import random
import re
from typing import Optional

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    JobProcess,
    ModelSettings,
    WorkerOptions,
    cli,
    llm,
)
from livekit.plugins import cartesia, deepgram, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from knowledgebase import (
    ESCALATION_KEYWORDS,
    LOAN_STATUS_AND_DISBURSEMENT,
    STATUS_IDENTIFIER_KEYWORDS,
    match_article,
    normalize_text,
)
from prompting import (
    ESCALATION_MESSAGE,
    FOLLOWUP_CHANNEL_QUESTION,
    FOLLOWUP_CONFIRM_TEMPLATE,
    FOLLOWUP_TIME_QUESTION,
    NO_FOLLOWUP_CLOSE,
    OPENING_DISCLOSURE,
    UNANSWERABLE_FALLBACK,
    VOICE_SYSTEM_INSTRUCTIONS,
    closing_message,
    resolution_question,
)


YES_PATTERNS = {"yes", "y", "yep", "yeah", "correct", "that helps", "solved", "resolved"}
NO_PATTERNS = {"no", "n", "nope", "not really", "didn't help", "did not help", "still need help"}


@dataclass
class ConversationState:
    awaiting_status_identifier: bool = False
    awaiting_resolution_confirmation: bool = False
    awaiting_followup_interest: bool = False
    awaiting_followup_channel: bool = False
    awaiting_followup_time: bool = False
    preferred_channel: Optional[str] = None
    preferred_time: Optional[str] = None
    account_identifier: Optional[str] = None
    failed_payment_mentions: int = 0


class SimpleLoansPolicyEngine:
    """Deterministic policy engine to avoid hallucinations and enforce fallback."""

    def __init__(self, seed: int = 7) -> None:
        self.state = ConversationState()
        self._rng = random.Random(seed)

    def answer(self, user_message: str) -> str:
        text = user_message.strip()
        normalized = normalize_text(text)

        if "failed payment" in normalized or "payment failed" in normalized:
            self.state.failed_payment_mentions += 1

        if self._requires_immediate_escalation(normalized):
            self._reset_pending_prompts()
            return ESCALATION_MESSAGE

        if self.state.awaiting_followup_interest:
            self.state.awaiting_followup_interest = False
            if _is_yes(normalized):
                self.state.awaiting_followup_channel = True
                return FOLLOWUP_CHANNEL_QUESTION
            return NO_FOLLOWUP_CLOSE

        if self.state.awaiting_followup_channel:
            self.state.preferred_channel = text
            self.state.awaiting_followup_channel = False
            self.state.awaiting_followup_time = True
            return FOLLOWUP_TIME_QUESTION

        if self.state.awaiting_followup_time:
            self.state.preferred_time = text
            self.state.awaiting_followup_time = False
            channel = self.state.preferred_channel or "your preferred channel"
            when = self.state.preferred_time or "your preferred time"
            return FOLLOWUP_CONFIRM_TEMPLATE.format(channel=channel, when=when)

        if self.state.awaiting_status_identifier:
            if _looks_like_identifier(text):
                self.state.account_identifier = text
                self.state.awaiting_status_identifier = False
                return (
                    f"Thank you. {LOAN_STATUS_AND_DISBURSEMENT} "
                    f"{self._resolution_question()}"
                )
            return "I still need your account identifier to check status. Please share it when ready."

        if self.state.awaiting_resolution_confirmation:
            if _is_yes(normalized):
                self.state.awaiting_resolution_confirmation = False
                return closing_message(self._rng)
            if _is_no(normalized):
                self.state.awaiting_resolution_confirmation = False
                self.state.awaiting_followup_channel = True
                return FOLLOWUP_CHANNEL_QUESTION

        if self._is_status_request(normalized):
            self.state.awaiting_status_identifier = True
            return "I can help with your loan status. Please share your account identifier."

        matched_article = match_article(normalized)
        if matched_article is None:
            self.state.awaiting_followup_interest = True
            return UNANSWERABLE_FALLBACK

        answer_text = matched_article.answer
        if matched_article.intent == "loan_status_and_disbursement":
            self.state.awaiting_status_identifier = False

        return f"{answer_text} {self._resolution_question()}"

    def _requires_immediate_escalation(self, normalized_message: str) -> bool:
        if any(keyword in normalized_message for keyword in ESCALATION_KEYWORDS):
            return True
        if self.state.failed_payment_mentions >= 2:
            return True
        if "policy exception" in normalized_message or "make an exception" in normalized_message:
            return True
        return False

    def _is_status_request(self, normalized_message: str) -> bool:
        status_phrases = (
            "status",
            "where is my loan",
            "check my loan",
            "my application",
            "application status",
            "pending",
        )
        return any(phrase in normalized_message for phrase in status_phrases) or any(
            keyword in normalized_message for keyword in STATUS_IDENTIFIER_KEYWORDS
        )

    def _resolution_question(self) -> str:
        self.state.awaiting_resolution_confirmation = True
        return resolution_question(self._rng)

    def _reset_pending_prompts(self) -> None:
        self.state.awaiting_status_identifier = False
        self.state.awaiting_resolution_confirmation = False
        self.state.awaiting_followup_interest = False
        self.state.awaiting_followup_channel = False
        self.state.awaiting_followup_time = False


class SimpleLoansVoiceAgent(Agent):
    """LiveKit Agent that routes user turns through a deterministic policy engine."""

    def __init__(self) -> None:
        super().__init__(instructions=VOICE_SYSTEM_INSTRUCTIONS)
        self._policy = SimpleLoansPolicyEngine()

    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        model_settings: ModelSettings,
    ) -> AsyncIterable[str]:
        del tools, model_settings
        user_text = _latest_user_message(chat_ctx)
        response = self._policy.answer(user_text)
        return _single_response_stream(response)


def prewarm(proc: JobProcess) -> None:
    """Load VAD and turn detector once per process for low cold-start latency."""
    proc.userdata["vad"] = silero.VAD.load(
        min_speech_duration=0.05,
        min_silence_duration=0.45,
        prefix_padding_duration=0.35,
        activation_threshold=0.55,
        sample_rate=16000,
        force_cpu=True,
    )
    proc.userdata["turn_detector"] = MultilingualModel()


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    await ctx.wait_for_participant()

    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        turn_detection=ctx.proc.userdata["turn_detector"],
        stt=deepgram.STT(
            model=os.getenv("DEEPGRAM_MODEL", "nova-3"),
            language="en-US",
            endpointing_ms=25,
            no_delay=True,
            smart_format=True,
            filler_words=False,
        ),
        tts=cartesia.TTS(
            model=os.getenv("CARTESIA_MODEL", "sonic-3"),
            voice=os.getenv("CARTESIA_VOICE_ID", "f786b574-daa5-4673-aa0c-cbe3e8534c02"),
            language="en",
            speed=1.05,
            text_pacing=False,
        ),
        allow_interruptions=True,
        min_endpointing_delay=0.25,
        max_endpointing_delay=1.2,
        preemptive_generation=True,
    )

    await session.start(agent=SimpleLoansVoiceAgent(), room=ctx.room)
    await session.say(OPENING_DISCLOSURE, allow_interruptions=True)


def _latest_user_message(chat_ctx: llm.ChatContext) -> str:
    for message in reversed(chat_ctx.messages()):
        if str(message.role) == "user":
            return message.text_content
    return ""


async def _single_response_stream(text: str) -> AsyncIterable[str]:
    yield text


def _is_yes(normalized_value: str) -> bool:
    return _starts_with_or_equals(normalized_value, YES_PATTERNS)


def _is_no(normalized_value: str) -> bool:
    return _starts_with_or_equals(normalized_value, NO_PATTERNS)


def _starts_with_or_equals(normalized_value: str, candidates: set[str]) -> bool:
    for candidate in candidates:
        if normalized_value == candidate or normalized_value.startswith(f"{candidate} "):
            return True
    return False


def _looks_like_identifier(value: str) -> bool:
    compact = value.strip()
    return bool(re.search(r"[a-zA-Z]", compact) and re.search(r"\d", compact) and len(compact) >= 5)


if __name__ == "__main__":
    load_dotenv()
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name="simple-loans-voice-support",
        )
    )
