from .base import Adapter, Unsupported
from .rest import Rest
from .rosbridge import Rosbridge
from .vda5050 import Vda5050

PROTOCOLS: dict[str, type[Adapter]] = {a.protocol: a for a in (Vda5050, Rosbridge, Rest)}

__all__ = ["PROTOCOLS", "Adapter", "Unsupported"]
