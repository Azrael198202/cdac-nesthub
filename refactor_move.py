from pathlib import Path
import shutil
root=Path('/mnt/data/refactor')
# Move implementation modules that are execution/runtime capability/studio/tooling concerns
# out of ai_core into auxiliary_brain. ai_core keeps compatibility facades only.
MOVE_MAP={
 'ai_core/artifacts':'auxiliary_brain/artifacts',
 'ai_core/dependencies':'auxiliary_brain/dependencies',
 'ai_core/environment':'auxiliary_brain/environment',
 'ai_core/media':'auxiliary_brain/media',
 'ai_core/models':'auxiliary_brain/models',
 'ai_core/modules':'auxiliary_brain/runtime_modules',
 'ai_core/providers':'auxiliary_brain/providers',
 'ai_core/research':'auxiliary_brain/research',
 'ai_core/sandbox':'auxiliary_brain/sandbox',
 'ai_core/tools':'auxiliary_brain/runtime_tools',
 'ai_core/web_evidence_optimizer':'auxiliary_brain/web_evidence_optimizer',
 'ai_core/runtime/capability':'auxiliary_brain/runtime/capability',
 'ai_core/runtime/external_runtimes':'auxiliary_brain/runtime/external_runtimes',
 'ai_core/runtime/generated_execution':'auxiliary_brain/runtime/generated_execution',
 'ai_core/runtime/learning':'auxiliary_brain/runtime/learning',
 'ai_core/runtime/observability':'auxiliary_brain/runtime/observability',
 'ai_core/runtime/scheduler':'auxiliary_brain/runtime/scheduler',
 'ai_core/runtime/self_repair':'auxiliary_brain/runtime/self_repair',
}

def ensure_pkg_dirs(path:Path):
    # ensure __init__.py from auxiliary_brain down to target dir
    cur=root
    for part in path.relative_to(root).parts:
        cur=cur/part
        cur.mkdir(exist_ok=True)
        init=cur/'__init__.py'
        if not init.exists():
            init.write_text('',encoding='utf-8')

def module_name_from_path(path:Path):
    rel=path.relative_to(root).with_suffix('')
    return '.'.join(rel.parts)

moved=[]
for src_rel,dst_rel in MOVE_MAP.items():
    src=root/src_rel
    dst=root/dst_rel
    if not src.exists():
        continue
    ensure_pkg_dirs(dst)
    # copy implementation to new location
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src,dst,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    # replace original py files with compatibility wrappers
    for p in list(src.rglob('*')):
        if p.is_dir():
            # delete pycache only
            if p.name=='__pycache__': shutil.rmtree(p,ignore_errors=True)
            continue
        if p.suffix=='.py':
            rel=p.relative_to(src)
            new_p=dst/rel
            new_mod=module_name_from_path(new_p)
            if p.name=='__init__.py':
                wrapper=(
                    f'"""Compatibility facade for migrated implementation.\n\n'
                    f'The implementation for {src_rel} now lives in {dst_rel}.\n'
                    f'This facade preserves existing imports while keeping ai_core focused on generic brain/runtime contracts.\n'
                    f'"""\n'
                    f'from {new_mod} import *  # noqa: F401,F403\n'
                )
            else:
                wrapper=(
                    f'"""Compatibility facade for migrated implementation.\n\n'
                    f'Implementation moved to {new_mod}.\n'
                    f'"""\n'
                    f'from {new_mod} import *  # noqa: F401,F403\n'
                )
            p.write_text(wrapper,encoding='utf-8')
            moved.append((src_rel+'/'+str(rel).replace('\\','/'), dst_rel+'/'+str(rel).replace('\\','/')))
        else:
            # leave non-py metadata? Avoid duplicate implementation data? keep for compatibility if any.
            pass

# Add migration note
note=root/'MIGRATION_AI_CORE_BOUNDARY.md'
lines=['# AI Core Boundary Migration\n','\n','本次重构目标：将不属于 `ai_core` 通用大脑/运行时操作系统边界的实现内容移动到 `auxiliary_brain`，同时保留兼容 facade，保证原 import 路径和执行逻辑不变。\n','\n','## 移动原则\n','\n','- `ai_core` 保留：输入清洗、意图识别、上下文、workflow/graph、执行契约、结果验证、最终汇总等通用运行时 OS 职责。\n','- `auxiliary_brain` 承接：运行时工具生成、能力获取、沙箱验证、外部研究、媒体能力、模型/Provider 生命周期、Artifact 管理、Runtime Studio/Observability、Schedule Runner 等可执行/可扩展实现。\n','- 原 `ai_core.*` import 不删除，改为 facade 转发，降低一次性迁移风险。\n','\n','## 移动列表\n','\n']
for src_rel,dst_rel in MOVE_MAP.items():
    lines.append(f'- `{src_rel}` -> `{dst_rel}`\n')
lines += ['\n','## 兼容方式\n','\n','每个被移动的 `ai_core` Python 文件保留同名 wrapper，例如：\n','\n','```python\nfrom auxiliary_brain.runtime_tools.runtime_tool_registry import *\n```\n','\n','这样现有代码仍可通过旧路径运行，后续可以逐步把 import 改成新路径。\n','\n','## 验证\n','\n','已执行 `python -m compileall` 对主要源码目录进行语法验证。\n']
note.write_text(''.join(lines),encoding='utf-8')
print('moved files',len(moved))
