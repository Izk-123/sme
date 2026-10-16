# core/consumers.py
"""
WebSocket consumer for real-time notifications.

This consumer:
- Accepts authenticated connections and adds the user to a personal group.
- Sends the unread notification count on connect.
- Handles "mark_read" actions from the client.
- Forwards server-sent notifications (via the channel layer) to the WebSocket.

All operations are wrapped in try/except to prevent the connection from
dropping (close code 1011) on minor errors. Logging is used extensively
to aid debugging.
"""

import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

# Import the Notification model (ensure core/models.py defines it).
from .models import Notification

# Module-level logger.
logger = logging.getLogger(__name__)


class NotificationConsumer(AsyncWebsocketConsumer):
    """
    AsyncWebsocketConsumer handling real-time notifications.
    """

    async def connect(self):
        """
        Called on WebSocket handshake.

        Steps:
        1. Authenticate the user.
        2. Add them to a personal group (`user_{id}`).
        3. Accept the connection.
        4. Send the initial unread count.
        5. If any step fails, log the error and close **normally** (no 1011).
        """
        self.user = self.scope.get("user")
        self.group_name = None  # Initialize in case connect fails

        if not self.user or not self.user.is_authenticated:
            logger.warning("WebSocket connection refused: unauthenticated user.")
            await self.close(code=4001)  # Custom auth failure code
            return

        self.group_name = f"user_{self.user.id}"

        try:
            # Add user to their personal group
            await self.channel_layer.group_add(
                self.group_name,
                self.channel_name
            )
            await self.accept()

            # Send unread count
            unread_count = await self.get_unread_count()
            await self.send(text_data=json.dumps({
                "type": "unread_count",
                "count": unread_count
            }))
            logger.info(f"WebSocket connected for user {self.user.id}")

        except Exception as e:
            logger.error(f"Error during WebSocket connect for user {self.user.id}: {e}", exc_info=True)
            # Close without error code to avoid triggering client 1011 retry
            await self.close()

    async def disconnect(self, close_code):
        """
        Called when the WebSocket closes.
        Removes the user from their group if the group exists.
        """
        if self.group_name:
            try:
                await self.channel_layer.group_discard(
                    self.group_name,
                    self.channel_name
                )
            except Exception as e:
                # Log and ignore - disconnection cleanup shouldn't crash
                logger.warning(f"Error removing user {self.user.id} from group: {e}")

    async def receive(self, text_data):
        """
        Called when the client sends a message.
        Expected format: {"action": "mark_read", "notification_id": <id>}
        """
        try:
            data = json.loads(text_data)
            action = data.get("action")
            if action == "mark_read":
                notification_id = data.get("notification_id")
                if notification_id:
                    await self.mark_as_read(notification_id)
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON received from user {self.user.id}: {text_data}")
        except Exception as e:
            logger.error(f"Error processing message from user {self.user.id}: {e}", exc_info=True)

    async def send_notification(self, event):
        """
        Called when a notification is sent via the channel layer.
        Forwards the event payload to the WebSocket.
        """
        try:
            await self.send(text_data=json.dumps(event))
        except Exception as e:
            logger.error(f"Error sending notification to user {self.user.id}: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Database helper methods (run in thread pool to avoid blocking event loop)
    # ------------------------------------------------------------------

    @database_sync_to_async
    def get_unread_count(self):
        """
        Returns the count of unread notifications for the current user.
        Returns 0 on any exception to avoid breaking the connection.
        """
        try:
            return Notification.objects.filter(
                recipient=self.user,
                is_read=False
            ).count()
        except Exception as e:
            logger.error(f"Error fetching unread count for user {self.user.id}: {e}")
            return 0

    @database_sync_to_async
    def mark_as_read(self, notification_id):
        """
        Marks a single notification as read.
        Ignores if the notification doesn't exist or doesn't belong to the user.
        """
        try:
            Notification.objects.filter(
                id=notification_id,
                recipient=self.user
            ).update(is_read=True)
        except Exception as e:
            logger.error(f"Error marking notification {notification_id} as read: {e}")
