from dataclasses import dataclass, field
from logging import DEBUG, getLogger
from typing import Dict, List, Optional, Union

from app.util.consts import VALUE, TEXT

logger = getLogger(__name__)
logger.setLevel(DEBUG)


@dataclass
class Tree:
    levels: List[str]
    root: Optional["TreeNode"] = None
    description: Optional[str] = None

    @staticmethod
    def from_dict(data: Dict):
        assert "root" in data
        assert "levels" in data

        tree = Tree(levels=data["levels"], root=data["root"])
        if "description" in data:
            tree.description = data["description"]

        tree.root = TreeNode.from_dict(data["root"], tree, None)
        return tree

    def pretty_print(self):
        def rec_pretty_print(node):
            print("- " * node.get_level(), node.value)
            for kid in node.children:
                rec_pretty_print(kid)

        rec_pretty_print(self.root)

    def tree_find_duplicate(
        self, on_levels: Optional[List[Union[int, str]]] = None
    ) -> Dict[str, List["TreeNode"]]:

        value_dict: Dict = {}

        new_on_level: List[int] = []
        for lvl in on_levels:
            if type(lvl) == int:
                new_on_level.append(lvl)
            else:
                if lvl in self.levels:
                    new_on_level.append(self.levels.index(lvl) + 1)
                else:
                    logger.warning(
                        "trying to get duplicates on level that is not in the tree"
                    )

        on_levels = new_on_level
        # print("on levels:", on_levels)
        logger.info("on levels: %s", on_levels)

        def rec_find_duplicates(node: TreeNode):
            # print(node.value, node.get_level())
            logger.debug(node.value, node.get_level())
            if not on_levels or node.get_level() in on_levels:
                # print(node.value, "?")
                nodes: List[TreeNode] = value_dict.setdefault(node.value, [])
                nodes.append(node)
            # print(value_dict[node.value])
            for k in node.children:
                rec_find_duplicates(k)

        rec_find_duplicates(self.root)
        return {k: v for (k, v) in value_dict.items()}

    def dumps(self):
        data = {
            "levels": self.levels,
            "root": self.root.dumps(),
        }
        # todo, kick out? I dont think this is filled by anything
        if self.description:
            data["description"] = self.description
        return data


@dataclass
class TreeNode:
    tree: Optional[Tree]
    parent: Optional["TreeNode"] = None
    value: Optional[str] = None
    text: Optional[str] = None
    children: List["TreeNode"] = field(default_factory=list)
    tag: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    extra: Optional[Dict] = None

    @staticmethod
    def from_dict(
        data: Dict, tree: Optional[Tree], parent: Optional["TreeNode"]
    ) -> "TreeNode":
        node = TreeNode(tree=tree, parent=parent)
        if value := data.get(VALUE):
            node.value = value
        if text := data.get(TEXT):
            node.text = text
        node.tree = tree
        if parent:
            node.parent = parent

        for kid in data.get("children", []):
            node.children.append(TreeNode.from_dict(kid, tree, node))

        # print(data.get("code"))
        for d in ["tag", "description", "code", "icon", "extra"]:
            if d in data:
                setattr(node, d, data[d])

        return node

    def get_level(self) -> int:
        def rec_parent_lvl(node: TreeNode, level: int = 0):
            if node.parent:
                return rec_parent_lvl(node.parent, level + 1)
            else:
                return level

        return rec_parent_lvl(self)

    def get_level_value(self) -> str:
        return self.tree.levels[self.get_level()]

    def get_branch(
        self, include_root: bool = False, include_self=True
    ) -> List["TreeNode"]:
        def rec_parent(node: TreeNode):

            if node.parent:
                if include_self and node is self or node is not self:
                    return rec_parent(node.parent) + [node]
                else:
                    return rec_parent(node.parent) + []
            else:
                if include_root:
                    return [node]
                else:
                    return []

        return rec_parent(self)

    def __repr__(self):
        return f"{self.value}, {self.tag} , {len(self.children)}"

    def dumps(self):
        data = {}
        for d in ["value", "text", "tag", "code", "description", "icon", "extra"]:
            if getattr(self, d):
                data[d] = getattr(self, d)

        if self.children:
            data["children"] = list(k.dumps() for k in self.children)

        return data
