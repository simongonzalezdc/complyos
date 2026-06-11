"""Tests for ComplyOS profile definitions."""

from __future__ import annotations

import pytest

from complyos.profiles import ComplyOSProfile, get_profile, list_profiles, render_profile_config


def test_list_profiles_returns_workforce_then_campus():
    assert [profile.name for profile in list_profiles()] == ["workforce", "campus"]


def test_workforce_profile_terms_and_connectors():
    profile = get_profile("workforce")

    assert profile.display_name == "ComplyOS Workforce"
    assert profile.learner_term == "employee"
    assert profile.learning_item_term == "training"
    assert "cornerstone" in profile.recommended_connectors


def test_campus_profile_terms_and_connectors_from_enum():
    profile = get_profile(ComplyOSProfile.CAMPUS)

    assert profile.display_name == "ComplyOS Campus"
    assert profile.learner_term == "student"
    assert profile.learning_item_term == "course"
    assert "canvas" in profile.recommended_connectors


def test_unknown_profile_raises_value_error():
    with pytest.raises(ValueError, match="Unknown ComplyOS profile"):
        get_profile("unknown")


def test_render_profile_config_contains_campus_defaults():
    config = render_profile_config("campus")

    assert "profile: campus" in config
    assert "connector:" in config
    assert "type: csv" in config
    assert "learner_term: student" in config


def test_get_profile_normalizes_whitespace_and_case():
    assert get_profile(" Workforce ").name == "workforce"
