"""Drives the CLI-shaped login() from a web UI.

`TelegramSource.login()` asks for the code (and 2FA password) through blocking
callbacks, which suits a terminal. The browser answers over separate HTTP
requests instead, so the callbacks park on a queue until one arrives.

One login at a time, in memory only: starting a new one abandons the old.
Nothing here is persisted, and the phone/code/password are never logged —
they exist only inside this object for the seconds the flow takes.
"""

import asyncio
import contextlib
import queue
from typing import Optional

from .source import TelegramSource
from .types import TgAccount, TgError

# The user has to read a code out of another app; a minute is not enough and
# an idle flow must not pin a thread forever.
ANSWER_TIMEOUT = 300

# Cancelling the task does not touch the worker thread parked on the queue, so
# an abandoned login would hold a thread for ANSWER_TIMEOUT. This wakes it.
_ABORT = object()


class WebLogin:
    """States: idle -> code -> [password] -> done, or failed at any point."""

    def __init__(self) -> None:
        self.stage = "idle"
        self.error: Optional[str] = None
        self.account: Optional[TgAccount] = None
        self._task: Optional[asyncio.Task] = None
        self._answers: "queue.Queue[str]" = queue.Queue(maxsize=1)

    @property
    def waiting(self) -> bool:
        return self.stage in ("code", "password")

    def state(self) -> dict:
        return {
            "stage": self.stage,
            "error": self.error,
            "account": self.account.label if self.account else None,
        }

    async def start(self, source: TelegramSource, phone: str) -> dict:
        self.cancel()
        self.stage = "starting"
        self.error = None
        self.account = None
        self._answers = queue.Queue(maxsize=1)
        self._task = asyncio.create_task(self._run(source, phone))
        # Telegram has to accept the number and send the code before the UI can
        # honestly ask for one; surface "no such number" here, not later.
        return await self.wait_for_change("starting", timeout=60)

    def cancel(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        with contextlib.suppress(queue.Full):
            self._answers.put_nowait(_ABORT)
        self.stage = "idle"
        self.error = None

    async def submit(self, answer: str) -> dict:
        """Hand the pending prompt its answer and report the state it lands in."""
        if not self.waiting:
            raise TgError("目前沒有等待中的驗證步驟")
        was = self.stage
        try:
            self._answers.put_nowait(answer)
        except queue.Full:
            raise TgError("上一個答案還在處理中") from None
        return await self.wait_for_change(was, timeout=60)

    async def wait_for_change(self, previous: str, timeout: float) -> dict:
        """Poll rather than signal: the prompts run in a worker thread, so an
        asyncio.Event would have to be woken across loops for no real gain."""
        deadline = asyncio.get_running_loop().time() + timeout
        while self.stage == previous and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.1)
        return self.state()

    async def _run(self, source: TelegramSource, phone: str) -> None:
        mine = asyncio.current_task()
        try:
            account = await source.login(phone, self._ask_code, self._ask_password)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # includes TgBadCode / TgFloodWait
            if self._task is mine:  # a superseded attempt must not clobber the
                self.error = str(exc)  # state of the one that replaced it
                self.stage = "failed"
            return
        if self._task is mine:
            self.account = account
            self.stage = "done"

    # Both run in a worker thread (the adapter uses asyncio.to_thread).

    def _ask_code(self) -> str:
        # Reaching the prompt *is* the proof that Telegram accepted the number
        # and sent a code, which is when the UI may ask for one.
        self.stage = "code"
        return self._take("驗證碼")

    def _ask_password(self) -> str:
        self.stage = "password"
        return self._take("兩步驟驗證密碼")

    def _take(self, what: str) -> str:
        try:
            answer = self._answers.get(timeout=ANSWER_TIMEOUT)
        except queue.Empty:
            raise TgError(f"等待{what}逾時，請重新登入") from None
        if answer is _ABORT:
            raise TgError("登入已取消")
        return answer


web_login = WebLogin()
