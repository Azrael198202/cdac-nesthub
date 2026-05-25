# v9 下一步完善方案与第一步实现说明

## 1. 当前判断

v9 是相对干净的版本，适合作为下一阶段产品化基线。但当前最需要先补的不是更多业务能力，而是运行时的结构稳定性：

1. 元信息、可执行节点、数据流边界必须分离。
2. 执行不能只依赖顺序循环，必须支持按边调度。
3. 验收不能只看 completed，要验证节点、边、输出约束。
4. 修复不能只靠人工改代码，要形成 runtime self-check 与 repair plan。
5. UI 后续需要能展示 dataflow DAG，而不是只展示 participant 和 trace。

## 2. 产品化路线建议

### Phase 1：图边界与执行可靠性

目标：让 runtime 知道什么可以执行、什么只是定义/元信息、哪个节点依赖哪个节点。

交付：

- metadata graph / execution graph / dataflow graph 分离
- edge-driven scheduler
- output binding
- runtime self-check
- repair plan 生成
- 场景矩阵测试入口

### Phase 2：Context Lifecycle System

目标：把 session、workflow、execution、user goal、generated artifact、summary、long term memory 分层管理。

交付：

- session boundary
- short term context
- workflow context
- execution context
- generated artifact context
- rolling summary
- high quality conversation promotion

### Phase 3：产品化运行能力

目标：支持多场景稳定运行。

交付：

- API auto integration
- web research planning
- document generation
- multi-agent collaboration
- browser runtime
- autonomous repair
- long-running task control

### Phase 4：UI 与可观测性

目标：能看到真实执行 DAG 和每条边的数据绑定。

交付：

- DAG view
- node status
- edge status
- skipped / failed / reused / repaired 标记
- repair history
- acceptance report

### Phase 5：质量门禁

目标：每次修改必须通过结构扫描、单元测试、场景矩阵测试。

交付：

- no domain vocabulary in core scan
- no generated sample data scan
- graph matrix tests
- acceptance check tests
- integration smoke tests

## 3. 第一阶段本次已实现内容

新增目录：

```text
ai_core/graph/
  __init__.py
  graph_contract.py
  edge_scheduler.py
  graph_self_check.py
```

新增测试：

```text
tests/test_graph_boundary_scheduler_self_check.py
```

### 3.1 GraphBoundaryNormalizer

职责：

- 将输入 graph 拆分为 metadata_graph / execution_graph / dataflow_graph
- 非可执行节点不会进入 execution_graph
- 只有 execution node 之间的边才进入 dataflow_graph
- 无效边进入 rejected_edges

### 3.2 EdgeDrivenScheduler

职责：

- 根据 dataflow edges 判断 ready nodes
- start node
- bind output
- unlock downstream
- failed node 后跳过受影响下游节点
- 输出可检查 summary

### 3.3 GraphSelfCheck

职责：

- 验证节点是否全部完成
- 验证 edge source 是否完成
- 验证 edge output 是否绑定到 downstream input
- 验证 final output 的基本验收约束
- 生成 repair_plan

## 4. 已验证项目

已执行：

```bash
pytest -q tests/test_graph_boundary_scheduler_self_check.py tests/test_graph_dataflow_runtime.py
```

结果：

```text
7 passed
```

## 5. 下一步建议

下一步不要马上接 UI，而是先把 `ai_core/orchestration/workflow_runtime.py` 的顺序循环逐步迁移为：

```text
normalize graph
  -> scheduler.ready_nodes
  -> execute ready node
  -> bind output
  -> unlock downstream
  -> final synthesis
  -> self check
  -> repair if needed
```

建议先以兼容模式接入：旧 workflow 仍可运行，新 graph runtime 先作为可选路径，等场景矩阵稳定后再替换默认执行路径。
