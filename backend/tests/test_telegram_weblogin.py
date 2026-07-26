"""The web login state machine: the browser answers prompts that the seam
still asks through blocking callbacks.

asyncio.run per test instead of pytest-asyncio — one helper beats a dev
dependency for six tests.
"""

import asyncio

import pytest

from app.telegram.types import TgAccount, TgBadCode, TgError
from app.telegram.weblogin import WebLogin


def run(coro):
    return asyncio.run(coro)


class FakeSource:
    """Mimics the adapter: prompts are blocking callables run off the loop."""

    def __init__(self, *, code="12345", password=None, send_fails=False):
        self.code, self.password, self.send_fails = code, password, send_fails

    async def login(self, phone, ask_code, ask_password):
        if self.send_fails:
            raise TgBadCode("invalid phone number")
        if (await asyncio.to_thread(ask_code)) != self.code:
            raise TgBadCode("wrong code")
        if self.password and (await asyncio.to_thread(ask_password)) != self.password:
            raise TgBadCode("wrong password")
        return TgAccount(id=1, first_name="Neko", username="neko")


def test_code_only_login_reaches_done():
    async def scenario():
        login = WebLogin()
        assert (await login.start(FakeSource(), "+886912345678"))["stage"] == "code"
        return await login.submit("12345")

    state = run(scenario())
    assert state["stage"] == "done"
    assert state["account"] == "@neko"


def test_two_step_verification_asks_for_the_password_next():
    async def scenario():
        login = WebLogin()
        await login.start(FakeSource(password="hunter2"), "+886912345678")
        assert (await login.submit("12345"))["stage"] == "password"
        return await login.submit("hunter2")

    assert run(scenario())["stage"] == "done"


def test_wrong_code_fails_with_the_reason_shown():
    async def scenario():
        login = WebLogin()
        await login.start(FakeSource(), "+886912345678")
        return await login.submit("00000")

    state = run(scenario())
    assert state["stage"] == "failed"
    assert "wrong code" in state["error"]


def test_a_rejected_phone_number_never_asks_for_a_code():
    """Otherwise the UI shows a code box for a code Telegram never sent."""

    async def scenario():
        return await WebLogin().start(FakeSource(send_fails=True), "+1")

    assert run(scenario())["stage"] == "failed"


def test_answering_when_nothing_is_pending_is_rejected():
    async def scenario():
        await WebLogin().submit("12345")

    with pytest.raises(TgError):
        run(scenario())


def test_starting_again_abandons_the_previous_attempt():
    async def scenario():
        login = WebLogin()
        await login.start(FakeSource(), "+886900000000")
        await login.start(FakeSource(), "+886911111111")
        return await login.submit("12345")

    assert run(scenario())["stage"] == "done"
