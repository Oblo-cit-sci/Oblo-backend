import itertools
from logging import getLogger
from typing import Any, Dict, Union, List, Tuple, Sequence, Callable, Set, Iterator

from deepdiff import deephash, DeepDiff
from deepmerge import Merger, STRATEGY_END
from deepmerge.exception import InvalidMerge
from pydantic import BaseModel
from pymemcache.client.murmur3 import murmur3_32

from app.util.consts import TEXT, MESSAGE_TABLE_INDEX_COLUMN, NAME

logger = getLogger(__name__)


def pull_dict_up(data: Dict, key_to_pull: str) -> Dict:
    """
    e.g.
    {a: {x: 1, y:2}, b: 4}
    key_to_pull: a
    -> {x: 1, y:2, b: 4}
    @param data:
    @param key_to_pull:
    @return:
    """
    for (k, v) in data.get(key_to_pull, {}).items():
        data[k] = v
    del data[key_to_pull]
    return data


def pull_up(
        data: Dict, dict_top_key: str, key_to_pull: str, new_key_name: str = None
) -> Dict:
    if new_key_name:
        data[new_key_name] = data[dict_top_key][key_to_pull]
    else:
        data[key_to_pull] = data[dict_top_key][key_to_pull]
    return data


def delete_none(data: Dict) -> Dict:
    to_del = []
    for (k, v) in data.items():
        if v is None:
            to_del.append(k)
        if type(v) == dict:
            delete_none(v)
        elif type(v) == list:
            for i in v:
                if type(i) == dict:
                    delete_none(i)
    for k in to_del:
        del data[k]
    return data


def move_keys_into(data: Dict, keys: List[str], into: str):
    if into not in data:
        data[into] = {}
    for k in keys:
        if k in data:
            data[into][k] = data[k]
            del data[k]


def delete_keys(data: Dict, keys) -> Dict:
    for k in keys:
        del data[k]
    return data


def match_values(
        input1: Union[str, Dict, Any], input2: Union[str, Dict, Any], key: str = None
):
    """
    @deprecated
    NOT USED
    @param input1:
    @param input2:
    @param key:
    @return:
    """
    if input1 == None or input2 == None:
        return False

    t1 = type(input1)
    t2 = type(input2)

    v1 = input1
    v2 = input2
    if t1 == t2 and t1 == str:
        return v1 == v2
    elif not key:
        raise ValueError("key missing")
    for (t, v) in zip([t1, t2], [v1, v2]):
        if t == dict:
            v = v[key]
        else:
            v = getattr(v, key, None)
    return v1 == v2


def update_strict(origin: dict, d2: dict):
    """
    like normal update, but only inserts keys that exist in the original dict
    """
    origin.update(**{k: d2[k] for k in d2 if k in origin})


def obj_hash(data: Union[Dict, List, Tuple]) -> bytes:
    # todo could maybe also be *args
    # print(bytes(deephash.DeepHash(data, hasher=murmur3_32)[data]))
    # print(str(deephash.DeepHash(data, hasher=murmur3_32)[data]).encode("utf-8"))
    return str(deephash.DeepHash(data, hasher=murmur3_32)[data]).encode("utf-8")


def _list_item_merge_strategy(config: Merger, path, base: list, nxt: list):
    for i, (b, n) in enumerate(itertools.zip_longest(base, nxt)):
        if b is None:
            if len(base) < i + 1:
                base.append(n)
            else:
                base[i] = n
        elif n is None:
            continue
        else:
            config.merge(b, n)
    return base


def _strict_list_item_merge_strategy(config: Merger, path, base: list, nxt: list):
    if len(base) != len(nxt):
        logger.error(
            f"Merging failed cuz of unequal length of lists. base: {len(base)}, next: {len(nxt)}"
        )
        return STRATEGY_END
    return _list_item_merge_strategy(config, path, base, nxt)


def fallback(config: Merger, path, base, nxt):
    if base is not None and nxt is None:
        return base
    if base is None and nxt is not None:
        return nxt
    return STRATEGY_END


def deep_merge(base: Dict, update: Dict, strict: bool = False):
    """
    makes a deepmerge through dict, list.
    dicts are deep-merged.
    lists are merged per item
    destructive
    @param base:
    @param update:
    @param strict: list must have same length
    @return:
    """
    base_merger = Merger(
        [
            (
                list,
                _strict_list_item_merge_strategy
                if strict
                else _list_item_merge_strategy,
            ),
            (dict, "merge"),
        ],
        ["override"],
        [fallback],
    )
    return base_merger.merge(base, update)


