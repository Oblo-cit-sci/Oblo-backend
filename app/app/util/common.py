from datetime import date
from re import match
from typing import Any, Callable, List, Union, Set
from uuid import uuid4

import Levenshtein
import base58


def replace_value(
    data: dict, loc: List[Union[str, int]], func: Callable[[Any], Any]
) -> bool:
    """
    replace a value in a dict by passing it through a callable.
    the location is a list of str (key) and int (index) items.
    """
    sel = data
    for l in loc[:-1]:
        try:
            sel = sel[l]
        except:
            print("replace_value failed at: %s for key/index: %s" % (sel, l))
            return False
    try:
        sel[loc[-1]] = func(sel[loc[-1]])
    except:
        print("replacing failed for %s" % sel.get(loc[-1]))
        return False
    return True


def guarantee_list(val: Any) -> List:
    """
    turn anything into a list, if its not yet
    """
    if isinstance(val, list):
        return val
    else:
        return [val]


def guarantee_set(val) -> Set:
    """
    turn anything into a set, if its not yet
    """
    if isinstance(val, set):
        return val
    elif isinstance(val, list):
        return set(val)
    else:
        return {val}


def uuid4_regex_match(word):
    return (
        match(
            "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", word
        )
        is not None
    )


def uuid4_as_base58():
    return base58.b58encode(str(uuid4()))


def jsonpath2index_string(jsonpath: str) -> str:
    """
    @todo check if that a duplicate
    @param jsonpath:
    @return:
    """
    return jsonpath.replace("][", ".").replace("'", "")[2:-1]


def find_best_levensthein_match(word: str, word_list: List[str]):
    best_dist = 100000
    best_index = -1

    for index, w in enumerate(word_list):
        dist = Levenshtein.distance(w, word)
        if dist < best_dist:
            best_dist = dist
            best_index = index
    return best_index


def iso_date_str(date_: date = None) -> str:
    if not date_:
        date_ = date.today()
    return date_.isoformat()
