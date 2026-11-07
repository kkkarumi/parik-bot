"""152-ФЗ в боте: согласие перед первой записью, /privacy, /forget."""
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update

import legal
from app.db import SessionLocal
from app.models import Booking, Client, Master, Service
from e2e.conftest import ADMIN, CLIENT, MASTER1, tomorrow
from e2e.test_e2e_client import _book


async def _client(tg=CLIENT):
    async with SessionLocal() as s:
        return await s.scalar(select(Client).where(Client.telegram_id == tg))


async def _bookings():
    async with SessionLocal() as s:
        return await s.scalar(select(func.count(Booking.id)))


async def test_new_client_consent_then_booking(h):
    c = h.chat(CLIENT, "Иван", "ivan")
    await c.send("/start")
    await c.press("menu_book")
    text = c.last_text()
    assert "Согласие на обработку персональных данных" in text
    assert "«Парик»" in text and "+79280000000" in text and "/forget" in text
    assert [t for t, _ in c.buttons()] == ["✅ Согласен", "Отмена"]
    assert (await _client()).consent_at is None

    await c.press("consent_yes")
    assert "Выберите услугу" in c.last_text()
    assert (await _client()).consent_at is not None
    await _book(c, phone_contact="+79281112233")  # второй заход — согласие уже не спрашивают
    assert "Вы записаны" in c.last_text()


async def test_refuse_consent_no_booking(h):
    c = h.chat(CLIENT, "Иван")
    await c.send("/start")
    await c.press("menu_book")
    await c.press("consent_no")
    assert "Без согласия" in c.last_text() and "+79280000000" in c.last_text()
    assert ("📅 Записаться", "menu_book") in c.buttons()
    assert await _bookings() == 0 and (await _client()).consent_at is None
    # кнопка из старого сообщения «Согласен» вне диалога ничего не делает
    await c.press("consent_yes")
    assert (await _client()).consent_at is None


async def test_old_client_asked_on_next_booking(h):
    """Клиент из базы до обновления (без consent_at, с телефоном и записью) — не блокируется,
    но перед следующей записью видит тот же экран согласия."""
    async with SessionLocal() as s:
        t_id = (await s.scalar(select(Master))).tenant_id
        old = Client(tenant_id=t_id, telegram_id=CLIENT, name="Иван", phone="+79281112233")
        s.add(old)
        await s.flush()
        m = await s.scalar(select(Master).where(Master.name == "Алим"))
        sv = await s.scalar(select(Service).where(Service.name == "Стрижка"))
        start = datetime.now(timezone.utc) + timedelta(days=2)
        s.add(Booking(tenant_id=t_id, master_id=m.id, service_id=sv.id, client_id=old.id, starts_at=start,
                      ends_at=start + timedelta(hours=1), price=800, status="confirmed"))
        await s.commit()
    c = h.chat(CLIENT, "Иван")
    await c.press("menu_profile")  # свои записи видит без согласия
    assert any("Стрижка" in t for t in c.texts())
    await c.press("menu_book")
    assert "Согласие на обработку" in c.last_text()
    await c.press("consent_yes")
    await c.press(c.button("Стрижка"))
    await c.press(c.button("Алим"))
    await c.press(f"day:{tomorrow()}")
    await c.press(c.button("12:00"))
    assert "Проверьте запись" in c.last_text()  # телефон уже известен
    await c.press("confirm_yes")
    assert "Вы записаны" in c.last_text() and await _bookings() == 2


async def test_consent_withdrawn_during_booking(h):
    c = h.chat(CLIENT, "Иван")
    await c.send("/start")
    await c.open_booking()
    await c.press(c.button("Стрижка"))
    await c.press(c.button("Алим"))
    await c.press(f"day:{tomorrow()}")
    await c.press(c.button("12:00"))
    await c.send_contact("+79281112233")
    async with SessionLocal() as s:  # согласие пропало (например, /forget с другого устройства)
        await s.execute(update(Client).values(consent_at=None))
        await s.commit()
    await c.press("confirm_yes")
    assert "Согласие на обработку" in c.last_text() and await _bookings() == 0
    await c.press("consent_yes")
    assert "Проверьте запись" in c.last_text()  # продолжаем с того же места
    await c.press("confirm_yes")
    assert "Вы записаны" in c.last_text()


async def test_privacy_command_and_menu(h):
    c = h.chat(CLIENT, "Иван")
    await c.send("/start")
    assert ("🔒 Мои данные", "menu_privacy") in c.buttons()
    await c.send("/privacy")
    assert "Как «Парик» обрабатывает ваши данные" in c.last_text()
    assert "ещё не давали" in c.last_text()
    await _book(c)
    await c.press("menu_privacy")
    assert re.search(r"Согласие на обработку данных вы дали \d\d\.\d\d\.\d{4} в \d\d:\d\d", c.last_text())
    assert ("🗑 Удалить мои данные", "forget_ask") in c.buttons()


async def test_forget(h):
    c = h.chat(CLIENT, "Иван", "ivan")
    await _book(c)
    await c.send("/forget")
    assert "Удалить ваши данные?" in c.last_text()
    await c.press("back_to_menu")  # передумал
    assert (await _client()).phone == "+79281112233"

    await c.press("forget_ask")
    await c.press("forget_yes")
    assert "Ваши данные удалены" in c.last_text() and "Отменено будущих записей: 1" in c.last_text()
    assert await _client() is None  # по Telegram ID больше не найти
    async with SessionLocal() as s:
        erased = await s.scalar(select(Client).where(Client.erased_at.is_not(None)))
        assert (erased.name, erased.phone, erased.username) == ("Удалён", None, None)
        assert (await s.scalar(select(Booking))).status == "cancelled"
    for chat in (MASTER1, ADMIN):
        assert any("удалил свои данные" in t and "+79281112233" not in t for t in h.notified(chat))
    assert "client" not in h.app.user_data.get(CLIENT, {})  # и из памяти бота стёрто

    await c.open_booking()  # вернулся — снова спросят согласие, это новый клиент
    assert "Выберите услугу" in c.last_text()


def test_consent_text_fits_message():
    text = legal.render("consent.md", salon="Барбершоп «Длинное название»", contact="+7 928 000-00-00",
                        address="г. Нальчик")
    plain = re.sub(r"<[^>]+>", "", text)
    assert len(plain) <= 1000, len(plain)
    assert "{" not in plain and "<!--" not in plain
    assert len(re.sub(r"<[^>]+>", "", legal.render("privacy.md", **legal.salon_values({})))) <= 3500


def test_render_escapes_html():
    text = legal.render("consent.md", salon="<b>X&Y</b>", contact="1", address="2")
    assert "&lt;b&gt;X&amp;Y&lt;/b&gt;" in text and "<b>Согласие" in text


async def test_forget_in_the_middle_of_booking(h):
    c = h.chat(CLIENT, "Иван")
    await c.send("/start")
    await c.open_booking()
    await c.press(c.button("Стрижка"))
    await c.send("/forget")
    await c.press("forget_yes")
    assert "Ваши данные удалены" in c.last_text()
    await c.press("mst:1")  # кнопка из прерванной записи
    assert "Главное меню" in c.last_text()  # «устаревшая кнопка», а не ошибка
    assert not any("пошло не так" in t for t in c.texts())
