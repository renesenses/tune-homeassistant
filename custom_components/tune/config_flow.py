"""Config flow for Tune Music Server."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT

from .const import DEFAULT_HOST, DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)


class TuneConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tune."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            try:
                info = await self._validate_connection(host, port)
                name = info.get("name", f"Tune ({host})")
                version = info.get("version", "unknown")

                await self.async_set_unique_id(f"tune_{host}_{port}")
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=name,
                    data={CONF_HOST: host, CONF_PORT: port},
                    description_placeholders={"version": version},
                )
            except aiohttp.ClientError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
                    vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                }
            ),
            errors=errors,
        )

    async def _validate_connection(self, host: str, port: int) -> dict:
        """Validate that we can connect to the Tune server."""
        url = f"http://{host}:{port}/api/v1/system/version"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return {
                    "name": f"Tune {data.get('version', '')}",
                    "version": data.get("version", "unknown"),
                }
