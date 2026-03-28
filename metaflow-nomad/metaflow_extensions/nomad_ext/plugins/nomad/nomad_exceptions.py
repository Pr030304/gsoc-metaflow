try:
    from metaflow.exception import MetaflowException
except Exception:  # pragma: no cover - fallback for the standalone demo path
    class MetaflowException(Exception):
        headline = "Metaflow error"


class NomadException(MetaflowException):
    headline = "Nomad error"


class NomadKilledException(MetaflowException):
    headline = "Nomad batch job killed"
