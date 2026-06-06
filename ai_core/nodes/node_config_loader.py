from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import PROJECT_ROOT
class NodeConfigLoader:
    def __init__(self): self.loader=ConfigLoader()
    def load(self, workflow_node: dict)->dict:
        config_path=workflow_node.get('node_config')
        if not config_path: raise ValueError(f'workflow node missing node_config: {workflow_node}')
        path=PROJECT_ROOT/config_path; cfg=self.loader.load_yaml(path)
        if not cfg: raise ValueError(f'node config not found or empty: {path}')
        return cfg
