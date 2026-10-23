from datetime import datetime, timedelta

from tests.conftest import ADMIN, M1, M2, book, to, tomorrow_at


async def test_catalog(api, salon):
    r = await api.get("/salon")
    assert r.status_code == 200 and r.json()["name"] == "Парик"
    assert [s["name"] for s in (await api.get("/services")).json()] == ["Борода", "Стрижка", "Комбо"]
    assert [m["name"] for m in (await api.get("/masters", params={"service_id": salon["beard"]})).json()] == ["Алим"]
    assert len((await api.get("/masters", params={"service_id": salon["cut"]})).json()) == 2


async def test_bad_api_key(api, salon):
    r = await api.get("/salon", headers={"X-Api-Key": "nope"})
    assert r.status_code == 401


async def test_services_hidden_without_active_masters(api, salon):
    await api.patch(f"/admin/masters/{salon['m1']}", params={"telegram_id": ADMIN}, json={"is_active": False})
    assert [s["name"] for s in (await api.get("/services")).json()] == ["Стрижка"]


async def test_days_and_slots(api, salon):
    days = (await api.get("/days", params={"master_id": salon["m1"], "service_id": salon["cut"]})).json()
    tomorrow = tomorrow_at(0).date().isoformat()
    assert tomorrow in [d["day"] for d in days]
    assert len(days) >= 14
    slots = (await api.get("/slots", params={"master_id": salon["m1"], "service_id": salon["cut"],
                                             "date": tomorrow})).json()
    # 10:00..19:00 с шагом 30 минут
    assert len(slots) == 19
    assert datetime.fromisoformat(slots[0]) == tomorrow_at(10)
    assert datetime.fromisoformat(slots[-1]) == tomorrow_at(19)


async def test_happy_path_and_notifications(api, salon, sent):
    r = await book(api, salon)
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["status"] == "confirmed" and b["price"] == 800 and b["prepay_amount"] == 0
    assert "Новая запись" in to(sent, M1)[0]["text"]
    assert "Новая запись" in to(sent, ADMIN)[0]["text"]
    assert not to(sent, M2)
    mine = (await api.get("/bookings", params={"telegram_id": 501})).json()
    assert [x["id"] for x in mine] == [b["id"]]


async def test_double_booking_rejected(api, salon):
    assert (await book(api, salon)).status_code == 201
    r = await book(api, salon, client="c2")
    assert r.status_code == 409
    # другой мастер в это же время — можно
    assert (await book(api, salon, client="c2", master="m2")).status_code == 201


async def test_overlap_by_duration(api, salon):
    assert (await book(api, salon, service="combo", at=tomorrow_at(12))).status_code == 201  # 12:00–13:30
    for h, m in ((12, 30), (13, 0)):
        assert (await book(api, salon, client="c2", at=tomorrow_at(h, m))).status_code == 409
    assert (await book(api, salon, client="c2", at=tomorrow_at(13, 30))).status_code == 201
    assert (await book(api, salon, client="c2", at=tomorrow_at(11))).status_code == 201  # 11–12 впритык


async def test_master_without_service(api, salon):
    r = await book(api, salon, master="m2", service="beard")
    assert r.status_code == 409


async def test_outside_hours_and_past(api, salon):
    assert (await book(api, salon, at=tomorrow_at(19, 30))).status_code == 409  # не влезает до 20:00
    assert (await book(api, salon, at=tomorrow_at(8))).status_code == 409
    assert (await book(api, salon, at=tomorrow_at(12) - timedelta(days=2))).status_code == 409


async def test_active_bookings_limit(api, salon):
    for h in (10, 12, 14):
        assert (await book(api, salon, at=tomorrow_at(h))).status_code == 201
    assert (await book(api, salon, at=tomorrow_at(16))).status_code == 429


async def test_blocked_client(api, salon):
    r = await api.patch(f"/staff/clients/{salon['c1']}", params={"telegram_id": ADMIN}, json={"is_blocked": True})
    assert r.status_code == 200
    assert (await book(api, salon)).status_code == 403


async def test_client_cancel(api, salon, sent):
    b = (await book(api, salon)).json()
    sent.clear()
    r = await api.post(f"/bookings/{b['id']}/cancel", params={"telegram_id": 501})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert "Клиент отменил" in to(sent, M1)[0]["text"] and to(sent, ADMIN)
    assert (await api.post(f"/bookings/{b['id']}/cancel", params={"telegram_id": 501})).status_code == 409
    # чужую запись не отменить
    b2 = (await book(api, salon)).json()  # слот снова свободен
    assert (await api.post(f"/bookings/{b2['id']}/cancel", params={"telegram_id": 502})).status_code == 404


async def test_upsert_client(api, salon):
    r1 = await api.put("/clients", json={"telegram_id": 777, "name": "Новый", "username": "new"})
    r2 = await api.put("/clients", json={"telegram_id": 777, "phone": "+79991112233"})
    assert r1.json()["id"] == r2.json()["id"]
    assert r2.json()["name"] == "Новый" and r2.json()["phone"] == "+79991112233"


async def test_time_off_hides_day(api, salon):
    d = tomorrow_at(0).date()
    r = await api.post(f"/admin/masters/{salon['m1']}/timeoff", params={"telegram_id": ADMIN},
                       json={"day": d.isoformat()})
    assert r.status_code == 200
    slots = (await api.get("/slots", params={"master_id": salon["m1"], "service_id": salon["cut"],
                                             "date": d.isoformat()})).json()
    assert slots == []
    days = (await api.get("/days", params={"master_id": salon["m1"], "service_id": salon["cut"]})).json()
    assert d.isoformat() not in [x["day"] for x in days]
    assert (await book(api, salon)).status_code == 409


async def test_concurrent_same_slot(api, salon):
    import asyncio
    res = await asyncio.gather(*[book(api, salon, client=c) for c in ("c1", "c2", "c1", "c2", "c1")])
    codes = sorted(r.status_code for r in res)
    assert codes.count(201) == 1 and codes.count(409) == 4
