# notifications/services.py
from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from .models import Notification

# You’ll need to install and configure these:
# Twilio for SMS (and WhatsApp via Twilio’s WhatsApp API)
# from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

def send_notification(notification):
    """
    Send a Notification instance to the user via all enabled channels.
    """
    user = notification.recipient
    prefs = user.notification_preferences  # assumes the OneToOne exists

    # Only proceed if the user has the preference record
    if not prefs:
        return

    # Helper to build message text
    message_text = f"{notification.title}\n\n{notification.message}"
    if notification.action_url:
        # Build full URL
        full_url = settings.BASE_URL + notification.action_url
        message_text += f"\n\nView: {full_url}"

    # Send email
    if prefs.email_enabled and user.email:
        try:
            send_mail(
                subject=notification.title,
                message=message_text,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
        except Exception as e:
            # Log error
            print(f"Email failed: {e}")

    # Send SMS (Twilio example)
    if prefs.sms_enabled and user.phone_numbers.filter(is_primary=True).exists():
        primary_phone = user.phone_numbers.filter(is_primary=True).first()
        if primary_phone and primary_phone.number:
            # Ensure phone number is in international format (e.g., +265...)
            from twilio.rest import Client
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            try:
                client.messages.create(
                    body=message_text,
                    from_=settings.TWILIO_PHONE_NUMBER,
                    to=primary_phone.number
                )
            except TwilioRestException as e:
                print(f"SMS failed: {e}")

    # Send WhatsApp (Twilio WhatsApp Business API)
    if prefs.whatsapp_enabled and user.phone_numbers.filter(is_primary=True).exists():
        primary_phone = user.phone_numbers.filter(is_primary=True).first()
        if primary_phone and primary_phone.number:
            from twilio.rest import Client
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            try:
                client.messages.create(
                    body=message_text,
                    from_=settings.TWILIO_WHATSAPP_NUMBER,
                    to=f"whatsapp:{primary_phone.number}"
                )
            except TwilioRestException as e:
                print(f"WhatsApp failed: {e}")

    # Mark notification as sent (optional)
    # notification.sent_at = timezone.now()
    # notification.save(update_fields=['sent_at'])