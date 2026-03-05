LiveKit Sales Agent with Fast Local Knowledge Base

This repository contains a production-ready LiveKit voice sales agent that:

- sounds natural and consultative (expert sales style),
- uses LiveKit `AgentSession` + tools,
- answers policy and pricing questions from a local knowledge base with low latency,
- captures transcript and call disposition,
- writes post-call reports to disk and optionally posts to a webhook.

Files:

- `support_bot.py` - main LiveKit sales worker
- `knowledge_base.py` - fast local KB indexing + retrieval
- `prompting.py` - sales-specific system prompt builder
- `knowledge_base/` - add your sales/policy docs (`.md`, `.txt`, `.json`, `.yaml`, `.yml`)

Quick start:

1) Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Configure environment

```bash
cp .env.example .env
```

Set at minimum:

- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `OPENAI_API_KEY`
- `ASSEMBLYAI_API_KEY`
- `CARTESIA_API_KEY`

3) Add your knowledge base files

Place your sales and policy docs in `knowledge_base/`.
The bot indexes them at startup and serves answers through the `lookup_knowledge_base` tool.

4) Run the worker

```bash
python3 support_bot.py dev
```

How the bot answers quickly:

- The KB is loaded and indexed once at startup.
- Retrieval uses an in-memory inverted index with BM25-style scoring.
- `lookup_knowledge_base` returns an evidence-backed answer plus excerpts.
- The assistant calls KB lookup only when factual precision is needed, reducing latency and hallucinations.
- Low-latency defaults are enabled for English voice calls (`ASSEMBLYAI_STT_MODEL=universal-streaming`, `AGENT_TURN_DETECTION=stt`).
- A response watchdog forces fast acknowledgment if the model is slow to answer.
- Greeting handling avoids repeated self-introductions for natural flow.

Production resiliency:

- STT runs with automatic failover (AssemblyAI primary -> OpenAI fallback) when available.
- TTS runs with automatic failover (Cartesia primary -> OpenAI fallback) when available.
- Configure fallback behavior in `.env`:
  - `OPENAI_STT_FALLBACK_ENABLED=true`
  - `STT_FALLBACK_ATTEMPT_TIMEOUT_SEC=8.0`
  - `OPENAI_TTS_FALLBACK_ENABLED=true`
  - `TTS_FALLBACK_ATTEMPT_TIMEOUT_SEC=8.0`
  - `RESPONSE_WATCHDOG_ACK_SEC=2.6`
  - `RESPONSE_WATCHDOG_FORCE_SEC=5.8`
  - `RESPONSE_WATCHDOG_RETRY_SEC=2.4`

Company baseline:

- Set `SUPPORT_COMPANY_DESCRIPTION` in `.env`.
- The agent can answer "who are you / what is <company>" immediately from this baseline without waiting on KB tools.

Live transfer to a human agent:

- The bot supports real-time handoff with the `request_live_transfer` tool.
- Default mode is SIP dial-out into the same LiveKit room.
- Configure:
  - `LIVE_TRANSFER_MODE=sip`
  - `LIVE_TRANSFER_SIP_TRUNK_ID=<your outbound trunk id>`
  - `LIVE_TRANSFER_TARGET_NUMBER=<human agent phone number>`
  - 10-digit US numbers are auto-normalized to E.164 (for example `7863891976` -> `+17863891976`).
- Optional webhook mode:
  - `LIVE_TRANSFER_MODE=webhook`
  - `LIVE_TRANSFER_WEBHOOK_URL=<your transfer orchestration endpoint>`

Post-call output:

- JSON reports are saved to `post_call_reports/` by default.
- You can change output path with `SUPPORT_REPORT_OUTPUT_DIR`.
- Optional webhook post with `SUPPORT_REPORT_WEBHOOK_URL`.
