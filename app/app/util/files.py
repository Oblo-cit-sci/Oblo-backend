import _csv
import csv
import json
import os
import pathlib
import re
import shutil
import zipfile
from csv import DictReader
from datetime import datetime
from glob import glob
from logging import getLogger
from os import makedirs, path
from os.path import basename, isabs, isdir, isfile, join, splitext
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Dict, List, Type, Union, IO, Sequence, Tuple

import aiofiles
from aiofiles.os import remove as async_remove

import chardet
import orjson
from deepdiff import DeepDiff
from deprecated.classic import deprecated
from frictionless import Resource
from pydantic import BaseModel, ValidationError

from app import settings
from app.settings import BASE_DATA_FOLDER, TEMP_APP_FILES
from app.util.common import iso_date_str

logger = getLogger()


def orjson_dumps(v, *, default):
    # orjson.dumps returns bytes, to match standard json.dumps we need to decode
    return orjson.dumps(v, default=default).decode()


def get_abs_path(rel_filepath: str):
    return (
        rel_filepath
        if isabs(rel_filepath)
        else get_abs_path(join(settings.BASE_DATA_FOLDER, rel_filepath))
    )


class JSONPath(pathlib.PosixPath):
    def __init__(self, *args, raise_error: bool = True):
        """
        checks if the file exists and if it ends with .json, else FileNotFoundError, ValueError
        file exists check can
        @param args:
        """
        super().__init__()
        # todo could also have a flag if no error. which makes it safer to use (prevent overwrite)

        if not isfile(self.as_posix()) and raise_error:
            raise FileNotFoundError(
                f"Missing file: {self.relative_to(BASE_DATA_FOLDER)}"
            )
        if self.suffix != ".json":
            raise ValueError(self.as_posix())

    # noinspection PyDefaultArgument
    def read(self, setdefault: dict = {}) -> dict:
        try:
            data = read_orjson(self.as_posix())
        except orjson.JSONDecodeError as err:
            logger.error(f"Cannot read file, decoder error: {self.as_posix()}")
            raise err
        for k, v in setdefault.items():
            data.setdefault(k, v)

        return data

    # def read(self) -> dict:
    #     try:
    #         data = read_orjson(self.as_posix())
    #     except orjson.JSONDecodeError as err:
    #         logger.error(f"Cannot read file, decoder error: {self.as_posix()}")
    #         raise err
    #     return data

    # noinspection PyDefaultArgument
    def read_insert(self, insert: dict = {}, setdefault: dict = {}) -> dict:
        """
        @param insert:
        @param setdefault:
        @return:
        """
        data = self.read()
        for k, v in insert.items():
            if (e := data.get(k)) and e != v:
                logger.warning(
                    f"file {self.as_posix()} gets value overwritten: {e} => {v}"
                )
            data[k] = v
        for k, v in setdefault.items():
            data.setdefault(k, v)

        return data

    # noinspection PyDefaultArgument
    def read_validate(
            self, model: Type[BaseModel], insert: dict = {}
    ) -> Union[BaseModel, Exception]:
        """
        @param model: which model
        @param insert: inserted after reading json from file
        @return: Pydantic basemodel
        """
        try:
            data = self.read_insert(insert)
            return model(**data)
        except orjson.JSONDecodeError as err:
            logger.error(err)
            raise err
        except ValidationError as err:
            logger.error(err)
            return err

    def write(self, data: Union[dict, list], pretty: bool = False) -> None:
        """
        write some data to the file
        @param data: data
        @param pretty: indent file
        """
        if not pretty:
            write_orjson(data, self.as_posix())
        else:
            write_json(data, self.as_posix(), True)


class CSVPath(pathlib.PosixPath):
    def __init__(self, *args, **kwargs):
        """
        checks if the file exists and if it ends with .json, else FileNotFoundError, ValueError
        file exists check can
        @param args:
        @param kwargs:
        """
        super().__init__()
        # todo could also have a flag if no error. which makes it safer to use (prevent overwrite)
        if not isfile(self.as_posix()) and kwargs.get("raise_error", True):
            raise FileNotFoundError(self.as_posix())
        if self.suffix != ".csv":
            raise ValueError(self.as_posix())

    def read(self, as_dict: bool = False, to_list: bool = False) -> Union[DictReader, _csv.reader, list]:
        fin = open(self.as_posix(), encoding="utf-8")
        dialect = csv.Sniffer().sniff(fin.read(1024))
        fin.seek(0)
        if as_dict:
            reader = csv.DictReader(fin, dialect=dialect)
        else:
            reader = csv.reader(fin, dialect)
        if to_list:
            return list(reader)
        else:
            return reader

    def write(self, data: List[Dict], fieldnames) -> None:
        with open(self.as_posix(), "w", encoding="utf-8") as fout:
            writer = csv.DictWriter(fout, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)


