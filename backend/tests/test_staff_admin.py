from datetime import timedelta

from tests.conftest import ADMIN, M1, M2, STRANGER, book, to, tomorrow_at


async def test_roles(api, salon):
    assert (await api.get("/staff/role", params={"telegram_id": ADMIN})).json()["role"] == "admin"
    r = (await api.get("/staff/role", params={"telegram_id": M1})).json()
    assert r["role"] == "master" and r["master_id"] == salon["m1"]
    assert (await api.get("/staff/role", params={"telegram_id": STRANGER})).json()["role"] is None
    ids = (await api.get("/staff/ids")).json()
    assert ids["admin"] == ADMIN and sorted(ids["masters"]) == [M1, M2]


async def test_schedule_visibility(api, salon):
    await book(api, salon)
    await book(api, salon, client="c2", master="m2")
    day = tomorrow_at(0).date().isoformat()
    assert len((await api.get("/staff/schedule", params={"telegram_id": ADMIN, "day": day})).json()) == 2
    own = (await api.get("/staff/schedule", params={"telegram_id": M1, "day": day})).json()
    assert [b["master_name"] for b in own] == ["Алим"]
    r = await api.get("/staff/schedule", params={"telegram_id": STRANGER, "day": day})
    assert r.status_code == 403


async def test_staff_cancel_notifies_client(api, salon, sent):
    b = (await book(api, salon)).json()
    sent.clear()
    # мастер Тимур не может отменить запись Алима
    assert (await api.post(f"/staff/bookings/{b['id']}/cancel", params={"telegram_id": M2})).status_code == 404
    r = await api.post(f"/staff/bookings/{b['id']}/cancel", params={"telegram_id": M1})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert "отменена салоном" in to(sent, 501)[0]["text"]
    assert to(sent, ADMIN) and not to(sent, M1)  # отменивший мастер не получает эхо


async def test_no_show_only_after_start(api, salon):
    b = (await book(api, salon)).json()
    r = await api.post(f"/staff/bookings/{b['id']}/no_show", params={"telegram_id": ADMIN})
    assert r.status_code == 409


async def test_master_invite_flow(api, salon):
    inv = (await api.post(f"/admin/masters/{salon['m2']}/invite", params={"telegram_id": ADMIN})).json()["code"]
    assert inv.startswith("m_")
    r = await api.post("/staff/link", json={"code": inv, "telegram_id": 4242})
    assert r.status_code == 200 and r.json() == {"role": "master", "master_id": salon["m2"], "name": "Тимур"}
    assert (await api.post("/staff/link", json={"code": inv, "telegram_id": 4343})).status_code == 404  # одноразовая
    assert (await api.get("/staff/role", params={"telegram_id": M2})).json()["role"] is None  # старый отвязан


async def test_admin_invite_flow(api, salon):
    inv = (await api.post("/admin/salon/admin-invite", params={"telegram_id": ADMIN})).json()["code"]
    assert (await api.post("/staff/link", json={"code": "admin_wrong", "telegram_id": 5555})).status_code == 404
    r = await api.post("/staff/link", json={"code": inv, "telegram_id": 5555})
    assert r.json()["role"] == "admin"
    assert (await api.get("/admin/salon", params={"telegram_id": ADMIN})).status_code == 403
    assert (await api.get("/admin/salon", params={"telegram_id": 5555})).status_code == 200


async def test_admin_only(api, salon):
    for tid in (M1, STRANGER):
        assert (await api.get("/admin/services", params={"telegram_id": tid})).status_code == 403


async def test_services_crud(api, salon):
    p = {"telegram_id": ADMIN}
    r = await api.post("/admin/services", params=p, json={"name": "Укладка", "price": 400, "duration_min": 30})
    assert r.status_code == 201
    sid = r.json()["id"]
    # новая услуга сразу доступна у активных мастеров
    assert len((await api.get("/masters", params={"service_id": sid})).json()) == 2
    r = await api.patch(f"/admin/services/{sid}", params=p, json={"price": 450, "is_active": False})
    assert r.json()["price"] == 450 and r.json()["is_active"] is False
    assert sid not in [s["id"] for s in (await api.get("/services")).json()]
    assert (await api.post("/admin/services", params=p, json={"name": "", "price": 1, "duration_min": 30})).status_code == 422


