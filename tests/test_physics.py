import pytest

from chuh0o.core.geometry import Area
from chuh0o.core.physics import PhysicsBody

AREA = Area(0, 0, 1000, 800)
WIDTH, HEIGHT = 144, 198
FLOOR = AREA.height - HEIGHT


def test_drop_bounces_loses_energy_and_settles_without_jitter():
    body = PhysicsBody()
    body.place(400, 50, AREA, WIDTH, HEIGHT)
    impacts = 0
    landed = False
    for _ in range(240):
        contact = body.advance(1 / 30, AREA, WIDTH, HEIGHT)
        impacts += contact.impacts
        landed |= contact.landed
        assert 0 <= body.y <= FLOOR
    assert impacts >= 1 and landed
    assert body.grounded and body.vy == 0 and body.y == FLOOR
    for _ in range(120):
        assert not body.advance(1 / 30, AREA, WIDTH, HEIGHT).landed
        assert body.y == FLOOR and body.vy == 0


def test_floor_support_and_friction_stop_a_horizontal_slide():
    body = PhysicsBody()
    body.place(100, FLOOR, AREA, WIDTH, HEIGHT)
    body.vx = 400
    for _ in range(60):
        body.advance(1 / 60, AREA, WIDTH, HEIGHT)
    assert body.x > 100 and body.vx == 0
    assert body.grounded and body.y == FLOOR and body.vy == 0


def test_fixed_step_is_independent_of_render_cadence():
    area = Area(-1000, -1000, 4000, 4000)

    def simulate(fps):
        body = PhysicsBody()
        body.place(200, 0, area, WIDTH, HEIGHT)
        body.release()
        body.vx, body.vy = 120, -100
        for _ in range(fps):
            body.advance(1 / fps, area, WIDTH, HEIGHT)
        return body.x, body.y, body.vx, body.vy

    assert simulate(30) == pytest.approx(simulate(60), abs=1e-7)
    assert simulate(60) == pytest.approx(simulate(100), abs=1e-7)


def test_walls_and_ceiling_reflect_velocity_and_stay_inside_negative_monitor():
    area = Area(-1000, -200, 1000, 800)
    body = PhysicsBody()
    body.place(-999, -199, area, WIDTH, HEIGHT)
    body.release()
    body.vx, body.vy = -1000, -800
    contact = body.advance(1 / 30, area, WIDTH, HEIGHT)
    assert contact.wall_hits == 1
    assert body.vx > 0 and body.vy > 0
    assert area.x <= body.x <= area.x + area.width - WIDTH
    assert area.y <= body.y <= area.y + area.height - HEIGHT


def test_grab_and_release_clear_momentum_then_gravity_resumes():
    body = PhysicsBody()
    body.place(300, 100, AREA, WIDTH, HEIGHT)
    body.vx, body.vy = 400, -300
    body.grab()
    body.advance(2, AREA, WIDTH, HEIGHT)
    assert body.x == 300 and body.y == 100 and body.vx == body.vy == 0
    body.vx, body.vy = 200, -200
    body.release()
    assert body.vx == body.vy == 0
    body.advance(1 / 30, AREA, WIDTH, HEIGHT)
    assert body.y > 100 and body.vy > 0


def test_long_frame_and_tiny_workarea_are_bounded():
    body = PhysicsBody()
    body.place(300, 100, AREA, WIDTH, HEIGHT)
    body.advance(3600, AREA, WIDTH, HEIGHT)
    assert 100 < body.y < 120
    tiny = Area(0, 0, 10, 10)
    body.place(300, 100, tiny, WIDTH, HEIGHT)
    body.advance(0.1, tiny, WIDTH, HEIGHT)
    assert body.x == body.y == body.vx == body.vy == 0 and body.grounded
