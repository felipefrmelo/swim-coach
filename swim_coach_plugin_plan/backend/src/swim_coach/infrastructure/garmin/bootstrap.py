"""Interactive Garmin login confined to a one-time bootstrap boundary."""

from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
from collections.abc import Callable

from swim_coach.application.ports.garmin import (
    GarminErrorCategory,
    GarminProviderError,
)


class GarminConnectBootstrap:
    def __init__(self) -> None:
        try:
            self._observed_version = importlib.metadata.version("garminconnect")
        except importlib.metadata.PackageNotFoundError:
            self._observed_version = "unknown"

    @property
    def observed_version(self) -> str:
        return self._observed_version

    @staticmethod
    def _authenticate(
        email: str,
        password: str,
        prompt_mfa: Callable[[], str],
    ) -> bytes:
        module = importlib.import_module("garminconnect")
        client = module.Garmin(email, password, prompt_mfa=prompt_mfa)
        try:
            client.login()
            return str(client.client.dumps()).encode()
        finally:
            password = ""
            email = ""

    async def authenticate(
        self,
        email: str,
        password: str,
        prompt_mfa: Callable[[], str],
    ) -> bytes:
        try:
            return await asyncio.to_thread(
                self._authenticate,
                email,
                password,
                prompt_mfa,
            )
        except Exception as exc:
            name = type(exc).__name__
            if name == "GarminConnectAuthenticationError":
                error = GarminProviderError(GarminErrorCategory.AUTH_REQUIRED, retryable=False)
            elif name == "GarminConnectTooManyRequestsError":
                error = GarminProviderError(
                    GarminErrorCategory.RATE_LIMITED,
                    retryable=True,
                    retry_after_seconds=900,
                )
            elif name == "GarminConnectConnectionError":
                error = GarminProviderError(GarminErrorCategory.NETWORK, retryable=True)
            else:
                error = GarminProviderError(GarminErrorCategory.UNKNOWN, retryable=False)
            raise error from exc
