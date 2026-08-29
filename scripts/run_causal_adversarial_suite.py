"""S3（54 计划）长程因果防线对抗集可重跑脚本.

用法：.venv\\Scripts\\python.exe scripts/run_causal_adversarial_suite.py
输出 5 类攻击 × 正例/负控 的覆盖矩阵；exit 0 = 全过。
"""
from __future__ import annotations

import sys

from src.domain_layer.causal_adversarial_suite import ATTACK_CLASSES, run_suite


def main() -> int:
    report = run_suite()
    print("S3 长程因果防线对抗样本集（5 类攻击，可重跑）")
    print(f"样本总数: {report['total_cases']}，通过: {report['ok_cases']}")
    for cls in ATTACK_CLASSES:
        st = report["per_class"][cls]
        mark = "PASS" if st["ok"] else "FAIL"
        print(
            f"  [{mark}] {cls:<20} cases={st['cases']} "
            f"positive_detected={st['positive_detected']} "
            f"negative_clean={st['negative_clean']}"
        )
    print(f"SUITE: {'PASS' if report['suite_pass'] else 'FAIL'}")
    return 0 if report["suite_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
