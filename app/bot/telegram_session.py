import socket

from aiogram.client.session.aiohttp import AiohttpSession


def create_ipv4_session() -> AiohttpSession:
    session = AiohttpSession()
    # Windows + VPN setups can prefer a broken IPv6 route for api.telegram.org.
    # For polling we only need a stable route, so force IPv4.
    session._connector_init["family"] = socket.AF_INET
    return session
