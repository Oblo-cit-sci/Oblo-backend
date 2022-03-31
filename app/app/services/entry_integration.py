from logging import getLogger
from typing import Optional, List

from jsonpath import jsonpath
from pydantic import BaseModel

from app.models.orm import RegisteredActor, Entry
from app.services.service_worker import ServiceWorker
from app.util.consts import NO_DOMAIN, REQUIRES_REVIEW, GLOBAL_ROLE_LITERAL

logger = getLogger(__name__)

class EntryCreateRequiresReviewCommon(BaseModel):
    # todo use literal
    actor_role: Optional[List[GLOBAL_ROLE_LITERAL]]

class DomainEntryCreateRequiresReview(EntryCreateRequiresReviewCommon):
    pass

class TemplateRulesCreateRequiresReview(EntryCreateRequiresReviewCommon):
    entry_values_missing: Optional[List[str]]

class EntryCreateRequiresReview(EntryCreateRequiresReviewCommon):
    entry_values_missing: Optional[List[str]]

    def merge(self, other: EntryCreateRequiresReviewCommon):
        other_dict = other.dict(exclude_none=True)
        for k,v in other_dict.items():
            setattr(self, k, v)


def entry_create_requires_review(sw: ServiceWorker, entry: Entry, user: RegisteredActor) -> bool:
    all_rules = EntryCreateRequiresReview()
    # template domain rules
    domain_meta = sw.domain.crud_read_meta(entry.domain)
    domain_entry_create_requires_review = jsonpath(domain_meta.content, "entry.create.requires_review")
    if domain_entry_create_requires_review:
        all_rules.merge(DomainEntryCreateRequiresReview.parse_obj(domain_entry_create_requires_review))
    # plaftorm rules
    platform_meta = sw.domain.crud_read_meta(NO_DOMAIN)
    platform_entry_create_requires_review = jsonpath(platform_meta.content, "entry.create.requires_review")
    if platform_entry_create_requires_review:
        all_rules.merge(DomainEntryCreateRequiresReview.parse_obj(platform_entry_create_requires_review))
    # template rules
    template_rules_create_requires_review = jsonpath(entry.template.rules, "create.requires_review")
    if template_rules_create_requires_review:
        all_rules.merge(TemplateRulesCreateRequiresReview.parse_obj(template_rules_create_requires_review))

    logger.warning(f"rules: {all_rules.dict()}")
    for rule_name, rule in all_rules.dict(exclude_none=True).items():
        if rule_name == "actor_role":
            if user.global_role in rule:
                return True
        if rule_name == "entry_values_missing":
            for path in rule:
                result = jsonpath(entry.values, path)
                if result:  # its proper path.
                    value = result[0]
                    if not value:  # null, or empty list
                        return True
                else:
                    logger.warning(
                        "given path for requires_review_if_missing does not exist: {path}. Ignoring..."
                    )
    return False