from functools import reduce
from typing import Union, Sequence, Mapping, Tuple, List, Optional

input_coordinate_format = Union[Sequence[float], Mapping[str, float]]
coordinate_format = Sequence[float]

LAT = "lat"
LON = "lon"
LNG = "lng"
ALT = "alt"

# these are not the expected sequences of coordinates for sequences but the keys ordered (in mapping)
LAT_LON_SEQ = [LAT, LON]
LAT_LNG_SEQ = [LAT, LNG]
ALT_LAT_LON_SEQ = [ALT, LAT, LON]
ALT_LAT_LNG_SEQ = [ALT, LAT, LNG]


def validate_value(value: Union[float, int]) -> bool:
    return isinstance(value, float) or isinstance(value, int)


def validate_coordinate(coordinate: input_coordinate_format) -> bool:
    try:
        assert isinstance(coordinate, Sequence) or isinstance(coordinate, Mapping)
        assert len(coordinate) in [2, 3]
        if isinstance(coordinate, Sequence):
            assert all(map(validate_value, coordinate))
        else:
            assert sorted(coordinate.keys()) in [LAT_LON_SEQ, LAT_LNG_SEQ, ALT_LAT_LON_SEQ, ALT_LAT_LNG_SEQ]
            # assert all(map(lambda key: isinstance(key, str), coordinate))
            assert all(map(validate_value, coordinate.values()))
    except AssertionError:
        return False
    return True


def validate_line_string(lineString: Sequence[input_coordinate_format]) -> bool:
    try:
        assert isinstance(lineString, Sequence)
        assert len(lineString) > 1
        assert all(map(validate_coordinate, lineString))
    except AssertionError:
        return False
    return True


def coordinate_to_normal_shape(coordinate: input_coordinate_format) -> coordinate_format:
    if isinstance(coordinate, Sequence):
        return coordinate
    elif isinstance(coordinate, Mapping):
        keys = sorted(coordinate.keys())
        if keys == LAT_LON_SEQ:
            return [coordinate[k] for k in (LON, LAT)]
        elif keys == LAT_LNG_SEQ:
            return [coordinate[k] for k in (LNG, LAT)]
        elif keys == ALT_LAT_LON_SEQ:
            return [coordinate[k] for k in (LON, LAT, ALT)]
        elif keys == ALT_LAT_LNG_SEQ:
            return [coordinate[k] for k in (LNG, LAT, ALT)]
    raise ValueError("Invalid coordinate format")


def validate_polygon(lineString: Sequence[input_coordinate_format], proper_wrap: bool = True,
                     return_normalized: bool = True) -> Union[
    bool, Tuple[bool, Sequence[input_coordinate_format]], Tuple[bool, Sequence[Sequence[input_coordinate_format]]]]:
    """
    proper wrap assumes that we just get a linestring. it will be wrapped into an array
    so it has the proper format for polygons: [[geo_0:[lat, lng], ...[lat, lng], ...], [geo_2:...]
    """
    try:
        assert isinstance(lineString, Sequence)
        assert len(lineString) > 3
        normalized = list(map(coordinate_to_normal_shape, lineString))
        assert all(map(validate_coordinate, normalized))
        assert normalized[0] == normalized[-1]
    except AssertionError:
        return False
    if return_normalized:
        if proper_wrap:
            return True, [normalized]
        return True, normalized
    return True


def merge_bbox(bbox: Sequence[float], new_bbox: Sequence[float]) -> Sequence[float]:
    return [
        min(bbox[0], new_bbox[0]), max(bbox[1], new_bbox[1]),
        max(bbox[2], new_bbox[2]), min(bbox[3], new_bbox[3])
    ]


def create_linestring_bbox(linestring: Sequence[coordinate_format], format: str = "wsen") \
        -> List[float]:
    """
    format: [west, south, east, north]
    """
    min_lon = linestring[0][0]
    min_lat = linestring[0][1]
    max_lon = min_lon
    max_lat = min_lat
    for coord in linestring:
        if coord[0] < min_lon:
            min_lon = coord[0]
        if coord[0] > max_lon:
            max_lon = coord[0]
        if coord[1] < min_lat:
            min_lat = coord[1]
        if coord[1] > max_lat:
            max_lat = coord[1]
    # if format == "wsen":
    return [min_lon, min_lat, max_lon, max_lat]


def create_bbox(geojson_object: dict) -> Sequence[float]:
    if geojson_object["type"] == "Point":
        return [geojson_object["coordinates"][0], geojson_object["coordinates"][1],
                geojson_object["coordinates"][0], geojson_object["coordinates"][1]]
    elif geojson_object["type"] == "LineString":
        return create_linestring_bbox(geojson_object["coordinates"])
    elif geojson_object["type"] == "Polygon":
        lines_strings_bboxes = list(map(create_linestring_bbox, geojson_object["coordinates"]))
        return reduce(merge_bbox, lines_strings_bboxes)
    elif geojson_object["type"] == "Feature":
        return create_bbox(geojson_object["geometry"])
    elif geojson_object["type"] == "FeatureCollection":
        bboxes = list(map(create_bbox, geojson_object["features"]))
        return reduce(merge_bbox, bboxes)
    else:
        raise ValueError("Invalid geojson object")


if __name__ == "__main__":
    coordinates = [
        ("das,31", False),
        ([1, 2], True),
        ([1, 2.6, 3], True),
        ([1, 2.6, "6"], False),
        ([1, 2, 3, 6], False),
        ([1.12], False),
        ({'lat': 1, 'lon': 2}, True),
        ({'lat': 1, 'lng': 2}, True),
        ({'lat': 1, 'lng': "2"}, False),
        ({'lat': 1, 'lng': 2, "alt": 67}, True),
        ({'lat': 1, 'lna': 2, "alt": 67}, False),
    ]

    for index, c_res in enumerate(coordinates):
        c = c_res[0]
        res = c_res[1]
        try:
            assert validate_coordinate(c) == res
        except AssertionError as e:
            print(f"{index}: {c} does not pass the test. Expected: {res}")

    polies = [
        ([[56, 1]], False),
        ([[56, 1], [1, 6]], False),
        ([[56, 1], [1, 6], [1, 7]], False),
        ([[56, 1], [1, 6], [1, 7], [1, 8]], False),
        ([[[56, 1], [1, 6], [1, 7], [56, 1]]], True)
    ]

    for index, c_res in enumerate(polies):
        poly = c_res[0]
        res = c_res[1]
        try:
            assert validate_polygon(poly, False) == res
        except AssertionError as e:
            print(f"{index}: {poly} does not pass the test. Expected: {res}")
