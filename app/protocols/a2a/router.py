"""
In-memory A2A message router.
Routes messages between agents during a single pipeline run.
"""
import logging
from collections import defaultdict
from typing import Callable, Optional
from .messages import A2AMessage

logger = logging.getLogger(__name__)


class MessageRouter:
    """
    Simple publish/subscribe router for A2A messages.
    Agents register handlers; messages are delivered synchronously.
    """
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._message_log: list[A2AMessage] = []

    def register(self, agent_name: str, handler: Callable[[A2AMessage], None]) -> None:
        """Register a handler for messages addressed to agent_name."""
        self._handlers[agent_name].append(handler)
        logger.debug(f"Registered handler for agent '{agent_name}'")

    def send(self, message: A2AMessage) -> int:
        """
        Deliver message to recipient. Returns number of handlers called.
        If recipient is 'broadcast', delivers to all registered handlers.
        """
        self._message_log.append(message)
        targets = (
            list(self._handlers.keys())
            if message.recipient == "broadcast"
            else [message.recipient]
        )
        count = 0
        for target in targets:
            for handler in self._handlers.get(target, []):
                try:
                    handler(message)
                    count += 1
                except Exception as exc:
                    logger.error(f"Handler error for agent '{target}': {exc}")
        return count

    def get_log(self, session_id: Optional[str] = None) -> list[A2AMessage]:
        if session_id:
            return [m for m in self._message_log if m.session_id == session_id]
        return list(self._message_log)

    def clear(self) -> None:
        self._message_log.clear()
        self._handlers.clear()

