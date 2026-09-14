import json

from jsonschema import Draft202012Validator


def test_candidate_schema_is_valid(repository_root):
    schema = json.loads(
        (repository_root / "contracts" / "candidate-output.schema.json").read_text()
    )
    Draft202012Validator.check_schema(schema)


def test_offline_fixture_matches_json_schema(repository_root, candidate_path):
    schema = json.loads(
        (repository_root / "contracts" / "candidate-output.schema.json").read_text()
    )
    payload = json.loads(candidate_path.read_text())

    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(
        payload
    )
