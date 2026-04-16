from __future__ import annotations

import httpx

from doc_pipeline.domain.hooks.types import HookContext, VirusScanResult


class HttpVirusScanHook:
    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._base_url = base_url
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def scan(self, ctx: HookContext) -> VirusScanResult:
        payload = {"bucket": ctx.bucket, "key": ctx.key}
        if self._client is not None:
            response = await self._client.post(
                self._base_url,
                json=payload,
                timeout=self._timeout_seconds,
            )
        else:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self._base_url,
                    json=payload,
                    timeout=self._timeout_seconds,
                )
        response.raise_for_status()
        data = response.json()
        return VirusScanResult(
            clean=bool(data["clean"]),
            scanner=str(data["scanner"]),
            scan_id=str(data["scan_id"]),
        )
