from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from app.util.plugins import AvailablePlugin

available_plugins: Dict[str, "AvailablePlugin"] = {}
registered_plugins = {}
