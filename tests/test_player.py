from cagsyntax.viewer.player import CinePlayer


def test_step_forward():
    p = CinePlayer(5, 15)
    p.step(1)
    assert p.index == 1


def test_step_back_clamps_at_zero():
    p = CinePlayer(5, 15)
    p.step(-1)
    assert p.index == 0


def test_step_past_end_clamps():
    p = CinePlayer(5, 15)
    p.step(99)
    assert p.index == 4


def test_tick_while_paused_does_not_move():
    p = CinePlayer(5, 15)
    p.tick()
    assert p.index == 0


def test_tick_while_playing_advances_and_wraps():
    p = CinePlayer(3, 15)
    p.play()
    p.tick(); p.tick()
    assert p.index == 2
    p.tick()
    assert p.index == 0


def test_seek_clamps():
    p = CinePlayer(5, 15)
    p.seek(99)
    assert p.index == 4
    p.seek(-3)
    assert p.index == 0


def test_toggle():
    p = CinePlayer(5, 15)
    p.toggle()
    assert p.playing
    p.toggle()
    assert not p.playing


def test_interval_ms():
    assert CinePlayer(5, 15).interval_ms == 67


def test_single_frame_series():
    p = CinePlayer(1, 15)
    p.play(); p.tick(); p.step(1); p.step(-1)
    assert p.index == 0
