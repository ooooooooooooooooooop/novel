# -*- coding: utf-8 -*-
"""
论文查询工具

通过 paper_id 查询论文的完整信息，包括标题、创新度、影响力、分类等。

用法:
    python scripts/query/query_paper.py <paper_id>                    # 查询单篇论文
    python scripts/query/query_paper.py --title "关键词"              # 按标题搜索
    python scripts/query/query_paper.py --role Pioneer --year 2020    # 按分类和年份筛选
    python scripts/query/query_paper.py --top 10 --year 2020          # 查询某年 Top N
    python scripts/query/query_paper.py --export 2020                 # 导出某年带标题的数据
"""

import os
import sys
import json
import sqlite3
import argparse
from pathlib import Path
from typing import Optional, List, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import load_project_config, get_paths, get_runtime, get_years

# 配置路径
_cfg = load_project_config()
_paths = get_paths(_cfg)
_runtime = get_runtime(_cfg)
CONFIG = {
    'db_path': _paths['rpu_db_path'],
    'signals_dir': _paths['paper_signals_output_dir'],
    'years': list(get_years(_runtime)),
}


def apply_config(config_path: str = None):
    cfg = load_project_config(config_path)
    paths = get_paths(cfg)
    runtime = get_runtime(cfg)
    CONFIG.update({
        'db_path': paths['rpu_db_path'],
        'signals_dir': paths['paper_signals_output_dir'],
        'years': list(get_years(runtime)),
    })


