from pathlib import Path


def test_milestone_three_stays_inside_approved_boundary(repository_root: Path):
    package_files = {
        path.relative_to(repository_root).as_posix()
        for path in (repository_root / "src").rglob("*.py")
    }

    assert any("catalyst" in path for path in package_files)
    assert any("clinical" in path for path in package_files)
    assert not any("scoring" in path for path in package_files)
    assert not any("valuation" in path for path in package_files)
    assert not any("financial" in path for path in package_files)
    assert not any("market_data" in path for path in package_files)
    assert not any("technical" in path for path in package_files)
    assert not any("ui" in path for path in package_files)
