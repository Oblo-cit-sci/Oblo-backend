from typing import List, Optional, Union

from pydantic import BaseModel


class ValueTreeNode(BaseModel):
    name: str
    children: List["ValueTreeNode"] = []
    # parent: "ValueTreeNode" = None


ValueTreeNode.update_forward_refs()


class Item(BaseModel):
    name: str
    description: Optional[str]
    image: Optional[str]


class ValueTree(BaseModel):
    root: ValueTreeNode
    levels: Optional[Union[List[str], List[Item]]]


# class TagRule_from_tree(BaseModel):
# 	levels = List[Union[int, str]]
#
#
# class TagsRule(BaseModel):
# 	from_tree: Optional[TagRule_from_tree]
