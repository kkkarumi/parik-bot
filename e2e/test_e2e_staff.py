from sqlalchemy import select

from app.db import SessionLocal
from app.models import Booking, Master, MasterTimeOff, Service, Tenant, WorkingHours
from e2e.conftest import ADMIN, CLIENT, MASTER1, tomorrow
from e2e.test_e2e_client import _book


async def test_admin_menu_only_for_admin(h):
    c = h.chat(CLIENT, "Иван")
    await c.send("/admin")
    assert "только администратору" in c.last_text()
    await c.press("a:svcs")
    assert "Нажмите на услугу" not in c.last_text()


async def test_add_service_via_dialog(h):
    a = h.chat(ADMIN, "Админ")
    await a.send("/admin")
    assert "Админка «Парик»" in a.last_text()
    await a.press("a:svcs")
    await a.press("a:svc_add")
    await a.send("Камуфляж седины")
    await a.send("дорого")
    assert "Нужно число" in a.last_text()
    await a.send("700")
    await a.send("40 мин")
    assert any("добавлена" in t for t in a.texts())
    async with SessionLocal() as s:
        sv = await s.scalar(select(Service).where(Service.name == "Камуфляж седины"))
    assert sv.price == 700 and sv.duration_min == 40
    # поменять цену
    await a.press(f"a:svc_f:{sv.id}:price")
    await a.send("750₽")
    assert "750₽" in a.last_text()
    # скрыть
    await a.press(f"a:svc_tog:{sv.id}")
    assert "скрыта" in a.last_text()


async def test_ask_cancel_returns_back(h):
    a = h.chat(ADMIN, "Админ")
    await a.press("a:find")
    await a.press("ask_cancel:a:menu")
    assert "Админка" in a.last_text()
    await a.send("Иван")  # ввод больше не ждём
    assert "Выберите действие" in a.last_text()


async def test_master_hours_timeoff_invite(h):
    a = h.chat(ADMIN, "Админ")
    async with SessionLocal() as s:
        timur = await s.scalar(select(Master).where(Master.name == "Тимур"))
    await a.press(f"a:mst:{timur.id}")
    assert "не подключён" in a.last_text()
    await a.press(f"a:mhd:{timur.id}:0")
    await a.send("10-14 15:00-20")
    assert "Не понял" in a.last_text()
    await a.send("10-14, 15:00-20")
    assert "Пн: 10:00–14:00, 15:00–20:00" in [t for t, _ in a.buttons()]
    await a.press(f"a:mhc:{timur.id}:weekdays")
    async with SessionLocal() as s:
        rows = (await s.scalars(select(WorkingHours).where(WorkingHours.master_id == timur.id,
                                                           WorkingHours.weekday == 3))).all()
    assert len(rows) == 2
    await a.press(f"a:mhd:{timur.id}:6")
    await a.send("выходной")
    assert "Вс: выходной" in " ".join(t for t, _ in a.buttons())
    # выходной день
    await a.press(f"a:moad:{timur.id}:{tomorrow()}")
    async with SessionLocal() as s:
        assert await s.scalar(select(MasterTimeOff).where(MasterTimeOff.master_id == timur.id))
    # приглашение мастера
    await a.press(f"a:minv:{timur.id}")
    link = [w for w in a.last_text().split() if w.startswith("https://t.me/parik_test_bot?start=")][0]
    code = link.split("start=")[1]
    t = h.chat(2002, "Тимур")
    await t.send(f"/start {code}")
    assert any("Готово, Тимур" in x for x in t.texts())
    assert any(n == "setMyCommands" for n, _ in h.tg.calls)
    await t.send("/schedule")
    assert "Записей нет" in t.last_text()
    t2 = h.chat(2003, "Хитрый")
    await t2.send(f"/start {code}")
    assert any("недействительна" in x for x in t2.texts())


async def test_schedule_booking_card_cancel_and_client_card(h):
    c = h.chat(CLIENT, "Иван", "ivan")
    await _book(c)
    m = h.chat(MASTER1, "Алим")
    await m.send("/schedule")
    await m.press(f"sch:{tomorrow()}")
    assert "Стрижка" in m.last_text() and "Иван" in m.last_text()
    bk = m.button("12:00")
    await m.press(bk)
    assert "Запись №" in m.last_text()
    await m.press(m.button("Карточка клиента"))
    assert "Визитов: <b>0</b>" in m.last_text()
    assert "⛔️ Заблокировать" not in [t for t, _ in m.buttons()]  # блокирует только админ
    await m.press(m.button("Заметка"))
    await m.send("Любит покороче")
    assert "Любит покороче" in m.last_text()
    await m.press(bk)
    await m.press(m.button("Отменить запись"))
    await m.press(m.button("Да, отменить"))
    assert "клиент уведомлён" in m.last_text()
    assert any("отменена салоном" in t for t in h.notified(CLIENT))
    # клиент видит, что записей нет
    await c.press("menu_profile")
    assert "Предстоящих записей нет" in c.last_text()


