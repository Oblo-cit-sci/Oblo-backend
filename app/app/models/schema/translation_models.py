from typing import List, Dict

from pydantic import BaseModel, validator, HttpUrl

from app.settings import L_MESSAGE_COMPONENT


class UserGuideMappingFormat(BaseModel):
    pages: Dict[str, HttpUrl]
    mapping: Dict[str, str]


### TODO NO IDEA HOW THESE ARE USED:::


class Message_Block(BaseModel):
    language: str
    value: str


class Translation_Block(BaseModel):
    path: str
    name: str
    source_messages: List[Message_Block]
    destination_message: Message_Block


class Translation_Languages(BaseModel):
    source_languages: List[str]
    destination_language: str


class Translation(BaseModel):
    languages: Translation_Languages
    messages: List[Translation_Block]

    @validator("messages", each_item=True)
    def validate_messages(cls, value, values):
        return Translation_Block.parse_obj(value)


def gen_for_languages(translation: Translation, messages: Translation_Block):
    return {"aspects": [{"name": 3}]}


Translation.parse_obj(
    {
        "languages": {"source_languages": ["en"], "destination_language": "es"},
        "messages": [
            {
                "path": "title",
                "name": "domain_title",
                "source_messages": [],
                "destination_message": {"language": "es", "value": ""},
            }
        ],
    }
)
e_g = {
    "components": [
        {"name": "path", "type": "str", "label": "path"},
        {"name": "name", "type": "str", "label": "Name"},
        {"name": "language", "type": "str", "label": "Sprache"},
        {"name": "value", "type": "str", "label": "Text"},
    ]
}


class ComponentMessageBlock(BaseModel):
    component: L_MESSAGE_COMPONENT
    messages: List["ContractedMessageBlock"]


class ContractedMessageBlock(BaseModel):
    index: str
    translations: Dict[str, str]


class LanguageStatus(BaseModel):
    lang_code: str
    active: bool
    fe_msg_count: int
    be_msg_count: int

    class Config:
        orm_mode = True


ComponentMessageBlock.update_forward_refs()
