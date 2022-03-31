from typing import Dict, List, Union

from app.models.schema import ActorBase, EntryActorRelationOut


def fix_constructed_entry_actors(
    entry_actors: List[Union[Dict, EntryActorRelationOut]]
):
    """
    returns a list of EntryActorRelationOuts from a mixed list of EntryActorRelationOut and raw data (actor, role)
    """

    def construct_ear(ear_data: dict):
        return EntryActorRelationOut(
            actor=ActorBase.construct(**ear_data["actor"]), role=ear_data["role"]
        )

    return [
        a_r if type(a_r) == EntryActorRelationOut else construct_ear(a_r)
        for a_r in entry_actors
    ]
