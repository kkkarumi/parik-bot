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
    assert "Предстоящих записей нет" in t.last_text()
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
    assert any("ждёт предоплату" in t for t in h.notified(MASTER1))  # мастер видит бронь сразу
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
    assert any("Предоплата получена" in t for t in h.notified(MASTER1))
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


async def test_admin_cancels_client_booking_from_list(h):
    """Админ: /admin → «Записи клиентов» → запись → «Отменить» → «Да» → клиент уведомлён, запись пропала."""
    c1, c2 = h.chat(CLIENT, "Иван", "ivan"), h.chat(502, "Аслан")
    await _book(c1)
    await _book(c2, master="Тимур", time="15:00", phone_contact="+79282223344")
    a = h.chat(ADMIN, "Админ")
    await a.send("/start")
    await a.press(a.button("Записи клиентов"))
    assert "Предстоящие записи: 2" in a.last_text()
    assert "Иван" in a.last_text() and "Аслан" in a.last_text()
    # фильтр по мастеру
    flt = {t: d for t, d in a.buttons() if d.startswith("up:0")}
    assert set(flt) == {"• Все", "Алим", "Тимур"}
    await a.press(flt["Тимур"])
    assert "Предстоящие записи: 1" in a.last_text() and "Аслан" in a.last_text()
    await a.press("up:0")
    await a.press(a.button("Иван"))
    assert "Запись №" in a.last_text()
    await a.press(a.button("Отменить запись"))
    await a.press(a.button("Да, отменить"))
    assert "отменена, клиент уведомлён" in a.last_text()
    assert any("отменена салоном" in t for t in h.notified(CLIENT))
    assert any("Запись отменена" in t for t in h.notified(MASTER1))  # мастер Алим тоже знает
    await a.press(a.button("К списку записей"))
    assert "Предстоящие записи: 1" in a.last_text() and "Иван" not in a.last_text()
    async with SessionLocal() as s:
        statuses = sorted(b.status for b in (await s.scalars(select(Booking))).unique().all())
    assert statuses == ["cancelled", "confirmed"]


async def test_admin_menu_has_bookings_button(h):
    a = h.chat(ADMIN, "Админ")
    await a.send("/admin")
    assert a.button("Записи клиентов") == "up:0"


async def test_list_pagination_and_back_from_client_card(h):
    from datetime import datetime, timedelta, timezone
    from app.models import Client
    async with SessionLocal() as s:
        t = await s.scalar(select(Tenant))
        m = await s.scalar(select(Master).where(Master.name == "Алим"))
        sv = await s.scalar(select(Service).where(Service.name == "Борода"))
        cl = Client(tenant_id=t.id, telegram_id=777, name="Мурат", phone="+79280000001")
        s.add(cl)
        await s.flush()
        start = datetime.now(timezone.utc) + timedelta(days=1)
        for i in range(13):
            st = start + timedelta(hours=i)
            s.add(Booking(tenant_id=t.id, master_id=m.id, service_id=sv.id, client_id=cl.id, starts_at=st,
                          ends_at=st + timedelta(minutes=30), price=500, status="confirmed"))
        await s.commit()
    mst = h.chat(MASTER1, "Алим")
    await mst.send("/schedule")
    assert "Предстоящие записи: 13" in mst.last_text()
    await mst.press(mst.button("Дальше"))
    assert len([b for b in mst.buttons() if b[1].startswith("bk:")]) == 3
    first = [d for _, d in mst.buttons() if d.startswith("bk:")][0]
    assert first.endswith(":u1")
    await mst.press(first)
    await mst.press(mst.button("Карточка клиента"))
    assert "Мурат" in mst.last_text()
    await mst.press(mst.button("Назад"))
    assert "Запись №" in mst.last_text()
    await mst.press(mst.button("К списку записей"))
    assert "Раньше" in " ".join(t for t, _ in mst.buttons())


async def test_master_cabinet_full_cycle(h):
    """Админ приглашает мастера → мастер открывает ссылку → кабинет → получает запись → отмечает выходной."""
    a = h.chat(ADMIN, "Админ")
    async with SessionLocal() as s:
        timur = await s.scalar(select(Master).where(Master.name == "Тимур"))
    await a.press(f"a:mst:{timur.id}")
    assert "не подключён к боту" in a.last_text()
    await a.press(a.button("Пригласить мастера"))
    assert "Мастер ещё не подключён" in a.last_text()
    code = a.last_text().split("start=")[1].split()[0]

    t = h.chat(2002, "Тимур")
    await t.send(f"/start {code}")
    txt = t.last_text()
    assert "Готово, Тимур" in txt and "мастер «Парик»" in txt and "Что можно сделать" in txt
    assert any("Тимур</b> подключился" in m for m in h.notified(ADMIN))
    assert [x for x, _ in t.buttons()][:4] == ["📋 Мои записи", "📅 По дням", "🌴 Выходной / отгул", "🕒 Мой график"]

    # клиент записывается к Тимуру — мастер получает уведомление
    c = h.chat(CLIENT, "Иван")
    await _book(c, master="Тимур")
    assert any("Новая запись" in m for m in h.notified(2002))

    await t.send("/start")
    assert "всего впереди: <b>1</b>" in t.last_text()
    await t.press("me:hours")
    assert "Пн: 10:00–20:00" in t.last_text() and "Стрижка" in t.last_text()
    await t.press("me:off")
    await t.press("me:offpick:0")
    await t.press(f"me:offadd:{tomorrow()}")
    assert "уже есть записи (1)" in t.last_text()
    assert any("Тимур</b> отметил выходной" in m and "записей: 1" in m for m in h.notified(ADMIN))
    await t.press(t.button("Иван"))
    await t.press(t.button("Отменить запись"))
    await t.press(t.button("Да, отменить"))
    assert any("отменена салоном" in m for m in h.notified(CLIENT))
    await t.press("me:off")
    assert "❌" in " ".join(x for x, _ in t.buttons())
    await t.press(f"me:offdel:{tomorrow()}")
    assert "выходных не отмечено" in t.last_text()
    await t.press("me:client")
    assert "📅 Записаться" in [x for x, _ in t.buttons()]
    await t.press("me")
    assert "Кабинет" in t.last_text() or "мастер «Парик»" in t.last_text()


async def test_admin_who_is_also_master(h):
    a = h.chat(ADMIN, "Админ")
    async with SessionLocal() as s:
        alim = await s.scalar(select(Master).where(Master.name == "Алим"))
        alim.telegram_chat_id = None
        await s.commit()
    await a.press(f"a:minv:{alim.id}")
    code = a.last_text().split("start=")[1].split()[0]
    await a.send(f"/start {code}")
    labels = [x for x, _ in a.buttons()]
    assert "⚙️ Админка" in labels and "💇 Кабинет мастера" in labels
    await a.press("me")
    assert "Алим" in a.last_text() and "⚙️ Админка" in [x for x, _ in a.buttons()]
