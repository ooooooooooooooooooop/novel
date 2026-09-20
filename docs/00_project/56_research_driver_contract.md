# 研究驱动公共边界（2026-09-19）

适用范围：已授权的本地研究驱动。本文不新增模型、预算、自动运行或生产授权。

根因是各驱动复制流程并自行解释输入、重试与成功条件。修复放在公共代码，具体材料仍留本地。

- **全链评审输入**：`ReviewUnit.build_prompt` 在 `extend*`、`compose*`、`a1-post-prose` 下调用 `validate_input`，缺 state/cast/PlotUnit、悬空引用或重复 ID 均在生成 prompt 前拒绝。`audit` 保留诊断不完整重建的用途，不得用它绕过全链验收。
- **缓存路径也受约束**：先对已解析对象调用 `ReviewUnit.validate_input`；复用 Review 响应前调用 `src.experiment.review_result.validate_cached_review`，核对原 prompt 与当前完整输入。旧缓存不匹配时保存证据并停止复用，不自动重跑整批。
- **调用与收据**：新研究驱动使用 `src.experiment.recorded_call.call_recorded`，不复制重试循环。同 evidence directory + prompt hash + requested model 累计最多三次，成功、HTTP 重试及后续 schema 重生成共同计数。三票仲裁是三次独立调用，不复用同一成功响应伪装三票。该边界不替代整批预算。
- **不确定请求**：429/5xx 有界重试；超时、非重试错误、已有预约但缺结果收据时停止，跨重启也不盲目重发。不得换目录、改 prompt 或清空收据绕过上限；恢复先核对实际送达情况和适用授权。
- **真实来源**：记录 requested model、响应自报 model、prompt/response SHA-256，以及服务提供的 id/usage。响应模型未提供、旧缓存无收据均为 `UNKNOWN`；多来源冲突为 `AMBIGUOUS`。响应自报身份不是对底层供应商路由的独立证明，未知用量也不能当零成本。
- **统一验收**：`combined_review_issues` 合并代码硬规则、领域规则和模型意见，再按专项仲裁及 `resolve_route` 处理。`write_review_result` 仅在 pass、无 blocking、正文非空时写 `prose_final.txt`；阻断正文写 rejected，旧误标 final 保留归档。来源完整性与内容通过分别记录，不把任一项当整体研究或生产资格。

必要验证：`python scripts/check_recorded_call_contract.py`（纯离线），以及既有 `tests/test_review_after_prose.py::test_review_prompt_zero_cost_without_prose`；后者包含输入、调用、缓存和验收回归，不增加测试收集数量。新驱动先零调用预检，再按原授权运行。

外部自检：复用 [Pydantic 校验机制](https://docs.pydantic.dev/latest/concepts/validators/) 和 [Python HTTP 错误类型](https://docs.python.org/3/library/urllib.error.html)。单对象 schema 不能代替跨对象引用检查；HTTP 错误应按状态分类，不能把所有异常放进长重试循环。关键遗漏检查补入缓存旁路、三票独立性、并发预约和旧进程未加载新代码；已启动的旧进程不会因源码变化自动升级。

实现边界：防护覆盖接入这些公共入口的调用方。任意另写 HTTP 脚本仍可能绕过；代码修复不承诺任意未来实现永不出错。当前私有接入清单和运行断点读取 `.workspace_local/task_control/CURRENT_TASK.md`。
