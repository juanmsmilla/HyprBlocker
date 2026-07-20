"""Tests for the tier-3 constrained-grammar validator (daemon.grants.executor)."""

import pytest

from daemon.grants import executor


class TestValidCommands:
    def test_pacman_install_package(self):
        cmd = executor.validate_command(["pacman", "-S", "--noconfirm", "ripgrep"])
        assert cmd.template_name == "pacman-install"
        assert cmd.argv == ("/usr/bin/pacman", "-S", "--noconfirm", "ripgrep")

    def test_pacman_full_upgrade(self):
        cmd = executor.validate_command(["pacman", "-Syu", "--noconfirm"])
        assert cmd.template_name == "pacman-upgrade"

    def test_absolute_path_accepted(self):
        cmd = executor.validate_command(["/usr/bin/pacman", "-Syu", "--noconfirm"])
        assert cmd.argv[0] == "/usr/bin/pacman"

    def test_canonicalization_returns_absolute_path(self):
        cmd = executor.validate_command(["flatpak", "update", "-y"])
        assert cmd.argv == ("/usr/bin/flatpak", "update", "-y")

    def test_describe_mentions_argv(self):
        cmd = executor.validate_command(["pacman", "-S", "--noconfirm", "ripgrep"])
        assert "ripgrep" in executor.describe(cmd)


class TestRejectedCommands:
    @pytest.mark.parametrize(
        "argv",
        [
            [],
            ["bash", "-c", "echo hi"],  # free-form shell: never
            ["sh", "-c", "pacman -Syu"],
            ["rm", "-rf", "/"],
            ["pacman", "-U", "/tmp/evil.pkg.tar.zst"],  # local package install not in grammar
            ["pacman", "-S", "ripgrep"],  # wrong arity (missing --noconfirm)
            ["pacman", "-S", "--noconfirm", "ripgrep", "fd"],  # extra args
            ["pacman", "-R", "--noconfirm", "ripgrep"],  # removal not in grammar
        ],
    )
    def test_shape_rejections(self, argv):
        with pytest.raises(executor.CommandRejected):
            executor.validate_command(argv)

    def test_lookalike_binary_path_rejected(self):
        with pytest.raises(executor.CommandRejected):
            executor.validate_command(["/tmp/pacman", "-Syu", "--noconfirm"])

    def test_shell_metacharacters_in_package_rejected(self):
        for pkg in ["rg; rm -rf ~", "rg$(id)", "rg name", "../etc", "-Syu"]:
            with pytest.raises(executor.CommandRejected):
                executor.validate_command(["pacman", "-S", "--noconfirm", pkg])

    def test_package_referencing_blocker_rejected(self):
        with pytest.raises(executor.CommandRejected, match="blocker"):
            executor.validate_command(["pacman", "-S", "--noconfirm", "hyprblocker"])

    def test_denylisted_argv_rejected_even_if_shaped_like_grammar(self):
        with pytest.raises(executor.CommandRejected, match="denylist"):
            executor.validate_command(["systemctl", "-Syu", "--noconfirm"])

    def test_touching_protected_paths_rejected(self):
        with pytest.raises(executor.CommandRejected):
            executor.validate_command(["cat", "/var/lib/hyprblocker/secure/lock.json"])


class TestGrammarIntegrity:
    def test_no_free_form_templates(self):
        for template in executor.GRAMMAR:
            first = template.argv[0]
            assert isinstance(first, str), "argv[0] must be a literal binary path"
            assert first.startswith("/"), "argv[0] must be absolute"
            assert "bash" not in first and first.rsplit("/", 1)[-1] != "sh"

    def test_grammar_summary_lists_all_templates(self):
        summary = executor.grammar_summary()
        assert len(summary) == len(executor.GRAMMAR)
        assert any("pacman-install" in line for line in summary)
