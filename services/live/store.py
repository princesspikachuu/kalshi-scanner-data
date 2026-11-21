"""LIVE records have a distinct namespace from Demo and paper simulation."""
from services.demo.store import DemoStore
class LiveStore(DemoStore):
    namespace='live'
