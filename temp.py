import asyncio
import time
import json
import logging
from typing import Optional

import redis.asyncio as aioredis  # async redis client

log = logging.getLogger(__name__)

class AppConfig:
    _state: dict[str, PersistentConfig]
    _redis: Optional[aioredis.Redis] = None
    _prefix: str = "open-webui:config:"

    # throttle background refreshes so we don't spam Redis on hot reads
    _last_refresh_ts: dict[str, float]
    _refresh_min_interval_sec: float = 2.0

    def __init__(self, redis_url: Optional[str] = None, redis_sentinels: Optional[list] = []):
        super().__setattr__("_state", {})
        super().__setattr__("_prefix", "open-webui:config:")
        super().__setattr__("_last_refresh_ts", {})
        super().__setattr__("_refresh_min_interval_sec", 2.0)

        if redis_url:
            # Async Redis client (non-Sentinel). Add timeouts so tasks don't hang forever.
            r = aioredis.from_url(
                redis_url,
                decode_responses=True,
                socket_timeout=5.0,           # read/write timeout
                socket_connect_timeout=3.0,   # connect timeout
                health_check_interval=30,     # keep connections fresh
            )
            super().__setattr__("_redis", r)

        # NOTE: if you actually use Sentinel, wire it here with:
        # from redis.asyncio.sentinel import Sentinel
        # sent = Sentinel(redis_sentinels, decode_responses=True, socket_timeout=5.0, socket_connect_timeout=3.0)
        # super().__setattr__("_redis", sent.master_for("mymaster"))

    # -------- attribute API (purely in-memory; non-blocking) --------
    def __setattr__(self, key, value):
        if key in {"_state", "_redis", "_prefix", "_last_refresh_ts", "_refresh_min_interval_sec"}:
            return super().__setattr__(key, value)

        if isinstance(value, PersistentConfig):
            self._state[key] = value
            return

        if key not in self._state:
            raise AttributeError(f"Config key '{key}' not found")

        # update local + DB synchronously (your existing behavior)
        self._state[key].value = value
        self._state[key].save()

        # push to Redis in the background (fire-and-forget)
        if self._redis:
            redis_key = f"{self._prefix}{key}"
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._aset_redis(redis_key, self._state[key].value))
            except RuntimeError:
                # no running loop yet (import time / sync context) -> skip; you can hydrate on startup
                pass

    def __getattr__(self, key):
        if key not in self._state:
            raise AttributeError(f"Config key '{key}' not found")

        # return local value immediately
        val = self._state[key].value

        # schedule a throttled background refresh from Redis
        if self._redis:
            now = time.time()
            last = self._last_refresh_ts.get(key, 0.0)
            if now - last >= self._refresh_min_interval_sec:
                self._last_refresh_ts[key] = now
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._refresh_from_redis(key))
                except RuntimeError:
                    # no loop (rare) — skip refresh
                    pass

        return val

    # -------- explicit async APIs when you want to await --------
    async def aset(self, key: str, value):
        """Strong write: update local+DB and await Redis SET."""
        if key not in self._state:
            raise AttributeError(f"Config key '{key}' not found")
        self._state[key].value = value
        self._state[key].save()
        if self._redis:
            await self._redis.set(f"{self._prefix}{key}", json.dumps(value))

    async def aget(self, key: str):
        """Strong read: fetch from Redis (if available) before returning."""
        if key not in self._state:
            raise AttributeError(f"Config key '{key}' not found")
        await self._refresh_from_redis(key)
        return self._state[key].value

    async def arefresh_all_from_redis(self):
        """Hydrate all known keys from Redis once (e.g., on startup)."""
        if not self._redis:
            return
        for key in list(self._state.keys()):
            try:
                await self._refresh_from_redis(key)
            except Exception:
                log.exception("Failed refreshing %s from Redis", key)

    async def aclose(self):
        if self._redis:
            await self._redis.close()

    # -------- internals --------
    async def _aset_redis(self, rkey: str, value):
        try:
            await self._redis.set(rkey, json.dumps(value))
        except Exception:
            log.exception("Failed writing config %s to Redis", rkey)

    async def _refresh_from_redis(self, key: str):
        if not self._redis:
            return
        rkey = f"{self._prefix}{key}"
        try:
            raw = await self._redis.get(rkey)
            if raw is None:
                return
            decoded = json.loads(raw)
            if self._state[key].value != decoded:
                self._state[key].value = decoded
                log.info("Updated %s from Redis: %s", key, decoded)
        except json.JSONDecodeError:
            log.error("Invalid JSON in Redis for %s", key)
        except Exception:
            log.exception("Redis GET failed for %s", rkey)
@app.on_event("startup")
async def boot():
    # e.g., app.state.config = AppConfig(redis_url=REDIS_URL)
    # and register: app.state.config.ENABLE_API_KEY = PersistentConfig(...)
    await app.state.config.arefresh_all_from_redis()