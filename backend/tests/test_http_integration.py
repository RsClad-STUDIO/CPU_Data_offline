"""Loopback integration tests for the shared HTTP transport."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import requests

from cpu_data.infrastructure import http


class _Handler(BaseHTTPRequestHandler):
    retry_attempts = 0

    def do_GET(self):
        if self.path == "/retry":
            type(self).retry_attempts += 1
            if type(self).retry_attempts < 3:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b"temporarily unavailable")
                return

        if self.path == "/not-found":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):
        pass


class HTTPTransportIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.server.daemon_threads = True
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        _Handler.retry_attempts = 0

    def _session(self):
        settings = SimpleNamespace(
            http_retries=2,
            retry_backoff=0,
            http_connect_timeout=1,
            http_read_timeout=1,
        )
        with patch.object(http, "SETTINGS", settings):
            return http.build_session()

    def test_get_returns_successful_response(self):
        session = self._session()
        try:
            with patch.object(http, "SESSION", session):
                response = http.get(f"{self.base_url}/ok")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.text, "ok")
        finally:
            session.close()

    def test_get_preserves_http_status_errors(self):
        session = self._session()
        try:
            with patch.object(http, "SESSION", session):
                with self.assertRaises(requests.HTTPError) as caught:
                    http.get(f"{self.base_url}/not-found")
            self.assertEqual(caught.exception.response.status_code, 404)
        finally:
            session.close()

    def test_get_retries_temporary_server_errors(self):
        session = self._session()
        try:
            with patch.object(http, "SESSION", session):
                response = http.get(f"{self.base_url}/retry")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(_Handler.retry_attempts, 3)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
