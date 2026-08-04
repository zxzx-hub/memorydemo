"""Redis connection owner and readiness probe."""

from redis.asyncio import Redis


class RedisConnection:
    """Own a decoded async Redis client."""

    name = "redis"

    def __init__(self, redis_url: str) -> None:
        self._client: Redis = Redis.from_url(
            redis_url,
            decode_responses=True,
        )

    @property
    def client(self) -> Redis:
        return self._client

    async def ping(self) -> None:
        await self._client.ping()

    async def close(self) -> None:
        await self._client.aclose()
