from collections import Counter
from typing import List, Dict, Optional

from app.util.files import CSVPath


def count_unique_values(data: List[str], comma_separated: bool = False):
    data_extended = []
    if comma_separated:
        for item in data:
            data_extended.extend((v.strip() for v in item.split(',')))
    else:
        data_extended = data
    counter = Counter(data_extended)
    return counter


def check_headers(input_file: CSVPath) -> bool:
    reader = input_file.read(True)
    counts = Counter(reader.fieldnames)
    duplicates = list(filter(lambda col__count: col__count[1] > 1, counts.items()))
    header_ok = True
    if duplicates:
        print(f"Duplicate headers found: {duplicates}")
        header_ok = False
    #
    bad_fieldnames = list(filter(lambda name: name != name.strip(), reader.fieldnames))
    if bad_fieldnames:
        print(f"Bad fieldnames found: {bad_fieldnames}")
        header_ok = False
    return header_ok


def merge_counter(counters: List[Counter]):
    merged_counter = Counter()
    for counter in counters:
        merged_counter += counter
    return merged_counter


def value_fixer(input_file: CSVPath, fixer_config: dict, output_path: CSVPath, report_unfixed_values: bool = False) -> \
        Optional[Dict[str, List[str]]]:
    reader = input_file.read(True)
    fieldnames = [name.strip() for name in reader.fieldnames]
    result_rows = []
    missing_values = {}

    # fixer config can have a list of list(column_names, and dicts). the columns get the dicts merged in
    # the individual fixes have priority over the wildcard fixes
    if wildcard := fixer_config.get('*'):
        for group in wildcard:
            column_names, fixes = group
            for column_name in column_names:
                fixes.update(fixer_config.get(column_name, {}))
                fixer_config[column_name] = fixes
    for row in reader:
        result_row = {}
        for key, value in row.items():
            field_name = key.strip()
            if field_name in fixer_config:
                values = value.split(",")
                result_values = []
                for ind_value in values:
                    clean_value = ind_value.strip()
                    if clean_value in fixer_config[field_name]:
                        result_values.append(fixer_config[field_name][clean_value])
                    else:
                        result_values.append(clean_value)
                        if report_unfixed_values and clean_value not in fixer_config[field_name].values():
                            missing_values.setdefault(field_name, set()).add(clean_value)
                result_row[field_name] = ",".join(result_values)
            else:
                result_row[field_name] = value.strip()
        result_rows.append(result_row)
    output_path.write(result_rows, fieldnames)
    if report_unfixed_values:
        return missing_values