class PaperQuery:
    """论文查询类"""

    def __init__(self):
        self.conn = None
        self.title_cache = {}
        self.signals_cache = {}

    def connect(self):
        """连接数据库"""
        if not os.path.exists(CONFIG['db_path']):
            print(f"错误: 数据库不存在 - {CONFIG['db_path']}")
            sys.exit(1)
        self.conn = sqlite3.connect(CONFIG['db_path'])
        self.conn.row_factory = sqlite3.Row

    def close(self):
        """关闭连接"""
        if self.conn:
            self.conn.close()

    def get_paper_title(self, paper_id: str) -> Optional[Dict]:
        """获取论文标题信息"""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT paper_id, title, pub_year FROM papers WHERE paper_id = ?",
            (paper_id,)
        )
        row = cursor.fetchone()
        if row:
            return {
                'paper_id': row['paper_id'],
                'title': row['title'],
                'pub_year': row['pub_year']
            }
        return None

    def search_by_title(self, keyword: str, limit: int = 20) -> List[Dict]:
        """按标题关键词搜索"""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT paper_id, title, pub_year FROM papers WHERE title LIKE ? LIMIT ?",
            (f'%{keyword}%', limit)
        )
        return [dict(row) for row in cursor.fetchall()]

    def load_signals(self, year: int) -> Dict[str, Dict]:
        """加载某年的信号数据"""
        if year in self.signals_cache:
            return self.signals_cache[year]

        path = os.path.join(CONFIG['signals_dir'], f'paper_signals_{year}.jsonl')
        if not os.path.exists(path):
            return {}

        signals = {}
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line.strip())
                    signals[d['paper_id']] = d
                except:
                    continue

        self.signals_cache[year] = signals
        return signals

    def get_paper_signals(self, paper_id: str, year: int = None) -> Optional[Dict]:
        """获取论文的信号数据"""
        if year:
            signals = self.load_signals(year)
            return signals.get(paper_id)

        # 如果未指定年份，遍历所有年份
        for y in CONFIG['years']:
            signals = self.load_signals(y)
            if paper_id in signals:
                return signals[paper_id]
        return None

    def query_paper(self, paper_id: str) -> Optional[Dict]:
        """查询论文完整信息"""
        # 获取标题
        title_info = self.get_paper_title(paper_id)
        if not title_info:
            return None

        # 获取信号
        signals = self.get_paper_signals(paper_id, title_info['pub_year'])

        result = {
            'paper_id': paper_id,
            'title': title_info['title'],
            'pub_year': title_info['pub_year'],
        }

        if signals:
            result.update({
                'innovation_score': signals.get('innovation_score', 0),
                'impact_score': signals.get('impact_score', 0),
                'role': signals.get('role', 'Unknown'),
                'paper_type': signals.get('paper_type', 'unknown'),
                'diffusion_norm': signals.get('diffusion_norm', 0),
                'persistence_gate': signals.get('persistence_gate', 0),
            })

        return result

    def query_by_role(self, role: str, year: int, limit: int = 10) -> List[Dict]:
        """按分类和年份查询"""
        signals = self.load_signals(year)
        results = []

        for paper_id, data in signals.items():
            if data.get('role') == role:
                title_info = self.get_paper_title(paper_id)
                results.append({
                    'paper_id': paper_id,
                    'title': title_info['title'] if title_info else '',
                    'pub_year': year,
                    'innovation_score': data.get('innovation_score', 0),
                    'impact_score': data.get('impact_score', 0),
                    'role': role,
                })
                if len(results) >= limit:
                    break

        return results

    def query_top_papers(self, year: int, n: int = 10, sort_by: str = 'innovation') -> List[Dict]:
        """查询某年 Top N 论文"""
        signals = self.load_signals(year)

        # 排序
        sort_key = 'innovation_score' if sort_by == 'innovation' else 'impact_score'
        sorted_papers = sorted(
            signals.values(),
            key=lambda x: x.get(sort_key, 0),
            reverse=True
        )[:n]

        results = []
        for data in sorted_papers:
            paper_id = data['paper_id']
            title_info = self.get_paper_title(paper_id)
            results.append({
                'paper_id': paper_id,
                'title': title_info['title'] if title_info else '',
                'pub_year': year,
                'innovation_score': data.get('innovation_score', 0),
                'impact_score': data.get('impact_score', 0),
                'role': data.get('role', 'Unknown'),
            })

        return results

    def export_with_title(self, year: int, output_path: str = None):
        """导出带标题的数据"""
        if not output_path:
            output_path = os.path.join(CONFIG['signals_dir'], f'paper_signals_with_title_{year}.jsonl')

        signals = self.load_signals(year)
        if not signals:
            print(f"错误: {year} 年数据不存在")
            return

        print(f"正在导出 {year} 年数据 ({len(signals):,} 篇)...")

        # 批量加载标题
        cursor = self.conn.cursor()
        cursor.execute("SELECT paper_id, title FROM papers WHERE pub_year = ?", (year,))
        title_map = {row[0]: row[1] for row in cursor.fetchall()}

        count = 0
        with open(output_path, 'w', encoding='utf-8') as f:
            for paper_id, data in signals.items():
                data['title'] = title_map.get(paper_id, '')
                f.write(json.dumps(data, ensure_ascii=False) + '\n')
                count += 1

        print(f"已导出: {output_path}")
        print(f"共 {count:,} 篇论文")


def print_paper(paper: Dict):
    """格式化打印论文信息"""
    print("=" * 70)
    print(f"Paper ID: {paper['paper_id']}")
    print(f"标题: {paper.get('title', 'N/A')}")
    print(f"年份: {paper.get('pub_year', 'N/A')}")
    if 'role' in paper:
        role_cn = {
            'Pioneer': '先驱者', 'Ahead-of-time': '超前者',
            'Diffuser': '传播者', 'Routine': '常规者'
        }
        print(f"分类: {role_cn.get(paper['role'], paper['role'])}")
        print(f"创新度: {paper.get('innovation_score', 0):.2f}")
        print(f"影响力: {paper.get('impact_score', 0):.2f}")
        if 'paper_type' in paper:
            print(f"论文类型: {paper['paper_type']}")
    print("=" * 70)


