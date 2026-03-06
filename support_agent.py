from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RunContext,
    WorkerOptions,
    cli,
    function_tool,
    stt as stt_adapter,
    tts as tts_adapter,
)
from livekit.plugins import assemblyai, cartesia, openai

from knowledge_base import FALLBACK_MESSAGE, KnowledgeBase

DEFAULT_OPENING_GREETING = "Hello, thank you for calling so simple customer support how can i help you today."


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return float(value)


def _prefixed_model(provider: str, model: str) -> str:
    if "/" in model:
        return model
    return f"{provider}/{model}"


def _build_stt_pipeline() -> Any:
    stt_providers: list[Any] = []

    if _env_bool("ASSEMBLYAI_STT_ENABLED", True):
        stt_providers.append(
            assemblyai.STT(
                model=os.getenv("ASSEMBLYAI_STT_MODEL", "universal-streaming"),
            )
        )

    if _env_bool("OPENAI_STT_FALLBACK_ENABLED", True):
        stt_providers.append(
            openai.STT(
                model=os.getenv("OPENAI_STT_MODEL", "gpt-4o-transcribe"),
                language=os.getenv("OPENAI_STT_LANGUAGE", "en"),
            )
        )

    if not stt_providers:
        raise RuntimeError(
            "No STT providers enabled. Enable ASSEMBLYAI_STT_ENABLED and/or OPENAI_STT_FALLBACK_ENABLED."
        )

    if len(stt_providers) == 1:
        return stt_providers[0]

    return stt_adapter.FallbackAdapter(
        stt=stt_providers,
        attempt_timeout=_env_float("STT_FALLBACK_ATTEMPT_TIMEOUT_SEC", 8.0),
        max_retry_per_stt=int(os.getenv("STT_FALLBACK_MAX_RETRY_PER_PROVIDER", "1")),
        retry_interval=_env_float("STT_FALLBACK_RETRY_INTERVAL_SEC", 0.6),
    )


def _build_tts_pipeline() -> Any:
    tts_providers: list[Any] = []

    if _env_bool("CARTESIA_TTS_ENABLED", True):
        tts_providers.append(
            cartesia.TTS(
                model=os.getenv("CARTESIA_TTS_MODEL", "sonic-3"),
                language=os.getenv("TTS_LANGUAGE", "en"),
                speed=_env_float("CARTESIA_TTS_SPEED", 1.06),
            )
        )

    if _env_bool("OPENAI_TTS_FALLBACK_ENABLED", True):
        tts_providers.append(
            openai.TTS(
                model=os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
                voice=os.getenv("OPENAI_TTS_VOICE", "alloy"),
                speed=_env_float("OPENAI_TTS_SPEED", 1.0),
            )
        )

    if not tts_providers:
        raise RuntimeError(
            "No TTS providers enabled. Enable CARTESIA_TTS_ENABLED and/or OPENAI_TTS_FALLBACK_ENABLED."
        )

    if len(tts_providers) == 1:
        return tts_providers[0]

    return tts_adapter.FallbackAdapter(
        tts=tts_providers,
        attempt_timeout=_env_float("TTS_FALLBACK_ATTEMPT_TIMEOUT_SEC", 8.0),
        max_retry_per_tts=int(os.getenv("TTS_FALLBACK_MAX_RETRY_PER_PROVIDER", "1")),
        retry_interval=_env_float("TTS_FALLBACK_RETRY_INTERVAL_SEC", 0.6),
    )


def _build_instructions() -> str:
    company_name = os.getenv("SUPPORT_COMPANY_NAME", "So Simple Customer Support")
    agent_name = os.getenv("SUPPORT_AGENT_NAME", "Support Agent")
    company_description = os.getenv(
        "SUPPORT_COMPANY_DESCRIPTION",
        "We provide customer support and answer account and service questions.",
    ).strip()

    return f"""
You are {agent_name}, a voice customer support assistant for {company_name}.

Company context:
{company_description}

Conversation flow rules:
1) Keep responses concise and natural for live voice. Usually 1-3 short sentences.
2) For support/factual questions, ALWAYS call the lookup_knowledge_base tool first.
3) If the tool returns found=true, answer only the question using the tool answer.
4) If the tool returns found=false, say this exactly:
   "{FALLBACK_MESSAGE}"
5) After each completed support answer, ask exactly:
   "Do you need any other help today?"
6) If the caller gives a social greeting (for example "hello" or "how are you"),
   you may reply briefly and warmly (for example "Hello, how are you today?")
   and then return to support by asking what they need help with.
7) Do not invent policies, pricing, troubleshooting steps, or account data that are not in the tool result.
8) If needed, ask one brief clarifying question before tool lookup.
9) Do not mention internal tools, confidence scores, or internal implementation details.
"""


class SupportVoiceAgent(Agent):
    def __init__(self, knowledge_base: KnowledgeBase) -> None:
        super().__init__(instructions=_build_instructions())
        self._knowledge_base = knowledge_base

    @function_tool()
    async def lookup_knowledge_base(self, context: RunContext, customer_question: str) -> dict[str, Any]:
        """
        Find an answer for a customer support question using the local knowledge base.

        Args:
            customer_question: The customer's support question.
        """
        result = self._knowledge_base.answer_query(customer_question)
        return {
            "found": result.found,
            "answer": result.answer,
            "matched_article_id": result.matched_article_id,
            "matched_question": result.matched_question,
            "confidence": result.confidence,
            "noted_for_follow_up": result.noted_for_follow_up,
        }


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    root = Path(__file__).resolve().parent
    kb_dir = Path(os.getenv("KNOWLEDGE_BASE_DIR", "knowledge_base"))
    if not kb_dir.is_absolute():
        kb_dir = root / kb_dir

    kb = KnowledgeBase.from_directory(
        directory=kb_dir,
        unanswered_log_path=kb_dir / "unanswered_questions.jsonl",
    )

    session = AgentSession(
        stt=_build_stt_pipeline(),
        llm=_prefixed_model("openai", os.getenv("OPENAI_MODEL", "gpt-4.1-mini")),
        tts=_build_tts_pipeline(),
        preemptive_generation=_env_bool("AGENT_PREEMPTIVE_SYNTHESIS", True),
    )

    await session.start(
        room=ctx.room,
        agent=SupportVoiceAgent(knowledge_base=kb),
    )

    opening_greeting = os.getenv("SUPPORT_OPENING_GREETING", DEFAULT_OPENING_GREETING)
    await session.generate_reply(
        instructions=f'Say exactly this sentence and nothing else: "{opening_greeting}"'
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
