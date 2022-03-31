import re
from logging import getLogger
from typing import List, Tuple

logger = getLogger(__name__)


def get_language_code_from_domain_path(file_path) -> str:
    """
    this works nice for me
    @param file_path:
    @return:
    """
    folder_names = file_path.split("/")
    return folder_names[folder_names.index("lang") + 1]


def table_col2dict(cols: List[Tuple[str, str]]) -> dict:
    """
    todo move to dict_rearrange
    turns messages with index_ into a dict, where index_ is dot separated to create the dict structure.
    the last location in the index, can be string (e.g. a.a) or an int (e.g. a.0)
    actually the numbers dont really matter. an int means, list all msges will be appended
    param cols: a list of list of 2 strings, 1. the index_ and 2nd the message (in a certain language)
    """
    result = {}
    for col in cols:  # index, msg
        # print("col", col)
        act = result
        split_loc: List[str] = col[0].split(".")
        last_index: int = len(split_loc) - 1
        act_is_list = False
        for index, loc in enumerate(split_loc):
            # print(index, loc, act, act_is_list)
            if index == last_index:
                if act_is_list:
                    act.append(col[1])
                else:
                    act[loc] = col[1]
            else:
                index_part = split_loc[index + 1]
                if re.match("\d*$", index_part):
                    act_index: int = int(index_part)
                    if act_is_list:
                        act.append(act := [])
                    else:
                        act = act.setdefault(loc, [])
                    act_is_list = True
                else:
                    if act_is_list:
                        # logger.warning(f"the problematic branch of table_col2dict has been entered, {act}, {act_index} {act_index >= len(act)}")
                        # todo this doesnt seem right. but it works at. not sure how if there would be 2 list after each other

                        if act_index >= len(act):
                            act.append(act := {})
                        else:
                            act = act[act_index]
                    else:
                        act = act.setdefault(loc, {})
                    act_is_list = False
    return result


# TODO try to rewrite...
# def table_col2dict(rows: List[Tuple[str, str]]) -> Union[dict, List[dict]]:
#     """
#     todo move to dict_rearrange
#     turns messages with index_ into a dict, where index_ is dot separated to create the dict structure.
#     the last location in the index, can be string (e.g. a.a) or an int (e.g. a.0)
#     actually the numbers dont really matter. an int means, list all msges will be appended
#     param cols: a list of list of 2 strings, 1. the index_ and 2nd the message (in a certain language)
#     """
#     if not rows:
#         return {}
#     # todo this needs refactoring, to work with more cols
#     one_result = True #len(rows[0]) == 2
#     result: Union[dict, List[dict]] = {} if one_result else [{} for _ in range(len(rows[0]) - 1)]
#
#     def add_to_act(value, part: Union[str, int], col_index: int):
#         if one_result:
#
#             if act_is_list:
#                 act.append(value)
#             else:
#                 act[part] = value
#         return value
#
#     for row in rows:  # index, msg
#         # print("col", col)
#         act = result
#         # split assumed index_ into parts
#         parts: List[str] = row[0].split(".")
#         last_index: int = len(parts) - 1
#         act_is_list = False
#         act_index = 0
#
#         for part_index, part in enumerate(parts):
#             # print(index, loc, act, act_is_list)
#             # on the last index
#             if part_index == last_index:
#                 add_to_act(row[1], part)
#                 break  # out. no need for else
#
#             # check if the part ahead is an int
#             next_part = parts[part_index + 1]
#             if re.match("\d*$", next_part):
#                 # whats the index we are selecting? same index ->
#                 act_index: int = int(next_part)
#                 act = add_to_act([], part)
#                 act_is_list = True
#             else:
#                 if act_is_list:
#                     # logger.warning(f"the problematic branch of table_col2dict has been entered, {act}, {act_index} {act_index >= len(act)}")
#                     # todo this doesnt seem right. but it works atm. not sure how if there would be 2 list after each other
#                     if act_index >= len(act):
#                         act.append(act := {})
#                     else: # just go into it, since its already there
#                         act = act[act_index]
#                 else:
#                     act = act.setdefault(part, {})
#                 act_is_list = False
#     return result