def print_papers_table(papers: List[Dict], title: str = "查询结果"):
    """表格形式打印论文列表"""
    if not papers:
        print("未找到结果")
        return

    print(f"\n{title} ({len(papers)} 条)")
    print("=" * 100)
    print(f"{'序号':<4} {'分类':<8} {'创新度':>8} {'影响力':>8} {'标题':<60}")
    print("-" * 100)

    role_cn = {
        'Pioneer': '先驱者', 'Ahead-of-time': '超前者',
        'Diffuser': '传播者', 'Routine': '常规者'
    }

    for i, p in enumerate(papers, 1):
        role = role_cn.get(p.get('role', ''), p.get('role', 'N/A'))
        title = p.get('title', '')[:55] + '...' if len(p.get('title', '')) > 55 else p.get('title', '')
        print(f"{i:<4} {role:<8} {p.get('innovation_score', 0):>8.1f} {p.get('impact_score', 0):>8.1f} {title}")

    print("=" * 100)


def main():
    parser = argparse.ArgumentParser(
        description='论文查询工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/query/query_paper.py 000003b332a16d040d5350f7b9d80256    # 查询单篇
  python scripts/query/query_paper.py --title "machine learning"          # 按标题搜索
  python scripts/query/query_paper.py --role Pioneer --year 2020          # 查询先驱者
  python scripts/query/query_paper.py --top 10 --year 2020                # Top 10 创新度
  python scripts/query/query_paper.py --top 10 --year 2020 --sort impact  # Top 10 影响力
  python scripts/query/query_paper.py --export 2020                       # 导出带标题数据
        """
    )

    parser.add_argument('paper_id', nargs='?', help='论文 ID')
    parser.add_argument('--title', '-t', help='按标题关键词搜索')
    parser.add_argument('--role', '-r', choices=['Pioneer', 'Ahead-of-time', 'Diffuser', 'Routine'],
                        help='按分类筛选')
    parser.add_argument('--year', '-y', type=int, help='指定年份')
    parser.add_argument('--top', type=int, help='查询 Top N 论文')
    parser.add_argument('--sort', choices=['innovation', 'impact'], default='innovation',
                        help='排序方式 (默认: innovation)')
    parser.add_argument('--limit', '-n', type=int, default=20, help='结果数量限制 (默认: 20)')
    parser.add_argument('--export', type=int, metavar='YEAR', help='导出某年带标题的数据')
    parser.add_argument('--config', type=str, default=None, help='配置文件路径（JSON）')

    args = parser.parse_args()
    apply_config(args.config)

    # 初始化查询器
    query = PaperQuery()
    query.connect()

    try:
        # 导出模式
        if args.export:
            query.export_with_title(args.export)
            return

        # 查询单篇论文
        if args.paper_id:
            result = query.query_paper(args.paper_id)
            if result:
                print_paper(result)
            else:
                print(f"未找到论文: {args.paper_id}")
            return

        # 按标题搜索
        if args.title:
            results = query.search_by_title(args.title, args.limit)
            if results:
                # 补充信号数据
                for r in results:
                    signals = query.get_paper_signals(r['paper_id'], r['pub_year'])
                    if signals:
                        r.update({
                            'innovation_score': signals.get('innovation_score', 0),
                            'impact_score': signals.get('impact_score', 0),
                            'role': signals.get('role', 'Unknown'),
                        })
                print_papers_table(results, f"标题包含 '{args.title}' 的论文")
            else:
                print(f"未找到标题包含 '{args.title}' 的论文")
            return

        # 按分类查询
        if args.role:
            if not args.year:
                print("错误: 按分类查询需要指定 --year")
                return
            results = query.query_by_role(args.role, args.year, args.limit)
            role_cn = {'Pioneer': '先驱者', 'Ahead-of-time': '超前者',
                       'Diffuser': '传播者', 'Routine': '常规者'}
            print_papers_table(results, f"{args.year} 年 {role_cn[args.role]}")
            return

        # Top N 查询
        if args.top:
            if not args.year:
                print("错误: Top N 查询需要指定 --year")
                return
            results = query.query_top_papers(args.year, args.top, args.sort)
            sort_cn = '创新度' if args.sort == 'innovation' else '影响力'
            print_papers_table(results, f"{args.year} 年 Top {args.top} ({sort_cn})")
            return

        # 无参数时显示帮助
        parser.print_help()

    finally:
        query.close()


if __name__ == "__main__":
    main()

