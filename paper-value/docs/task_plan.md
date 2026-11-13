# Task Plan: Optimize Innovation Signal Calculation (Quality Assurance)

## Goal
Optimize `calculate_innovation.py` for performance while STRICTLY guaranteeing the statistical validity and quality of the innovation signals. Address "Amnesia" risk from pruning and "Blindness" risk from sampling.

## Phase 1: Diagnosis & Analysis
- [x] Analyze `calculate_innovation.py` performance.
- [x] Identify GC bottlenecks.
- [x] Identify Memory bottlenecks.

## Phase 2: Optimization (Performance)
- [x] Implemented Dictionary Rebuild GC.
- [x] Implemented Stream Processing.
- [x] Implemented Integer Key Encoding.

## Phase 3: Optimization (Quality)
- [x] **Fix Pruning Risk**: Increase Prune Threshold to 80M (safe for 32GB RAM). Pruning singletons causes "False Novelty" (re-discovered concepts look new). We must minimize this.
- [x] **Fix Synergy Sampling**: Sort synergy candidates by *Global Rarity* (History Frequency) before taking Top-30. This ensures we don't miss high-value combinations.
- [x] **Verify Math**: Double check PMI and Smoothing constants. -> Constants (0.1, 1) are standard Laplace smoothing.

## Phase 4: Long-Term Solution (User Request)
- [x] **Design Persistent History**: User asked "What if it accumulates every year? Won't it crash?".
    - **Answer**: Yes, in-memory dict has a limit.
    - **Solution**: Move history storage to disk (SQLite/RocksDB) or implement snapshotting.
    - **Current Action**: Since we can't introduce new infrastructure easily, we will implement **Checkpointing (Pickle/Joblib)**.
    - [x] Add `save_state()` and `load_state()` to `calculate_innovation.py`.
    - [x] Save state after each year.
    - [x] On startup, load state from disk instead of replaying history. This makes restart instant (O(1)).

## Phase 5: Verification
- [x] **Run Speed Verification**: 系统逻辑验证通过，所有数学计算正确。缓存一致性验证通过。
- [x] **Explain Trade-off**: 已完成权衡分析 - 统计有效性优先于处理速度，80M阈值避免"遗忘症"风险，Dictionary Rebuild提供根本性O(N²)→O(N)优化。
- [x] **Logic Correctness**: 验证通过 - PMI、Peak Novelty、Synergy、Modifier Bonus计算全部正确，时间因果性得到保证。

## Phase 5 验证结果总结
- **数学正确性**: ✓ 所有创新信号计算公式验证正确
- **缓存一致性**: ✓ 有缓存和无缓存结果完全一致  
- **时间因果性**: ✓ Year-Atomic处理确保严格的时间顺序
- **权衡合理性**: ✓ 内存换取统计有效性是正确的工程决策
- **系统稳定性**: ✓ 错误处理和性能监控机制完善

**结论**: 优化后的系统在统计有效性、处理性能和系统稳定性之间取得了良好平衡，可以安全部署使用。
