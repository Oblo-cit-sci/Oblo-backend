from uuid import uuid4

from passlib import pwd
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def generate_access_token():
    return pwd.genword(entropy=56, length=32)


def verify_hash(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def create_hash(password):
    return pwd_context.hash(password)


def obscure_email_address(email):
    parts = email.split("@")
    obs_p1 = parts[0][:2] + "*" * (len(parts[0]) - 2)  # just the first 2 chars
    obs_p1 = obs_p1[:-1] + parts[0][-1]  # bring back last char before @
    parts2_s = parts[1].split(".")  # split after the @ by the "."
    obs_p21 = parts2_s[0][0] + "*" * (len(parts2_s[0]) - 1)  # 1. char after the @
    obs_p22 = parts2_s[1]
    return f"{obs_p1}@{obs_p21}.{obs_p22}"


def uuid_and_hash():
    # () are not redundant ...
    # noinspection PyRedundantParentheses
    return (uuid := str(uuid4()), create_hash(uuid))
