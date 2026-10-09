import pytest

from app.services.rclone_config import (
    MegaCredentials,
    RcloneConfigResult,
    build_mega_config_args,
    build_remote_path,
    configure_mega_remotes,
    is_valid_remote_path,
    parse_remote_list,
    read_mega_credentials_file,
    remote_exists_in_config,
    remote_name_from_email,
    remote_name_from_path,
)


def test_build_mega_config_args_uses_obscured_password_and_optional_2fa():
    args = build_mega_config_args(
        "mega_archive",
        "user@example.com",
        "obscured-password",
        "123456",
    )

    assert args == [
        "config",
        "create",
        "mega_archive",
        "mega",
        "user",
        "user@example.com",
        "pass",
        "obscured-password",
        "--non-interactive",
        "2fa",
        "123456",
    ]


def test_build_mega_config_args_omits_empty_2fa():
    args = build_mega_config_args("mega", "user@example.com", "obscured-password")

    assert "2fa" not in args


def test_build_mega_config_args_can_update_existing_remote():
    args = build_mega_config_args(
        "mega",
        "user@example.com",
        "obscured-password",
        update=True,
    )

    assert args[:6] == ["config", "update", "mega", "type", "mega", "user"]
    assert "pass" in args


def test_remote_path_helpers_accept_named_remotes():
    assert remote_name_from_path("mega_2:Backup") == "mega_2"
    assert is_valid_remote_path("mega-archive:")
    assert build_remote_path("mega_3", "Photos") == "mega_3:Photos"


def test_remote_name_from_email_uses_text_before_at():
    assert remote_name_from_email("Account.One@example.com") == "account.one"
    assert remote_name_from_email("media+dvor@example.com") == "media_dvor"


def test_parse_remote_list_strips_trailing_colons_and_invalid_lines():
    assert parse_remote_list("mega:\nmega_2:\nnot valid:\nmega:\n") == [
        "mega",
        "mega_2",
    ]


def test_read_mega_credentials_file_reads_ini_sections(tmp_path):
    path = tmp_path / "credentials.txt"
    path.write_text(
        "[mega_1]\n"
        "email = one@example.com\n"
        "password = secret1\n"
        "\n"
        "[account-two]\n"
        "remote = mega_2\n"
        "user = two@example.com\n"
        "pass = secret2\n"
        "2fa = 123456\n",
        encoding="utf-8",
    )

    credentials = read_mega_credentials_file(path)

    assert credentials[0].remote_name == "mega_1"
    assert credentials[0].email == "one@example.com"
    assert credentials[0].password == "secret1"
    assert credentials[1].remote_name == "mega_2"
    assert credentials[1].twofa == "123456"


def test_read_mega_credentials_file_uses_email_section_as_login_and_remote(tmp_path):
    path = tmp_path / "credentials.ini"
    path.write_text(
        "[account1@example.com]\n"
        "password = secret1\n"
        "\n"
        "[account2@example.com]\n"
        "remote = mega_2\n"
        "password = secret2\n",
        encoding="utf-8",
    )

    credentials = read_mega_credentials_file(path)

    assert credentials[0].remote_name == "account1"
    assert credentials[0].email == "account1@example.com"
    assert credentials[1].remote_name == "mega_2"
    assert credentials[1].email == "account2@example.com"


def test_read_mega_credentials_file_uses_section_for_remote_even_with_email_field(
    tmp_path,
):
    path = tmp_path / "credentials.ini"
    path.write_text(
        "[first@example.com]\n"
        "email = shared@example.com\n"
        "password = secret1\n"
        "\n"
        "[second@example.com]\n"
        "email = shared@example.com\n"
        "password = secret2\n",
        encoding="utf-8",
    )

    credentials = read_mega_credentials_file(path)

    assert [item.remote_name for item in credentials] == ["first", "second"]
    assert [item.email for item in credentials] == [
        "shared@example.com",
        "shared@example.com",
    ]


def test_read_mega_credentials_file_rejects_duplicate_generated_remote_names(tmp_path):
    path = tmp_path / "credentials.ini"
    path.write_text(
        "[same@example.com]\n"
        "password = secret1\n"
        "\n"
        "[same@test.com]\n"
        "password = secret2\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="повторяется"):
        read_mega_credentials_file(path)


def test_read_mega_credentials_file_rejects_missing_password(tmp_path):
    path = tmp_path / "credentials.txt"
    path.write_text("[mega_1]\nemail = one@example.com\n", encoding="utf-8")

    with pytest.raises(ValueError, match="password"):
        read_mega_credentials_file(path)


def test_read_mega_credentials_file_rejects_plain_text_without_sections(tmp_path):
    path = tmp_path / "credentials.txt"
    path.write_text("email = one@example.com\npassword = secret\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Не удалось прочитать"):
        read_mega_credentials_file(path)


def test_remote_exists_in_config_reads_rclone_conf_sections(tmp_path):
    config_path = tmp_path / "rclone.conf"
    config_path.write_text(
        "[mega]\n"
        "type = mega\n"
        "\n"
        "[mega_2]\n"
        "type = mega\n",
        encoding="utf-8",
    )

    assert remote_exists_in_config(config_path, "mega_2")
    assert not remote_exists_in_config(config_path, "mega_3")


def test_configure_mega_remotes_continues_after_single_failure(tmp_path, monkeypatch):
    import app.services.rclone_config as rclone_config

    def fake_configure_mega_remote(**kwargs):
        remote_name = kwargs["remote_name"]
        if remote_name == "bad":
            return RcloneConfigResult(False, "failed", "")
        return RcloneConfigResult(True, "ok", "")

    monkeypatch.setattr(
        rclone_config,
        "configure_mega_remote",
        fake_configure_mega_remote,
    )

    result = configure_mega_remotes(
        rclone_path="rclone.exe",
        config_path=tmp_path / "rclone.conf",
        credentials=[
            MegaCredentials("good", "good@example.com", "secret"),
            MegaCredentials("bad", "bad@example.com", "secret"),
        ],
    )

    assert result.success is False
    assert result.configured_remote_names == ["good"]
    assert result.failed_remote_names == ["bad"]
