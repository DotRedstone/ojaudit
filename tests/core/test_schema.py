"""
Module: Schema Tests
Description: 验证标准提交对象字段约束。
Scope: Test
"""

import pytest

from ojaudit.core.schema import Submission, validate_submission


def test_submission_accepts_supported_buckets():
    item = Submission("demo", "c1", "s1", "u1", 0, "cpp", "AC", 100, 1, "contest", "int main(){}")
    validate_submission(item)


def test_submission_rejects_invalid_phase():
    item = Submission("demo", "c1", "s1", "u1", 0, "cpp", "AC", 100, 1, "during", "")
    with pytest.raises(ValueError):
        validate_submission(item)
