import os
from os.path import join

from jsonschema import Draft7Validator, validators

from app.settings import SCHEMA_FOLDER
from app.util.files import read_orjson

domain_data_schema_file = "domain_schema.json"
user_settings_schema_file = "user_settings_schema.json"


def _extend_with_default(validator_class):
    validate_properties = validator_class.VALIDATORS["properties"]

    def set_defaults(validator, properties, instance, schema):
        for property, subschema in properties.items():
            if "default" in subschema:
                instance.setdefault(property, subschema["default"])

        for error in validate_properties(
            validator,
            properties,
            instance,
            schema,
        ):
            yield error

    return validators.extend(
        validator_class,
        {"properties": set_defaults},
    )


DefaultValidatingDraft7Validator = _extend_with_default(Draft7Validator)


def get_schema(filename: str):
    file_path = join(SCHEMA_FOLDER, filename)
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"schema file missing {filename} in {SCHEMA_FOLDER}")
    return read_orjson(file_path)


def validate(schema_filename: str, obj: dict):
    schema: dict = get_schema(schema_filename)
    return Draft7Validator(schema).validate(obj)


def default_validate(schema_filename: str, obj: dict):
    schema: dict = get_schema(schema_filename)
    return DefaultValidatingDraft7Validator(schema).validate(obj)


def get_schema_from_id(id):
    pass
