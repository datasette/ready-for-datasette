import pytest

import skipped_plugins


def test_load_skipped_plugins_normalizes_names_and_ignores_comments(tmp_path):
    skip_file = tmp_path / "skip-these.txt"
    skip_file.write_text(
        """
        # Temporarily excluded packages
        Datasette.Example
        datasette_example  # duplicate

        datasette-other
        """
    )

    assert skipped_plugins.load_skipped_plugins(skip_file) == frozenset(
        {"datasette-example", "datasette-other"}
    )


def test_load_skipped_plugins_reports_the_line_with_an_invalid_name(tmp_path):
    skip_file = tmp_path / "skip-these.txt"
    skip_file.write_text("datasette-example\nnot/a-package\n")

    with pytest.raises(ValueError, match=r"line 2: 'not/a-package'"):
        skipped_plugins.load_skipped_plugins(skip_file)


def test_without_skipped_records_filters_every_matching_repository_record():
    records = [
        {"name": "Datasette.Example", "github_repo": "one/datasette-example"},
        {"name": "datasette_example", "github_repo": "two/datasette-example"},
        {"name": "datasette-other", "github_repo": "one/datasette-other"},
    ]

    assert skipped_plugins.without_skipped_records(
        records,
        frozenset({"datasette-example"}),
    ) == [records[2]]
