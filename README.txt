So Simple Customer Support Voice Agent (LiveKit)

This project provides a LiveKit voice support bot with a conversation flow tuned for natural support calls and strict answer behavior.

What it does:
- Opens every call with exactly:
  "Hello, thank you for calling so simple customer support how can i help you today."
- Uses a local knowledge base directory (`KNOWLEDGE_BASE_DIR`, default `knowledge_base`) to answer support questions.
- If no answer is found, it replies with exactly:
  "I apologize, but I do not have the answer to that question. I can note this down for one of our representatives to get back to you."
- Logs unanswered questions to:
  `<KNOWLEDGE_BASE_DIR>/unanswered_questions.jsonl`
- After each support answer, it asks:
  "Do you need any other help today?"
- Handles quick social greetings naturally, then steers back to support.
- Uses STT failover chain:
  AssemblyAI primary -> OpenAI fallback
- Uses TTS failover chain:
  Cartesia primary -> OpenAI fallback

Files:
- `support_agent.py` - LiveKit agent entrypoint and conversation rules
- `knowledge_base.py` - KB matching and unanswered-question logging
- `knowledge_base/knowledge_base.json` - editable support knowledge base entries

Setup:
1) Create and activate a Python 3.10+ virtual environment.
2) Install dependencies:
   `pip install -r requirements.txt`
3) Copy `.env.example` to `.env` and fill your keys.
4) Run in dev mode:
   `python3 support_agent.py dev`
   (The app auto-loads `.env` via `python-dotenv`.)

Customizing your knowledge base:
- Edit `knowledge_base/knowledge_base.json` (or add more `*.json` files in `KNOWLEDGE_BASE_DIR`) and add entries in this shape:
  {
    "id": "unique-id",
    "question": "Canonical customer question",
    "keywords": ["related", "search", "terms"],
    "answer": "Approved support answer"
  }

Notes:
- For best results, keep answers short and customer-ready.
- Add synonyms in `keywords` to improve match quality.
- `SUPPORT_COMPANY_NAME`, `SUPPORT_AGENT_NAME`, and `SUPPORT_COMPANY_DESCRIPTION` are used in the assistant's system instructions.
- `SUPPORT_OPENING_GREETING` can override the opening script if needed.
- If startup fails with missing config, verify `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` are set in `.env`.
