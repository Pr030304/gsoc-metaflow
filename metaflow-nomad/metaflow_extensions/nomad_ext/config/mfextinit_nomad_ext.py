from metaflow.metaflow_config_funcs import from_conf


NOMAD_ADDRESS = from_conf("NOMAD_ADDRESS")
NOMAD_NAMESPACE = from_conf("NOMAD_NAMESPACE")
NOMAD_REGION = from_conf("NOMAD_REGION")
NOMAD_TOKEN = from_conf("NOMAD_TOKEN")
NOMAD_DATACENTERS = from_conf("NOMAD_DATACENTERS")
NOMAD_IMAGE = from_conf("NOMAD_IMAGE")
