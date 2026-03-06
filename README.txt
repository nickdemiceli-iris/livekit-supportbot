So Simple Customer Support Voice Agent (LiveKit)

This project provides a LiveKit voice support bot with a conversation flow tuned for natural support calls and strict answer behavior.

What it does:
- Opens every call with exactly:
  "Hello, thank you for calling so simple customer support how can i help you today."
- Uses a local knowledge base (`data/knowledge_base.json`) to answer support questions.
- If no answer is found, it replies with exactly:
  "I apologize, but I do not have the answer to that question. I can note this down for one of our representatives to get back to you."
- Logs unanswered questions to:
  `data/unanswered_questions.jsonl`
- After each support answer, it asks:
  "Do you need any other help today?"
- Handles quick social greetings naturally, then steers back to support.

Files:
- `support_agent.py` - LiveKit agent entrypoint and conversation rules
- `knowledge_base.py` - KB matching and unanswered-question logging
- `data/knowledge_base.json` - editable support knowledge base entries

Setup:
1) Create and activate a Python 3.10+ virtual environment.
2) Install dependencies:
   `pip install -r requirements.txt`
3) Copy `.env.example` to `.env` and fill your keys.
4) Run in dev mode:
   `python support_agent.py dev`

Customizing your knowledge base:
- Edit `data/knowledge_base.json` and add entries in this shape:
  {
    "id": "unique-id",
    "question": "Canonical customer question",
    "keywords": ["related", "search", "terms"],
    "answer": "Approved support answer"
  }

Notes:
- For best results, keep answers short and customer-ready.
- Add synonyms in `keywords` to improve match quality.
