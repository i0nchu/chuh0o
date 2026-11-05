from pathlib import Path

import pytest

from chuh0o.core.animator import Animator, SpriteBank

ASSETS = Path(__file__).resolve().parents[1] / "assets"


def test_manifest_v3_keeps_individual_sizes_anchors_and_next_clips(app):
    clips = SpriteBank(ASSETS).scaled(0.75)
    assert (clips["idle"].width, clips["idle"].height) == (144, 198)
    assert (clips["wave"].width, clips["wave"].height) == (168, 198)
    assert (clips["jump_right"].width, clips["jump_right"].height) == (144, 258)
    assert (clips["liedown_right"].width, clips["liedown_right"].height) == (216, 216)
    assert (clips["lie_right"].width, clips["lie_right"].height) == (216, 120)
    assert clips["wave"].ground_anchor == clips["idle"].ground_anchor == (72, 198)
    assert clips["lie_right"].ground_anchor == (108, 120)
    assert clips["drag"].anchor != clips["drag"].ground_anchor
    assert clips["liedown_right"].next_name == "lie_right"
    assert max(clips["jump_right"].foot_lifts) > 0


def test_non_looping_clip_finishes_once_and_holds_last_frame(app):
    animator = Animator(SpriteBank(ASSETS).scaled(0.75))
    animator.play("wave")
    animator.advance(sum(animator.clip.durations) - 1)
    assert animator.index == 9 and not animator.finished
    animator.advance(1)
    assert animator.finished and animator.just_finished and animator.index == 9
    assert not animator.advance(10000)
    assert animator.finished and not animator.just_finished and animator.index == 9


@pytest.mark.parametrize("name,expected", [("jump_right", 66), ("jump_left", -66)])
def test_jump_motion_includes_skipped_frames_and_is_not_reapplied(app, name, expected):
    animator = Animator(SpriteBank(ASSETS).scaled(0.75))
    animator.play(name)
    first_duration = sum(animator.clip.durations[:5])
    animator.advance(first_duration)
    first_motion = animator.motion[0]
    assert animator.index == 5
    animator.advance(sum(animator.clip.durations) - first_duration)
    assert animator.finished
    assert first_motion + animator.motion[0] == pytest.approx(expected)
    assert animator.motion[1] == 0
    animator.advance(1000)
    assert animator.motion == (0, 0)
