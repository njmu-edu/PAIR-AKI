# 集成标准

[English](INTEGRATION.md) | 简体中文 · [项目首页](README.zh-CN.md)

## 应用API v2

前缀为 `/api/competition/v2`，请求和响应均为UTF-8 JSON。参考Python服务只监听loopback。[schemas/](schemas/)提供JSON Schema说明，实际执行检查仍为准入依据。

| 方法 | 路径 | 合同 |
| --- | --- | --- |
| GET | `/capabilities` | 实际协调/医学提供器模式、模型ID、预算和来源身份 |
| GET | `/cases` | 已登记合成病例快照 |
| GET | `/cases/{case_ref}` | 指定评估时点快照 |
| POST | `/runs` | 启动有界任务，HTTP 202返回 `run_id` |
| GET | `/runs/{run_id}` | 读取状态、有序事件及终态结果 |

### 启动任务

```json
{
  "goal": "请只预测这个病例未来24小时首次合格肌酐事件，输出0或1。",
  "case_ref": "ae-201",
  "snapshot_ref": "<从GET /cases复制完整snapshot_ref>",
  "mode": "autonomous"
}
```

`mode`取 `autonomous`、`general` 或 `fixed`。goal是用户原始目标，不是隐藏正确路线；不接受任意患者字段、SQL、文件路径或模型URL。

使用返回的run ID轮询，直到状态离开 `queued` / `running`。终态为 `succeeded`、`partial`、`blocked`、`needs_clarification`、`failed`。读回已有任务不会重新提交。

### 成功预测结构

```json
{
  "label": 1,
  "receipt": {
    "role": "M_P",
    "mode": "trained",
    "model_id": "your-predictor-id",
    "contract_version": "mp-binary-v1",
    "input_sha256": "<已接纳快照SHA-256>",
    "bundle_sha256": "<已登记模型包SHA-256>"
  }
}
```

label才是业务决策。结果缺失、调用失败或输入受阻不会输出0；业务/协调边界拒绝模型分数、logit、校准字段和概率。

完整结果含 `prediction`、`comparables`、`narrative`、`evidence`、`limitations`、`final_snapshot`、metrics、versions和终止信息。经AGH运行时额外包含 `execution_runtime`，记录session ID、内层run ID、阶段、账本SHA和外层成本。

### 输入标准

- 评估时间采用ISO 8601，`event_hours` 和 `available_hours` 相对评估时点，预测禁止使用未来观测。
- 肌酐单位明确，已有转换逻辑归一可兼容单位；未知/冲突不填成正常值。
- 端点和快照版本须与模型支持签名匹配。端点为首次合格肌酐事件，不扩写为完整AKI诊断。
- 病例、患者/住院、来源类型、来源定位和哈希分别管理，不混用身份。
- 公开服务来源为 `synthetic`；医院来源适配和采集入口不在本版本中。

## 协调模型接入

协调器调用本地OpenAI兼容 `/v1` 服务下的 `/chat/completions`，要求支持非流式JSON Schema响应并返回配置的准确模型ID。Python还会核验动作，结构化生成不替代执行检查。

```sh
export PAIR_AKI_MODEL_URL=http://127.0.0.1:8000/v1
export PAIR_AKI_MODEL=your-served-model-id
# 如有需要，在环境中设置 PAIR_AKI_MODEL_API_KEY。
python3 -m pair_aki.server --state-dir "$HOME/.local/state/pair-aki/live" --synthetic-medical
```

只连接明确配置的本地端点，不接受重定向或代理环境绕行；密钥不写模型请求回执。

## 医学模型提供器接入

`pair_aki/medical_provider.py`使用标准库连接两个独立模型服务，不加载私有训练工件，也不会把任意模型回答转换成决策。

| 端点 | 请求 | 响应 |
| --- | --- | --- |
| GET `/identity` | 无 | `role`、`mode: trained`、`model_id`、`bundle_sha256`、`support_signature` |
| POST `/predict` | `{"states": [snapshot]}` | `M_P`返回 `{"label": 0或1, "receipt": ...}` |
| POST `/compare` | `{"states": [query, candidate_a, candidate_b]}` | `M_R`返回 `{"choice": "A"或"B", "margin": 有限数值, "receipt": ...}` |

