from __future__ import annotations

import json

from app.core.config import TwscrapeAccountSettings, _parse_twscrape_accounts


def test_parse_twscrape_accounts_supports_cookie_and_credential_accounts() -> None:
    payload = json.dumps(
        [
            {
                "username": "cookie_user",
                "auth_token": "token-1",
                "ct0": "ct0-1",
            },
            {
                "username": "credential_user",
                "password": "password",
                "email": "user@example.com",
                "email_password": "mailpass",
                "mfa_code": "123456",
            },
        ]
    )

    accounts = _parse_twscrape_accounts(payload)

    assert len(accounts) == 2
    assert isinstance(accounts[0], TwscrapeAccountSettings)
    assert accounts[0].cookies_value() == "auth_token=token-1; ct0=ct0-1"
    assert accounts[0].has_cookie_auth() is True
    assert accounts[1].has_password_auth() is True
    assert accounts[1].mfa_code == "123456"
