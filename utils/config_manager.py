"""
Configuration management for the Streamlit dashboard.
Handles .env file operations securely.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv, set_key
except ImportError:
    raise ImportError("Please install python-dotenv: pip install python-dotenv")


class ConfigManager:
    """Safely manage .env configuration."""

    def __init__(self, env_path=None):
        """Initialize config manager with .env file path."""
        self.env_path = Path(env_path or ".env")
        if self.env_path.exists():
            load_dotenv(self.env_path)

    def get(self, key, default=""):
        """Get environment variable safely."""
        return os.getenv(key, default).strip()

    def set(self, key, value):
        """Set environment variable and save to .env."""
        if not self.env_path.exists():
            self.env_path.write_text("")
        set_key(str(self.env_path), key, value)
        os.environ[key] = value

    def has(self, key):
        """Check if key is configured."""
        return bool(self.get(key))

    def get_all(self):
        """Get all configured values (sensitive keys return '*' if set)."""
        sensitive_keys = {"HUNTER_API_KEY", "SERPER_API_KEY", "ANTHROPIC_API_KEY", "SMTP_PASSWORD"}
        values = {}
        for key in [
            "HUNTER_API_KEY", "SERPER_API_KEY", "ANTHROPIC_API_KEY",
            "MY_NAME", "MY_TARGET_ROLE", "MY_PHONE", "MY_LINKEDIN",
            "SMTP_USER", "SMTP_PASSWORD"
        ]:
            val = self.get(key)
            if key in sensitive_keys:
                values[key] = "***" if val else ""
            else:
                values[key] = val
        return values

    def validate(self):
        """Check if all required configs are set."""
        required = [
            "HUNTER_API_KEY", "SERPER_API_KEY", "ANTHROPIC_API_KEY",
            "MY_NAME", "MY_TARGET_ROLE",
        ]
        for_sending = ["SMTP_USER", "SMTP_PASSWORD"]

        missing_required = [k for k in required if not self.has(k)]
        missing_sending = [k for k in for_sending if not self.has(k)]

        return {
            "ready": len(missing_required) == 0,
            "missing_required": missing_required,
            "missing_for_sending": missing_sending,
        }
