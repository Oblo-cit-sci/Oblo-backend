from app.services.service_worker import ServiceWorker


def init_cache(sw: ServiceWorker):
    """
    for now. loading:
        - language statuses
    @param sw:
    @return:
    """
    # todo maybe just into a global vars like oauth
    active_statuses = {lang[0]: lang[1] for lang in sw.messages.get_all_statuses()}
    sw.app.state.language_active_statuses = active_statuses
