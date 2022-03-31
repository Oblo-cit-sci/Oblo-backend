from email.message import EmailMessage
from logging import getLogger
from smtplib import SMTP_SSL, SMTPResponseException
from urllib.parse import urljoin

from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from app.settings import env_settings
from app.util.exceptions import ApplicationException

logger = getLogger(__name__)


def send_mail(receiver: str, subject: str, content: str):
    msg = EmailMessage()
    env = env_settings()
    msg["From"] = env.EMAIL_SENDER
    msg["To"] = receiver
    msg["Subject"] = subject
    msg.set_content(content)

    try:
        with SMTP_SSL(env.EMAIL_SSL_SERVER) as smtp:
            smtp.login(env.EMAIL_ACCOUNT, env.EMAIL_PWD.get_secret_value())
            smtp.send_message(msg)
    except SMTPResponseException as exc:
        logger.exception(exc)
        logger.critical(f"For email username: {env.EMAIL_ACCOUNT}")
        raise ApplicationException(
            HTTP_500_INTERNAL_SERVER_ERROR, "Problem sending email"
        )


def send_new_account_email(email_to: str, username: str, verification_code: str):
    env = env_settings()
    # probably works with a dict instead of putting a string together
    verification_url = urljoin(
        env.HOST,
        "basic/verify_email_address?" + f"user={username}&code={verification_code}",
    )
    send_mail(
        email_to,
        "Welcome to OpenTEK",
        f"Dear {username},\nWelcome to OpenTEK!\nClick here to verify your email address: {verification_url}",
    )


def send_password_reset_email(email_to: str, username: str, reset_code: str):
    env = env_settings()
    reset_code_url = urljoin(
        env.HOST, "basic/password_reset" + f"?user={username}&code={reset_code}"
    )
    send_mail(
        email_to,
        "Reset your password",
        f"Dear {username},\nYou can reset your password here: {reset_code_url}",
    )
