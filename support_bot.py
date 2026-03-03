from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any
from urllib import request

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RunContext,
    WorkerOptions,
    cli,
    function_tool,
)
from livekit.plugins import assemblyai, cartesia, openai, silero

from knowledge_base import KnowledgeBase
from prompting import build_system_prompt

load_dotenv()


SUPPORT_CONFIG: dict[str, str] = {
    "company_name": os.getenv("SUPPORT_COMPANY_NAME", "Simple Loans"),
    "agent_name": os.getenv("SUPPORT_AGENT_NAME", "Abby"),
}


@dataclass
class SupportDispositionState:
    customer_identified: bool = False
    customer_name: str | None = None
    account_identifier: str | None = None
    issue_summary: str | None = None
    product_area: str | None = None
    troubleshooting_steps: list[str] = field(default_factory=list)
    resolved: bool | None = None
    resolution_summary: str | None = None
    escalation_needed: bool = False
    escalation_reason: str | None = None
    follow_up_needed: bool = False
    follow_up_datetime: str | None = None
    preferred_contact_channel: str | None = None
    notes: str = ""


@dataclass
class TranscriptTurn:
    timestamp_utc: str
    role: str
    text: str
    interrupted: bool = False


def _to_role_string(role: Any) -> str:
    value = getattr(role, "value", role)
    return str(value).lower()


def _extract_item_text(item: Any) -> str:
    text_content = getattr(item, "text_content", None)
    if text_content:
        return str(text_content).strip()

    content = getattr(item, "content", None)
    if not content:
        return ""

    parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            if part.strip():
                parts.append(part.strip())
            continue
        transcript = getattr(part, "transcript", None)
        if transcript and str(transcript).strip():
            parts.append(str(transcript).strip())
    return " ".join(parts).strip()


def _is_user_role(role: str) -> bool:
    return role in {"user", "human", "customer"}


def _derive_outcome(disposition: SupportDispositionState) -> str:
    if disposition.resolved is True:
        return "resolved"
    if disposition.escalation_needed:
        return "escalated"
    if disposition.resolved is False:
        return "unresolved"
    return "incomplete"


def _derive_follow_up_needed(disposition: SupportDispositionState) -> bool:
    if disposition.follow_up_needed:
        return True
    if disposition.escalation_needed:
        return True
    if disposition.resolved is False:
        return True
    return False


def _infer_disposition_from_transcript(
    disposition: SupportDispositionState,
    transcript: list[TranscriptTurn],
) -> None:
    user_turns = [turn for turn in transcript if _is_user_role(turn.role)]
    if not user_turns:
        return

    if not disposition.issue_summary:
        for turn in user_turns:
            text = turn.text.strip()
            if len(text) >= 15:
                disposition.issue_summary = text
                break

    user_text_blob = " ".join(turn.text.lower() for turn in user_turns)
    if disposition.resolved is None:
        resolved_markers = [
            "that fixed it",
            "works now",
            "it's working",
            "problem solved",
            "thank you that helped",
        ]
        unresolved_markers = [
            "still broken",
            "still not working",
            "didn't work",
            "not fixed",
        ]
        if any(marker in user_text_blob for marker in resolved_markers):
            disposition.resolved = True
        elif any(marker in user_text_blob for marker in unresolved_markers):
            disposition.resolved = False

    if not disposition.escalation_needed:
        escalation_markers = [
            "talk to a person",
            "human agent",
            "supervisor",
            "escalate",
            "transfer me",
        ]
        if any(marker in user_text_blob for marker in escalation_markers):
            disposition.escalation_needed = True
            if not disposition.escalation_reason:
                disposition.escalation_reason = "Customer requested human escalation."


def _build_post_call_report(
    *,
    disposition: SupportDispositionState,
    transcript: list[TranscriptTurn],
    call_started_at: datetime,
    call_ended_at: datetime,
    room_name: str,
) -> dict[str, Any]:
    outcome = _derive_outcome(disposition)
    follow_up_needed = _derive_follow_up_needed(disposition)
    return {
        "call_metadata": {
            "room_name": room_name,
            "company_name": SUPPORT_CONFIG["company_name"],
            "agent_name": SUPPORT_CONFIG["agent_name"],
            "started_at_utc": call_started_at.isoformat(),
            "ended_at_utc": call_ended_at.isoformat(),
            "duration_seconds": max(
                0, int((call_ended_at - call_started_at).total_seconds())
            ),
        },
        "transcript": [asdict(turn) for turn in transcript],
        "analysis": {
            "outcome": outcome,
            "follow_up_needed": follow_up_needed,
            "follow_up_datetime": disposition.follow_up_datetime,
            "escalation_needed": disposition.escalation_needed,
            "escalation_reason": disposition.escalation_reason,
            "troubleshooting_step_count": len(disposition.troubleshooting_steps),
        },
        "disposition": asdict(disposition),
    }


