"""Бот: Sentry без ПДн, heartbeat-файл для HEALTHCHECK в Docker."""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
from telegram.request import HTTPXRequest

import config as bot_config
import heartbeat
import main as bot_main

ROOT = Path(__file__).resolve().parents[1]


def test_bot_sentry_options(monkeypatch):
    monkeypatch.setattr(bot_config, "SENTRY_DSN", "https://key@example.invalid/1")
    o = bot_main.sentry_options()
    assert o["send_default_pii"] is False and o["traces_sample_rate"] == 0.0 and o["include_local_variables"] is False
    ev = o["before_send"]({"message": f"tel +79281112233 token {bot_config.BOT_TOKEN} key {bot_config.API_KEY}"}, {})
    assert "+79281112233" not in ev["message"] and bot_config.API_KEY not in ev["message"]


def test_beat_only_when_telegram_answers(tmp_path, monkeypatch):
    f = tmp_path / "hb"
    monkeypatch.setattr(bot_config, "HEARTBEAT_FILE", str(f))
    import asyncio
    monkeypatch.setattr(heartbeat, "_last_ok", time.monotonic() - heartbeat.STALE_AFTER - 1)  # давно нет ответа
    asyncio.run(heartbeat.beat(None))
    assert not f.exists()
    monkeypatch.setattr(heartbeat, "_last_ok", time.monotonic())
    asyncio.run(heartbeat.beat(None))
    assert f.exists()


async def test_updates_request_marks_success(monkeypatch):
    results = iter([(502, b"bad gateway"), (200, b'{"ok":true,"result":[]}')])

    async def fake(self, *a, **k):
        return next(results)
    monkeypatch.setattr(HTTPXRequest, "do_request", fake)
    monkeypatch.setattr(heartbeat, "_last_ok", 0.0)
    req = heartbeat.UpdatesRequest()
    await req.do_request("u", "POST")
    assert not heartbeat.telegram_ok()
    await req.do_request("u", "POST")
    assert heartbeat.telegram_ok()


def test_build_registers_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setattr(bot_config, "STATE_FILE", "")
    monkeypatch.setattr(bot_config, "HEARTBEAT_FILE", str(tmp_path / "hb"))
    app = bot_main.build()
    assert [j.name for j in app.job_queue.jobs()] == ["heartbeat"]
    assert isinstance(app.bot._request[0], heartbeat.UpdatesRequest)  # [0] — запрос для getUpdates


@pytest.mark.skipif(sys.platform == "win32", reason="sh")
def test_dockerfile_healthcheck_command(tmp_path):
    text = (ROOT / "bot/Dockerfile").read_text()
    cmd = re.search(r"HEALTHCHECK .*?\\\n\s+CMD (.+)", text).group(1)
    env = {**os.environ, "BOT_HEARTBEAT_FILE": str(tmp_path / "hb")}
    cmd = cmd.replace("python ", f"{sys.executable} ", 1)
    run = lambda: subprocess.run(["sh", "-c", cmd], env=env).returncode  # noqa: E731
    assert run() == 1                      # файла нет — unhealthy
    (tmp_path / "hb").touch()
    assert run() == 0                      # свежий — healthy
    old = time.time() - 121
    os.utime(tmp_path / "hb", (old, old))
    assert run() == 1                      # старше 120 с — unhealthy
