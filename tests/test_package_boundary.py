from pathlib import Path


def test_milestone_four_stays_inside_approved_boundary(repository_root: Path):
    package_files = {
        path.relative_to(repository_root).as_posix()
        for path in (repository_root / "src").rglob("*.py")
    }

    assert any("catalyst" in path for path in package_files)
    assert any("clinical" in path for path in package_files)
    assert any("financial" in path for path in package_files)

    forbidden_components = {
        "market_data",
        "scoring",
        "technical",
        "ui",
        "valuation",
    }
    for package_file in package_files:
        components = set(Path(package_file).parts)
        stem = Path(package_file).stem
        assert not (forbidden_components & components)
        assert stem not in forbidden_components
