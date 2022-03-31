from typing import Optional

from pydantic import BaseModel

from app.models.schema import EntryRef, TagData


# probably not used...
class TagDB(TagData):
    parent: Optional["TagDB"] = None  # try if it works, otherwise, Any
    source_entry: Optional[EntryRef]
    # actors_interested: Optional[List[ActorBase]]

    class Config:
        orm_mode = True


class TagOut(BaseModel):
    value: str
    text: str
    description: Optional[str]


TagDB.update_forward_refs()
