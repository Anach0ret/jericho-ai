from collections.abc import Mapping

from jericho.core import ServiceConfig
from tests.core.sample_services.clipboard import Clipboard


class Memory:
    def text(self) -> str:
        return "скопировано"


class ClipboardService(ServiceConfig):
    name = "clipboard"

    def provides(self) -> Mapping[type, object]:
        return {Clipboard: Memory()}
