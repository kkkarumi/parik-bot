import httpx

import config


class ApiError(Exception):
    def __init__(self, status: int, detail: str = ""):
        super().__init__(f"{status}: {detail}")
        self.status, self.detail = status, detail


class Api:
    def __init__(self):
        self.c = httpx.AsyncClient(base_url=config.API_URL, headers={"X-Api-Key": config.API_KEY}, timeout=15)

    async def request(self, method: str, path: str, json=None, **params):
        r = await self.c.request(method, path, json=json, params=params or None)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", "")
            except ValueError:
                detail = r.text
            raise ApiError(r.status_code, str(detail))
        return r.json() if r.content else None

    async def get(self, path, **params):
        return await self.request("GET", path, **params)

    async def post(self, path, json=None, **params):
        return await self.request("POST", path, json=json, **params)

    async def put(self, path, json=None, **params):
        return await self.request("PUT", path, json=json, **params)

    async def patch(self, path, json=None, **params):
        return await self.request("PATCH", path, json=json, **params)

    async def delete(self, path, **params):
        return await self.request("DELETE", path, **params)


api = Api()
