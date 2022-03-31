from typing import List, Union, Optional

from app.models.orm import Actor, Entry
from app.models.schema import EntrySearchQueryIn, SearchValueDefinition
from app.util.consts import ACTOR, TEMPLATE, DOMAIN, LANGUAGE

"""
maybe not necessary, since the entry service has a bunch of small methods
"""


def build(
    *,
    domain_names: Optional[List[str]] = None,
    of_actor: Union[str, Actor] = None,
    of_template: Union[str, Entry] = None,
    languages: List[str]
) -> EntrySearchQueryIn:
    required: List[SearchValueDefinition] = []
    if domain_names:
        required.append(SearchValueDefinition(name=DOMAIN, value=domain_names))
    if of_actor:
        if type(of_actor) == str:
            actor_name = of_actor
        else:
            actor_name = of_actor.registered_name
        required.append(SearchValueDefinition(name=ACTOR, value=actor_name))
    if of_template:
        if type(of_template) == str:
            template_slug = of_template
        else:
            template_slug = of_template.slug
        required.append(SearchValueDefinition(name=TEMPLATE, value=template_slug))
    if languages:
        required.append(SearchValueDefinition(name=LANGUAGE, value=languages))
    return EntrySearchQueryIn(required=required)
