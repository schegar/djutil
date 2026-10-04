import threading
import time

from djutil_agent.sync.watcher import Debouncer


def test_debouncer_fires_once_after_quiet():
    fired = threading.Event()
    calls = []

    def cb():
        calls.append(1)
        fired.set()

    d = Debouncer(0.05, cb)
    d.notify()
    d.notify()
    d.notify()
    assert fired.wait(1.0)
    time.sleep(0.1)
    assert calls == [1]


def test_debouncer_cancel():
    fired = threading.Event()
    d = Debouncer(0.05, fired.set)
    d.notify()
    d.cancel()
    assert not fired.wait(0.3)


def test_debouncer_refires():
    calls = []
    d = Debouncer(0.03, lambda: calls.append(1))
    d.notify()
    time.sleep(0.15)
    d.notify()
    time.sleep(0.15)
    assert len(calls) == 2
