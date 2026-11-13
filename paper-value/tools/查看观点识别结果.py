import sqlite3
import pandas as pd
from pathlib import Path
import os

# 项目根目录（脚本在根目录或 tools/ 下均可用）
_root = Path(__file__).resolve().parent
if _root.name == "tools":
    _root = _root.parent
os.chdir(_root)

# 数据库路径（优先 output/v6_opinion，兼容旧目录）
_base = Path("output/v6_opinion")
db_path = _root / _base / "stage1_opinion_extraction/opinion_mentions.db"

if not db_path.exists():
    print("❌ 数据库文件不存在，程序可能尚未运行完成")
    exit(1)

# 检查进度数据库
progress_db_path = _root / _base / "stage1_opinion_extraction/checkpoints_streaming/paper_progress.db"
if progress_db_path.exists():
    try:
        progress_conn = sqlite3.connect(str(progress_db_path))
        progress_cursor = progress_conn.cursor()
        progress_cursor.execute("SELECT COUNT(*) FROM paper_progress")
        processed_papers = progress_cursor.fetchone()[0]
        progress_conn.close()
        print(f"📊 已处理论文数: {processed_papers:,} 篇")
    except:
        pass

conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

print("=" * 80)
print("观点识别结果预览")
print("=" * 80)

# 总体统计
print("\n【总体统计】")
cursor.execute('SELECT COUNT(*) FROM opinion_mentions')
total_mentions = cursor.fetchone()[0]
print(f"总提及记录数: {total_mentions:,} 条")

if total_mentions == 0:
    print("\n⚠️  警告：数据库为空！")
    print("可能的原因：")
    print("  1. 主程序还没有运行完成")
    print("  2. 观点提取函数没有找到任何符合条件的观点")
    print("     - 规则召回阶段：需要包含观点性动词、比较性表述等")
    print("     - 分类器筛选：语义相似度需要 >= 0.75")
    print("     - 结构化抽取：需要能匹配模板或依存句法")
    print("     - 规范化：需要能规范化成字符串")
    print("  3. 所有论文都被跳过了（已处理过）")
    print("  4. 程序在写入前出错了")
    print("\n建议：")
    print("  - 检查主程序的运行日志")
    print("  - 确认输入CSV文件包含有效的标题和摘要")
    print("  - 考虑降低分类器阈值（当前为0.75）")
    conn.close()
    exit(0)

cursor.execute('SELECT COUNT(DISTINCT opinion_id) FROM opinion_mentions')
unique_opinions = cursor.fetchone()[0]
print(f"不同观点数: {unique_opinions:,} 个")

cursor.execute('SELECT COUNT(DISTINCT paper_id) FROM opinion_mentions')
unique_papers = cursor.fetchone()[0]
print(f"不同论文数: {unique_papers:,} 篇")

cursor.execute('SELECT MIN(year), MAX(year) FROM opinion_mentions WHERE year IS NOT NULL')
year_range = cursor.fetchone()
if year_range[0] is not None:
    print(f"年份范围: {year_range[0]} - {year_range[1]}")

# 核心观点统计
cursor.execute('SELECT COUNT(*) FROM opinion_mentions WHERE is_core_opinion = 1')
core_mentions = cursor.fetchone()[0]
print(f"核心观点提及数: {core_mentions:,} 条")

cursor.execute('SELECT COUNT(DISTINCT opinion_id) FROM opinion_mentions WHERE is_core_opinion = 1')
core_opinions = cursor.fetchone()[0]
print(f"核心观点数: {core_opinions:,} 个")

# 按年份统计
print("\n【各年份统计（最近10年）】")
cursor.execute("""
    SELECT year, 
           COUNT(*) as mention_count,
           COUNT(DISTINCT opinion_id) as unique_opinions,
           COUNT(DISTINCT paper_id) as unique_papers,
           SUM(CASE WHEN is_core_opinion = 1 THEN 1 ELSE 0 END) as core_mentions
    FROM opinion_mentions
    WHERE year IS NOT NULL
    GROUP BY year
    ORDER BY year DESC
    LIMIT 10
""")
print(f"{'年份':<8} {'提及数':>15} {'观点数':>12} {'论文数':>12} {'核心观点':>12}")
print("-" * 70)
for row in cursor.fetchall():
    year, mention_count, unique_opinions, unique_papers, core_mentions = row
    print(f"{year:<8} {mention_count:>15,} {unique_opinions:>12,} {unique_papers:>12,} {core_mentions:>12,}")

