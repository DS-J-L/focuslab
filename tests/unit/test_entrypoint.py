"""Verify the initial entry point makes its limited scope explicit."""

from focuslab.__main__ import main


def test_entrypoint_reports_scaffold(capsys):
    main()
    output = capsys.readouterr().out
    assert "initial scaffold" in output
    assert "not implemented yet" in output