支持签名包含 `version: specialist-support-v1`、role、cohort_id、population_id、snapshot_version、endpoint、age_days_min、age_days_max。每次医学调用前重新核身份。M_P回执绑定 `input_sha256`；M_R绑定 `query_sha256`、`left_sha256`、`right_sha256`，并包含角色、模式、模型、合同和模型包身份。

`M_R.margin`只用于内部顺序聚合和私有审计，从业务结果中移除，不解释为临床概率。执行器检查choice和margin符号一致。

```sh
export PAIR_AKI_PREDICTOR_URL=http://127.0.0.1:8001
export PAIR_AKI_RERANKER_URL=http://127.0.0.1:8002
python3 -m pair_aki.server --state-dir "$HOME/.local/state/pair-aki/trained"
```

模型服务由使用者自行准备，仓库不分发权重，不自动降级为合成提供器，输入仍限定为内置合成来源。

## 通过AGH运行

适配固定官方AGH提交 **`4bc36bc4c4441206388a53bece17379c1d7be14d`**。当前上游API可能已变化；本适配不宣称兼容最新上游版本。

准备Node.js 24.10+、Python 3.11+、Git和本地协调模型，从仓库根执行：

```sh
export PAIR_AKI_AGH_UPSTREAM="$HOME/.cache/pair-aki/agh-source"
# 使用全新目录，原有检出保持不动。
sh agh/prepare.sh
(cd agh && npm ci --ignore-scripts && npm run build)
```

`agh/build.mjs`在构建原版Kernel前核对固定manifest及源码闭包逐文件SHA。上游单独检出，不复制到本仓库。

先启动真实协调器模式的内层服务，医学工具可显式选择合成演示：

```sh
export PAIR_AKI_MODEL_URL=http://127.0.0.1:8000/v1
export PAIR_AKI_MODEL=your-served-model-id
python3 -m pair_aki.server --state-dir "$HOME/.local/state/pair-aki/inner" --synthetic-medical
```

另一个终端设置相同模型变量并启动AGH网关：

```sh
export PAIR_AKI_ALLOW_SYNTHETIC=1
# 显式允许合成医学提供器，不会将其改标为已训练模型。
python3 -m pair_aki.compat.gateway \
  --state "$HOME/.local/state/pair-aki/agh" \
  --node "$(command -v node)" --runner "$PWD/agh/dist/runner.mjs" \
  --api-url http://127.0.0.1:30886 \
  --llm-url "$PAIR_AKI_MODEL_URL" --port 30888
```

通过AGH提交：

```sh
python3 -m pair_aki.cli --api http://127.0.0.1:30888 \
  --goal '请联合评估：预测未来24小时首次合格肌酐事件，并提供三名可比历史患者。'
```

Vite工作台在执行 `make web-dev` 前设置 `PAIR_AKI_API_TARGET=http://127.0.0.1:30888`，也可以复制 `.env.example` 为本地未跟踪 `.env` 后填写。30886直连只运行内层Agent，30888才经过AGH链路，录屏和比较需保留这一区分。

### 三个实际阶段

1. `admit_case`：读取病例和当前模型身份。
2. `execute_assessment`：提交原始目标，等待应用真实终态。
3. `verify_assessment`：复读并核验绑定结果，保持原应用状态。

正常会话的AGH原生账本应有三个配对的 `tool/call` 和 `tool/result`。preflight、打印阶段名称及脚本快速开始都不能作为实际接入证据。

## 执行记录

网关状态目录中保存：

```text
agh/<application-run-id>/<agh-session-id>/
  kernel-ledger.json
  provider-receipts.json
  tool-trace.jsonl
  run-receipt.json
  verified-result.json
```

内层run ID和AGH session ID不同，需同时保留，并记录事件顺序、toolUseId、实际模型身份/模式、失败、成本及账本SHA。原始记录放在源码之外；公开脱敏副本需明确修改范围、保留原件SHA作为血缘，并单独计算导出件哈希。

状态目录使用独占服务锁。恢复后中断任务保留为失败；响应不明的内层提交不自动重复。医学任务失败或部分完成时，即使外层流程运行完毕，也不能描述为成功临床评估。
