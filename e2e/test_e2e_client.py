from sqlalchemy import select

from app.db import SessionLocal
from app.models import Booking
from e2e.conftest import ADMIN, CLIENT, MASTER1, tomorrow


async def _book(chat, *, master="Алим", time="12:00", phone_contact="+79281112233"):
    await chat.send("/start")
    await chat.press("menu_book")
    assert "Выберите услугу" in chat.last_text()
    await chat.press(chat.button("Стрижка"))
    assert "Выберите мастера" in chat.last_text()
    await chat.press(chat.button(master))
    assert "Выберите дату" in chat.last_text()
    await chat.press(f"day:{tomorrow()}")
    assert "Выберите время" in chat.last_text()
    await chat.press(chat.button(time))
    if phone_contact:
        assert "номер телефона" in chat.last_text()
        await chat.send_contact(phone_contact)
    assert "Проверьте запись" in chat.last_text()
    return await chat.press("confirm_yes")


async def test_start_menu(h):
    c = h.chat(CLIENT, "Иван", "ivan")
    await c.send("/start")
    assert "Добро пожаловать в «Парик»" in c.last_text()
    labels = [t for t, _ in c.buttons()]
    assert "📅 Записаться" in labels and "⚙️ Админка" not in labels


async def test_admin_sees_admin_button(h):
    a = h.chat(ADMIN, "Админ")
    await a.send("/start")
    assert "⚙️ Админка" in [t for t, _ in a.buttons()]


async def test_full_booking_flow(h):
    c = h.chat(CLIENT, "Иван", "ivan")
    await _book(c)
    assert "Вы записаны" in c.last_text()
    async with SessionLocal() as s:
        b = (await s.scalars(select(Booking))).unique().one()
    assert b.status == "confirmed" and b.client.phone == "+79281112233"
    assert any("Новая запись" in t for t in h.notified(MASTER1))
    assert any("Новая запись" in t for t in h.notified(ADMIN))
    # второй раз телефон не спрашиваем
    await _book(c, time="15:00", phone_contact=None)
    assert "Вы записаны" in c.last_text()


async def test_phone_typed_and_validated(h):
    c = h.chat(CLIENT, "Иван")
    await c.send("/start")
    await c.press("menu_book")
    await c.press(c.button("Борода"))
    await c.press(c.button("Тимур"))
    await c.press(f"day:{tomorrow()}")
    await c.press(c.button("10:30"))
    await c.send("привет")
    assert "Не похоже на номер" in c.last_text()
    await c.send("8 (928) 111-22-33")
    assert "Проверьте запись" in c.last_text() and "+79281112233" in c.last_text()


async def test_slot_taken_meanwhile(h):
    c1, c2 = h.chat(CLIENT, "Иван"), h.chat(502, "Аслан")
    for c in (c1, c2):
        await c.send("/start")
        await c.press("menu_book")
        await c.press(c.button("Стрижка"))
        await c.press(c.button("Алим"))
        await c.press(f"day:{tomorrow()}")
        await c.press(c.button("12:00"))
        await c.send_contact("+7928000000" + str(c.id % 10))
    await c1.press("confirm_yes")
    assert "Вы записаны" in c1.last_text()
    await c2.press("confirm_yes")
    assert "только что заняли" in c2.last_text()
    await c2.press("back_days")
    assert "Выберите дату" in c2.last_text()


async def test_back_navigation_and_cancel(h):
    c = h.chat(CLIENT, "Иван")
    await c.send("/start")
    await c.press("menu_book")
    await c.press(c.button("Стрижка"))
    await c.press("back_services")
    assert "Выберите услугу" in c.last_text()
    await c.press(c.button("Стрижка"))
    await c.press(c.button("Алим"))
    await c.press("back_masters")
    assert "Выберите мастера" in c.last_text()
    await c.press("cancel_booking")
    assert "Главное меню" in c.last_text()


