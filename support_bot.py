from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Awaitable, Callable
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
class LiveTransferOutcome:
    success: bool
    message: str
    method: str
    target: str | None = None
    participant_identity: str | None = None


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
    live_transfer_requested: bool = False
    live_transfer_started: bool = False
    live_transfer_connected: bool = False
    live_transfer_method: str | None = None
    live_transfer_target: str | None = None
    live_transfer_participant_identity: str | None = None
    live_transfer_reason: str | None = None
    live_transfer_error: str | None = None
    handoff_summary: str | None = None
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
            disposition.live_transfer_requested = True
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
            "live_transfer_requested": disposition.live_transfer_requested,
            "live_transfer_connected": disposition.live_transfer_connected,
            "live_transfer_method": disposition.live_transfer_method,
            "live_transfer_target": disposition.live_transfer_target,
            "live_transfer_error": disposition.live_transfer_error,
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


def _as_bool(value: str, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _normalize_transfer_target(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    if raw.startswith("+"):
        return raw
    digits_only = re.sub(r"\D+", "", raw)
    if len(digits_only) == 10:
        return f"+1{digits_only}"
    if len(digits_only) == 11 and digits_only.startswith("1"):
        return f"+{digits_only}"
    return raw


class LiveTransferService:
    def __init__(self) -> None:
        self.mode = os.getenv("LIVE_TRANSFER_MODE", "sip").strip().lower()
        self.default_target = os.getenv("LIVE_TRANSFER_TARGET_NUMBER", "").strip()
        self.sip_trunk_id = os.getenv("LIVE_TRANSFER_SIP_TRUNK_ID", "").strip()
        self.participant_name = (
            os.getenv("LIVE_TRANSFER_PARTICIPANT_NAME", "Human Support Specialist").strip()
            or "Human Support Specialist"
        )
        self.wait_until_answered = _as_bool(
            os.getenv("LIVE_TRANSFER_WAIT_UNTIL_ANSWERED", "true"),
            default=True,
        )
        self.transfer_webhook_url = os.getenv("LIVE_TRANSFER_WEBHOOK_URL", "").strip()

    async def transfer(
        self,
        *,
        room_name: str,
        reason: str,
        handoff_summary: str,
        transfer_target: str = "",
    ) -> LiveTransferOutcome:
        if self.mode == "disabled":
            return LiveTransferOutcome(
                success=False,
                method="disabled",
                message="Live transfer is disabled in configuration.",
            )

        target = _normalize_transfer_target(transfer_target) or _normalize_transfer_target(
            self.default_target
        )
        if self.mode == "webhook":
            return await self._transfer_via_webhook(
                room_name=room_name,
                reason=reason,
                handoff_summary=handoff_summary,
                target=target,
            )

        return await self._transfer_via_sip(
            room_name=room_name,
            reason=reason,
            handoff_summary=handoff_summary,
            target=target,
        )

    async def _transfer_via_sip(
        self,
        *,
        room_name: str,
        reason: str,
        handoff_summary: str,
        target: str,
    ) -> LiveTransferOutcome:
        if not target:
            return LiveTransferOutcome(
                success=False,
                method="sip",
                message=(
                    "No transfer target is configured. Set LIVE_TRANSFER_TARGET_NUMBER "
                    "or pass transfer_target in the tool call."
                ),
            )
        if not self.sip_trunk_id:
            return LiveTransferOutcome(
                success=False,
                method="sip",
                message="LIVE_TRANSFER_SIP_TRUNK_ID is not configured.",
            )

        try:
            from livekit import api as lkapi
            from livekit.protocol.sip import CreateSIPParticipantRequest
        except Exception as exc:
            return LiveTransferOutcome(
                success=False,
                method="sip",
                message=f"LiveKit SIP SDK is unavailable: {exc}",
            )

        participant_identity = (
            f"human-transfer-{datetime.now(tz=timezone.utc).strftime('%Y%m%d%H%M%S')}"
        )
        req = CreateSIPParticipantRequest(
            sip_trunk_id=self.sip_trunk_id,
            sip_call_to=target,
            room_name=room_name,
            participant_identity=participant_identity,
            participant_name=self.participant_name,
            wait_until_answered=self.wait_until_answered,
        )

        livekit_api = lkapi.LiveKitAPI()
        try:
            await livekit_api.sip.create_sip_participant(req)
        except Exception as exc:
            return LiveTransferOutcome(
                success=False,
                method="sip",
                target=target,
                message=f"SIP transfer failed: {exc}",
            )
        finally:
            close_coro = getattr(livekit_api, "aclose", None)
            if callable(close_coro):
                try:
                    await close_coro()
                except Exception:
                    pass

        summary_note = handoff_summary.strip()
        if summary_note:
            message = (
                "Connected to human agent. "
                f"Handoff summary prepared: {summary_note[:220]}"
            )
        else:
            message = "Connected to human agent."
        return LiveTransferOutcome(
            success=True,
            method="sip",
            target=target,
            participant_identity=participant_identity,
            message=message,
        )

    async def _transfer_via_webhook(
        self,
        *,
        room_name: str,
        reason: str,
        handoff_summary: str,
        target: str,
    ) -> LiveTransferOutcome:
        if not self.transfer_webhook_url:
            return LiveTransferOutcome(
                success=False,
                method="webhook",
                target=target or None,
                message="LIVE_TRANSFER_WEBHOOK_URL is not configured.",
            )

        payload = {
            "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
            "room_name": room_name,
            "target": target or None,
            "reason": reason.strip(),
            "handoff_summary": handoff_summary.strip(),
            "company_name": SUPPORT_CONFIG["company_name"],
        }
        encoded = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self.transfer_webhook_url,
            data=encoded,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=10) as resp:
                if 200 <= int(resp.status) < 300:
                    return LiveTransferOutcome(
                        success=True,
                        method="webhook",
                        target=target or None,
                        message=f"Transfer webhook accepted with status {resp.status}.",
                    )
                return LiveTransferOutcome(
                    success=False,
                    method="webhook",
                    target=target or None,
                    message=f"Transfer webhook returned status {resp.status}.",
                )
        except Exception as exc:
            return LiveTransferOutcome(
                success=False,
                method="webhook",
                target=target or None,
                message=f"Transfer webhook failed: {exc}",
            )


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


LiveTransferHandler = Callable[
    [str, str, str],
    Awaitable[LiveTransferOutcome],
]


class SupportAgent(Agent):
    def __init__(
        self,
        instructions: str,
        disposition: SupportDispositionState,
        knowledge_base: KnowledgeBase,
        live_transfer_handler: LiveTransferHandler,
    ) -> None:
        super().__init__(instructions=instructions)
        self._disposition = disposition
        self._knowledge_base = knowledge_base
        self._live_transfer_handler = live_transfer_handler
        self._transfer_in_progress = False

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
    async def request_live_transfer(
        self,
        context: RunContext,
        reason: str,
        handoff_summary: str = "",
        transfer_target: str = "",
    ) -> str:
        """Connect the caller to a human support agent in real time."""
        clean_reason = reason.strip() or "Customer requested a live human transfer."
        clean_handoff_summary = handoff_summary.strip()
        clean_target = transfer_target.strip()

        self._disposition.escalation_needed = True
        self._disposition.escalation_reason = clean_reason
        self._disposition.live_transfer_requested = True
        self._disposition.live_transfer_reason = clean_reason
        if clean_handoff_summary:
            self._disposition.handoff_summary = clean_handoff_summary

        if self._disposition.live_transfer_connected:
            return (
                "TRANSFER_ALREADY_CONNECTED: A live human agent is already connected to the call."
            )
        if self._transfer_in_progress:
            return "TRANSFER_IN_PROGRESS: Live transfer is already in progress."

        self._transfer_in_progress = True
        self._disposition.live_transfer_started = True
        try:
            outcome = await self._live_transfer_handler(
                clean_reason,
                clean_handoff_summary,
                clean_target,
            )
        finally:
            self._transfer_in_progress = False

        self._disposition.live_transfer_method = outcome.method
        if outcome.target:
            self._disposition.live_transfer_target = outcome.target
        if outcome.participant_identity:
            self._disposition.live_transfer_participant_identity = (
                outcome.participant_identity
            )

        if outcome.success:
            self._disposition.live_transfer_connected = True
            self._disposition.live_transfer_error = None
            return f"TRANSFER_CONNECTED: {outcome.message}"

        self._disposition.live_transfer_connected = False
        self._disposition.live_transfer_error = outcome.message
        return f"TRANSFER_FAILED: {outcome.message}"

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


def build_agent(
    *,
    live_transfer_handler: LiveTransferHandler,
) -> tuple[SupportAgent, SupportDispositionState, KnowledgeBase]:
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
            live_transfer_handler=live_transfer_handler,
        ),
        disposition,
        kb,
    )


async def entrypoint(ctx: JobContext) -> None:
    transfer_service = LiveTransferService()

    async def _handle_live_transfer(
        reason: str,
        handoff_summary: str,
        transfer_target: str,
    ) -> LiveTransferOutcome:
        room_name = str(getattr(ctx.room, "name", "unknown"))
        return await transfer_service.transfer(
            room_name=room_name,
            reason=reason,
            handoff_summary=handoff_summary,
            transfer_target=transfer_target,
        )

    agent, disposition, kb = build_agent(
        live_transfer_handler=_handle_live_transfer,
    )
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
    print(
        "Live transfer mode: "
        f"{transfer_service.mode or 'sip'}",
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