def merge_aspects_one_by_one(base: Dict, update: Dict, strict: bool = False):
    base_aspects = base.get("aspects", [])
    update_aspects = update.get("aspects", [])
    base_merger = Merger(
        [
            (
                list,
                _strict_list_item_merge_strategy
                if strict
                else _list_item_merge_strategy,
            ),
            (dict, "merge"),
        ],
        ["override"],
        [fallback],
    )
    result = []
    for index,base_aspect in enumerate(base_aspects):
        try:
            result.append(base_merger.merge(base_aspect, update_aspects[index]))
        except InvalidMerge:
            logger.error(f"Failed to merge aspect {base_aspect[NAME]}:{index}")
            result.append(None)
    return result

def flatten_sequence(seq: Sequence) -> List:
    if type(seq) in {set}:
        seq = list(seq)
    if len(seq) == 0:
        return seq
    if type(seq[0]) in {set, list}:
        return flatten_sequence(seq[0]) + flatten_sequence(seq[1:])
    return seq[:1] + flatten_sequence(seq[1:])


def extract_diff(a, b):
    """
    removes all key,value pairs in a, that are also in b
    e.g.
    extract_diff(
    {"value":"a", "text": "A", "more": {"value":"a", "text": "A"}},
    {"value": "a", "map": {}, "more": {"value": "a"}})
    => {'text': 'A', 'more': {'text': 'A'}}
    @param a:
    @param b:
    @return:
    """
    res = {}
    if type(a) == type(b) and type(a) not in [list, dict]:
        return None
    if isinstance(a, list):
        assert len(a) == len(b)
        res = []
        for index, _ in enumerate(a):
            t = extract_diff(a[index], b[index])
            if t:
                res.append(t)
        return res

    for k, av in a.items():
        if b == None or k not in b:
            res[k] = av
            continue
        bv = b.get(k)
        if isinstance(av, dict):
            t = extract_diff(av, bv)
            if t:
                res[k] = t
        elif isinstance(av, list):
            assert len(av) == len(bv)
            res[k] = []
            for index, _ in enumerate(av):
                t = extract_diff(av[index], bv[index])
                if t:
                    res[k].append(t)
    return res


def dict2row_iter(lang_data):
    def rec_key(data, parent: str = ""):
        if type(data) == dict:
            go_into = {}
            for k, v in data.items():
                if type(v) not in [dict, list]:
                    yield parent + k, v
                else:
                    go_into[k] = v
            for k, v in go_into.items():
                for res in rec_key(v, parent + k + "."):
                    yield res
        else:
            for k, v in enumerate(data):
                if type(v) not in [dict, list]:
                    yield parent + str(k), v
                else:
                    for res in rec_key(v, parent + str(k) + "."):
                        yield res

    return rec_key(lang_data)


def dict2index_dict(dict_data: dict):
    """
    recursively runs through a dict and turn it into a flat dict,
    where they keys are the indices and values are ... the values under the given index-path
    @return:
    """
    result = {}

    def a_rec_key(data, parent: str = ""):
        if type(data) == dict:
            go_into = {}
            for k, v in data.items():
                if type(v) not in [dict, list]:
                    result[parent + k] = v
                else:
                    go_into[k] = v
            for k, v in go_into.items():
                a_rec_key(v, parent + k + ".")
                # for res in :
                #     result[res[0]] = res[1]
        else:
            for k, v in enumerate(data):
                if type(v) not in [dict, list]:
                    result[parent + str(k)] = v
                    # result[parent + str(k)] = v
                else:
                    a_rec_key(v, parent + str(k) + ".")
                    # for res in :
                    #     # yield res
                    #     result[res[0]] = res[1]

    a_rec_key(dict_data)
    return result

    # def validate_no_empty_text(data: dict) -> List[str]:
    #     def extend_path(parent: str, sub: str):
    #         return f"{parent}.{sub}" if parent else sub
    #
    #     def rec_validate(s_data: dict, parent_path: str = "") -> List[str]:
    #         missing_texts = []
    #         if type(s_data) not in [list, dict]:
    #             return []
    #         for k, v in s_data.items():
    #             if k == TEXT and v == "":
    #                 missing_texts.append(extend_path(parent_path, k))
    #             if isinstance(v, list):
    #                 for index, item in enumerate(v):
    #                     missing_texts.extend(rec_validate(item, extend_path(parent_path, str(index))))
    #             elif isinstance(v, dict):
    #                 missing_texts.extend(rec_validate(v, extend_path(parent_path, k)))
    #         return missing_texts

    # return rec_validate(data)


