"""
ASGI configuration for the SME Business OS project.

Supports both HTTP and WebSocket traffic.
"""

import os
from django.core.asgi import get_asgi_application

# 1. Set the settings module and load Django early
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django_asgi_app = get_asgi_application()

# 2. Import Channels and routing AFTER Django is ready
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import core.routing

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            core.routing.websocket_urlpatterns
        )
    ),
})
