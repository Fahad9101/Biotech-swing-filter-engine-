from boe.cli import main


def test_cli_validates_scorecard_and_candidate(scorecard_path, candidate_path, capsys):
    result = main(["--scorecard", str(scorecard_path), "--candidate", str(candidate_path)])

    captured = capsys.readouterr().out
    assert result == 0
    assert "scorecard=BOE-1.0.0" in captured
    assert "candidate=TEST" in captured
    assert "classification=CATALYST_SWING" in captured
