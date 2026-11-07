"""Тексты согласия и политики в боте (bot/texts) совпадают с черновиками для юриста (docs/legal)."""
import re
from pathlib import Path

import pytest

import legal

ROOT = Path(__file__).resolve().parents[1]


def _block(doc: str) -> str:
    text = (ROOT / "docs/legal" / doc).read_text(encoding="utf-8")
    return re.search(r"<!-- bot-text:start -->\n(.*?)\n<!-- bot-text:end -->", text, re.S).group(1).strip()


@pytest.mark.parametrize("bot_file,doc", [("consent.md", "согласие.md"), ("privacy.md", "политика_пдн.md")])
def test_bot_texts_match_legal_drafts(bot_file, doc):
    assert legal.raw(bot_file) == _block(doc), f"bot/texts/{bot_file} и docs/legal/{doc} разошлись — поправьте оба"


def test_legal_drafts_marked_as_draft():
    for f in (ROOT / "docs/legal").glob("*.md"):
        assert "ЧЕРНОВИК. Не является юридической консультацией, требует проверки юристом" in f.read_text(), f.name


def test_bot_texts_get_into_docker_image():
    ignore = (ROOT / "bot/.dockerignore").read_text()
    assert "texts" not in ignore and "*.md" not in ignore
    assert "COPY . ." in (ROOT / "bot/Dockerfile").read_text()
