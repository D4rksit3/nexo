"""Configuración por variables de entorno (ver README)."""
import os
import socket
from dataclasses import dataclass, field


def _bool(name, default):
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "si", "sí", "on")


@dataclass
class Config:
    data_dir: str = field(default_factory=lambda: os.environ.get("NEXO_DATA", "/data"))
    org_name: str = field(default_factory=lambda: os.environ.get("NEXO_ORG_NAME", "Mi organización"))
    public_host: str = field(default_factory=lambda: os.environ.get("NEXO_PUBLIC_HOST", socket.gethostname()))
    public_url: str = field(default_factory=lambda: os.environ.get("NEXO_PUBLIC_URL", ""))
    ssh_bind: str = field(default_factory=lambda: os.environ.get("NEXO_SSH_BIND", "0.0.0.0"))
    ssh_port: int = field(default_factory=lambda: int(os.environ.get("NEXO_SSH_PORT", "2222")))
    public_ssh_port: int = field(default_factory=lambda: int(os.environ.get("NEXO_PUBLIC_SSH_PORT", "0")))
    http_bind: str = field(default_factory=lambda: os.environ.get("NEXO_HTTP_BIND", "0.0.0.0"))
    http_port: int = field(default_factory=lambda: int(os.environ.get("NEXO_HTTP_PORT", "8080")))
    token_hours: float = field(default_factory=lambda: float(os.environ.get("NEXO_TOKEN_HOURS", "12")))
    web_hours: float = field(default_factory=lambda: float(os.environ.get("NEXO_WEB_HOURS", "8")))
    record: bool = field(default_factory=lambda: _bool("NEXO_RECORD", True))
    trust_proxy: bool = field(default_factory=lambda: _bool("NEXO_TRUST_PROXY", False))
    secure_cookie: str = field(default_factory=lambda: os.environ.get("NEXO_SECURE_COOKIE", "auto"))

    def __post_init__(self):
        if not self.public_ssh_port:
            self.public_ssh_port = self.ssh_port
        if not self.public_url:
            self.public_url = f"http://{self.public_host}:{self.http_port}"

    def cookie_secure(self, req):
        if self.secure_cookie in ("1", "true", "yes"):
            return True
        if self.secure_cookie in ("0", "false", "no"):
            return False
        proto = req.headers.get("X-Forwarded-Proto", "") if self.trust_proxy else ""
        return req.secure or proto == "https" or self.public_url.startswith("https://")
