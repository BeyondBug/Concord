"""Credential Broker — per-connector scoped tokens. No master credential."""
import os


class CredentialBroker:
    def get_token(self, connector_name: str) -> str:
        """Return the scoped token for one specific connector.

        Each connector has its own token env var.
        No agent ever holds another agent's credential.
        """
        env_key = connector_name.upper() + "_TOKEN"
        token = os.getenv(env_key, "")
        if not token:
            raise ValueError(
                f"No token for connector '{connector_name}'. "
                f"Set {env_key} in your .env file."
            )
        return token
