"""Тексты согласия и политики ПДн: лежат в bot/texts/*.md, чтобы их можно было править без кода."""
import html
import re
from pathlib import Path

TEXTS = Path(__file__).resolve().parent / "texts"


def raw(name: str) -> str:
    """Текст шаблона без комментариев-подсказок <!-- … -->."""
    text = (TEXTS / name).read_text(encoding="utf-8")
    return re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()


def render(name: str, **values) -> str:
    """Шаблон → HTML для Telegram: всё экранируется, {ключ} подставляется, **жирный** → <b>."""
    text = html.escape(raw(name), quote=False)
    for key, value in values.items():
        text = text.replace("{" + key + "}", html.escape(str(value or ""), quote=False))
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def salon_values(salon: dict) -> dict:
    return {"salon": salon.get("name") or "салон",
            "contact": salon.get("phone") or "через администратора салона",
            "address": salon.get("address") or "адрес — в разделе «Контакты»"}
