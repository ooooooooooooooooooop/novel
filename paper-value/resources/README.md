# 外部资源

二进制与外部资源统一放于此目录。

| 文件 | 说明 |
|------|------|
| lid.176.bin | FastText 语言识别模型（若使用语言检测时需此文件） |

**迁移**：若根目录存在 `lid.176.bin`，请在本机执行一次复制到此处，例如：
- PowerShell: `Copy-Item "lid.176.bin" "resources\"`
- 或运行项目根目录下的 `copy_lid_to_resources.py`（若有）。

引用时使用 `resources/lid.176.bin`（以项目根为基准）。
