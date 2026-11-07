
import unittest
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from benchmark_server import BenchmarkHandler


class ServerTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), BenchmarkHandler
        )
        threading.Thread(
            target=cls.server.serve_forever, daemon=True
        ).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def post(self, path):
        return urlopen(Request(
            self.url + path,
            data=b"X" * 64,
            method="POST"
        ), timeout=3)

    def test_health(self):
        with urlopen(self.url + "/health") as r:
            self.assertEqual(r.status, 200)

    def test_normal_request(self):
        with self.post("/1?response_delay_ms=0") as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(len(r.read()), 128)
            self.assertEqual(r.headers["X-Server-ID"], "1")

    def test_stall(self):
        with self.post("/1?mode=STALL&stall_ms=200") as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(len(r.read()), 128)

    def test_drop(self):
        with self.assertRaises((URLError, ConnectionError, OSError)):
            self.post("/1?mode=DROP&drop_ms=0")

    def test_invalid_mode(self):
        with self.assertRaises(HTTPError) as e:
            self.post("/1?mode=INVALID")
        self.assertEqual(e.exception.code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)

