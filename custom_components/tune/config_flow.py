"""Config flow for Tune Music Server."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession

try:  # HA >= 2025.1
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
except ImportError:  # pragma: no cover - older HA
    from homeassistant.components.zeroconf import ZeroconfServiceInfo

from .const import (
    API_BASE,
    CONF_API_KEY,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DOMAIN,
    auth_headers,
    url_host,
)

_LOGGER = logging.getLogger(__name__)


class InvalidAuth(Exception):
    """The Tune server refused the request (authentication enabled)."""


class TuneConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tune."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str = DEFAULT_HOST
        self._port: int = DEFAULT_PORT
        self._version: str = ""

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle zeroconf discovery of a Tune server (`_tune-server._tcp`)."""
        self._host = str(discovery_info.ip_address or discovery_info.host)
        self._port = discovery_info.port or DEFAULT_PORT
        self._version = str(discovery_info.properties.get("version", ""))

        await self.async_set_unique_id(f"tune_{self._host}_{self._port}")
        self._abort_if_unique_id_configured()

        self.context["title_placeholders"] = {
            "name": f"Tune {self._version} ({self._host})".replace("  ", " ")
        }
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm zeroconf discovery (API key only if auth is enabled)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = (user_input.get(CONF_API_KEY) or "").strip()
            try:
                info = await self._validate_connection(self._host, self._port, api_key)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=info["name"],
                    data=self._entry_data(self._host, self._port, api_key),
                )

        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=vol.Schema({vol.Optional(CONF_API_KEY, default=""): str}),
            description_placeholders={"host": self._host, "port": str(self._port)},
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            api_key = (user_input.get(CONF_API_KEY) or "").strip()

            await self.async_set_unique_id(f"tune_{host}_{port}")
            self._abort_if_unique_id_configured()

            try:
                info = await self._validate_connection(host, port, api_key)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=info["name"], data=self._entry_data(host, port, api_key)
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
                    vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                    vol.Optional(CONF_API_KEY, default=""): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Authentication was enabled on the server: ask for an API key."""
        self._host = entry_data[CONF_HOST]
        self._port = entry_data[CONF_PORT]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = (user_input.get(CONF_API_KEY) or "").strip()
            try:
                await self._validate_connection(self._host, self._port, api_key)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data=self._entry_data(self._host, self._port, api_key),
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    @staticmethod
    def _entry_data(host: str, port: int, api_key: str) -> dict[str, Any]:
        data: dict[str, Any] = {CONF_HOST: host, CONF_PORT: port}
        if api_key:
            data[CONF_API_KEY] = api_key
        return data

    async def _validate_connection(self, host: str, port: int, api_key: str) -> dict:
        """Reach the server, then check that the zones are readable.

        `/system/version` is public even with authentication enabled, so the
        credentials are checked against `/zones`.
        """
        session = async_get_clientsession(self.hass)
        base = f"http://{url_host(host)}:{port}{API_BASE}"
        timeout = aiohttp.ClientTimeout(total=5)
        async with session.get(f"{base}/system/version", timeout=timeout) as resp:
            resp.raise_for_status()
            data = await resp.json()
        async with session.get(
            f"{base}/zones", headers=auth_headers(api_key), timeout=timeout
        ) as resp:
            if resp.status in (401, 403):
                raise InvalidAuth
            resp.raise_for_status()
        version = data.get("version", "")
        return {"name": f"Tune {version}".strip(), "version": version or "unknown"}