def _persist_post_call_report(report: dict[str, Any]) -> str:
    output_dir = os.getenv("SUPPORT_REPORT_OUTPUT_DIR", "post_call_reports")
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    customer_name = str(
        report.get("disposition", {}).get("customer_name", "unknown")
    ).lower()
    safe_name = re.sub(r"[^a-z0-9]+", "_", customer_name).strip("_") or "unknown"
    path = os.path.join(output_dir, f"{timestamp}_{safe_name}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    return os.path.abspath(path)


def _post_report_to_webhook(report: dict[str, Any]) -> tuple[bool, str]:
    webhook_url = os.getenv("SUPPORT_REPORT_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return False, "SUPPORT_REPORT_WEBHOOK_URL not set; webhook post skipped."
    payload = json.dumps(report).encode("utf-8")
    req = request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=10) as resp:
            return True, f"Webhook post succeeded with status {resp.status}."
    except Exception as exc:  # pragma: no cover
        return False, f"Webhook post failed: {exc}"


def _finalize_post_call(
    *,
    disposition: SupportDispositionState,
    transcript: list[TranscriptTurn],
    call_started_at: datetime,
    room_name: str,
    trigger: str,
) -> None:
    _infer_disposition_from_transcript(disposition, transcript)
    call_ended_at = datetime.now(tz=timezone.utc)
    report = _build_post_call_report(
        disposition=disposition,
        transcript=transcript,
        call_started_at=call_started_at,
        call_ended_at=call_ended_at,
        room_name=room_name,
    )
    report["call_metadata"]["finalization_trigger"] = trigger
    report_path = _persist_post_call_report(report)
    posted, webhook_message = _post_report_to_webhook(report)

    print("=== SUPPORT DISPOSITION SUMMARY ===", flush=True)
    print(json.dumps(asdict(disposition), indent=2), flush=True)
    print("=== POST CALL REPORT ===", flush=True)
    print(json.dumps(report, indent=2), flush=True)
    print(f"Saved report: {report_path}", flush=True)
    print(webhook_message, flush=True)
    if posted:
        print("Webhook delivery: success", flush=True)


@lru_cache(maxsize=4)
def _load_knowledge_base(knowledge_dir: str) -> KnowledgeBase:
    kb = KnowledgeBase(knowledge_dir=knowledge_dir)
    kb.load()
    return kb


class SupportAgent(Agent):
    def __init__(
        self,
        instructions: str,
        disposition: SupportDispositionState,
        knowledge_base: KnowledgeBase,
    ) -> None:
        super().__init__(instructions=instructions)
        self._disposition = disposition
        self._knowledge_base = knowledge_base

    @function_tool
    async def lookup_knowledge_base(
        self,
        context: RunContext,
        question: str,
        top_k: int = 1,
    ) -> str:
        """Search the internal knowledge base and return the most relevant evidence-backed answer."""
        safe_top_k = max(1, min(top_k, 5))
        return self._knowledge_base.render_tool_payload(question, top_k=safe_top_k)

    @function_tool
    async def record_customer_identity(
        self,
        context: RunContext,
        customer_name: str,
        account_identifier: str = "",
        note: str = "",
    ) -> str:
        """Record customer identity details when known."""
        cleaned_name = customer_name.strip()
        self._disposition.customer_identified = bool(cleaned_name)
        self._disposition.customer_name = cleaned_name or self._disposition.customer_name
        if account_identifier.strip():
            self._disposition.account_identifier = account_identifier.strip()
        if note:
            self._append_note(note)
        return "Customer identity recorded."

    @function_tool
    async def record_issue_details(
        self,
        context: RunContext,
        issue_summary: str,
        product_area: str = "",
        note: str = "",
    ) -> str:
        """Record the customer's issue summary and product area."""
        self._disposition.issue_summary = issue_summary.strip()
        if product_area.strip():
            self._disposition.product_area = product_area.strip()
        if note:
            self._append_note(note)
        return "Issue details recorded."

    @function_tool
    async def record_troubleshooting_step(
        self,
        context: RunContext,
        step: str,
    ) -> str:
        """Record a troubleshooting step suggested or completed during the call."""
        clean_step = step.strip()
        if clean_step:
            self._disposition.troubleshooting_steps.append(clean_step)
        return "Troubleshooting step recorded."

    @function_tool
    async def record_resolution(
        self,
        context: RunContext,
        resolved: bool,
        resolution_summary: str = "",
        note: str = "",
    ) -> str:
        """Record whether the issue is resolved and summarize final outcome."""
        self._disposition.resolved = resolved
        if resolution_summary.strip():
            self._disposition.resolution_summary = resolution_summary.strip()
        if note:
            self._append_note(note)
        return "Resolution outcome recorded."

    @function_tool
    async def mark_escalation(
        self,
        context: RunContext,
        reason: str,
        note: str = "",
    ) -> str:
        """Record that the issue must be escalated to a human support specialist."""
        self._disposition.escalation_needed = True
        self._disposition.escalation_reason = reason.strip() or "Escalation requested."
        if note:
            self._append_note(note)
        return "Escalation recorded."

    @function_tool
    async def schedule_follow_up(
        self,
        context: RunContext,
        next_step_datetime: str,
        preferred_contact_channel: str,
        note: str = "",
    ) -> str:
        """Record follow-up schedule and preferred contact channel."""
        self._disposition.follow_up_needed = True
        self._disposition.follow_up_datetime = next_step_datetime.strip()
        self._disposition.preferred_contact_channel = preferred_contact_channel.strip()
        if note:
            self._append_note(note)
        return "Follow-up details recorded."

    def _append_note(self, note: str) -> None:
        clean_note = note.strip()
        if not clean_note:
            return
        if self._disposition.notes:
            self._disposition.notes += f" | {clean_note}"
        else:
            self._disposition.notes = clean_note


def build_agent() -> tuple[SupportAgent, SupportDispositionState, KnowledgeBase]:
    company_name = SUPPORT_CONFIG["company_name"]
    agent_name = SUPPORT_CONFIG["agent_name"]
    kb_dir = os.path.abspath(os.getenv("KNOWLEDGE_BASE_DIR", "knowledge_base"))
    kb = _load_knowledge_base(kb_dir)

    prompt = build_system_prompt(
        company_name=company_name,
        agent_name=agent_name,
        knowledge_base_summary=kb.inventory_summary(),
    )
    disposition = SupportDispositionState()
    return (
        SupportAgent(
            instructions=prompt,
            disposition=disposition,
            knowledge_base=kb,
        ),
        disposition,
        kb,
    )


async def entrypoint(ctx: JobContext) -> None:
    agent, disposition, kb = build_agent()
    await ctx.connect()
    call_started_at = datetime.now(tz=timezone.utc)
    transcript: list[TranscriptTurn] = []
    finalized = False

    session = AgentSession(
        stt=assemblyai.STT(
            model=os.getenv("ASSEMBLYAI_STT_MODEL", "universal-streaming-multilingual")
        ),
        llm=openai.LLM(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini")),
        tts=cartesia.TTS(
            model=os.getenv("CARTESIA_TTS_MODEL", "sonic-3"),
            language=os.getenv("TTS_LANGUAGE", "en"),
        ),
        vad=silero.VAD.load(),
    )

    @session.on("conversation_item_added")
    def _on_conversation_item_added(event: Any) -> None:
        item = getattr(event, "item", None)
        if item is None:
            return
        text = _extract_item_text(item)
        if not text:
            return
        transcript.append(
            TranscriptTurn(
                timestamp_utc=datetime.now(tz=timezone.utc).isoformat(),
                role=_to_role_string(getattr(item, "role", "unknown")),
                text=text,
                interrupted=bool(getattr(item, "interrupted", False)),
            )
        )

    def _finalize_once(trigger: str) -> None:
        nonlocal finalized
        if finalized:
            return
        finalized = True
        room_name = str(getattr(ctx.room, "name", "unknown"))
        try:
            _finalize_post_call(
                disposition=disposition,
                transcript=transcript,
                call_started_at=call_started_at,
                room_name=room_name,
                trigger=trigger,
            )
        except Exception as exc:
            print(f"Post-call finalization error: {exc}", flush=True)

    @session.on("close")
    def _on_session_close(event: Any) -> None:
        reason = str(getattr(event, "reason", "unknown"))
        _finalize_once(f"session_close:{reason}")

    print(
        "Knowledge base loaded: "
        f"{kb.source_count} sources, {kb.chunk_count} chunks.",
        flush=True,
    )

    company_name = SUPPORT_CONFIG["company_name"]
    agent_name = SUPPORT_CONFIG["agent_name"]
    await session.start(room=ctx.room, agent=agent)
    await session.generate_reply(
        instructions=(
            "Start the support call with this exact line: "
            f"\"Hi, thank you for contacting {company_name} support. "
            f"I'm {agent_name}. How can I help you today?\""
        )
    )

    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        _finalize_once("entrypoint_finally")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
