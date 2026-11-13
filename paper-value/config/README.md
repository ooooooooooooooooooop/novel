# 配置与词表

停用词等配置统一放于此目录。脚本中请使用 `config/xxx.txt`（以项目根为基准）或 `Path(项目根)/config/xxx.txt`。

## 文件说明

| 文件 | 说明 |
|------|------|
| stopwords_en.txt | 英文停用词 |
| stopwords_cn.txt | 中文停用词 |
| structural_stopwords.txt | 结构性停用词（论文结构、出版商等） |
| opinion_stopwords.txt | 观点停用短语 |
| scientific_stopwords_doc_freq.txt | 科研领域文档频率停用词（由「科研停用词筛选」生成） |

若 `scientific_stopwords_doc_freq.txt` 尚未在此目录，请在项目根执行：`python copy_scientific_to_config.py`（一次性复制脚本，执行后可删除）。
