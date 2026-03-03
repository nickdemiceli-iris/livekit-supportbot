LiveKit Support Bot with Fast Local Knowledge Base

This repository contains a production-ready LiveKit voice support bot that:

- sounds natural and concise (modeled after your sales-bot structure),
- uses LiveKit `AgentSession` + tools,
- answers support questions from a local knowledge base with low latency,
- captures transcript and support disposition,
- writes post-call reports to disk and optionally posts to a webhook.

Files:

- `support_bot.py` - main LiveKit support worker
- `knowledge_base.py` - fast local KB indexing + retrieval
- `prompting.py` - support-specific system prompt builder
- `knowledge_base/` - add your support docs (`.md`, `.txt`, `.json`, `.yaml`, `.yml`)

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

Place your support docs in `knowledge_base/`.
The bot indexes them at startup and serves answers through the `lookup_knowledge_base` tool.

4) Run the worker

```bash
python3 support_bot.py dev
```

How the bot answers quickly:

- The KB is loaded and indexed once at startup.
- Retrieval uses an in-memory inverted index with BM25-style scoring.
- `lookup_knowledge_base` returns an evidence-backed answer plus excerpts.
- The assistant is instructed to call KB lookup before factual responses, reducing hallucinations.

Post-call output:

- JSON reports are saved to `post_call_reports/` by default.
- You can change output path with `SUPPORT_REPORT_OUTPUT_DIR`.
- Optional webhook post with `SUPPORT_REPORT_WEBHOOK_URL`.
