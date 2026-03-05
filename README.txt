Simple Loans Natural Support Bot

This project provides a natural, policy-grounded support bot for Simple Loans.
The bot introduces itself as a virtual assistant in the opening message, then
responds in a concise human-support style.

Key behaviors implemented:
- Uses the provided Simple Loans knowledge base as source of truth.
- Keeps responses concise and clear.
- Asks one question at a time.
- Confirms resolution before ending.
- Offers follow-up channel and time if unresolved.
- Escalates immediately for fraud/legal/identity mismatch/supervisor requests,
  repeated failed payments, or policy exceptions.

Run locally:

1) Start chat
   python3 app.py

2) Run tests
   python3 -m unittest discover -s tests -p "test_*.py"
