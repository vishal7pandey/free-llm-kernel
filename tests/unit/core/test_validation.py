"""Tests for the validation module.

These tests exercise ValidationError and the public validate() helper.
"""

import pytest


class TestValidationError:
    def test_validation_error_message(self):
        from llm_kernel.core import ValidationError

        err = ValidationError("temperature must be between 0 and 2")
        assert "temperature" in str(err)

    def test_validation_error_can_wrap_cause(self):
        from llm_kernel.core import ValidationError

        cause = ValueError("bad value")
        err = ValidationError("invalid", cause=cause)
        assert err.__cause__ is cause
