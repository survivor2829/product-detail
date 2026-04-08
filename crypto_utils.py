"""
API Key 加密/解密工具（Fernet 对称加密）
"""
import os
from cryptography.fernet import Fernet

_FERNET_KEY = os.environ.get("FERNET_KEY", "")

def _get_fernet():
    if not _FERNET_KEY:
        raise RuntimeError("未设置 FERNET_KEY 环境变量，无法加密/解密 API Key")
    return Fernet(_FERNET_KEY.encode() if isinstance(_FERNET_KEY, str) else _FERNET_KEY)

def encrypt_api_key(plaintext: str) -> str:
    """加密 API Key，返回密文字符串"""
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()

def decrypt_api_key(ciphertext: str) -> str:
    """解密 API Key，返回明文"""
    if not ciphertext:
        return ""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
