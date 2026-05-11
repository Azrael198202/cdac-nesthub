import json
class TemplateEngine:
    def render(self, template: str, variables: dict)->str:
        rendered=template
        for k,v in variables.items():
            if isinstance(v,(dict,list)): v=json.dumps(v,ensure_ascii=False,indent=2)
            rendered=rendered.replace('{{ '+k+' }}',str(v)).replace('{{'+k+'}}',str(v))
        return rendered