async def test_masters_admin(api, salon):
    p = {"telegram_id": ADMIN}
    m = (await api.post("/admin/masters", params=p, json={"name": "Мурат"})).json()
    assert m["linked"] is False and len(m["service_ids"]) == 3
    hours = (await api.get(f"/admin/masters/{m['id']}/hours", params=p)).json()
    assert hours[0]["intervals"] == [{"start": "10:00", "end": "20:00"}] and hours[6]["intervals"] == []
    r = await api.put(f"/admin/masters/{m['id']}/hours", params=p, json={
        "weekday": 0, "intervals": [{"start": "09:00", "end": "13:00"}, {"start": "14:00", "end": "18:00"}]})
    assert r.status_code == 200 and len(r.json()[0]["intervals"]) == 2
    bad = await api.put(f"/admin/masters/{m['id']}/hours", params=p, json={
        "weekday": 0, "intervals": [{"start": "09:00", "end": "13:00"}, {"start": "12:00", "end": "18:00"}]})
    assert bad.status_code == 422
    r = await api.put(f"/admin/masters/{m['id']}/services", params=p, json={"service_ids": [salon["beard"], 99999]})
    assert r.json()["service_ids"] == [salon["beard"]]
    r = await api.patch(f"/admin/masters/{m['id']}", params=p, json={"name": "Мурат К.", "is_active": False})
    assert r.json()["name"] == "Мурат К." and r.json()["is_active"] is False


async def test_timeoff_reports_clashes(api, salon):
    await book(api, salon)
    d = tomorrow_at(0).date().isoformat()
    r = (await api.post(f"/admin/masters/{salon['m1']}/timeoff", params={"telegram_id": ADMIN}, json={"day": d})).json()
    assert len(r["bookings"]) == 1
    assert (await api.get(f"/admin/masters/{salon['m1']}/timeoff", params={"telegram_id": ADMIN})).json() == [d]
    await api.delete(f"/admin/masters/{salon['m1']}/timeoff/{d}", params={"telegram_id": ADMIN})
    assert (await api.get(f"/admin/masters/{salon['m1']}/timeoff", params={"telegram_id": ADMIN})).json() == []


async def test_salon_settings_and_prepay_validation(api, salon):
    p = {"telegram_id": ADMIN}
    assert (await api.patch("/admin/salon", params=p, json={"prepay_amount": 300})).status_code == 422
    r = await api.patch("/admin/salon", params=p, json={"prepay_amount": 300, "payment_details": "Сбер 2202 ...",
                                                         "address": "  ", "welcome_text": "Салам!"})
    assert r.status_code == 200
    j = r.json()
    assert j["prepay_amount"] == 300 and j["address"] is None and j["welcome_text"] == "Салам!"
    assert (await api.get("/salon")).json()["prepay_amount"] == 300


