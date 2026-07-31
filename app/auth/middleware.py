"""Authentication middleware that installs a resolved TenantContext."""

from collections.abc import Awaitable, Callable

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.auth.tenant_resolver import TenantResolver
from app.core.errors import AppError

RequestHandler = Callable[[Request], Awaitable[Response]]


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Resolve trusted identity for memory routes before business execution."""

    def __init__(self, app: object, resolver: TenantResolver) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._resolver = resolver

    async def dispatch(
        self,
        request: Request,
        call_next: RequestHandler,
    ) -> Response:
        if not request.url.path.startswith("/v1/memory/"):
            return await call_next(request)
        try:
            request.state.tenant_context = await self._resolver.resolve(request)
        except AppError as error:
            return JSONResponse(
                status_code=error.status_code,
                content={
                    "error": {
                        "code": error.code,
                        "message": error.message,
                        "trace_id": "-",
                    }
                },
            )
        return await call_next(request)