def dict_process_proc_results(data: dict, prc: Callable):
    """
    Recursively go through the dict (into dicts and lists) and call prc on all other values
    @param data: data to go through
    @param prc:
    @return:
    """

    def rec_key(part, parent: str = ""):
        if type(part) == dict:
            go_into = {}
            for k, v in part.items():
                if type(v) not in [dict, list]:
                    yield parent + k, prc(k, v)
                else:
                    go_into[k] = v
            for k, v in go_into.items():
                for res in rec_key(v, parent + k + "."):
                    yield res
        else:
            for index, v in enumerate(part):
                if type(v) not in [dict, list]:
                    yield parent + str(index), prc(index, v)
                else:
                    for res in rec_key(v, parent + str(index) + "."):
                        yield res

    return rec_key(data)


def validate_complete_texts(
        data: dict, text_keys: List[str] = (TEXT,)
):  # could also include "label", "description"
    def check_text(key, value):
        if key in text_keys and value == "":
            return "missing"
        else:
            return None

    return [
        k_v[0]
        for k_v in filter(
            lambda k_v: k_v[1], dict_process_proc_results(data, check_text)
        )
    ]


def check_model_active(
        model_to_check_against: BaseModel,
        model_to_check: BaseModel,
        keys: Set[str],
        identity: str,
        check_all: bool = False,
        throw_warning: bool = False,
) -> Union[bool, List[str]]:
    """

    @param model_to_check_against: model in the defined default language
    @param model_to_check: model in another language
    @param keys:
    @param check_all:
    @param throw_warning:
    @return: bool, when check_all is false, we just return a bool. otherwise a list of all missing ones
    """
    to_check_against = model_to_check_against.dict(include=keys, exclude_none=True)
    to_check = model_to_check.dict(include=keys, exclude_none=True)
    diff = DeepDiff(to_check_against, to_check)

    if removed := diff.tree.get("dictionary_item_removed"):
        if throw_warning:
            logger.warning(f"value missing in {identity}")
            logger.warning(f"{removed}")
            return False

    all_text_present = True
    missing: List[str] = []
    if changes := diff.tree.get("values_changed"):
        for change in changes.items:
            if change.t1 != "" and change.t2 == "":
                all_text_present = False
                missing.append(change.t2)
                change_repr = repr(change.up).replace("'", "")
                change_repr = change_repr[5: (change_repr.index(" t1"))]
                if throw_warning:
                    logger.warning(
                        f"missing text  at {change_repr} for {identity}. Original says: {change.t1}"
                    )
                else:
                    logger.info(f"missing text  at {change_repr} for {identity}")
                if not check_all:
                    break

    if not check_all:
        return all_text_present
    else:
        return missing


def merge_row_iters(languages: List[str], row_iters: Iterator[List]):
    rows = []
    done = False
    last_language = languages[-1]
    while True:
        act_row = {}
        act_index = None
        for language, row_iter in zip(languages, row_iters):
            try:
                current = next(row_iter)
                # print(current)
                if not act_index:
                    act_index = current[0]
                    act_row[act_index] = {}
                    # print(act_index)
                else:
                    if current[0] != act_index:
                        logger.warning(
                            f"unequal index: {act_index} / {current[0]} for lang: {language}"
                        )
                        act_row[act_index][language] = None
                        # print(f"{current[0]} / {act_index} ... next")
                        continue
                        # raise ValueError(f"unequal index: {act_index} / {current[0]}")
                act_row[act_index][language] = current[1]
            except StopIteration:
                # print("stopp")
                # logger.warning("stopping")
                done = True
                break
        if any((act_row[act_index][lang] for lang in languages)):
            rows.append(act_row)
        if done:
            break
    # print("done")
    return rows


def merge_flat_dicts(
        languages: List[str], flat_dicts: List[dict]
) -> Dict[str, Dict[str, Any]]:
    """
    creates a dict of keys:index -> (key:languages -> value: text)
    when merging with merge and base
    :param languages:
    :param flat_dicts:
    """
    result = {}
    for index, value in flat_dicts[0].items():
        result[index] = {languages[0]: value}
        for lang, dict in zip(languages[1:], flat_dicts[1:]):
            result[index][lang] = dict.get(index)
    return result


def flat_dicts2dict_rows(flat_dict: dict) -> List[Dict[str, str]]:
    result = []
    for index, data in flat_dict.items():
        res = {**data, **{MESSAGE_TABLE_INDEX_COLUMN: index}}
        result.append(res)
    return result


def table2dict(columns: List[str], table_data: List[List[str]]):
    result = {}
    for row in table_data:
        index = row[0]
        result[index] = {col: row[i] for i, col in enumerate(columns)}
    return result
