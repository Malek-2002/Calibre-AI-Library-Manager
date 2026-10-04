import time

from calibre_ui.errors import UITimeout


def wait_until(predicate, timeout: float, *, interval: float = 0.25, what: str = "condition"):
    """Poll `predicate` until it returns something truthy (returned). Exceptions count as 'not yet'."""
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while True:
        try:
            result = predicate()
            if result:
                return result
        except Exception as e:  # UIA is flaky while windows open/close
            last_error = e
        if time.monotonic() >= deadline:
            extra = f" (last error: {last_error})" if last_error else ""
            raise UITimeout(f"Timed out after {timeout:.0f}s waiting for {what}{extra}")
        time.sleep(interval)
