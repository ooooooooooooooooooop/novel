import sqlite3
import json
import logging
import math
from collections import defaultdict, Counter
import sys
import os
import csv
import networkx as nx
from community import community_louvain

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('impact_calculation.log')
    ]
)
logger = logging.getLogger(__name__)

DB_PATH = r"d:\论文创新词汇统计\论文创新词汇统计7\output_7_deberta_full\rpu_database.db"

class ImpactCalculator:
    def __init__(self, db_path, csv_path=None):
        self.db_path = db_path
        self.csv_path = csv_path # Deprecated: Keywords are too noisy
        self.conn = None
        
        # Global Statistics
        self.core_counts = Counter()
        self.total_cores = 0
        self.core_domain_counts = defaultdict(Counter) # {core: {domain: count}}
        self.domain_totals = Counter()
        self.paper_domains = {} # Placeholder for compatibility
        
        # Graph-based Domain Analysis
        # We build a co-occurrence graph of Cores to discover latent domains.
        # Nodes: Cores
        # Edges: Co-occurrence in the same paper (weighted by frequency)
        self.core_graph = nx.Graph()
        self.core_community_map = {} # Core -> Community ID
        self.community_sizes = Counter() # Community ID -> Size (for Entropy normalization)
        
        # Cache for scores to avoid re-calculating for same core
        self.core_impact_cache = {}
        self.core_entropy_cache = {}

    def build_latent_domains(self):
        """
        Step 1: Build Core Co-occurrence Graph to discover Latent Domains.
        Instead of relying on noisy keywords, we define 'Domain' as a community of tightly connected Cores.
        """
        logger.info("Building Core Co-occurrence Graph...")
        
        # Pass 1: Build Graph Edges from RPU data
        query = "SELECT task_cores, object_cores FROM rpu"
        cursor = self.conn.execute(query)
        
        batch_size = 50000
        count = 0
        
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows: break
            
            for row in rows:
                try:
                    t = json.loads(row['task_cores']) if row['task_cores'] else []
                    o = json.loads(row['object_cores']) if row['object_cores'] else []
                except: continue
                
                # Clean and Normalize
                cores = [c.replace("RAW:", "").strip().lower() for c in t + o]
                unique_cores = list(set(cores))
                
                # Add nodes and edges
                for i in range(len(unique_cores)):
                    self.core_graph.add_node(unique_cores[i]) # Ensure node exists
                    for j in range(i + 1, len(unique_cores)):
                        u, v = unique_cores[i], unique_cores[j]
                        if self.core_graph.has_edge(u, v):
                            self.core_graph[u][v]['weight'] += 1
                        else:
                            self.core_graph.add_edge(u, v, weight=1)
                            
            count += len(rows)
            if count % 100000 == 0:
                logger.info(f"Processed {count} rows for graph building...")
                
        logger.info(f"Graph built: {self.core_graph.number_of_nodes()} nodes, {self.core_graph.number_of_edges()} edges.")
        
        # Step 2: Detect Communities (Latent Domains)
        logger.info("Detecting Latent Domains (Louvain Community Detection)...")
        if self.core_graph.number_of_nodes() > 0:
            # Louvain is fast and effective for large graphs
            self.core_community_map = community_louvain.best_partition(self.core_graph, weight='weight')
            
            # Statistics
            communities = list(self.core_community_map.values())
            self.community_sizes = Counter(communities)
            logger.info(f"Detected {len(self.community_sizes)} latent domains.")
            
            # Optional: Print top communities
            # top_comms = self.community_sizes.most_common(5)
            # logger.info(f"Top 5 domains by size: {top_comms}")
        else:
            logger.warning("Graph is empty! No domains detected.")

    def load_metadata(self):
        # Deprecated method
        pass

    def connect(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def create_table(self):
        query = """
        CREATE TABLE IF NOT EXISTS impact_signals (
            paper_id TEXT PRIMARY KEY,
            s_coverage REAL,
            s_entropy REAL,
            details JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(paper_id) REFERENCES papers(paper_id)
        );
        """
        self.conn.execute(query)
        self.conn.commit()

    def build_global_stats(self):
        """
        Scan the entire RPU table to build global frequency maps.
        This is a heavy operation, effectively building the 'Future Graph' 
        (if we consider the dataset as the whole world).
        """
        logger.info("Building global statistics from RPU database...")
        
        # We need to scan all RPUs.
        # To avoid OOM, we stream.
        query = "SELECT paper_id, task_cores, object_cores FROM rpu"
        cursor = self.conn.execute(query)
        
        batch_size = 10000
        count = 0
        
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
                
            for row in rows:
                try:
                    t_cores = json.loads(row['task_cores']) if row['task_cores'] else []
                    o_cores = json.loads(row['object_cores']) if row['object_cores'] else []
                except json.JSONDecodeError:
                    continue
                
                # Normalize
                all_cores = [c.replace("RAW:", "").strip().lower() for c in t_cores + o_cores]
                
                # Get domains for this paper
                # Note: 'row' here is from RPU table. We need paper_id.
                paper_id = row['paper_id']
                domains = self.paper_domains.get(paper_id, [])
                
                for core in all_cores:
                    self.core_counts[core] += 1
                    self.total_cores += 1
                    
                    # Update Domain Counts
                    # We strictly use 'keywords' from CSV as the domain proxy.
                    # The theoretical 'category' field from design doc does not exist in actual data.
                    for domain in domains:
                        self.core_domain_counts[core][domain] += 1
                        self.domain_totals[domain] += 1
            
            count += len(rows)
            if count % 100000 == 0:
                logger.info(f"Processed {count} rows...")
                
        logger.info(f"Global stats built. Total Cores occurrences: {self.total_cores}. Unique Cores: {len(self.core_counts)}")

    def calculate_core_coverage(self, core):
        """
        S_coverage(c) = log(Count(c))
        """
        count = self.core_counts.get(core, 0)
        if count == 0:
            return 0.0
        return math.log(count)

    def calculate_core_entropy(self, core):
        """
        H_domain(c) = - Sum P(d|c) log P(d|c)
        Where 'd' is the Latent Domain (Community ID) of the connected cores.
        
        Since a Core belongs to ONE community in hard partitioning, its own entropy is 0.
        BUT, we define Cross-Domain Entropy as: 
        "How much does this Core connect to OTHER domains?"
        
        We look at the neighbors of this Core in the graph.
        """
        if core not in self.core_graph:
            return 0.0
            
        # Get neighbors (Co-occurring Cores)
        neighbors = self.core_graph[core]
        if not neighbors:
            return 0.0
            
        # Count neighbor communities
        neighbor_domains = Counter()
        total_weight = 0
        
        for neighbor, attr in neighbors.items():
            weight = attr.get('weight', 1)
            domain = self.core_community_map.get(neighbor)
            if domain is not None:
                neighbor_domains[domain] += weight
                total_weight += weight
                
        if total_weight == 0:
            return 0.0
            
        # Calculate Entropy of Neighbor Domains
        entropy = 0.0
        for count in neighbor_domains.values():
            p = count / total_weight
            entropy -= p * math.log(p)
            
        # 🚀 Entropy Normalization (Correction based on Analysis Report)
        # Issue: Louvain community count (K) grows with graph size. 
        # Raw Entropy will naturally increase over time, causing Time Bias.
        # Fix: Normalize by log(K) to keep scale consistent [0, 1].
        
        num_communities = len(self.community_sizes)
        if num_communities > 1:
            max_entropy = math.log(num_communities)
            entropy = entropy / max_entropy
            
        return entropy

    def process_papers(self):
        logger.info("Calculating Impact Signals for all papers...")
        
        # Get all papers
        query = "SELECT paper_id, task_cores, object_cores FROM rpu"
        # Note: This iterates RPU rows. A paper might have multiple RPU rows (sentences).
        # We need to aggregate by paper_id.
        # Better strategy: Get list of paper_ids from papers table, then query RPUs?
        # Or just iterate RPU table and aggregate in memory (if it fits).
        # 40M papers * metadata might fit in memory? No.
        # We should iterate by paper_id.
        
        # Group by paper_id in SQL is expensive if no index on paper_id (there is one).
        # But fetching all RPUs for a paper requires random access or sorted access.
        # Best way: Iterate RPU table ordered by paper_id.
        
        cursor = self.conn.execute("SELECT paper_id, task_cores, object_cores FROM rpu ORDER BY paper_id")
        
        current_paper_id = None
        current_cores = set()
        
        batch_results = []
        
        count = 0
        
        while True:
            row = cursor.fetchone()
            if row is None:
                # Process last paper
                if current_paper_id:
                    self._process_single_paper(current_paper_id, current_cores, batch_results)
                break
            
            p_id = row['paper_id']
            
            if p_id != current_paper_id:
                if current_paper_id:
                    self._process_single_paper(current_paper_id, current_cores, batch_results)
                    count += 1
                    if count % 10000 == 0:
                        logger.info(f"Calculated {count} papers...")
                        if len(batch_results) > 1000:
                            self.save_results(batch_results)
                            batch_results = []
                
                current_paper_id = p_id
                current_cores = set()
            
            # Collect cores
            try:
                t = json.loads(row['task_cores']) if row['task_cores'] else []
                o = json.loads(row['object_cores']) if row['object_cores'] else []
                for c in t + o:
                    current_cores.add(c.replace("RAW:", "").strip().lower())
            except:
                pass
                
        if batch_results:
            self.save_results(batch_results)

    def _process_single_paper(self, paper_id, cores, batch_results):
        if not cores:
            return
            
        # Aggregation Logic
        # Impact of a paper = Max Impact of its Cores? Or Sum?
        # Usually "Max" defines the ceiling. If I use "Transformer", I have high coverage.
        # Let's use Max for now, or Average.
        # Design doc: "Impact Coverage... range".
        # Let's compute Max Coverage and Max Entropy.
        
        max_coverage = 0.0
        max_entropy = 0.0
        
        for core in cores:
            cov = self.calculate_core_coverage(core)
            ent = self.calculate_core_entropy(core)
            
            if cov > max_coverage: max_coverage = cov
            if ent > max_entropy: max_entropy = ent
            
        batch_results.append((
            paper_id,
            max_coverage,
            max_entropy,
            json.dumps({'core_count': len(cores)})
        ))

    def save_results(self, results):
        query = """
        INSERT OR REPLACE INTO impact_signals (paper_id, s_coverage, s_entropy, details)
        VALUES (?, ?, ?, ?)
        """
        self.conn.executemany(query, results)
        self.conn.commit()

    def run(self):
        self.connect()
        self.create_table()
        # Step 1: Build Graph & Detect Domains (Self-contained, no external metadata)
        self.build_latent_domains()
        # Step 2: Process Papers
        self.process_papers()
        logger.info("Impact Calculation Complete.")

if __name__ == "__main__":
    calc = ImpactCalculator(DB_PATH)
    calc.run()
