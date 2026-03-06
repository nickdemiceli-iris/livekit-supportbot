Simple Loans LiveKit Voice Support Agent

This project is a real LiveKit voice agent (not a text chatbot).
It is built for low latency and strict knowledge-base grounding.

What this implementation does:
- Uses LiveKit Agents worker pattern (`WorkerOptions`, `entrypoint`, `prewarm`)
- Prewarms Silero VAD + multilingual turn detector for faster startup
- Uses optimized speech pipeline:
  - STT: Deepgram Nova-3 (`endpointing_ms=25`, `no_delay=True`)
  - TTS: Cartesia Sonic-3 (fast voice rendering)
- Subscribes audio-only for lower runtime overhead
- Uses a deterministic policy engine so answers come from your KB only
- If out-of-scope, returns:
  - "I am unable to provide the answer for that, if you'd like I can note it down and make sure one of our representatives gets back to you."
- Supports escalation logic (fraud, legal, identity mismatch, repeated failed payments, supervisor request)
- Keeps responses concise, asks one question at a time, confirms resolution, and captures follow-up channel/time when unresolved

Files:
- `agent.py`:
  - LiveKit worker entrypoint
  - Voice session setup (VAD/STT/TTS/turn detection)
  - Deterministic Simple Loans policy engine
- `knowledgebase.py`:
  - Knowledge articles and keyword matcher
- `prompting.py`:
  - Voice phrasing and fallback text
- `tests/test_agent.py`:
  - Policy behavior tests

Setup:
1) Install deps
   pip install -r requirements.txt

2) Configure `.env`
   LIVEKIT_URL=wss://<your-livekit-host>
   LIVEKIT_API_KEY=<your-api-key>
   LIVEKIT_API_SECRET=<your-api-secret>
   DEEPGRAM_API_KEY=<your-deepgram-key>
   CARTESIA_API_KEY=<your-cartesia-key>

3) Download model assets once
   python3 agent.py download-files

4) Run in dev mode
   python3 agent.py dev

5) Run tests
   python3 -m unittest discover -s tests -p "test_*.py"
