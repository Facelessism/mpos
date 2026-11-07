# RUN: python benchmark_server.py --host 0.0.0.0 --port 8080

import argparse
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

DEFAULT_MODE = "MPOS CHECK"
DEFAULT_REQUEST_SIZE = 64
DEFAULT_RESPONSE_SIZE = 128
DEFAULT_RESPONSE_DELAY_MS = 100
DEFAULT_STALL_MS = 1000
DEFAULT_DROP_MS = 10000


class BenchmarkHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        try:
            server_id = int(parsed.path.strip("/").split("/")[-1])
        except (ValueError, IndexError):
            server_id = -1

        def get_int(name, default):
            try:
                return int(params.get(name, [default])[0])
            except (ValueError, TypeError):
                return default

        request_size = max(0, get_int("request_size", DEFAULT_REQUEST_SIZE))
        response_size = max(0, get_int("response_size", DEFAULT_RESPONSE_SIZE))
        response_delay_ms = max(
            0, get_int("response_delay_ms", DEFAULT_RESPONSE_DELAY_MS)
        )
        stall_ms = max(0, get_int("stall_ms", DEFAULT_STALL_MS))
        drop_ms = max(0, get_int("drop_ms", DEFAULT_DROP_MS))
        mode = params.get("mode", [DEFAULT_MODE])[0]
        normalized_mode = mode.strip().upper()

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "Invalid Content-Length")
            return

        if content_length < 0:
            self.send_error(400, "Negative Content-Length")
            return

        body = self.rfile.read(content_length)
        actual_request_size = len(body)
        received_at = time.perf_counter()

        if normalized_mode == "DROP":
            time.sleep(drop_ms / 1000.0)
            self.close_connection = True

            try:
                self.connection.shutdown(2)
            except OSError:
                pass

            try:
                self.connection.close()
            except OSError:
                pass

            return

        if normalized_mode == "STALL":
            time.sleep(stall_ms / 1000.0)
        elif normalized_mode in ("MPOS CHECK", "OK"):
            time.sleep(response_delay_ms / 1000.0)
        else:
            self.send_error(400, "Unsupported benchmark mode")
            return

        response_body = b"R" * response_size

        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(response_body)))
        self.send_header("Connection", "close")
        self.send_header("X-Server-ID", str(server_id))
        self.send_header("X-Request-Bytes", str(actual_request_size))
        self.send_header("X-Expected-Request-Bytes", str(request_size))
        self.send_header("X-Server-Received-At", str(received_at))
        self.send_header("X-Benchmark-Mode", mode)
        self.end_headers()

        try:
            self.wfile.write(response_body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.close_connection = True

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            body = b"MPOS PROC benchmark server ready"

            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()

            try:
                self.wfile.write(body)
            except OSError:
                pass

            return

        self.send_error(404, "Not Found")

    def log_message(self, fmt, *args):
        return


class BenchmarkHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


def main():
    parser = argparse.ArgumentParser(
        description="MPOS PROC HTTP benchmark server"
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    server = BenchmarkHTTPServer(
        (args.host, args.port),
        BenchmarkHandler,
    )

    print("MPOS PROC BENCHMARK SERVER")
    print("Listening host :", args.host)
    print("Listening port :", args.port)
    print("Default mode   :", DEFAULT_MODE)
    print("Response delay :", DEFAULT_RESPONSE_DELAY_MS, "ms")
    print("Stall duration :", DEFAULT_STALL_MS, "ms")
    print("Drop duration  :", DEFAULT_DROP_MS, "ms")
    print("Health endpoint: /health")
    print("Server is ready. Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping benchmark server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