async def test_prepay_approve_flow(api, salon, sent):
    await api.patch("/admin/salon", params={"telegram_id": ADMIN},
                    json={"prepay_amount": 300, "payment_details": "Карта 2202 0000"})
    b = (await book(api, salon)).json()
    assert b["status"] == "pending_payment" and b["prepay_amount"] == 300 and "2202" in b["payment_details"]
    assert to(sent, ADMIN) and not to(sent, M1)  # мастеру — только после оплаты
    mine = (await api.get("/bookings", params={"telegram_id": 501})).json()
    assert mine[0]["status"] == "pending_payment"
    # слот уже занят, пока ждём оплату
    assert (await book(api, salon, client="c2")).status_code == 409
    sent.clear()
    r = await api.post(f"/bookings/{b['id']}/receipt", params={"telegram_id": 501}, json={"file_id": "PHOTO1"})
    assert r.status_code == 201
    msg = to(sent, ADMIN)[0]
    assert msg["method"] == "sendPhoto" and msg["photo"] == "PHOTO1"
    cb = msg["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    pid = int(cb.split(":")[1])
    assert (await api.post(f"/admin/payments/{pid}/approve", params={"telegram_id": M1})).status_code == 403
    sent.clear()
    r = (await api.post(f"/admin/payments/{pid}/approve", params={"telegram_id": ADMIN})).json()
    assert r == {"ok": True, "status": "confirmed"}
    assert "Предоплата получена" in to(sent, 501)[0]["text"]
    assert "Новая запись" in to(sent, M1)[0]["text"]
    # повторное нажатие не ломает
    assert (await api.post(f"/admin/payments/{pid}/approve", params={"telegram_id": ADMIN})).json()["ok"] is False


async def test_prepay_reject_flow(api, salon, sent):
    await api.patch("/admin/salon", params={"telegram_id": ADMIN},
                    json={"prepay_amount": 300, "payment_details": "Карта"})
    b = (await book(api, salon)).json()
    await api.post(f"/bookings/{b['id']}/receipt", params={"telegram_id": 501},
                   json={"file_id": "DOC", "kind": "document"})
    pid = int(to(sent, ADMIN)[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].split(":")[1])
    assert to(sent, ADMIN)[-1]["method"] == "sendDocument"
    r = (await api.post(f"/admin/payments/{pid}/reject", params={"telegram_id": ADMIN})).json()
    assert r["status"] == "cancelled"
    assert "не подтверждена" in to(sent, 501)[-1]["text"]
    assert (await book(api, salon, client="c2")).status_code == 201  # слот освободился


async def test_receipt_without_prepay(api, salon):
    b = (await book(api, salon)).json()
    r = await api.post(f"/bookings/{b['id']}/receipt", params={"telegram_id": 501}, json={"file_id": "X"})
    assert r.status_code == 409


async def test_client_card_and_notes(api, salon):
    await book(api, salon)
    card = (await api.get(f"/staff/clients/{salon['c1']}", params={"telegram_id": M1})).json()
    assert card["name"] == "Иван" and len(card["history"]) == 1
    # Тимур к Ивану не записан — карточку не видит
    assert (await api.get(f"/staff/clients/{salon['c1']}", params={"telegram_id": M2})).status_code == 404
    r = await api.patch(f"/staff/clients/{salon['c1']}", params={"telegram_id": M1}, json={"notes": "Коротко по бокам"})
    assert r.json()["notes"] == "Коротко по бокам"
    assert (await api.patch(f"/staff/clients/{salon['c1']}", params={"telegram_id": M1},
                            json={"is_blocked": True})).status_code == 403


async def test_search_and_broadcast_ids(api, salon):
    p = {"telegram_id": ADMIN}
    assert [c["name"] for c in (await api.get("/admin/clients/search", params={**p, "q": "1112233"})).json()] == ["Иван"]
    assert [c["name"] for c in (await api.get("/admin/clients/search", params={**p, "q": "@ivan"})).json()] == ["Иван"]
    assert [c["name"] for c in (await api.get("/admin/clients/search", params={**p, "q": "асл"})).json()] == ["Аслан"]
    await api.patch(f"/staff/clients/{salon['c2']}", params=p, json={"is_blocked": True})
    assert (await api.get("/admin/clients/ids", params=p)).json() == [501]


async def test_stats(api, salon):
    from tests.test_background import _insert
    from app import reminders
    await _insert(salon, timedelta(hours=-3), timedelta(days=2))
    await _insert(salon, timedelta(hours=-6), timedelta(days=2))
    await reminders.tick()
    await book(api, salon)
    st = (await api.get("/admin/stats", params={"telegram_id": ADMIN})).json()
    assert st["completed"] == 2 and st["revenue"] == 1600 and st["upcoming"] == 1
    assert st["by_master"][0] == {"name": "Алим", "visits": 2, "revenue": 1600}


async def test_upcoming_list(api, salon):
    await book(api, salon, at=tomorrow_at(12))
    await book(api, salon, client="c2", master="m2", at=tomorrow_at(10))
    r = (await api.get("/staff/upcoming", params={"telegram_id": ADMIN})).json()
    assert [b["master_name"] for b in r] == ["Тимур", "Алим"]  # по времени
    assert len((await api.get("/staff/upcoming", params={"telegram_id": ADMIN, "master_id": salon["m1"]})).json()) == 1
    own = (await api.get("/staff/upcoming", params={"telegram_id": M1, "master_id": salon["m2"]})).json()
    assert [b["master_name"] for b in own] == ["Алим"]  # мастеру фильтр по чужому не помогает
    await api.post(f"/staff/bookings/{r[0]['id']}/cancel", params={"telegram_id": ADMIN})
    assert len((await api.get("/staff/upcoming", params={"telegram_id": ADMIN})).json()) == 1
    assert (await api.get("/staff/upcoming", params={"telegram_id": STRANGER})).status_code == 403
