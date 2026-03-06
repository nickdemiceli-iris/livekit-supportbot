from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from livekit.agents import Agent, AgentSession, JobContext, RunContext, WorkerOptions, cli, function_tool

from knowledge_base import FALLBACK_MESSAGE, KnowledgeBase

OPENING_GREETING = "Hello, thank you for calling so simple customer support how can i help you today."

SUPPORT_AGENT_INSTRUCTIONS = f"""
You are a voice customer support assistant for So Simple Customer Support.

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
        super().__init__(instructions=SUPPORT_AGENT_INSTRUCTIONS)
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
    kb = KnowledgeBase.from_json(
        path=root / "data" / "knowledge_base.json",
        unanswered_log_path=root / "data" / "unanswered_questions.jsonl",
    )

    session = AgentSession(
        stt=os.getenv("LIVEKIT_STT", "deepgram/nova-3:en"),
        llm=os.getenv("LIVEKIT_LLM", "openai/gpt-4.1-mini"),
        tts=os.getenv("LIVEKIT_TTS", "openai/gpt-4o-mini-tts:alloy"),
    )

    await session.start(
        room=ctx.room,
        agent=SupportVoiceAgent(knowledge_base=kb),
    )

    await session.generate_reply(
        instructions=f'Say exactly this sentence and nothing else: "{OPENING_GREETING}"'
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
