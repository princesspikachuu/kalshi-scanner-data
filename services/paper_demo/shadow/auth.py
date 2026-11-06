import base64
import time
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

class Signer:
    def __init__(self, key_id: str, pem: bytes):
        self.key_id = key_id
        self.key = serialization.load_pem_private_key(pem, password=None)
        if not isinstance(self.key, (rsa.RSAPrivateKey, ed25519.Ed25519PrivateKey)):
            raise ValueError("Expected RSA or Ed25519 private key")

    def headers(self, method: str, path: str) -> dict[str, str]:
        ts = str(time.time_ns() // 1_000_000)
        message = (ts + method + path.split("?", 1)[0]).encode()
        if isinstance(self.key, rsa.RSAPrivateKey):
            signature = self.key.sign(message, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                                                          salt_length=32), hashes.SHA256())
        else:
            signature = self.key.sign(message)
        return {"KALSHI-ACCESS-KEY": self.key_id, "KALSHI-ACCESS-TIMESTAMP": ts,
                "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode()}
