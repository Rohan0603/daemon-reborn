from __future__ import annotations

from daemon_reborn.ui.physics import PetPhysics, PhysicsBounds, PhysicsConfig, Vec2


def make_physics() -> PetPhysics:
    return PetPhysics(Vec2(20.0, 0.0), Vec2(10.0, 10.0), PhysicsBounds(0.0, 0.0, 100.0, 100.0))


def test_gravity_lands_without_tunneling() -> None:
    physics = PetPhysics(Vec2(20.0, 85.0), Vec2(10.0, 10.0), PhysicsBounds(0.0, 0.0, 100.0, 100.0))
    physics.step(0.12)

    assert physics.position.y == 90.0
    assert physics.velocity.y == 0.0


def test_drag_tracks_pointer_and_clamps_to_bounds() -> None:
    physics = make_physics()
    physics.begin_drag(Vec2(25.0, 5.0))
    physics.drag_to(Vec2(150.0, 150.0))

    assert physics.position == Vec2(90.0, 90.0)
    assert physics.velocity == Vec2(0.0, 0.0)
    physics.release()
    assert not physics.is_dragging


def test_chase_targets_horizontal_center() -> None:
    physics = make_physics()
    physics.step(0.1, target=Vec2(90.0, 50.0))

    assert physics.position.x > 20.0
    assert 0.0 < physics.position.y < 90.0


def test_zero_and_negative_delta_do_not_move() -> None:
    physics = make_physics()
    original = physics.position
    physics.step(0.0)
    physics.step(-1.0)

    assert physics.position == original


def test_bounds_reorder_and_oversized_pet_are_safe() -> None:
    physics = PetPhysics(
        Vec2(-10.0, -10.0), Vec2(200.0, 200.0), PhysicsBounds(100.0, 100.0, 0.0, 0.0)
    )

    assert physics.position == Vec2(0.0, 0.0)
    physics.set_bounds(PhysicsBounds(20.0, 20.0, 10.0, 10.0))
    assert physics.position == Vec2(10.0, 10.0)


def test_delayed_tick_is_bounded() -> None:
    config = PhysicsConfig(gravity=100.0, max_delta=0.12)
    physics = PetPhysics(
        Vec2(0.0, 0.0), Vec2(10.0, 10.0), PhysicsBounds(0.0, 0.0, 1000.0, 1000.0), config
    )
    physics.step(10.0)

    assert physics.position.y < 100.0


def test_invalid_config_is_rejected() -> None:
    try:
        PhysicsConfig(substep=0.0)
    except ValueError:
        pass
    else:
        raise AssertionError("non-positive substep must be rejected")
