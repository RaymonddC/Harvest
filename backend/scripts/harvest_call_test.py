"""Run real harvest (collect) calls against the live model with a scripted farmer, and count how often the
harvest gets saved (TODO item 12: "test a collect call before relying on it").

  python scripts/harvest_call_test.py            # 6 calls
  python scripts/harvest_call_test.py 10 --verbose

The farmer answers in text (send_client_content), picked from what the agent just said, so a run is quick and
repeatable; it tests the agent's logic (questions, read-back, tool calls), not speech recognition. Uses the real
prompt, tools and Live config. Needs Vertex settings (GOOGLE_GENAI_USE_VERTEXAI, GOOGLE_CLOUD_PROJECT,
GOOGLE_CLOUD_LOCATION, LIVE_MODEL) in the environment or the repo's .env, and VERTEX_ACCESS_TOKEN (fetched from
gcloud when missing). Runs one call at a time: parallel Live sessions hit the Vertex quota.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("HARVEST_NO_DOTENV", "1")

try:
    from dotenv import dotenv_values

    for k, v in dotenv_values(ROOT / ".env").items():
        if v and k.startswith(("GOOGLE_", "LIVE_MODEL", "TEXT_MODEL")):
            os.environ.setdefault(k, v)
except ImportError:
    pass
if not os.environ.get("VERTEX_ACCESS_TOKEN"):
    gcloud = "gcloud.cmd" if os.name == "nt" else "gcloud"
    os.environ["VERTEX_ACCESS_TOKEN"] = subprocess.run([gcloud, "auth", "print-access-token"], capture_output=True,
                                                       text=True, check=True).stdout.strip()

from google.genai import types  # noqa: E402

from app import live_session, seed_data, services  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.prompt import KICKOFF, build_system_instruction  # noqa: E402
from app.store import MemoryStore  # noqa: E402
from app.tools import CallSession, ToolHandlers  # noqa: E402

FARMER_ID = "f01"  # Pak Rahmat, no harvest on record yet
# Odd calls: ready before the short week (no offer). Even calls: ready after it, so the offer stage runs too.
HARVEST_LINES = ("Kira-kira satu koma enam ton, siap hari Senin depan.",
                 "Kira-kira satu koma enam ton, siap tanggal dua November.")

# (what the agent said, matched case-insensitively) -> the farmer's reply. First match wins.
RULES = [
    (r"sampai jumpa|terima kasih atas waktu|selamat (siang|pagi|sore)\W*$", "Sama-sama, terima kasih."),
    (r"berbicara dengan|bicara dengan", "Ya, saya sendiri. Boleh."),
    (r"izin|catatan tertulis|rekam", "Ya, boleh."),
    (r"tawar|harga|rp\s?\d|rupiah|menjual|lebih awal|lebih cepat|dimajukan", "Tidak, terima kasih. Saya kirim sesuai jadwal saja."),
    (r"betul\?|benar\?|sudah benar|apakah itu benar|saya ulangi|ulangi", "Ya, betul."),
    (r"panen|berapa (banyak|kilo|ton)|kapan|siap", "{harvest}"),
    (r"pertanyaan lain|ada lagi|ada yang", "Tidak ada, terima kasih."),
]


def farmer_reply(agent_text: str, harvest_line: str) -> str:
    low = agent_text.lower()
    for pattern, reply in RULES:
        if re.search(pattern, low):
            return reply.format(harvest=harvest_line)
    return "Ya."


async def one_call(n: int, verbose: bool) -> dict:
    settings = get_settings()
    store = MemoryStore()
    seed_data.load_seed(store, settings)
    farmer = store.get("farmers", FARMER_ID)
    gap = services.first_gap_week(store, "palm")
    call_id = services.queue_call(store, farmer, "collect", gap_week=gap["week"] if gap else None)
    campaign = services.get_campaign(store, settings, "palm")
    session = CallSession(call_id=call_id, farmer=farmer, kind="collect", gap_week=gap["week"] if gap else None,
                          questions=list((campaign or {}).get("questions") or []))
    handlers = ToolHandlers(store, settings, session)
    instruction = build_system_instruction(settings, farmer, "collect", session.gap_week, campaign=campaign)
    config = live_session.build_live_config(settings, instruction, language=farmer.get("language"))
    tools_used, said = [], []
    started = time.monotonic()
    client = live_session.genai_client()
    async with client.aio.live.connect(model=settings.live_model, config=config) as live:
        await live.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=KICKOFF)]),
                                       turn_complete=True)
        for turn in range(14):
            agent_text = ""
            # A turn that ends in a tool call is followed by another model turn once the tool answers: keep
            # listening until the agent has said something (or ended the call), as a farmer on the line would.
            for _ in range(6):
                async for msg in live.receive():
                    if msg.tool_call:
                        responses = []
                        for fn in msg.tool_call.function_calls or []:
                            result = handlers.dispatch(fn.name, dict(fn.args or {}))
                            tools_used.append((fn.name, dict(fn.args or {}), result.get("status")
                                               or result.get("error", "")[:40] or ("saved" if result.get("saved") else "ok")))
                            responses.append(types.FunctionResponse(id=fn.id, name=fn.name, response=result))
                        await live.send_tool_response(function_responses=responses)
                    sc = msg.server_content
                    if sc and sc.output_transcription and sc.output_transcription.text:
                        agent_text += sc.output_transcription.text
                    if sc and sc.turn_complete:
                        break
                if agent_text.strip() or session.ended:
                    break
            agent_text = " ".join(agent_text.split())
            said.append(("agent", agent_text))
            if session.ended:
                break
            reply = farmer_reply(agent_text, HARVEST_LINES[(n + 1) % 2])
            said.append(("farmer", reply))
            await live.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=reply)]),
                                           turn_complete=True)
    harvest = store.get("harvests", f"h-{FARMER_ID}-palm")
    result = {"n": n, "saved": bool(harvest), "kg": harvest and harvest["kg"], "ended": session.ended,
              "outcome": session.outcome, "turns": len(said), "seconds": round(time.monotonic() - started),
              "tools": [t[0] + (":" + str(t[1].get("confirmed_by_farmer")) if t[0] == "record_harvest" else "")
                        for t in tools_used]}
    if verbose:
        for who, text in said:
            print(f"    {who:6}: {text}")
        for t in tools_used:
            print(f"    tool  : {t[0]} {t[1]} -> {t[2]}")
    return result


async def main() -> None:
    count = int(next((a for a in sys.argv[1:] if a.isdigit()), "6"))
    verbose = "--verbose" in sys.argv
    results = []
    for n in range(1, count + 1):
        try:
            r = await one_call(n, verbose)
        except Exception as e:  # noqa: BLE001 - report and carry on with the next call
            r = {"n": n, "saved": False, "error": f"{type(e).__name__}: {e}"[:160]}
        results.append(r)
        print(f"call {n}: saved={r.get('saved')} kg={r.get('kg')} ended={r.get('ended')} "
              f"turns={r.get('turns')} {r.get('seconds')}s tools={r.get('tools')} {r.get('error', '')}", flush=True)
    saved = sum(1 for r in results if r.get("saved"))
    ended = sum(1 for r in results if r.get("ended"))
    print(f"\nHARVEST SAVED in {saved} of {len(results)} calls; end_call in {ended} of {len(results)}.")


if __name__ == "__main__":
    asyncio.run(main())
