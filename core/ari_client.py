"""
NEW in AgAI-33 -- no AgAI-7 equivalent. This is the real 15% gap: a client
for Asterisk's REST Interface (ARI), replacing Twilio's managed voice webhook
as the call-control layer.

Honest scope note: Twilio does speech-to-text FOR you -- a webhook arrives
with SpeechResult already transcribed. Asterisk does not. ARI gives you
call-control events (a call started, a channel is ringing) over a WebSocket,
and raw audio only via a separate bridged channel (externalMedia or
snoop-and-record). This module owns call control: answering, bridging,
hanging up, and playing audio back. Speech-to-text and the app-level
conversation loop live in ari_router.py, which is where this client's events
get turned into NormalizedMessage objects and handed to the same
core.orchestrator.run_agent() pipeline the rest of the project already uses.
"""

import asyncio
import json
from typing import Callable, Awaitable

import httpx
import websockets
from websockets.client import WebSocketClientProtocol

from core.config import get_settings
from core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class AriClient:
    """
    Thin wrapper around Asterisk's ARI REST + WebSocket event stream.

    REST calls (answer, play, hangup, create bridge, add channel to bridge)
    go through httpx against asterisk_ari_base_url. The event stream (channel
    entered Stasis, channel state changes, playback finished) arrives over a
    WebSocket and is dispatched to registered handlers by event type -- the
    same "one responsibility per handler" shape used throughout the ported
    LangGraph node functions elsewhere in this project.
    """

    def __init__(self):
        self.base_url = settings.asterisk_ari_base_url.rstrip("/")
        self.username = settings.asterisk_ari_username
        self.secret = settings.asterisk_ari_secret
        self.app_name = settings.asterisk_ari_app_name
        self._ws: WebSocketClientProtocol | None = None
        self._handlers: dict[str, list[Callable[[dict], Awaitable[None]]]] = {}
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            auth=(self.username, self.secret),
            timeout=10.0,
        )

    def on(self, event_type: str, handler: Callable[[dict], Awaitable[None]]) -> None:
        """Register an async handler for a given ARI event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    # ── Event stream ────────────────────────────────────────────────────────

    async def connect_and_listen(self) -> None:
        """
        Open the ARI WebSocket for this Stasis app and dispatch incoming
        events to registered handlers indefinitely. Reconnects with backoff
        on drop -- an ARI connection loss should never silently stop the
        dispatch pipeline from receiving calls.
        """
        ws_url = self._build_ws_url()
        backoff = 1

        while True:
            try:
                logger.info("ari_client.connecting", url=self._redact(ws_url))
                async with websockets.connect(ws_url) as ws:
                    self._ws = ws
                    backoff = 1
                    logger.info("ari_client.connected", app=self.app_name)

                    async for raw_message in ws:
                        await self._dispatch(raw_message)

            except (websockets.ConnectionClosed, OSError) as e:
                logger.warning(
                    "ari_client.disconnected",
                    error=str(e),
                    retry_in_seconds=backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _dispatch(self, raw_message: str) -> None:
        try:
            event = json.loads(raw_message)
        except json.JSONDecodeError:
            logger.error("ari_client.bad_event_payload", raw=raw_message[:200])
            return

        event_type = event.get("type", "")
        logger.info("ari_client.event_received", event_type=event_type)

        handlers = self._handlers.get(event_type, [])
        if not handlers:
            return

        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.error(
                    "ari_client.handler_failed",
                    event_type=event_type,
                    error=str(e),
                    exc_info=True,
                )

    def _build_ws_url(self) -> str:
        scheme = "wss" if self.base_url.startswith("https") else "ws"
        host_part = self.base_url.split("://", 1)[1].replace("/ari", "")
        return (
            f"{scheme}://{host_part}/ari/events"
            f"?app={self.app_name}&api_key={self.username}:{self.secret}"
            f"&subscribeAll=true"
        )

    @staticmethod
    def _redact(url: str) -> str:
        if "api_key=" in url:
            return url.split("api_key=")[0] + "api_key=***"
        return url

    # ── Call control (REST) ─────────────────────────────────────────────────
    # Same retry-and-log-never-crash pattern used in dispatch_agent's CRM
    # calls, applied here to Asterisk's REST endpoints.

    async def answer_channel(self, channel_id: str) -> bool:
        try:
            resp = await self._client.post(f"/channels/{channel_id}/answer")
            resp.raise_for_status()
            logger.info("ari_client.channel_answered", channel_id=channel_id)
            return True
        except Exception as e:
            logger.error("ari_client.answer_failed", channel_id=channel_id, error=str(e))
            return False

    async def hangup_channel(self, channel_id: str) -> bool:
        try:
            resp = await self._client.delete(f"/channels/{channel_id}")
            resp.raise_for_status()
            logger.info("ari_client.channel_hungup", channel_id=channel_id)
            return True
        except Exception as e:
            logger.error("ari_client.hangup_failed", channel_id=channel_id, error=str(e))
            return False

    async def play_media_uri(self, channel_id: str, media_uri: str) -> str | None:
        """
        Play a media URI (e.g. sound:some-file or a URL served by our own
        static route) into a channel. Returns the playback_id if accepted.
        """
        try:
            resp = await self._client.post(
                f"/channels/{channel_id}/play",
                params={"media": media_uri},
            )
            resp.raise_for_status()
            data = resp.json()
            playback_id = data.get("id")
            logger.info(
                "ari_client.playback_started",
                channel_id=channel_id,
                playback_id=playback_id,
            )
            return playback_id
        except Exception as e:
            logger.error("ari_client.play_failed", channel_id=channel_id, error=str(e))
            return None

    async def create_bridge(self, bridge_type: str = "mixing") -> str | None:
        try:
            resp = await self._client.post("/bridges", params={"type": bridge_type})
            resp.raise_for_status()
            bridge_id = resp.json().get("id")
            logger.info("ari_client.bridge_created", bridge_id=bridge_id)
            return bridge_id
        except Exception as e:
            logger.error("ari_client.create_bridge_failed", error=str(e))
            return None

    async def add_channel_to_bridge(self, bridge_id: str, channel_id: str) -> bool:
        try:
            resp = await self._client.post(
                f"/bridges/{bridge_id}/addChannel",
                params={"channel": channel_id},
            )
            resp.raise_for_status()
            logger.info(
                "ari_client.channel_added_to_bridge",
                bridge_id=bridge_id,
                channel_id=channel_id,
            )
            return True
        except Exception as e:
            logger.error(
                "ari_client.add_channel_to_bridge_failed",
                bridge_id=bridge_id,
                channel_id=channel_id,
                error=str(e),
            )
            return False

    async def start_external_media(
        self,
        channel_id_prefix: str,
        external_host: str,
        media_format: str = "ulaw",
    ) -> dict | None:
        """
        Create an externalMedia channel -- this is how ARI gives us raw
        audio: Asterisk streams RTP to a host:port we control, where our own
        STT service listens. Returns the channel object (including its id
        and connected address) on success.
        """
        try:
            resp = await self._client.post(
                "/channels/externalMedia",
                params={
                    "app": self.app_name,
                    "external_host": external_host,
                    "format": media_format,
                    "channelId": f"{channel_id_prefix}-ext",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(
                "ari_client.external_media_started",
                channel_id=data.get("id"),
                external_host=external_host,
            )
            return data
        except Exception as e:
            logger.error(
                "ari_client.external_media_failed",
                external_host=external_host,
                error=str(e),
            )
            return None

    async def close(self) -> None:
        await self._client.aclose()
        if self._ws:
            await self._ws.close()