def glob_json(path_: str, filter_underscore: bool = False):
    files = glob(Path(path_).as_posix() + "/*.json")
    return list(
        filter(lambda f: basename(f)[0] != "_", files) if filter_underscore else files
    )


def open_file(
        rel_filepath: str, binary: bool = False, encoding="utf-8", with_extension=False
):
    abs_path = get_abs_path(rel_filepath)

    if not isfile(abs_path):
        logger.warning(f"WARNING, FILE {abs_path} does not exist")
        return None
    fn, ext = splitext(abs_path)
    if with_extension:
        return open(abs_path, "r" if not binary else "rb", encoding=encoding), ext
    else:
        return open(abs_path, "r" if not binary else "rb", encoding=encoding)


def read_json(rel_filepath: str) -> dict:
    return json.load(open_file(rel_filepath))


def read_orjson(rel_filepath: str) -> dict:
    of = open(get_abs_path(rel_filepath), encoding="utf-8")
    return orjson.loads(of.read())


def write_text(string, rel_filepath):
    abs_path = get_abs_path(rel_filepath)
    open(abs_path, "w", encoding="utf-8").write(string)


def read_all_orjson(paths: List[str]) -> List[Dict]:
    return [read_orjson(path) for path in paths]


# todo also allow versioning,
# make auto-versioning wrapper
# which check for changes
# and has format var, default: <index>_<date>_<name>
def write_json(data: Dict, rel_filepath: str, indent: bool = None):
    json.dump(
        data,
        open(get_abs_path(rel_filepath), "w", encoding="utf-8"),
        indent=2 if indent else 0,
        ensure_ascii=False,
    )


def write_orjson(data, rel_filepath, indent: int = 0):
    abs_path = get_abs_path(rel_filepath)
    os.makedirs(Path(abs_path).parent.as_posix(), exist_ok=True)
    fout = open(abs_path, "w", encoding="utf-8")
    if not indent:
        fout.write(orjson.dumps(data).decode("utf-8"))
    else:
        fout.write(json.dumps(data, indent=2, ensure_ascii=False))
    fout.close()


def create_version_path(
        id: str, rel_filepath: str, version: int = 0, format: str = "json"
):
    return (
            rel_filepath
            + "/"
            + iso_date_str()
            + "_"
            + str(version)
            + "_"
            + id
            + "."
            + format
    )


def get_latest_path(id: str, rel_filepath: str, format: str = "json"):
    return rel_filepath + "/_latest_" + id + "." + format


def get_latest(id: str, rel_filepath: str, format: str = "json") -> str:
    return glob(get_latest_path(id, rel_filepath, format))


def get_latest_version_number(id: str, rel_filepath: str, format: str = "json"):
    all_files = glob(rel_filepath + "/*_*_" + id + "." + format)
    all_files = filter(lambda f: basename(f).split("_")[1] != "latest", all_files)
    if not all_files:
        return 0
    return max(int(basename(f).split("_")[1]) for f in all_files)


def write_versioned_json(
        data: dict,
        id: str,
        rel_filepath: str,
        indent: int = None,
        exclude_paths: set = None,
        log_diff: bool = False,
):
    latest_path = get_latest_path(id, rel_filepath)

    write_latest = False
    data_diff = None

    if isfile(latest_path):
        last_version_data = read_json(latest_path)
        next_version = 1 + get_latest_version_number(id, rel_filepath)
        data_diff = DeepDiff(data, last_version_data, exclude_paths)
        if data_diff:
            write_latest = True
        print("has latest")
    else:
        print("has no latest")
        next_version = 0
        write_latest = True

    if write_latest:
        print("writing latest")
        write_json(data, latest_path, indent)
        next_version_path = create_version_path(id, rel_filepath, next_version)
        shutil.copy(latest_path, next_version_path)
        if data_diff:
            print("writing diff")
            next_version_diff_path = create_version_path(
                id, rel_filepath, next_version, "diff.json"
            )
            write_json(data_diff, next_version_diff_path, indent)


def guarantee_path(path, get_abs):
    abs_path = get_abs_path(path)
    if not isdir(abs_path):
        makedirs(abs_path)
    return abs_path if get_abs else path


