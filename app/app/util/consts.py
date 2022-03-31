# Entry status
from collections import namedtuple
from typing import Literal

# domain relevant
TITLE = "title"
INDEX = "index"
CONTENT = "content"  # also used in entry orm model to deffer some columns
DEFAULT_LANGUAGE = "default_language"
IS_ACTIVE = "is_active"

# entry relevant
UUID = "uuid"
DRAFT = "draft"
PUBLISHED = "published"
REJECTED = "rejected"
# SUBMITTED = "submitted"  # not visible to the user? this for entries that are submitted but not public?
REQUIRES_REVIEW = "requires_review"
# default state of entries that need review. if assigned to reviewer, the status changes to in_review
# IN_REVIEW = "in_review"

LDRAFT = Literal["draft"]
LPUBLISHED = Literal["published"]
LREQUIRES_REVIEW = Literal["requires_review"]
LREJECTED = Literal["rejected"]

ENTRY_STATUSES = [DRAFT, REQUIRES_REVIEW, PUBLISHED, REJECTED]
LIT_ENTRY_STATUSES = Literal["draft", "requires_review", "published", "rejected"]

PUBLISHED_OR_EDITOR = "publishes_or_editor"

# Entry privacy
PRIVATE = "private"
PUBLIC = "public"

# Actor global_role
GLOBAL_ROLE = "global_role"
ADMIN = "admin"
USER = "user"
EDITOR = "editor"
VISITOR = "visitor"

ALL_GLOBAL_ROLES = [ADMIN, USER, EDITOR]

GLOBAL_ROLE_LITERAL = (Literal["visitor", "user", "editor", "admin"])

# Entry roles
CREATOR = "creator"
OWNER = "owner"
COLLABORATOR = "collaborator"
READ_ACCESS = "reader"
REVIEWER = "reviewer"

# ENTRY_TYPES

SCHEMA = "schema"
TEMPLATE = "template"
REGULAR = "regular"
CODE = "code"
BASE_CODE = "base_code"
BASE_TEMPLATE = "base_template"

BASE_ENTRIES = [BASE_CODE, BASE_TEMPLATE]
BASE_ENTRIES_LITERAL = Literal["base_code", "base_template"]

BASE_SCHEMA_ENTRIES = [BASE_CODE, BASE_TEMPLATE, SCHEMA]
CONCRETE_ENTRIES = [CODE, TEMPLATE]
CONCRETE_ENTRIES_LITERAL = Literal["code", "template"]

ENTRY_TYPES_LITERAL = Literal[
    "schema", "base_code", "base_template", "code", "template", "regular"
]

# for easier domain filtering. also default if no domain is set
NO_DOMAIN = "no_domain"

# ENTRY FIELDS
VERSION = "version"
SLUG = "slug"
STATUS = "status"
ENTRY_REFS = "entry_refs"
PRIVACY = "privacy"
TEMPLATE_VERSION = "template_version"
LICENSE = "license"
IMAGE = "image"

# used in files to create EntryEntryAssociation e.g. template -> code
REFERENCES = "references"
ENTRY = "entry"
# EntriesSearch query parameters
META = "meta"
COLUMN = "column"
ACTOR = "actor"
BEFORE_TS = "before_ts"
DOMAIN = "domain"
TYPE = "type"
# TEMPLATE = "template"
LANGUAGE = "language"
# all possible columns
LOCATION = "location"
TEMPLATE_SLUG = "template_slug"
ASPECTS = "aspects"
VALUES = "values"
RULES = "rules"
ACTORS = "actors"
CONFIG = "config"
DESCRIPTION = "description"

# TITLE = "title"  # redefinition
TAGS = "tags"
TAG = "tag"

# ACTOR CONFIGS
EMAIL_VERIFICATION_CODE = "email_verification_code"
PASSWORD_RESET_CODE = "password_reset_code"
TO_DELETE_ENTRIES = "to_delete_entries"
TO_DELETE_REMOVE_ACTOR = "to_delete_remove_actor"
PROFILE_EDITED = "profile_edited"

EDITOR_CONFIG = "editor"

# main environment
DEV = "dev"
PROD = "prod"
TEST = "test"

ASPECT = "aspect"
# TYPE = "type"
NAME = "name"
COMPONENTS = "components"
ATTR = "attr"
ENTRYLIST = "entrylist"
ITEMS = "items"
VALUE = "value"
TEXT = "text"  # used in selects
LIST_ITEMS = "list_items"

ANY = "<any>"  # special type for schemas
STR = "str"
HEAD = "head"
INT = "int"
FLOAT = "float"
SELECT = "select"
MULTISELECT = "multiselect"
IMAGES = "images"
LIST = "list"
# ENTRYLIST = "entrylist"
DATE = "date"
TREE = "tree"
TREEMULTISELECT = "treemultiselect"
# LOCATION = "location"
COMPOSITE = "composite"
OPTIONS = "options"
ENTRYLINK = "entrylink"
ENTRY_ROLES = "entry_roles"
EXTERNAL_ACCOUNT = "external_account"
VIDEO = "video"
GEOMETRY = "geometry"
MONTH = "month"

aspect_types = {
    ANY,
    LOCATION,
    STR,
    TREE,
    MULTISELECT,
    TREEMULTISELECT,
    INT,
    FLOAT,
    SELECT,
    OPTIONS,
    DATE,
    LIST,
    COMPOSITE,
    IMAGES,
    ENTRYLINK,
    ENTRY_ROLES,
    EXTERNAL_ACCOUNT,
    VIDEO,
    GEOMETRY,
    MONTH
}

SELECT_TYPES = {
    SELECT, MULTISELECT, TREE, TREEMULTISELECT
}

TERMINAL_ASPECT_TYPES = [t for t in aspect_types if t not in [COMPOSITE, LIST]]

REGISTERED_NAME = "registered_name"
EMAIL = "email"

# reference types in orm..EntryEntryAssociation
# CODE = "code"


MESSAGE_TABLE_INDEX_COLUMN = "index_"

LANGUAGE_TABLE_COLUMNS = ["639-1", "name"]  # 639-2
LANGUAGE_TABLE_COLUMNS_ALL_CODES = ["639-1", "639-2/T", "639-2/B", "name"]  # 639-2

ROLE = "role"

# ENTRY CONFIG KEYS
ACCESS_KEY_HASH = "access_key_hash"
FROM_FILE = "from_file"

# 2 MAIN CODE-SCHEMAS
VALUE_LIST = "value_list"
VALUE_TREE = "value_tree"

# IMPORTANT ENTRY-RULES FIELDS:
CODE_SCHEMA = "code_schema"

# TEMPLATE RULES KEYS:
LOCATION_ASPECT = "locationAspect"
# ...
# todo rename to something like value_location_validation or something
# todo can in the end also be jsonschema
Location_validation = namedtuple(
    "Location_validation", ["path", "required"], defaults={"required": False}
)
