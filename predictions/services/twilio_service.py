"""
Twilio Verify service for phone verification.
Uses Twilio Verify API for carrier-compliant SMS verification.
"""
import os
import logging
import phonenumbers
from phonenumbers import PhoneNumberFormat
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

logger = logging.getLogger(__name__)

_verify_service_sid = None


def get_twilio_client():
    """Get configured Twilio client."""
    account_sid = os.getenv('ACCOUNT_SID')
    auth_token = os.getenv('AUTH_TOKEN')

    if not account_sid or not auth_token:
        raise ValueError("Twilio credentials not configured")

    return Client(account_sid, auth_token)


def get_or_create_verify_service():
    """Get or create a Twilio Verify service."""
    global _verify_service_sid

    # Check if we have a configured service SID
    configured_sid = os.getenv('TWILIO_VERIFY_SERVICE_SID')
    if configured_sid:
        return configured_sid

    # Return cached SID if available
    if _verify_service_sid:
        return _verify_service_sid

    # Create a new verify service
    client = get_twilio_client()
    try:
        service = client.verify.v2.services.create(
            friendly_name='Voy a Mi Verification'
        )
        _verify_service_sid = service.sid
        logger.info(f"Created Twilio Verify service: {service.sid}")
        return _verify_service_sid
    except TwilioRestException as e:
        logger.error(f"Failed to create Verify service: {e}")
        raise


def normalize_phone_number(phone_number: str, default_region: str = 'US') -> str:
    """
    Normalize phone number to E.164 format.

    Args:
        phone_number: Phone number in any format
        default_region: Default region code if not specified in number

    Returns:
        Phone number in E.164 format (e.g., +12025551234)

    Raises:
        ValueError: If phone number is invalid
    """
    try:
        parsed = phonenumbers.parse(phone_number, default_region)

        if not phonenumbers.is_valid_number(parsed):
            raise ValueError("Invalid phone number")

        return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException as e:
        raise ValueError(f"Invalid phone number format: {e}")


def send_verification_code(phone_number: str) -> bool:
    """
    Send verification code via Twilio Verify API.

    Args:
        phone_number: Phone number in E.164 format

    Returns:
        True if verification started successfully

    Raises:
        Exception: If verification fails to start
    """
    try:
        client = get_twilio_client()
        service_sid = get_or_create_verify_service()

        verification = client.verify.v2.services(service_sid).verifications.create(
            to=phone_number,
            channel='sms'
        )

        logger.info(f"Verification sent to {phone_number}, status: {verification.status}")
        return verification.status == 'pending'

    except TwilioRestException as e:
        logger.error(f"Twilio Verify error for {phone_number}: {e}")
        raise Exception(f"Failed to send verification: {e.msg}")
    except Exception as e:
        logger.error(f"Error sending verification to {phone_number}: {e}")
        raise


def check_verification_code(phone_number: str, code: str) -> bool:
    """
    Verify a code using Twilio Verify API.

    Args:
        phone_number: Phone number in E.164 format
        code: 6-digit verification code

    Returns:
        True if code is valid, False otherwise

    Raises:
        Exception: If verification check fails
    """
    try:
        client = get_twilio_client()
        service_sid = get_or_create_verify_service()

        verification_check = client.verify.v2.services(service_sid).verification_checks.create(
            to=phone_number,
            code=code
        )

        logger.info(f"Verification check for {phone_number}, status: {verification_check.status}")
        return verification_check.status == 'approved'

    except TwilioRestException as e:
        # Code might be wrong or expired
        logger.warning(f"Twilio Verify check failed for {phone_number}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error checking verification for {phone_number}: {e}")
        raise
