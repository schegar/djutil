"""AgentStatus thread-safety and icon/status-line behaviour."""

import threading

from djutil_agent.status import AgentStatus


def test_defaults():
    s = AgentStatus().snapshot()
    assert s.configured
    assert s.connection == "disconnected"
    assert s.icon_color() == "amber"  # not yet connected, no error


def test_not_configured_is_red_with_hint():
    st = AgentStatus()
    st.set_configured(False)
    st.set_error("Not configured – use Open config or `djutil-agent configure`")
    snap = st.snapshot()
    assert snap.icon_color() == "red"
    assert "Not configured" in snap.status_line()


def test_connected_plus_ok_sync_is_green():
    st = AgentStatus()
    st.set_connection("connected")
    st.mark_sync(ok=True)
    assert st.snapshot().icon_color() == "green"
    line = st.snapshot().status_line()
    assert "connected" in line and "ok" in line


def test_failed_sync_is_red_error():
    st = AgentStatus()
    st.set_connection("connected")
    st.mark_sync(ok=False, error="boom")
    snap = st.snapshot()
    assert snap.icon_color() == "red"
    assert "boom" in snap.status_line()


def test_recording_and_last_play():
    st = AgentStatus()
    st.set_last_play("DJ X - Title 1")
    st.set_recording(True)
    snap = st.snapshot()
    assert snap.recording
    assert "DJ X - Title 1" in snap.status_line()


def test_threadsafe_concurrent_writes():
    st = AgentStatus()

    def writer(i):
        for _ in range(200):
            st.mark_sync(ok=True)
            st.set_connection("connected")
            st.set_last_play(f"t{i}")
            st.set_recording(bool(i % 2))

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    snap = st.snapshot()
    assert snap.last_sync_at is not None
