import sqlite3
import os
from pathlib import Path

# 获取脚本所在目录
script_dir = os.path.dirname(os.path.abspath(__file__))
db_path = Path(script_dir) / "output_6_vocabulary_statistics" / "vocabulary.db"

if not db_path.exists():
    print("数据库文件不存在，程序可能尚未运行完成")
    exit(1)

conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

print("=" * 80)
print("词库统计结果预览")
print("=" * 80)

# 统计信息
print("\n【总体统计】")
cursor.execute('SELECT COUNT(DISTINCT word) FROM word_year_freq')
word_count = cursor.fetchone()[0]
print(f"不同单词数: {word_count:,}")

cursor.execute('SELECT COUNT(DISTINCT phrase) FROM phrase_year_freq')
phrase_count = cursor.fetchone()[0]
print(f"不同短语数: {phrase_count:,}")

cursor.execute('SELECT COUNT(*) FROM word_year_freq')
word_records = cursor.fetchone()[0]
print(f"单词-年份记录数: {word_records:,}")

cursor.execute('SELECT COUNT(*) FROM phrase_year_freq')
phrase_records = cursor.fetchone()[0]
print(f"短语-年份记录数: {phrase_records:,}")

cursor.execute('SELECT MIN(year), MAX(year) FROM word_year_freq WHERE year IS NOT NULL')
year_range = cursor.fetchone()
if year_range[0]:
    print(f"年份范围: {year_range[0]} - {year_range[1]}")

# 单词统计（按总频次排序）
print("\n【高频单词 Top 30】")
cursor.execute("""
    SELECT word, SUM(freq) as total_freq, COUNT(DISTINCT year) as year_count
    FROM word_year_freq
    GROUP BY word
    ORDER BY total_freq DESC
    LIMIT 30
""")
print(f"{'单词':<30} {'总频次':>12} {'出现年份数':>12}")
print("-" * 60)
for row in cursor.fetchall():
    print(f"{row[0]:<30} {row[1]:>12,} {row[2]:>12}")

# 短语统计（按总频次排序）
print("\n【高频短语 Top 30】")
cursor.execute("""
    SELECT phrase, SUM(freq) as total_freq, COUNT(DISTINCT year) as year_count
    FROM phrase_year_freq
    GROUP BY phrase
    ORDER BY total_freq DESC
    LIMIT 30
""")
print(f"{'短语':<40} {'总频次':>12} {'出现年份数':>12}")
print("-" * 70)
for row in cursor.fetchall():
    print(f"{row[0]:<40} {row[1]:>12,} {row[2]:>12}")

# 按年份查看
print("\n【各年份统计（最近10年）】")
cursor.execute("""
    SELECT 
        w.year,
        COUNT(DISTINCT w.word) as word_count,
        COUNT(DISTINCT p.phrase) as phrase_count,
        COALESCE(SUM(w.freq), 0) as total_word_freq,
        COALESCE(SUM(p.freq), 0) as total_phrase_freq
    FROM word_year_freq w
    LEFT JOIN phrase_year_freq p ON p.year = w.year
    WHERE w.year IS NOT NULL
    GROUP BY w.year
    ORDER BY w.year DESC
    LIMIT 10
""")
print(f"{'年份':<8} {'单词数':>12} {'短语数':>12} {'单词总频次':>15} {'短语总频次':>15}")
print("-" * 70)
for row in cursor.fetchall():
    year, word_count, phrase_count, word_freq, phrase_freq = row
    print(f"{year:<8} {word_count or 0:>12,} {phrase_count or 0:>12,} {word_freq or 0:>15,} {phrase_freq or 0:>15,}")

conn.close()
print("\n查询完成！")