async def test_salon_settings(h):
    a = h.chat(ADMIN, "Админ")
    await a.press("a:salon")
    await a.press("a:sal:welcome_text")
    await a.send("Салам алейкум! Запишитесь к лучшим барберам Нальчика 💈")
    assert "Салам алейкум" in a.last_text()
    c = h.chat(CLIENT, "Иван")
    await c.send("/start")
    assert c.last_text().startswith("Салам алейкум")
    await a.press("a:sal:address")
    await a.send("-")
    async with SessionLocal() as s:
        assert (await s.scalar(select(Tenant))).address is None


async def test_prepay_full_cycle(h):
    a = h.chat(ADMIN, "Админ")
    await a.press("a:prepay")
    await a.press("a:pp:amount")
    await a.send("300")
    assert "реквизиты" in a.last_text().lower()  # без реквизитов не включить
    await a.send("Сбер 2202 2000 0000 0000, Алим К.")
    assert "включена, 300₽" in a.last_text()

    c = h.chat(CLIENT, "Иван")
    await _book(c)
    assert "осталась предоплата 300₽" in c.last_text() and "2202" in c.last_text()
    assert not any("Новая запись" in t for t in h.notified(MASTER1))  # мастеру — после оплаты
    await c.send_photo("CHECK1")
    assert "Чек отправлен" in c.last_text()
    check = [m for m in h.backend_sent if m.get("chat_id") == ADMIN and m["method"] == "sendPhoto"][-1]
    pay_ok = check["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    # мастер не может подтвердить оплату
    m = h.chat(MASTER1, "Алим")
    await m.press(pay_ok, caption="чек")
    assert any(n == "answerCallbackQuery" and p.get("show_alert") for n, p in h.tg.calls)
    await a.press(pay_ok, caption="💳 Чек о предоплате 300₽")
    assert "Оплата подтверждена" in a.last_text()
    assert any("Предоплата получена" in t for t in h.notified(CLIENT))
    assert any("Новая запись" in t for t in h.notified(MASTER1))
    async with SessionLocal() as s:
        assert (await s.scalar(select(Booking))).status == "confirmed"
    await a.press(pay_ok, caption="💳 Чек")
    assert "Уже обработано" in a.last_text()


async def test_photo_without_pending_payment(h):
    c = h.chat(CLIENT, "Иван")
    await c.send("/start")
    await c.send_photo()
    assert "нет" in c.last_text()


async def test_stats_find_broadcast_link(h):
    c = h.chat(CLIENT, "Иван", "ivan")
    await _book(c)
    a = h.chat(ADMIN, "Админ")
    await a.press("a:stats:30")
    assert "Статистика за 30 дн." in a.last_text()
    await a.press("a:find")
    await a.send("1112233")
    await a.press(a.button("Иван"))
    assert "Иван" in a.last_text() and "⛔️ Заблокировать" in [t for t, _ in a.buttons()]
    await a.press(a.button("Заблокировать"))
    assert "Заблокирован" in a.last_text()
    await a.press(a.button("Разблокировать"))
    await a.press("a:bc")
    await a.send("Скидка 20% в понедельник! <script>")
    assert "Отправить" in a.last_text()
    await a.press("a:bc_go")
    sends = [p for n, p in h.tg.calls if n == "sendMessage" and p.get("chat_id") == CLIENT]
    assert sends and "Скидка 20%" in sends[0]["text"] and "&lt;script&gt;" in sends[0]["text"]
    assert "доставлено 1" in a.last_text()  # заблокированные не получают; Иван разблокирован
    await a.press("a:link")
    photo = [p for n, p in h.tg.calls if n == "sendPhoto"]
    assert photo and "https://t.me/parik_test_bot" in photo[0]["caption"]


async def test_admin_handover(h):
    a = h.chat(ADMIN, "Админ")
    await a.press("a:adm_inv")
    code = a.last_text().split("start=")[1].split()[0]
    owner = h.chat(3000, "Владелец")
    await owner.send(f"/start {code}")
    assert any("Вы — администратор" in t for t in owner.texts())
    await a.send("/admin")
    assert "только администратору" in a.last_text()
    await owner.send("/admin")
    assert "Админка «Парик»" in owner.last_text()
