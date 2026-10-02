from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from catlabel.api.security import LocalSecurityMiddleware
from catlabel.core.server_security import ServerSecurity

TOKEN = "sample-access-token-at-least-32-characters"
CLIENT = {"X-CatLabel-Client": "1"}


def client_for(settings: ServerSecurity) -> tuple[TestClient, list[str]]:
    app = FastAPI()
    actions: list[str] = []

    @app.api_route("/api/action", methods=["GET", "POST", "DELETE"])
    def action():
        actions.append("called")
        return {"status": "ok"}

    @app.get("/")
    def home():
        return {"app": "CatLabel"}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["X-CatLabel-Client", "Content-Type", "Authorization"],
        allow_credentials=True,
    )
    app.add_middleware(LocalSecurityMiddleware, settings=settings)
    return TestClient(app, base_url="http://localhost:8000"), actions


class LocalSecurityTests(unittest.TestCase):
    def test_default_binding_and_lan_configuration_fail_closed(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = ServerSecurity.from_environment()
        self.assertEqual((settings.host, settings.port), ("127.0.0.1", 8000))
        for create in (
            lambda: ServerSecurity(host="0.0.0.0"),
            lambda: ServerSecurity(host="0.0.0.0", access_token=TOKEN),
            lambda: ServerSecurity(access_token="short"),
            lambda: ServerSecurity(allowed_origins=("*",)),
            lambda: ServerSecurity(allowed_origins=("http://localhost:8000/private",)),
            lambda: ServerSecurity(port=65536),
        ):
            with self.assertRaises(ValueError):
                create()

    def test_all_api_methods_require_the_client_header_before_side_effects(
        self,
    ) -> None:
        client, actions = client_for(ServerSecurity())
        for method in ("GET", "POST", "DELETE"):
            self.assertEqual(client.request(method, "/api/action").status_code, 403)
        self.assertEqual(actions, [])
        for method in ("GET", "POST", "DELETE"):
            self.assertEqual(
                client.request(method, "/api/action", headers=CLIENT).status_code, 200
            )
        self.assertEqual(len(actions), 3)

    def test_foreign_null_and_malformed_origins_cannot_reach_the_handler(self) -> None:
        client, actions = client_for(ServerSecurity())
        for origin in (
            "https://attacker.invalid",
            "null",
            "http://localhost:8001",
            "http://localhost:8000@attacker.invalid",
            "http://localhost:8000/path",
        ):
            with self.subTest(origin=origin):
                self.assertEqual(
                    client.post(
                        "/api/action", headers={**CLIENT, "Origin": origin}
                    ).status_code,
                    403,
                )
        self.assertEqual(actions, [])
        response = client.post(
            "/api/action", headers={**CLIENT, "Origin": "http://localhost:8000"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_dns_rebinding_and_cross_site_fetch_are_rejected(self) -> None:
        client, actions = client_for(ServerSecurity())
        for host in (
            "attacker.invalid:8000",
            "localhost.attacker.invalid",
            "localhost:8000@attacker.invalid",
        ):
            with self.subTest(host=host):
                self.assertEqual(
                    client.get(
                        "/api/action", headers={**CLIENT, "Host": host}
                    ).status_code,
                    400,
                )
        self.assertEqual(
            client.get(
                "/api/action", headers={**CLIENT, "Sec-Fetch-Site": "cross-site"}
            ).status_code,
            403,
        )
        self.assertEqual(actions, [])

    def test_explicit_dev_origin_preflight_and_cookie_access(self) -> None:
        settings = ServerSecurity(allowed_origins=("http://localhost:5173",))
        client, _actions = client_for(settings)
        response = client.options(
            "/api/action",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-CatLabel-Client,Content-Type",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["access-control-allow-origin"], "http://localhost:5173"
        )
        self.assertEqual(
            client.post(
                "/api/action", headers={**CLIENT, "Origin": "http://localhost:5173"}
            ).status_code,
            200,
        )

    def test_lan_authentication_and_same_origin_sign_in(self) -> None:
        settings = ServerSecurity(
            host="0.0.0.0",
            access_token=TOKEN,
            allowed_origins=("http://192.168.1.20:8000",),
        )
        self.assertEqual(settings.browser_url, "http://192.168.1.20:8000")
        client, actions = client_for(settings)
        self.assertEqual(client.get("/api/action", headers=CLIENT).status_code, 401)
        login = client.get("/", headers={"Accept": "text/html"})
        self.assertEqual(login.status_code, 401)
        self.assertIn('for="token"', login.text)
        self.assertNotIn(TOKEN, login.text)
        self.assertEqual(
            client.post("/auth/login", data={"token": TOKEN}).status_code, 403
        )
        self.assertEqual(
            client.post(
                "/auth/login",
                data={"token": TOKEN},
                headers={"Origin": "https://attacker.invalid"},
            ).status_code,
            403,
        )
        self.assertEqual(actions, [])
        bad = client.post(
            "/auth/login",
            data={"token": "wrong"},
            headers={"Origin": "http://localhost:8000"},
        )
        self.assertEqual(bad.status_code, 401)
        good = client.post(
            "/auth/login",
            data={"token": TOKEN},
            headers={"Origin": "http://localhost:8000"},
            follow_redirects=False,
        )
        self.assertEqual(good.status_code, 303)
        self.assertIn("HttpOnly", good.headers["set-cookie"])
        self.assertIn("SameSite=strict", good.headers["set-cookie"])
        self.assertNotIn(TOKEN, good.headers["set-cookie"])
        self.assertEqual(client.post("/api/action", headers=CLIENT).status_code, 200)

    def test_bearer_and_session_lifecycle(self) -> None:
        settings = ServerSecurity(access_token=TOKEN)
        client, _actions = client_for(settings)
        self.assertEqual(
            client.get(
                "/api/action", headers={**CLIENT, "Authorization": f"Bearer {TOKEN}"}
            ).status_code,
            200,
        )
        self.assertEqual(
            client.get(
                "/api/action", headers={**CLIENT, "Authorization": "Bearer wrong"}
            ).status_code,
            401,
        )
        client.post("/auth/login", data={"token": TOKEN}, headers=CLIENT)
        fresh, _fresh_actions = client_for(settings)
        fresh.cookies.update(client.cookies)
        self.assertEqual(fresh.get("/api/action", headers=CLIENT).status_code, 401)

    def test_oversized_and_duplicate_login_fields_are_rejected(self) -> None:
        client, _actions = client_for(ServerSecurity(access_token=TOKEN))
        headers = {**CLIENT, "Content-Type": "application/x-www-form-urlencoded"}
        self.assertEqual(
            client.post(
                "/auth/login", content="token=" + "x" * 4096, headers=headers
            ).status_code,
            413,
        )
        self.assertEqual(
            client.post(
                "/auth/login", content=f"token={TOKEN}&token={TOKEN}", headers=headers
            ).status_code,
            401,
        )


if __name__ == "__main__":
    unittest.main()
