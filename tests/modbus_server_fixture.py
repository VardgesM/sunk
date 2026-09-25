"""Deterministic software device used only by tests, never seeded by the application."""

from pymodbus.server import ModbusTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice


def test_devices() -> list[SimDevice]:
    return [
        SimDevice(
            id=unit,
            simdata=(
                [SimData(address=10, values=[True, False], datatype=DataType.BITS)],
                [SimData(address=20, values=[False, True], datatype=DataType.BITS)],
                [
                    SimData(
                        address=100,
                        values=[0x1234, 0x5678, 0xFFFE, 0x41C8, 0],
                        datatype=DataType.UINT16,
                    )
                ],
                [SimData(address=200, values=[unit, 0xFFFE], datatype=DataType.UINT16)],
            ),
        )
        for unit in (7, 11)
    ]


async def start_test_server(host: str = "127.0.0.1", port: int = 0) -> ModbusTcpServer:
    server = ModbusTcpServer(test_devices(), address=(host, port))
    await server.serve_forever(background=True)
    return server
