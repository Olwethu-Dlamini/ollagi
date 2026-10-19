from ollagi import __version__
from ollagi.cli import main


def test_no_command_prints_help_and_succeeds(capsys):
    assert main([]) == 0
    assert "usage: ollagi" in capsys.readouterr().out


def test_version_flag_reports_the_package_version(capsys):
    try:
        main(["--version"])
    except SystemExit as exit_:
        # argparse exits after printing the version; exit code 0 means success.
        assert exit_.code == 0
    assert capsys.readouterr().out.strip() == f"ollagi {__version__}"
