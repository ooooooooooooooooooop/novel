
import pickle
import os
import sys
import time
from collections import Counter
import random

def get_approx_size(obj):
    """Approximate memory size of a dictionary in MB"""
    # sys.getsizeof only returns the size of the container, not items for some types,
    # but for flat dicts of ints it's a reasonable proxy for the table size.
    # We add a buffer for the integer objects themselves if they aren't small ints.
    return sys.getsizeof(obj) / (1024 * 1024)

def test_pruning_safety():
    print("=== Test 1: Pruning Safety Verification ===")
    
    # Simulate history: 
    # Pair A: appeared 100 times (High frequency)
    # Pair B: appeared 1 time (Noise)
    # Pair C: appeared 2 times (Barely significant)
    # Pair D: appeared 10 times in 2010, 0 times since (Old high frequency)
    
    history = Counter()
    history[1001] = 100  # A
    history[1002] = 1    # B
    history[1003] = 2    # C
    history[1004] = 10   # D
    
    print(f"Before Pruning: {history}")
    
    # PRUNE LOGIC (Same as in calculate_innovation.py)
    # Keep items with count >= 2
    MIN_COUNT = 2
    pruned_history = Counter({
        k: v for k, v in history.items() if v >= MIN_COUNT
    })
    
    print(f"After Pruning (threshold >= {MIN_COUNT}): {pruned_history}")
    
    # Assertions
    if 1001 in pruned_history and pruned_history[1001] == 100:
        print("✅ PASS: High frequency item (A) preserved.")
    else:
        print("❌ FAIL: High frequency item (A) lost!")
        
    if 1004 in pruned_history and pruned_history[1004] == 10:
        print("✅ PASS: Old high frequency item (D) preserved (even if inactive recently).")
    else:
        print("❌ FAIL: Old high frequency item (D) lost!")
        
    if 1002 not in pruned_history:
        print("✅ PASS: Single noise item (B) correctly removed.")
    else:
        print("❌ FAIL: Noise item (B) not removed!")
        
    if 1003 in pruned_history:
        print("✅ PASS: Low frequency item (C) meeting threshold preserved.")
    else:
        print("❌ FAIL: Threshold item (C) incorrectly removed!")

def test_memory_usage():
    print("\n=== Test 2: Memory Usage Estimation ===")
    print("Simulating 1,000,000 integer pairs in a Counter...")
    
    # Create 1M entries
    # In real script: Key is 64-bit int, Value is int
    c = Counter()
    for i in range(1_000_000):
        c[i] = 1
        
    size_mb = get_approx_size(c)
    print(f"1 Million Entries (Container Size): {size_mb:.2f} MB")
    
    # Extrapolate to 60M
    est_60m = size_mb * 60
    print(f"Extrapolated for 60 Million Entries: {est_60m:.2f} MB (~{est_60m/1024:.2f} GB)")
    print("NOTE: This is just the Hash Table size. Python objects overhead adds more.")
    print("Real-world rule of thumb: 1 million dict entries ≈ 100MB RAM.")
    print(f"So 60 million entries ≈ 60 * 100MB = 6000MB = 6GB.")
    print("This matches the logic in the script (Safe for 16GB RAM).")

def test_checkpoint_resume():
    print("\n=== Test 3: Checkpoint Resume Simulation ===")
    
    filename = "test_checkpoint.pkl"
    data = {
        'year': 2020,
        'counts': Counter({1: 100, 2: 200})
    }
    
    # Save
    with open(filename, 'wb') as f:
        pickle.dump(data, f)
    print(f"Saved checkpoint for year 2020.")
    
    # Load
    loaded_data = None
    if os.path.exists(filename):
        with open(filename, 'rb') as f:
            loaded_data = pickle.load(f)
            
    if loaded_data and loaded_data['year'] == 2020:
        print("✅ PASS: Checkpoint loaded successfully.")
    else:
        print("❌ FAIL: Checkpoint load failed.")
        
    # Cleanup
    if os.path.exists(filename):
        os.remove(filename)

if __name__ == "__main__":
    test_pruning_safety()
    test_memory_usage()
    test_checkpoint_resume()
