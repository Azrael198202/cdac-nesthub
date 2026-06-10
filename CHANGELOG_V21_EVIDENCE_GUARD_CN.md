# v21 Evidence Guard 更新说明

本次修改目标：加强结果判断与最终答案约束，避免搜索结果已经包含更新事实时，最终答案仍输出旧事实或重复幻觉内容。

## 修改原则

- 不写具体业务关键词
- 不绑定具体网站、产品、数据库、版本名
- 不硬编码示例答案
- ai_core 只增加通用语义判断能力
- final_synthesis 只能使用经过验证的事实或可比较证据 claim

## 新增模块

### ai_core/runtime/semantic/evidence_claim_ranker.py

通用 Evidence Claim Ranker，用于：

1. 从证据材料中抽取可比较标识
2. 按来源强度排序
3. 按发布状态排序
4. 判断最终答案是否与最强证据一致
5. 在存在更强证据时，阻止旧标识进入最终答案

该模块不包含任何业务词汇，只使用通用语义规则。

## 修改模块

### ai_core/runtime/semantic/__init__.py

导出 EvidenceClaimRanker，供 presentation 层调用。

### ai_core/presentation/final_answer_synthesizer.py

增强 final_synthesis：

1. synthesis 前先抽取 evidence claims
2. direct answer 只有通过 answer-evidence consistency 才能直接输出
3. model synthesis 输出也必须通过一致性检查
4. 如果模型答案与证据冲突，回退到 deterministic synthesis
5. deterministic synthesis 优先输出最强证据 claim
6. synthesis metadata 中记录 evidence_claim_count 和 answer_evidence_consistency

## 新增测试

### tests/test_evidence_claim_ranker.py

覆盖：

1. 最强 evidence claim 选择
2. 答案中旧标识被一致性检查拦截

## 验证结果

```bash
python -m compileall -q ai_core auxiliary_brain verification_brain repair_brain task_runtime
python -m pytest -q
```

结果：

```text
2 passed
```