# 最常提及的观点（Top 20）
print("\n【最常提及的观点 Top 20】")
cursor.execute("""
    SELECT opinion_id, 
           canonical_label,
           COUNT(*) as mention_count,
           COUNT(DISTINCT paper_id) as paper_count,
           MIN(year) as first_year,
           MAX(year) as last_year,
           SUM(CASE WHEN is_core_opinion = 1 THEN 1 ELSE 0 END) as core_count
    FROM opinion_mentions
    GROUP BY opinion_id, canonical_label
    ORDER BY mention_count DESC
    LIMIT 20
""")
print(f"{'观点ID':<10} {'观点文本':<40} {'提及数':>12} {'论文数':>12} {'核心数':>10} {'年份范围':>15}")
print("-" * 110)
for row in cursor.fetchall():
    opinion_id, canonical_label, mention_count, paper_count, first_year, last_year, core_count = row
    year_range_str = f"{first_year}-{last_year}" if first_year and last_year else "N/A"
    label_short = canonical_label[:38] + ".." if len(canonical_label) > 40 else canonical_label
    print(f"{opinion_id:<10} {label_short:<40} {mention_count:>12,} {paper_count:>12,} {core_count:>10,} {year_range_str:>15}")

# 核心观点统计（Top 20）
print("\n【核心观点 Top 20（按提及数）】")
cursor.execute("""
    SELECT opinion_id, 
           canonical_label,
           COUNT(*) as mention_count,
           COUNT(DISTINCT paper_id) as paper_count,
           MIN(year) as first_year,
           MAX(year) as last_year
    FROM opinion_mentions
    WHERE is_core_opinion = 1
    GROUP BY opinion_id, canonical_label
    ORDER BY mention_count DESC
    LIMIT 20
""")
print(f"{'观点ID':<10} {'观点文本':<40} {'提及数':>12} {'论文数':>12} {'年份范围':>15}")
print("-" * 100)
for row in cursor.fetchall():
    opinion_id, canonical_label, mention_count, paper_count, first_year, last_year = row
    year_range_str = f"{first_year}-{last_year}" if first_year and last_year else "N/A"
    label_short = canonical_label[:38] + ".." if len(canonical_label) > 40 else canonical_label
    print(f"{opinion_id:<10} {label_short:<40} {mention_count:>12,} {paper_count:>12,} {year_range_str:>15}")

# 按年份查看示例数据（显示最近有数据的年份）
print("\n【按年份查看示例数据】")
cursor.execute("""
    SELECT MAX(year) as max_year FROM opinion_mentions WHERE year IS NOT NULL
""")
max_year_result = cursor.fetchone()
if max_year_result and max_year_result[0]:
    max_year = max_year_result[0]
    print(f"\n【{max_year}年提及数据示例（前20条，包含核心观点标记）】")
    cursor.execute("""
        SELECT opinion_id, canonical_label, alias, paper_id, year, is_core_opinion
        FROM opinion_mentions
        WHERE year = ?
        ORDER BY is_core_opinion DESC, opinion_id
        LIMIT 20
    """, (max_year,))
    print(f"{'观点ID':<10} {'观点文本':<30} {'别名':<30} {'核心':<6} {'论文ID':<20}")
    print("-" * 100)
    for row in cursor.fetchall():
        opinion_id, canonical_label, alias, paper_id, year, is_core = row
        label_short = canonical_label[:28] + ".." if len(canonical_label) > 30 else canonical_label
        alias_short = alias[:28] + ".." if len(alias) > 30 else alias
        paper_id_short = paper_id[:18] + ".." if len(paper_id) > 20 else paper_id
        core_mark = "✓" if is_core else ""
        print(f"{opinion_id:<10} {label_short:<30} {alias_short:<30} {core_mark:<6} {paper_id_short:<20}")
else:
    print("  无年份数据")

# 观点首次出现年份统计
print("\n【观点首次出现年份分布（最近10年）】")
cursor.execute("""
    SELECT first_seen_year, 
           COUNT(DISTINCT opinion_id) as new_opinions,
           COUNT(DISTINCT CASE WHEN is_core_opinion = 1 THEN opinion_id END) as new_core_opinions
    FROM opinion_mentions
    WHERE first_seen_year IS NOT NULL
    GROUP BY first_seen_year
    ORDER BY first_seen_year DESC
    LIMIT 10
""")
print(f"{'年份':<8} {'新观点数':>15} {'新核心观点数':>18}")
print("-" * 45)
for row in cursor.fetchall():
    year, new_opinions, new_core_opinions = row
    new_core_opinions = new_core_opinions if new_core_opinions else 0
    print(f"{year:<8} {new_opinions:>15,} {new_core_opinions:>18,}")

# 核心观点按年份分布
print("\n【核心观点按年份分布（最近10年）】")
cursor.execute("""
    SELECT year, 
           COUNT(*) as core_mentions,
           COUNT(DISTINCT opinion_id) as core_opinions,
           COUNT(DISTINCT paper_id) as papers_with_core
    FROM opinion_mentions
    WHERE year IS NOT NULL AND is_core_opinion = 1
    GROUP BY year
    ORDER BY year DESC
    LIMIT 10
""")
print(f"{'年份':<8} {'核心提及数':>15} {'核心观点数':>15} {'含核心论文数':>18}")
print("-" * 60)
for row in cursor.fetchall():
    year, core_mentions, core_opinions, papers_with_core = row
    print(f"{year:<8} {core_mentions:>15,} {core_opinions:>15,} {papers_with_core:>18,}")

conn.close()
print("\n查询完成！")

