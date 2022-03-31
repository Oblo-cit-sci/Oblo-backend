from logging import getLogger

from sqlalchemy.orm import Session

logger = getLogger(__name__)


def data_migration(session: Session):
    pass

    # fix identification // DONE FOR PRODUCTION!
    # user = session.query(RegisteredActor).all()
    # for u in user:
    #     u_configs = u.configs
    #     identification = u_configs.get("domain", {}).get(NO_DOMAIN, {}).get("identification")
    #     logger.warning(identification)
    #     if identification and (val := identification.get("value")):
    #         if isinstance(val, str):
    #             u_configs["domain"][NO_DOMAIN]["identification"] = {"value": [val]}
    #             logger.warning((u_configs["domain"][NO_DOMAIN]["identification"]))
    #             flag_modified(u, "configs")
    # session.commit()

    # production to version 0.9
    # db_actors: Dict[str, RegisteredActor] = {a.registered_name: a for a in session.query(RegisteredActor).all()}
    # # print(db_actors)
    # fin = open(join(CONFIG_DIR, "migration/registeredactor.csv"))
    # reader = csv.DictReader(fin)
    # for actor in reader:
    #
    #     if actor["registered_name"] in ["visitor", "admin"]:
    #         continue
    #     # print(actor["registered_name"])
    #     db_actor = db_actors.get(actor["registered_name"])
    #     if db_actor:
    #         db_actor.hashed_password = actor["hashed_password"]
    #         db_actor.email_validated = actor["email_validated"] == "true"
    #         db_actor.global_role = actor["global_role"]
    #         db_actor.account_deactivated = actor["account_deactivated"] == "true"
    #         db_actor.public_name = actor["public_name"]
    #         db_actor.description = actor["description"]
    #
    #         # print(actor.get("creation_date", datetime.now()))
    #         if not actor.get("creation_date"):
    #             actor["creation_date"] = datetime(2020, month=8, day=4, hour=12)
    #         db_actor.creation_date = actor["creation_date"]
    # session.commit()
    #
    # migration_data_folder = "/mnt/SSD/projects/opentek_be/app/data/production/"
    # fin = open(join(migration_data_folder, "registeredactor.csv"))
    # actor_reader = csv.DictReader(fin)
    # all_prev_actors = list(actor_reader)
    #
    # entry_fin = open(join(migration_data_folder, "opentek_public_entry.csv"))
    # entries = list(csv.DictReader(entry_fin))
    #
    # entry_actor_fin = open(join(migration_data_folder, "opentek_public_actorentryassociation.csv"))
    # all_entry_actors = list(csv.DictReader(entry_actor_fin))
    #
    # local_obs_template = session.query(Entry).filter(Entry.slug == "local_observation", Entry.language == "en").one()
    # local_observation_id = local_obs_template.id
    # local_observatio_version = local_obs_template.version
    #
    # db_actors = session.query(RegisteredActor).all()
    # # print(len(entries))
    #
    # count = 0
    #
    # for e in entries:
    #     if e["type"] != "regular":
    #         continue
    #     old_template_id = e["template_id"]
    #     old_template = list(filter(lambda e: e["id"] == old_template_id, entries))[0]
    #     old_template_slug = old_template["slug"]
    #     if old_template_slug == "local_observation":
    #         pass
    #     else:
    #         continue
    #     count +=1
    # print("local obs", count)
    #
    # for e in entries:
    #
    #     if e["type"] != "regular":
    #         continue
    #     # template_id = 0
    #     # template_version = 0
    #     tags = []
    #     entry_actors = []
    #     entry_refs = []
    #
    #     old_template_id = e["template_id"]
    #     old_template = list(filter(lambda e: e["id"] == old_template_id, entries))[0]
    #     old_template_slug = old_template["slug"]
    #     if old_template_slug == "local_observation":
    #         template_id = local_observation_id
    #         template_version = local_observatio_version
    #     else:
    #         # print(f"old template-slug {old_template_slug}")
    #         continue
    #
    #     if existing := session.query(Entry).filter(Entry.uuid == e["uuid"]).one_or_none():
    #         print(f"e exists... {e['uuid']}")
    #         print(existing)
    #         continue
    #
    #     e_id = e["id"]
    #
    #     print("create..")
    #
    #     # fixing CastingArray(JSONB)
    #     # print([at.replace("\\", "") for at in e["attached_files"][2:-2].split('","')])
    #     attached_files = []
    #     try:
    #         if e["attached_files"] != "{}":
    #             attached_files = [json.loads(at.replace('\\', "")) for at in e["attached_files"][2:-2].split('","')]
    #     except:
    #         print(f"attached files failed... {e['attached_files']}")
    #         continue
    #     # print([at for at in e["location"][2:-2].split('","')])
    #     location = []
    #     try:
    #         if e["location"] != "{}":
    #             location = [json.loads(l.replace('\\', "")) for l in e["location"][2:-2].split('","')]
    #     except:
    #         print(f"location failed... {e['location']}")
    #
    #         continue
    #
    #     values = json.loads(e["values"])
    #     values["location"] = values["Location"]
    #     del values["Location"]
    #     values["images"] = values["Images"]
    #     del values["Images"]
    #     values["Species affected"] = {"value": []}
    #
    #     observer_map = {
    #         'A lot of local people': "lot local",
    #     }
    #     if values.get("Observer"):
    #         print(values.get("Observer"))
    #         values["Observer"] = {"value": [v for v in values.get("Observer")]}
    #     else:
    #         print(values)
    #
    #     print(e["creation_ts"], e["last_edit_ts"])
    #     entry = Entry(
    #         uuid=e["uuid"], type="regular", creation_ts=e["creation_ts"], domain=e["domain"],
    #         template_id=template_id, template_version=template_version, last_edit_ts=e["last_edit_ts"],
    #         version=e["version"],
    #         title=e["title"], status=e["status"], description=e["description"], language=e["language"],
    #         privacy=e["privacy"], license=e["license"], image=e["image"], attached_files=attached_files,
    #         location=location, values=values, tags=tags, actors=[], entry_refs=entry_refs
    #     )
    #
    #     for ea in all_entry_actors:
    #         if ea["entry_id"] == e_id:
    #             old_actor = next(filter(lambda a: a["id"] == ea["actor_id"], all_prev_actors))
    #             old_actor_name = old_actor["registered_name"]
    #             # print(f"actor: {old_actor_name}")
    #             new_actor = next(filter(lambda a: a.registered_name == old_actor_name, db_actors))
    #             entry.actors.append(ActorEntryAssociation(entry=entry, actor=new_actor, role=ea["role"]))
    #
    #     if not existing:
    #         print("adding entry")
    #         try:
    #             session.add(entry)
    #             session.commit()
    #         except:
    #             session.rollback()
    #             print("FAILED")
    # entry_fin.close()
    # entry_actor_fin.close()
    #
    # logger.info("migration done")
    # print("migration done")
