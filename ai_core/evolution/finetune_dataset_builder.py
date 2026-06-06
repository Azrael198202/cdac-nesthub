import json
from ai_core.config.paths import RUNTIME_DATASETS
class FinetuneDatasetBuilder:
    def append_case(self,input_text:str,output_text:str,metadata:dict|None=None)->None:
        RUNTIME_DATASETS.mkdir(parents=True,exist_ok=True)
        with (RUNTIME_DATASETS/'finetune.jsonl').open('a',encoding='utf-8') as f: f.write(json.dumps({'input':input_text,'output':output_text,'metadata':metadata or {}},ensure_ascii=False)+'\n')
