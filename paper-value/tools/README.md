# 工具脚本

以下脚本已移入 `tools/`，运行前请将工作目录设为**项目根目录**（或在脚本内基于 `Path(__file__).resolve().parents[1]` 定位根目录）。

| 脚本 | 用途 |
|------|------|
| 匹配出版日期.py | 为数据补全出版日期 |
| 数据预处理排序.py | 为历史流程生成排序后的中间 CSV |
| 查看观点识别结果.py | 查看 output/v6_opinion 中观点识别结果 |
| 查看词库统计结果.py | 查看 output_6_vocabulary_statistics 词库统计结果 |
| 科研停用词筛选.py | 生成/筛选科研停用词（读 config/ 下停用词） |
| verify_logic.py | 逻辑校验 |
| cleanup_test_files.py | 清理测试文件 |

配置与路径：停用词等见 `config/`，输入数据见 `data/raw/`，输出见 `output/`。
