"""
Encryption utilities for Netease Cloud Music API.

Implements WEAPI encryption used by Netease Cloud Music.
"""

import base64
import binascii
import json
import random
import string
from typing import Any, Dict

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

# WEAPI encryption constants
WEAPI_PRESET_KEY = b'0CoJUm6Qyw8W8jud'
WEAPI_IV = b'0102030405060708'
WEAPI_RSA_EXPONENT = 0x010001
WEAPI_RSA_MODULUS = int(
    '00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7'
    'b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280'
    '104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932'
    '575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b'
    '3ece0462db0a22b8e7', 16
)


def create_secret_key(size: int = 16) -> bytes:
    """Generate a random secret key for encryption."""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(size)).encode()


def aes_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """
    Encrypt data using AES-128-CBC.

    Args:
        plaintext: Data to encrypt
        key: Encryption key (16 bytes)

    Returns:
        Base64 encoded encrypted data
    """
    cipher = AES.new(key, AES.MODE_CBC, WEAPI_IV)
    padded = pad(plaintext, AES.block_size)
    encrypted = cipher.encrypt(padded)
    return base64.b64encode(encrypted)


def rsa_encrypt(plaintext: bytes) -> str:
    """
    RSA encrypt the secret key.

    Netease uses a non-standard RSA implementation without proper padding.

    Args:
        plaintext: Data to encrypt (typically the secret key)

    Returns:
        Hex encoded encrypted data
    """
    # Reverse the plaintext (Netease's quirk)
    reversed_text = plaintext[::-1]
    # Convert to integer
    text_int = int(binascii.hexlify(reversed_text), 16)
    # RSA encryption: c = m^e mod n
    encrypted_int = pow(text_int, WEAPI_RSA_EXPONENT, WEAPI_RSA_MODULUS)
    return format(encrypted_int, 'x').zfill(256)


def weapi_encrypt(data: Dict[str, Any]) -> Dict[str, str]:
    """
    Encrypt request data for WEAPI endpoints.

    Uses two rounds of AES encryption and RSA for the key.

    Args:
        data: Request data as dictionary

    Returns:
        Dictionary with 'params' and 'encSecKey' for the request
    """
    text = json.dumps(data, separators=(',', ':')).encode()
    secret_key = create_secret_key()

    # First round: encrypt with preset key
    encrypted = aes_encrypt(text, WEAPI_PRESET_KEY)
    # Second round: encrypt with random secret key
    encrypted = aes_encrypt(encrypted, secret_key)

    # RSA encrypt the secret key
    enc_sec_key = rsa_encrypt(secret_key)

    return {
        'params': encrypted.decode(),
        'encSecKey': enc_sec_key
    }
