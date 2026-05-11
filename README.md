# AI Core Full Runtime Self-Bootstrap v3

新增能力：

```text
1. CLI 自动回答 auto_answers
2. CLI 类型识别 command_profiles
3. 自动追加安全参数，例如 winget --accept-source-agreements
4. pseudo-terminal / PTY 支持
5. Command Recovery: timeout / retry / recovery command
6. stdout / stderr / PTY 输出实时 stream 到 UI
7. 安装/下载/大处理显示百分比进度
8. Workflow checkpoint / resume
9. runtime 冷启动
10. ai_core 不包含具体业务逻辑
```

## 启动

```bash
pip install -r requirements.txt
python main.py
```

打开：

```text
http://127.0.0.1:8000
```

## 运行时配置

第一次运行会自动生成：

```text
runtime/configs/environment/providers.yaml
runtime/configs/environment/auto_answers.yaml
runtime/configs/environment/command_profiles.yaml
runtime/configs/workflows/base_orchestration.yaml
runtime/configs/models/model_routes.yaml
runtime/configs/capabilities/task_capability_map.yaml
```

## 说明

安装软件、启动服务、下载模型等命令默认需要 Human Approval。
Approve 后会真正 resume workflow，并继续执行命令。