def simple_timestring(dt: datetime):
    return (dt if dt else datetime.now()).strftime("%Y_%m_%d-%H_%M_%S")


#  not used atm but maybe later...
_filename_ascii_strip_re = re.compile(r"[^A-Za-z0-9_.-]")


def secure_filename(filename):
    """Pass it a filename and it will return a secure version of it
    from https://github.com/pallets/werkzeug/blob/master/src/werkzeug/utils.py
    :param filename: the filename to secure
    """
    if isinstance(filename, str):
        from unicodedata import normalize

        filename = normalize("NFKD", filename).encode("ascii", "ignore")

    for sep in path.sep, path.altsep:
        if sep:
            filename = filename.replace(sep, " ")
    filename = str(_filename_ascii_strip_re.sub("", "_".join(filename.split()))).strip(
        "._"
    )

    return filename


# noinspection PyDefaultArgument
# def read_validate(file_path: str, model: Type[BaseModel], insert: dict = {}) -> Union[
#     BaseModel, Union[orjson.JSONDecodeError, ValidationError]]:
#     """
#     @param file_path: json file
#     @param model: which model
#     @param insert: inserted after reading json from file
#     @return: Pydantic basemodel
#     """
#     try:
#         data = read_orjson(file_path)
#     except orjson.JSONDecodeError as err:
#         logger.error(err)
#         return err
#     for k, v in insert.items():
#         if (e := data.get(k)) and e != v:
#             logger.warning(f"init-file {file_path} gets value overwritten: {e} => {v}")
#         data[k] = v
#     try:
#         return data, model(**data)
#     except ValidationError as err:
#         logger.error(err)
#         return err


def dict_reader_guess_delimiter(file):
    if not isfile(file):
        print("invalid path", file)
        return None
    for delim in [",", ";"]:
        reader = DictReader(
            open(file, encoding="utf-8"), delimiter=delim, quotechar='"'
        )
        if len(reader.fieldnames) > 1:
            return reader


@deprecated(reason="Use util.files.frictionless_extract")
async def transform_spooledfile2csv(file: IO) -> List[Sequence[str]]:
    init_text = file.read()
    encoding = chardet.detect(init_text)
    dialect = csv.Sniffer().sniff(init_text.decode(encoding["encoding"]))
    # logger.warning(encoding)
    # logger.warning(dialect.__dict__)
    file.seek(0)
    # write it to a temporary file
    lines = [l for l in file.readlines()]
    try:
        temp = NamedTemporaryFile("wb", -1, delete=False)
        temp.writelines(lines)
        temp.close()
        # reopen file, (now with the dialect it should be clean)
        # clean header & empty cells
        lines = list(csv.reader(open(temp.name, encoding="utf-8"), dialect=dialect))
    # delete
    except Exception:
        lines = []
    finally:
        await aiofiles.os.remove(temp.name)
    return lines


async def frictionless_extract(file: IO):
    new_name = None
    try:
        temp = NamedTemporaryFile("wb", -1, delete=False)
        temp.write(file.read())
        temp.close()
        new_name = temp.name + ".csv"
        shutil.move(temp.name, new_name)
        resource = Resource(new_name)
        data = resource.read_lists()
    except Exception:
        data = []
    finally:
        if new_name:
            await async_remove(new_name)
    return data


async def create_temp_csv(columns, rows) -> NamedTemporaryFile:
    temp = NamedTemporaryFile("w", -1, encoding="utf-8", delete=False)
    csv_writer = csv.DictWriter(
        temp, delimiter=",", quoting=csv.QUOTE_MINIMAL, fieldnames=columns
    )
    csv_writer.writeheader()
    # slow! but would be more secure...
    # for row in rows:
    #     filtered_columns = {col: value for col in filter(lambda col: col in columns, row.keys())}
    #     csv_writer.writerow(filtered_columns)
    csv_writer.writerows(rows)
    return temp


async def zip_files(
        filename: str, files: List[Tuple[NamedTemporaryFile, str]]
) -> zipfile.ZipFile:
    zip_file = zipfile.ZipFile(
        join(TEMP_APP_FILES, filename), "w", zipfile.ZIP_DEFLATED
    )
    for file, filename in files:
        file.close()
        zip_file.write(file.name, filename)

    zip_file.close()
    return zip_file


def remove_last_empty_column(data: List[List[str]]) -> List[List[str]]:
    """
    some csvs come with an additional empty column... kick em out
    """
    empty_indices = [i for i, row in enumerate(data[0]) if not row]
    if empty_indices:
        for row in data:
            for i in empty_indices:
                del row[i]
    return data
