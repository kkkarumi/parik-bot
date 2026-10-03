import httpx

import config


class Api:
    def __init__(self):
        self.c = httpx.AsyncClient(base_url=config.API_URL, headers={"X-Api-Key": config.API_KEY}, timeout=15)

    async def get(self, path, **params):
        r = await self.c.get(path, params=params)
        r.raise_for_status()
        return r.json()

    async def post(self, path, json=None, **params):
        r = await self.c.post(path, json=json, params=params)
        r.raise_for_status()
        return r.json()

    async def put(self, path, json):
        r = await self.c.put(path, json=json)
        r.raise_for_status()
        return r.json()


api = Api()
