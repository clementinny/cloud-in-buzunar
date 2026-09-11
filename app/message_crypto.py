import base64
import hashlib
import hmac
import secrets
from pathlib import Path

import pyaes


DATA_DIR = Path.home() / "cloud-in-buzunar-data"
MESSAGE_KEY_PATH = DATA_DIR / "message-encryption-key"
TOKEN_PREFIX = "aes256ctr-hmacsha256:v1:"
TOKEN_VERSION = b"\x01"
NONCE_SIZE = 16
MAC_SIZE = 32


class MessageDecryptionError(RuntimeError):
    pass


def load_master_key():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with MESSAGE_KEY_PATH.open("xb") as key_file:
            key_file.write(
                base64.urlsafe_b64encode(
                    secrets.token_bytes(32)
                )
            )
    except FileExistsError:
        pass

    MESSAGE_KEY_PATH.chmod(0o600)

    try:
        key = base64.urlsafe_b64decode(
            MESSAGE_KEY_PATH.read_bytes().strip()
        )
    except (OSError, ValueError) as error:
        raise RuntimeError(
            "Cheia de criptare a mesajelor este invalidă."
        ) from error

    if len(key) != 32:
        raise RuntimeError(
            "Cheia de criptare a mesajelor este invalidă."
        )

    return key


def derive_keys(master_key):
    encryption_key = hmac.new(
        master_key,
        b"CloudInBuzunar message encryption v1",
        hashlib.sha256,
    ).digest()
    authentication_key = hmac.new(
        master_key,
        b"CloudInBuzunar message authentication v1",
        hashlib.sha256,
    ).digest()

    return encryption_key, authentication_key


def encrypt_message_content(content):
    encryption_key, authentication_key = derive_keys(
        load_master_key()
    )
    nonce = secrets.token_bytes(NONCE_SIZE)
    counter = pyaes.Counter(
        int.from_bytes(nonce, byteorder="big")
    )
    cipher = pyaes.AESModeOfOperationCTR(
        encryption_key,
        counter=counter,
    )
    ciphertext = cipher.encrypt(content.encode("utf-8"))
    authenticated_data = TOKEN_VERSION + nonce + ciphertext
    signature = hmac.new(
        authentication_key,
        authenticated_data,
        hashlib.sha256,
    ).digest()
    token = base64.urlsafe_b64encode(
        authenticated_data + signature
    ).decode("ascii")

    return f"{TOKEN_PREFIX}{token}"


def decrypt_message_content(stored_content):
    if not stored_content.startswith(TOKEN_PREFIX):
        return stored_content

    encoded_token = stored_content[len(TOKEN_PREFIX):]

    try:
        token = base64.urlsafe_b64decode(encoded_token)
    except (ValueError, TypeError) as error:
        raise MessageDecryptionError(
            "Mesajul criptat este invalid."
        ) from error

    minimum_size = len(TOKEN_VERSION) + NONCE_SIZE + MAC_SIZE

    if len(token) < minimum_size or token[:1] != TOKEN_VERSION:
        raise MessageDecryptionError(
            "Mesajul criptat este invalid."
        )

    authenticated_data = token[:-MAC_SIZE]
    stored_signature = token[-MAC_SIZE:]
    encryption_key, authentication_key = derive_keys(
        load_master_key()
    )
    expected_signature = hmac.new(
        authentication_key,
        authenticated_data,
        hashlib.sha256,
    ).digest()

    if not hmac.compare_digest(
        stored_signature,
        expected_signature,
    ):
        raise MessageDecryptionError(
            "Mesajul nu poate fi autentificat cu cheia serverului."
        )

    nonce_start = len(TOKEN_VERSION)
    nonce_end = nonce_start + NONCE_SIZE
    nonce = authenticated_data[nonce_start:nonce_end]
    ciphertext = authenticated_data[nonce_end:]
    counter = pyaes.Counter(
        int.from_bytes(nonce, byteorder="big")
    )
    cipher = pyaes.AESModeOfOperationCTR(
        encryption_key,
        counter=counter,
    )

    try:
        return cipher.decrypt(ciphertext).decode("utf-8")
    except UnicodeDecodeError as error:
        raise MessageDecryptionError(
            "Conținutul mesajului criptat este invalid."
        ) from error
