from pathlib import Path


def test_milestone_two_stays_inside_approved_boundary(repository_root: Path):
    package_files = {
        path.relative_to(repository_root).as_posix()
        for path in (repository_root / "src").rglob("*.py")
    }

    assert not any("scoring" in path for path in package_files)
    assert not any("valuation" in path for path in package_files)
    assert not any("catalyst" in path for path in package_files)
    assert not any("clinical" in path for path in package_files)
    assert not any("technical" in path for path in package_files)
