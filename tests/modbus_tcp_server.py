"""Optional software Modbus device, isolated from application source/configuration."""

import argparse
import asyncio

from modbus_server_fixture import start_test_server


async def main(host: str, port: int) -> None:
    server = await start_test_server(host, port)
    try:
        await asyncio.Event().wait()
    finally:
        await server.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.host, args.port))