async def test_my_bookings_and_cancel_with_confirmation(h):
    c = h.chat(CLIENT, "Иван")
    await _book(c)
    await c.press("menu_profile")
    assert any("Стрижка" in t for t in c.texts())
    async with SessionLocal() as s:
        bid = (await s.scalars(select(Booking.id))).one()
    await c.press(f"cancel_id:{bid}")
    assert ("Да, отменить", f"cancel_yes:{bid}") in c.buttons()
    await c.press(f"cancel_no:{bid}")
    await c.press(f"cancel_id:{bid}")
    await c.press(f"cancel_yes:{bid}")
    assert "отменена" in c.last_text()
    assert any("Клиент отменил" in t for t in h.notified(MASTER1))
    await c.press(f"cancel_yes:{bid}")
    assert "уже отменена" in c.last_text()


async def test_prices_contacts(h):
    c = h.chat(CLIENT, "Иван")
    await c.press("menu_price")
    assert "Борода" in c.last_text() and "500₽" in c.last_text()
    await c.press("menu_contacts")
    assert "Кабардинская" in c.last_text()
    await c.press("menu_portfolio")
    assert "скоро" in c.last_text()


async def test_stale_button_and_random_text(h):
    c = h.chat(CLIENT, "Иван")
    await c.press("svc:1")  # кнопка из старого диалога
    assert "Главное меню" in c.last_text()
    await c.send("сколько стоит стрижка?")
    assert "Выберите действие" in c.last_text()


async def test_backend_down(h, monkeypatch):
    import httpx
    import api_client

    async def down(*a, **k):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(api_client.api.c, "request", down)
    c = h.chat(CLIENT, "Иван")
    await c.send("/start")
    assert "временно недоступен" in c.last_text()


async def test_reminder_buttons_and_rating(h):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from app import reminders
    c = h.chat(CLIENT, "Иван")
    await _book(c)
    async with SessionLocal() as s:
        b = (await s.scalars(select(Booking))).unique().one()
    await c.press(f"rem_cancel:{b.id}")
    assert ("Нет, приду", f"rem_ok:{b.id}") in c.buttons()
    await c.press(f"rem_ok:{b.id}")
    async with SessionLocal() as s:
        assert (await s.get(Booking, b.id)).client_confirmed is True
    # визит прошёл -> просьба оценить -> оценка
    now = datetime.now(timezone.utc)
    async with SessionLocal() as s:
        await s.execute(update(Booking).values(starts_at=now - timedelta(hours=2), ends_at=now - timedelta(hours=1)))
        await s.commit()
    await reminders.tick()
    assert any("Оцените" in t for t in h.notified(CLIENT))
    await c.press(f"rev:{b.id}:5")
    assert "Спасибо" in c.last_text()
    assert any("Отзыв 5/5" in t for t in h.notified(ADMIN))
    await c.press(f"rev:{b.id}:1")
    assert "уже учтена" in c.last_text()


async def test_start_during_phone_step_resets(h):
    c = h.chat(CLIENT, "Иван")
    await c.send("/start")
    await c.press("menu_book")
    await c.press(c.button("Стрижка"))
    await c.press(c.button("Алим"))
    await c.press(f"day:{tomorrow()}")
    await c.press(c.button("12:00"))
    await c.send("/start")
    texts = c.texts()
    assert "Запись прервана." in texts and any("Добро пожаловать" in t for t in texts)
    await c.send("+79281112233")  # это уже не телефон для записи
    assert "Выберите действие" in c.last_text()


async def test_conflict_and_network_errors_are_one_line(h, caplog):
    import logging
    from types import SimpleNamespace
    from telegram.error import Conflict, NetworkError
    from handlers import common
    common._last_warn.clear()
    caplog.set_level(logging.ERROR, logger="handlers.common")
    for _ in range(5):
        await common.on_error(None, SimpleNamespace(error=Conflict("terminated by other getUpdates request")))
        await common.on_error(None, SimpleNamespace(error=NetworkError("httpx.ConnectError")))
    msgs = [r.getMessage() for r in caplog.records]
    assert len(msgs) == 2  # по одной строке, без трейсбеков
    assert "другой запущенный бот" in msgs[0].lower() or "ДРУГОЙ" in msgs[0]
    assert all(r.exc_info is None for r in caplog.records)
