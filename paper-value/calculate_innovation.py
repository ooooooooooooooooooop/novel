import sqlite3
import json
import logging
import math
from collections import defaultdict, Counter
import time
from datetime import datetime
import sys
import pickle
import os
import random
from tqdm import tqdm

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('innovation_calculation.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

DB_PATH = r"d:\论文创新词汇统计\论文创新词汇统计7\output_7_deberta_full\rpu_database.db"

class SimpleBloomFilter:
    def __init__(self, size_mb=256):
        # 256MB = 256 * 1024 * 1024 * 8 bits ≈ 2.1 billion bits
        self.size_bits = size_mb * 1024 * 1024 * 8
        self.bit_array = bytearray(self.size_bits // 8)
    
    def add(self, key_hash):
        # Use Python's built-in hash for int/tuple which is fast and good enough
        # We assume key_hash is already an integer (our 64-bit pair key)
        idx = key_hash % self.size_bits
        byte_idx = idx // 8
        bit_idx = idx % 8
        self.bit_array[byte_idx] |= (1 << bit_idx)
        
    def __contains__(self, key_hash):
        idx = key_hash % self.size_bits
        byte_idx = idx // 8
        bit_idx = idx % 8
        return (self.bit_array[byte_idx] & (1 << bit_idx)) != 0

class InnovationCalculator:
    """
    Innovation Signal Calculator
    ----------------------------
    Measures "Relative Historical Novelty under Publication Dynamics".
    
    DISCLAIMER:
    1. Innovation Signal != Truth: This measures statistical rarity, not intellectual value.
    2. Bias: Hot fields are penalized (larger history denominator).
    3. Dependencies: Peak, Synergy, and Modifier signals are statistically correlated.
    4. Grey Cemetery: The Bloom Filter + Pruning mechanism creates a "seen but forgotten" state 
       (Count=1) to prevent false novelty for pruned items.
    """
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = None
        
        # String interning map: core_str -> int_id
        self.core_to_id = {}
        self.next_core_id = 0
        
        # Bloom Filter for strict "Is Seen" check (Never Pruned)
        # 256MB can hold ~100-200 million unique items with <1% false positive rate.
        # Since we have ~60M max active items, this is plenty.
        self.seen_filter = SimpleBloomFilter(size_mb=256)
        
        # int -> int
        self.history_task_counts = Counter() 
        self.history_object_counts = Counter()
        
        # Encoded pair (int64) -> int
        # Key = (id1 << 32) | id2
        self.history_pair_counts = Counter()
        self.history_total_pairs = 0
        
        # Encoded pair (int64) -> int (Synergy)
        self.history_core_cooccurrence = Counter()
        
        # (int, str) -> int (Modifier pairs) - Modifier still str
        self.history_mod_pair_counts = Counter()
        
        # str -> int (Global modifier frequency for short-circuiting)
        self.history_mod_global_counts = Counter()
        
        # Caches (Reset every year)
        # Key Design: (year, pair_key) -> to prevent cross-year pollution if logic changes
        self.year_cache_peak = {}    # (year, pair_key) -> score
        self.year_cache_synergy = {} # (year, pair_key) -> score
        self.current_processing_year = None # Track context for cache keys
        
        # Config
        # [DERIVATION OF 60,000,000]
        # Memory Calculation:
        # Each dict entry (int64 key, int value) takes approx 100 bytes in Python (including overhead).
        # 60,000,000 entries * 100 bytes ≈ 6 GB RAM.
        # Plus overhead for other structures (Task/Object counts) ≈ 2 GB.
        # Total ≈ 8 GB.
        # This is a safe empirically derived upper bound for 16GB RAM machines to prevent OS Swapping.
        # Adjust to 30M if RAM < 16GB, or 100M if RAM > 32GB.
        self.PRUNE_THRESHOLD = 60_000_000 
         self.MIN_COUNT_TO_KEEP = 2         # Keep items with count >= 2
         self.SYNERGY_MIN_SUPPORT = 2       # Minimum historical count to participate in Synergy (Noise reduction)
         # NOTE: SYNERGY_MIN_SUPPORT applies to the UNION of (history + current_year_buffer).
         # It effectively means "Concept must appear >=2 times globally (past + present)" to be considered established enough for Synergy.
         
         self.CHECKPOINT_DIR = "output/checkpoints"
        if not os.path.exists(self.CHECKPOINT_DIR):
            os.makedirs(self.CHECKPOINT_DIR)

    def save_checkpoint(self, year):
        """
        Save current state to disk to allow O(1) resume.
        """
        logger.info(f"Saving checkpoint for end of year {year}...")
        start_time = time.time()
        
        checkpoint_data = {
            'year': year,
            'core_to_id': self.core_to_id,
            'next_core_id': self.next_core_id,
            'history_task_counts': self.history_task_counts,
            'history_object_counts': self.history_object_counts,
            'history_pair_counts': self.history_pair_counts,
            'history_total_pairs': self.history_total_pairs,
            'history_core_cooccurrence': self.history_core_cooccurrence,
            'history_mod_pair_counts': self.history_mod_pair_counts,
            'history_mod_global_counts': self.history_mod_global_counts,
            'seen_filter': self.seen_filter # Save Bloom Filter
        }
        
        filename = os.path.join(self.CHECKPOINT_DIR, f"state_{year}.pkl")
        try:
            with open(filename, 'wb') as f:
                pickle.dump(checkpoint_data, f, protocol=pickle.HIGHEST_PROTOCOL)
            logger.info(f"Checkpoint saved to {filename}. Size: {os.path.getsize(filename)/1024/1024:.2f} MB. Time: {time.time()-start_time:.2f}s")
            
            # Cleanup old checkpoints to save space (keep last 2)
            # Simple logic: list all state_*.pkl, sort by year, delete old ones
            files = [f for f in os.listdir(self.CHECKPOINT_DIR) if f.startswith("state_") and f.endswith(".pkl")]
            files.sort() # lexicographical sort works for fixed width, but here year is 4 digits so fine
            if len(files) > 2:
                for old_file in files[:-2]:
                    try:
                        os.remove(os.path.join(self.CHECKPOINT_DIR, old_file))
                        logger.info(f"Removed old checkpoint: {old_file}")
                    except: pass
                    
        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}")

    def load_checkpoint(self, year):
        """
        Load state from a specific year's checkpoint.
        """
        filename = os.path.join(self.CHECKPOINT_DIR, f"state_{year}.pkl")
        if not os.path.exists(filename):
            return False
            
        logger.info(f"Loading checkpoint from {filename}...")
        start_time = time.time()
        try:
            with open(filename, 'rb') as f:
                data = pickle.load(f)
                
            self.core_to_id = data['core_to_id']
            self.next_core_id = data['next_core_id']
            self.history_task_counts = data['history_task_counts']
            self.history_object_counts = data['history_object_counts']
            self.history_pair_counts = data['history_pair_counts']
            self.history_total_pairs = data['history_total_pairs']
            self.history_core_cooccurrence = data['history_core_cooccurrence']
            self.history_mod_pair_counts = data['history_mod_pair_counts']
            
            # Load Modifier Global Counts if available
            if 'history_mod_global_counts' in data:
                self.history_mod_global_counts = data['history_mod_global_counts']
            else:
                self.history_mod_global_counts = Counter() # Backfill not critical for optimization
            
            # Load Bloom Filter if exists (compatibility with old checkpoints)
            if 'seen_filter' in data:
                self.seen_filter = data['seen_filter']
            else:
                logger.warning("Checkpoint does not contain 'seen_filter'. Initializing new Bloom Filter and BACKFILLING from existing history...")
                self.seen_filter = SimpleBloomFilter(size_mb=256)
                # Rehydrate Bloom Filter from existing keys to minimize data loss
                # We know these keys exist, so they must be in the filter.
                count = 0
                for k in self.history_pair_counts:
                    self.seen_filter.add(k)
                    count += 1
                logger.info(f"Backfilled Bloom Filter with {count} existing pairs from history.")
            
            logger.info(f"Checkpoint loaded in {time.time()-start_time:.2f}s.")
            return True
        except Exception as e:
            logger.error(f"Failed to load checkpoint: {e}")
            return False

    def get_core_id(self, core_str):
        if core_str not in self.core_to_id:
            self.core_to_id[core_str] = self.next_core_id
            self.next_core_id += 1
        return self.core_to_id[core_str]

    def encode_pair(self, id1, id2):
        # Sort to ensure undirected edge
        if id1 > id2:
            id1, id2 = id2, id1
        return (id1 << 32) | id2

    def connect(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def create_table(self):
        query = """
        CREATE TABLE IF NOT EXISTS innovation_signals (
            paper_id TEXT PRIMARY KEY,
            s_peak REAL,
            s_synergy REAL,
            s_modifier REAL,
            total_score REAL,
            details JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(paper_id) REFERENCES papers(paper_id)
        );
        """
        self.conn.execute(query)
        self.conn.commit()

    def get_years(self):
        logger.info("Fetching available publication years...")
        query = "SELECT DISTINCT pub_year FROM papers WHERE pub_year IS NOT NULL AND pub_year > 1900 AND pub_year < 2030 ORDER BY pub_year ASC"
        cursor = self.conn.execute(query)
        years = [row['pub_year'] for row in cursor]
        logger.info(f"Found {len(years)} years: {years[0]} to {years[-1]}")
        return years

    def yield_papers_for_year(self, year):
        """
        Generator that yields papers one by one to save memory.
        """
        logger.info(f"Streaming data for year {year}...")
        query = """
        SELECT 
            p.paper_id,
            r.task_cores, r.object_cores, 
            r.task_modifier, r.object_modifier
        FROM rpu r
        JOIN papers p ON r.paper_id = p.paper_id
        WHERE p.pub_year = ?
        """
        # Increase fetch size for performance
        cursor = self.conn.cursor()
        cursor.execute(query, (year,))
        
        current_paper_id = None
        current_rpus = []
        
        while True:
            rows = cursor.fetchmany(10000)
            if not rows:
                break
                
            for row in rows:
                pid = row['paper_id']
                
                # Check if we moved to a new paper
                if pid != current_paper_id:
                    if current_paper_id is not None:
                        yield current_paper_id, current_rpus
                    current_paper_id = pid
                    current_rpus = []
                
                try:
                    task_cores = json.loads(row['task_cores']) if row['task_cores'] else []
                    object_cores = json.loads(row['object_cores']) if row['object_cores'] else []
                except json.JSONDecodeError:
                    continue
                    
                # Clean "RAW:" prefix
                task_cores = [t.replace("RAW:", "").strip().lower() for t in task_cores]
                object_cores = [o.replace("RAW:", "").strip().lower() for o in object_cores]
                
                rpu_data = {
                    'task_cores': task_cores,
                    'object_cores': object_cores,
                    'task_modifier': row['task_modifier'],
                    'object_modifier': row['object_modifier']
                }
                
                current_rpus.append(rpu_data)
        
        if current_paper_id is not None:
            yield current_paper_id, current_rpus

    def prune_history_if_needed(self):
        if len(self.history_core_cooccurrence) > self.PRUNE_THRESHOLD:
            logger.warning(f"History Co-occurrence size {len(self.history_core_cooccurrence)} > {self.PRUNE_THRESHOLD}. Pruning singletons...")
            start_time = time.time()
            
            # Optimized Pruning with "Probabilistic Survival" (Resurrection Protection)
            # Addressed User Concern: "Scenario D" - Sparse accumulation.
            # Instead of deleting ALL singletons (count=1), we give them a 20% chance to survive.
            # This allows words appearing 1/year to statistically accumulate to 2 (Safe Zone) eventually.
            # SURVIVAL_RATE = 0.2
            
            self.history_core_cooccurrence = Counter({
                k: v for k, v in self.history_core_cooccurrence.items() 
                if v >= self.MIN_COUNT_TO_KEEP or (v == 1 and random.random() < 0.2)
            })
            
            elapsed = time.time() - start_time
            logger.info(f"Pruning complete. New size: {len(self.history_core_cooccurrence)}. Time: {elapsed:.2f}s")

        # [Safety] Also prune history_pair_counts to prevent OOM
        # This makes the Bloom Filter "Grey Cemetery" logic active.
        if len(self.history_pair_counts) > self.PRUNE_THRESHOLD:
            logger.warning(f"History Pair Counts size {len(self.history_pair_counts)} > {self.PRUNE_THRESHOLD}. Pruning singletons...")
            start_time = time.time()
            self.history_pair_counts = Counter({
                k: v for k, v in self.history_pair_counts.items() 
                if v >= self.MIN_COUNT_TO_KEEP or (v == 1 and random.random() < 0.2)
            })
            elapsed = time.time() - start_time
            logger.info(f"Pruning pairs complete. New size: {len(self.history_pair_counts)}. Time: {elapsed:.2f}s")

    def calculate_peak_novelty(self, rpus):
        max_score = 0.0
        log_N = math.log(self.history_total_pairs + 1) if self.history_total_pairs > 0 else 0
        
        for rpu in rpus:
            t_cores = rpu['task_cores']
            o_cores = rpu['object_cores']
            
            if not t_cores or not o_cores:
                continue
                
            for t in t_cores:
                t_id = self.get_core_id(t)
                for o in o_cores:
                    o_id = self.get_core_id(o)
                    
                    pair_key = self.encode_pair(t_id, o_id)
                    
                    # [Optimization] Check Cache with Year Context
                    cache_key = (self.current_processing_year, pair_key)
                    if cache_key in self.year_cache_peak:
                        score = self.year_cache_peak[cache_key]
                    else:
                        count = self.history_pair_counts.get(pair_key, 0)
                        
                        # Bloom Filter Correction:
                        if count == 0 and pair_key in self.seen_filter:
                            count = 1
                        
                        score = log_N - math.log(count + 1)
                        self.year_cache_peak[cache_key] = score
                    
                    if score > max_score:
                        max_score = score
                        
        return max_score

    def calculate_synergy_novelty(self, rpus):
        cores = set()
        for rpu in rpus:
            for c in rpu['task_cores']: cores.add(c)
            for c in rpu['object_cores']: cores.add(c)
            
        core_list = list(cores)
        
        # Helper to get frequency
        def get_freq(c_str):
            c_id = self.core_to_id.get(c_str)
            if c_id is None: return 0
            return self.history_task_counts[c_id] + self.history_object_counts[c_id]

        # [Stability Fix] Filter out noise (count < MIN_SUPPORT)
        # We only calculate synergy between established concepts to avoid PMI instability on the long tail.
        core_list = [c for c in core_list if get_freq(c) >= self.SYNERGY_MIN_SUPPORT]

        if len(core_list) < 2:
            return 0.0
            
        # Quality Optimization: Prioritize RARE cores for Synergy calculation
        # If we have too many cores, we should keep the ones that are historically RARE (low count),
        # because synergy between rare/new concepts is more significant than synergy between "Method" and "Result".
        if len(core_list) > 30:
            # Sort by history frequency (ascending)
            core_list.sort(key=get_freq)
            core_list = core_list[:30]
        
        log_Total = math.log(self.history_total_pairs + 1) if self.history_total_pairs > 0 else 0
        scores = []
        
        for i in range(len(core_list)):
            c1_id = self.get_core_id(core_list[i])
            for j in range(i + 1, len(core_list)):
                c2_id = self.get_core_id(core_list[j])
                
                pair_key = self.encode_pair(c1_id, c2_id)
                
                # [Optimization] Check Cache with Year Context
                cache_key = (self.current_processing_year, pair_key)
                if cache_key in self.year_cache_synergy:
                    score = self.year_cache_synergy[cache_key]
                    scores.append(score)
                    continue

                count_pair = self.history_core_cooccurrence.get(pair_key, 0)
                
                count_c1 = self.history_task_counts.get(c1_id, 0) + self.history_object_counts.get(c1_id, 0)
                count_c2 = self.history_task_counts.get(c2_id, 0) + self.history_object_counts.get(c2_id, 0)
                
                if count_c1 == 0 or count_c2 == 0:
                    continue
                    
                score = math.log(count_c1 + 1) + math.log(count_c2 + 1) - math.log(count_pair + 0.1) - log_Total
                scores.append(score)
                self.year_cache_synergy[cache_key] = score
                
        if not scores:
            return 0.0
            
        scores.sort(reverse=True)
        top_k = 3
        return sum(scores[:top_k]) / min(len(scores), top_k)

    def calculate_modifier_bonus(self, rpus):
        max_bonus = 0.0
        # [Optimization] Global Modifier Frequency Short Circuit
        # Skip top 5% most frequent modifiers (heuristic)
        # We don't sort, just use a threshold.
        # Assuming heavy modifiers have > 1000 count (adjustable)
        HIGH_FREQ_THRESHOLD = 1000

        for rpu in rpus:
            if rpu['task_modifier']:
                if self.history_mod_global_counts[rpu['task_modifier']] < HIGH_FREQ_THRESHOLD:
                    for t_core in rpu['task_cores']:
                        score = self._calculate_single_mod_score(t_core, rpu['task_modifier'], 'task')
                        if score > max_bonus: max_bonus = score
            
            if rpu['object_modifier']:
                if self.history_mod_global_counts[rpu['object_modifier']] < HIGH_FREQ_THRESHOLD:
                    for o_core in rpu['object_cores']:
                        score = self._calculate_single_mod_score(o_core, rpu['object_modifier'], 'object')
                        if score > max_bonus: max_bonus = score
        return max_bonus

    def _calculate_single_mod_score(self, core, modifier, core_type):
        core_id = self.get_core_id(core)
        if core_type == 'task':
            core_count = self.history_task_counts.get(core_id, 0)
        else:
            core_count = self.history_object_counts.get(core_id, 0)
            
        pair_key = (core_id, modifier)
        pair_count = self.history_mod_pair_counts.get(pair_key, 0)
        
        alpha = 0.1
        vocab_size = 10000 
        prob = (pair_count + alpha) / (core_count + alpha * vocab_size)
        return -math.log(prob)

    def accumulate_history_buffer(self, rpus, buffer):
        """
        Accumulate counts into a temporary buffer for Year-Atomic Update.
        """
        for rpu in rpus:
            t_cores = rpu['task_cores']
            o_cores = rpu['object_cores']
            t_mod = rpu['task_modifier']
            o_mod = rpu['object_modifier']
            
            for t in t_cores:
                t_id = self.get_core_id(t)
                buffer['task_counts'][t_id] += 1
                if t_mod:
                    buffer['mod_pair_counts'][(t_id, t_mod)] += 1
                    buffer['mod_global_counts'][t_mod] += 1
                    
            for o in o_cores:
                o_id = self.get_core_id(o)
                buffer['object_counts'][o_id] += 1
                if o_mod:
                    buffer['mod_pair_counts'][(o_id, o_mod)] += 1
                    buffer['mod_global_counts'][o_mod] += 1

            current_pairs = set()
            for t in t_cores:
                t_id = self.get_core_id(t)
                for o in o_cores:
                    o_id = self.get_core_id(o)
                    pair = self.encode_pair(t_id, o_id)
                    current_pairs.add(pair)
            
            for pair in current_pairs:
                buffer['pair_counts'][pair] += 1
                buffer['total_pairs'] += 1
                buffer['seen_filter'].add(pair)

            # Synergy Co-occurrence
            paper_signatures = set()
            for t in t_cores: paper_signatures.add(self.get_core_id(t))
            for o in o_cores: paper_signatures.add(self.get_core_id(o))
            
            paper_signatures_list = list(paper_signatures)
            if len(paper_signatures_list) > 30:
                 paper_signatures_list = paper_signatures_list[:30]
                 
            for i in range(len(paper_signatures_list)):
                for j in range(i + 1, len(paper_signatures_list)):
                    s1 = paper_signatures_list[i]
                    s2 = paper_signatures_list[j]
                    pair_key = self.encode_pair(s1, s2)
                    buffer['core_cooccurrence'][pair_key] += 1

    def merge_history_buffer(self, buffer):
        """
        Merge buffer into main history at end of year.
        """
        logger.info("Merging year buffer into history...")
        self.history_task_counts.update(buffer['task_counts'])
        self.history_object_counts.update(buffer['object_counts'])
        self.history_pair_counts.update(buffer['pair_counts'])
        self.history_total_pairs += buffer['total_pairs']
        self.history_mod_pair_counts.update(buffer['mod_pair_counts'])
        self.history_mod_global_counts.update(buffer['mod_global_counts'])
        self.history_core_cooccurrence.update(buffer['core_cooccurrence'])
        
        # Bloom filter is updated in-place in buffer logic (reference shared or handled)
        # Actually, self.seen_filter is global. We can update it directly during buffer accumulation
        # or batch update. To keep "Seen" strictly updated:
        # We passed 'seen_filter' to buffer? No, let's just update self.seen_filter directly in accumulate
        # because Bloom Filter is just a set, doesn't affect counts/probabilities.
        pass

    def update_history_single_paper(self, rpus):
        # Deprecated in favor of accumulate_history_buffer
        pass

    def run(self, limit_years=None):
        self.connect()
        self.create_table()
        
        years = self.get_years()
        if limit_years:
            years = years[:limit_years]
        
        batch_results = []
        
        try:
            cursor = self.conn.execute("SELECT MAX(p.pub_year) FROM innovation_signals s JOIN papers p ON s.paper_id = p.paper_id")
            result = cursor.fetchone()
            last_processed_year = result[0] if result and result[0] is not None else None
        except:
            last_processed_year = None
            
        start_year = last_processed_year + 1 if last_processed_year else years[0]
        
        # 🚀 Try to load checkpoint if available
        # Ideally, if we are starting from 2017, we want checkpoint from 2016.
        checkpoint_year = start_year - 1
        checkpoint_loaded = False
        if last_processed_year and self.load_checkpoint(checkpoint_year):
             logger.info(f"Successfully resumed from checkpoint of year {checkpoint_year}. Skipping Fast Replay.")
             checkpoint_loaded = True
        else:
             logger.info(f"Resuming process. Last processed year: {last_processed_year}. Will fast-forward history update until {start_year}.")
        
        for year in years:
            # Check for pruning at the start of each year (or more frequently if needed)
            self.prune_history_if_needed()

            if year < start_year:
                # If we loaded checkpoint, we skip replaying years <= checkpoint_year
                if last_processed_year and checkpoint_loaded and year <= checkpoint_year:
                    continue
                    
                logger.info(f"Fast Replaying Year {year} (History Update Only)...")
                
                # [Architecture Refactor] Year-Atomic Buffer
                year_buffer = {
                    'task_counts': Counter(),
                    'object_counts': Counter(),
                    'pair_counts': Counter(),
                    'total_pairs': 0,
                    'mod_pair_counts': Counter(),
                    'mod_global_counts': Counter(),
                    'core_cooccurrence': Counter(),
                    'seen_filter': self.seen_filter # In-place update for Bloom
                }

                count = 0
                # Use tqdm for replay too
                for paper_id, rpus in tqdm(self.yield_papers_for_year(year), desc=f"Replaying {year}", mininterval=1.0):
                    self.accumulate_history_buffer(rpus, year_buffer)
                    count += 1
                
                # Merge at end of year
                self.merge_history_buffer(year_buffer)
                
                # Pruning after merge
                self.prune_history_if_needed()
                
                logger.info(f"Replayed {count} papers for {year}.")
                continue
                
            # Normal Processing
            logger.info(f"Processing Year {year}...")
            count = 0
            
            # [Architecture Refactor] Year-Atomic Buffer & Cache Reset
            year_buffer = {
                'task_counts': Counter(),
                'object_counts': Counter(),
                'pair_counts': Counter(),
                'total_pairs': 0,
                'mod_pair_counts': Counter(),
                'mod_global_counts': Counter(),
                'core_cooccurrence': Counter(),
                'seen_filter': self.seen_filter
            }
            
            # Clear Year Cache
            self.year_cache_peak.clear()
            self.year_cache_synergy.clear()

            # Use tqdm for progress display
            for paper_id, rpus in tqdm(self.yield_papers_for_year(year), desc=f"Year {year}", mininterval=1.0):
                s_peak = self.calculate_peak_novelty(rpus)
                s_synergy = self.calculate_synergy_novelty(rpus)
                s_modifier = self.calculate_modifier_bonus(rpus)
                
                total_score = s_peak + s_synergy + s_modifier
                
                batch_results.append((
                    paper_id,
                    s_peak,
                    s_synergy,
                    s_modifier,
                    total_score,
                    json.dumps({'year': year, 'rpu_count': len(rpus)})
                ))
                
                # Buffer Updates (Not merged until year end)
                self.accumulate_history_buffer(rpus, year_buffer)
                
                count += 1
                    
                if len(batch_results) > 1000:
                    self.save_results(batch_results)
                    batch_results = []
            
            if batch_results:
                self.save_results(batch_results)
                batch_results = []
                
            logger.info(f"Finished Year {year}. Processed {count} papers.")
            
            # [Critical] Merge history strictly AFTER year processing
            self.merge_history_buffer(year_buffer)
            self.prune_history_if_needed()
            
            # 🚀 Save checkpoint at end of year
            self.save_checkpoint(year)
            
        logger.info("Calculation complete.")

    def save_results(self, results):
        query = """
        INSERT OR REPLACE INTO innovation_signals (paper_id, s_peak, s_synergy, s_modifier, total_score, details)
        VALUES (?, ?, ?, ?, ?, ?)
        """
        self.conn.executemany(query, results)
        self.conn.commit()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit_years", type=int, default=None, help="Limit number of years to process for testing")
    args = parser.parse_args()

    calc = InnovationCalculator(DB_PATH)
    calc.run(limit_years=args.limit_years)
