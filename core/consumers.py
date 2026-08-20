import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Notification

class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        if self.user.is_authenticated:
            self.group_name = f"user_{self.user.id}"
            await self.channel_layer.group_add(
                self.group_name,
                self.channel_name
            )
            await self.accept()
            
            # Send unread count immediately
            unread_count = await self.get_unread_count()
            await self.send(text_data=json.dumps({
                "type": "unread_count",
                "count": unread_count
            }))
        else:
            await self.close()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        # Mark as read when user clicks dismiss
        data = json.loads(text_data)
        if data.get("action") == "mark_read":
            await self.mark_as_read(data.get("notification_id"))

    async def send_notification(self, event):
        await self.send(text_data=json.dumps(event))

    @database_sync_to_async
    def get_unread_count(self):
        return Notification.objects.filter(recipient=self.user, is_read=False).count()

    @database_sync_to_async
    def mark_as_read(self, notification_id):
        Notification.objects.filter(id=notification_id, recipient=self.user).update(is_read=True)