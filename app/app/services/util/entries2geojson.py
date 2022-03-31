from typing import Dict, List, Optional, Tuple

from geojson import Feature, FeatureCollection, MultiPoint, Point

from app.app_logger import get_logger
from app.models.schema import MapEntry
from app.util.consts import PUBLISHED

logger = get_logger(__name__)

def coordinates2array(geo_data: Dict[str, float]) -> Optional[Tuple[float, float]]:
    try:
        return float(geo_data["lon"]), float(geo_data["lat"])
    except:
        return None


def entry2feature(entry: MapEntry, id: int):
    entry_data = entry.dict(exclude={"location"})
    geometry = entry.location
    if not geometry:
        print("something weird with", entry.title)
        return None
    if len(geometry) == 1:
        geometry = Point(coordinates2array(entry.location[0]["coordinates"]))
    else:
        geometry = MultiPoint(
            [
                coordinates2array(l["coordinates"])
                for l in entry.location
                if coordinates2array(l["coordinates"])
            ]
        )
    if not geometry:
        print("problem with geo data", entry.location)
        return None
    # we generateIds on the client
    return Feature(id=id, geometry=geometry, properties=entry_data)


def entry2features_no_multipoint(entry: MapEntry) -> Optional[List[Feature]]:
    # this exclude kicks out status, cuz its just required for "required_review"
    entry_data = entry.dict(exclude=set([s for s in [entry.status] if s != PUBLISHED]))

    if entry.geojson_location:
        if entry.geojson_location["type"] == "FeatureCollection":
            return entry.geojson_location["features"]
        elif entry.geojson_location["type"] == "Feature":
            return [entry.geojson_location]
        else:
            logger.warning("Entry geojson_location should be either FeatureCollection or Feature")
            return []
    geometry = entry.location
    if not geometry:
        return []
    if len(geometry) == 1:
        geometry = Point(coordinates2array(entry.location[0]["coordinates"]))
        if not geometry:
            print("problem with geo data", entry.location)
            return []
        return [Feature(geometry=geometry, properties={**entry_data, "l_id": 0})]
    else:
        # todo this should maybe just pass the location by index instead of the whole entry.location
        geometries = [
            Point(coordinates2array(l["coordinates"]))
            for l in entry.location
            if coordinates2array(l["coordinates"])
        ]
        features: List[Feature] = [
            # Feature(
            #     id=id + id_i, geometry=geometry, properties={**entry_data, "l_id": id_i}
            # )
            Feature(geometry=geometry, properties={**entry_data, "l_id": id_i})
            for id_i, geometry in enumerate(geometries)
            if geometry
        ]
        # for index, f in enumerate(features):
        #     f.properties["location"] = geometry[index]
        return features


def entries2feature_collection(entries: List[MapEntry]):
    geo2json_data = []
    feature_id = 0
    for e in entries:
        features = entry2features_no_multipoint(e)
        geo2json_data.extend(features)
        feature_id += len(features)

    return FeatureCollection(geo2json_data)
