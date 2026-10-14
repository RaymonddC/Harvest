"""The stand-in farmer ("Play the farmer for me") answers what the agent said, not a fixed order."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FLOWS = {
    # a clean recorded call
    "clean": [
        "Hello, this is an AI assistant calling for Koperasi Sawit Maju. Am I speaking with Pak Wahyu F.? With your permission Koperasi Sawit Maju keeps a written transcript of this call. Is that all right?",
        "Terima kasih, Pak Wahyu. Kami sedang membutuhkan tandan buah segar kelapa sawit untuk minggu ketiga nanti, sekitar tanggal 2 sampai 8 November. Apakah Bapak bisa mengirimkan sebagian atau seluruh panen Bapak pada waktu itu?",
        "Baik, saya catat ya, Pak. 1.600 kilo untuk minggu ketiga November. Apakah sudah benar?",
        "Harga referensi pasar hari ini adalah Rp3.100 per kilogram. Untuk 1.600 kilo, kami bisa memberikan penawaran Rp3.100 juga. Apakah Bapak setuju?",
        "Baik, Pak. Kami bisa menyetujui harga Rp3.300 per kilogram ya. Apakah Bapak setuju untuk menjual 1.600 kilo dengan harga itu?",
        "Baik, Pak, saya sudah catat. Bapak setuju menjual 1.600 kilo dengan harga Rp3.300 per kilogram. Namun, penawaran ini masih menunggu persetujuan dari koperasi. Apakah ada yang ingin ditanyakan lagi?",
    ],
    # the agent re-asks things and mixes English in, as in the calls that went off script
    "wandering": [
        "Hello, this is an AI assistant calling for Koperasi Sawit Maju. Am I speaking with Pak Wahyu F.? With your permission Koperasi Sawit Maju keeps a written transcript of this call. Is that all right?",
        "Dengan izin Anda, Koperasi Sawit Maju menyimpan transkrip panggilan ini. Apakah itu baik-baik saja?",
        "Terima kasih. Apakah Bapak bisa mengirimkan panen di minggu ketiga? how many kilograms?",
        "Baik, saya catat 1600 kg untuk minggu pertama November. Apakah sudah benar?",
        "Mohon maaf, saya perlu mengkonfirmasi kembali. Bapak akan mengirimkan 1600 kg. Apakah benar?",
        "Today's market reference price is 3,100 IDR per kg. Apakah Bapak tertarik untuk mendiskusikan harganya?",
        "Baik, kami bisa menyetujui harga Rp3.300 per kilogram. Apakah Bapak setuju?",
        "Baik, sudah kami catat. Penawaran ini masih menunggu persetujuan koperasi. Apakah ada pertanyaan lain?",
    ],
    # nothing the agent says can trigger a later step early
    "early_price_word": [
        "Hello, this is an AI assistant calling for Koperasi Sawit Maju. Harga pasar hari ini bagus. Is that all right?",
        "Apakah Bapak setuju? Harga sawit naik.",
    ],
}
EXPECTED = {
    "clean": ["identity", "volume", "readback", "counter", "agree", "closing"],
    "wandering": ["identity", "yes", "volume", "readback", "readback", "counter", "agree", "closing"],
    "early_price_word": ["identity", "yes"],
}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_stand_in_answers_what_the_agent_said():
    out = subprocess.run(
        ["node", str(ROOT / "backend/tests/stand_in_check.mjs"), str(ROOT / "web/samples/farmer-lines.json"),
         str(ROOT / "web/js/stand-in.js")], input=json.dumps(FLOWS), capture_output=True, text=True, check=True)
    chosen = json.loads(out.stdout)
    for name, want in EXPECTED.items():
        # "yes" is the short fallback; the goodbye is only chosen once the deal is agreed
        assert chosen[name][: len(want)] == want, (name, chosen[name])


def test_every_stand_in_line_points_at_a_clip_and_the_goodbye_ends_it():
    lines = json.loads((ROOT / "web/samples/farmer-lines.json").read_text())
    assert len({line["id"] for line in lines}) == len(lines)
    ids = {line["id"] for line in lines}
    for line in lines:
        assert (ROOT / "web" / line["audio"]).exists(), line["audio"]
        assert line.get("after") in (None, *ids)
    assert [line["id"] for line in lines if line.get("ends")] == ["closing"]
    assert sum(1 for line in lines if line.get("fallback")) == 1
