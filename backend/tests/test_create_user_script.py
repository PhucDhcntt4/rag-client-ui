from unittest.mock import patch
from uuid import UUID

from create_admin import prompt_permission_group, prompt_role


def test_prompt_role_accepts_number_and_defaults_to_employee():
    with patch("builtins.input", return_value="2"):
        assert prompt_role() == "manager"
    with patch("builtins.input", return_value=""):
        assert prompt_role() == "employee"


def test_admin_does_not_need_permission_group():
    groups = [
        (
            UUID("00000000-0000-0000-0000-000000000001"),
            "STORE",
            "Nhân viên cửa hàng",
        )
    ]
    assert prompt_permission_group(groups, "admin") is None


def test_employee_can_choose_one_permission_group():
    group_id = UUID("00000000-0000-0000-0000-000000000001")
    groups = [(group_id, "STORE", "Nhân viên cửa hàng")]
    with patch("builtins.input", return_value="1"):
        assert prompt_permission_group(groups, "employee") == group_id
