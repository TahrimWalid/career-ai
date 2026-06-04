#!/usr/bin/env python3
"""
Normalize location data by merging variants and cleaning duplicates
"""
import sqlite3
import re
from collections import defaultdict

def normalize_location(location):
    """
    Normalize a location string to canonical form.
    Handles variants: "Helsinki" == "HELSINKI" == "Helsinki, Finland"
    """
    if not location or location in ('Pending', 'Unknown', ''):
        return None
    
    # Remove anything after comma (e.g., "Helsinki, Finland" -> "Helsinki")
    location = location.split(',')[0].strip()
    
    # Title case standardization
    location = location.title()
    
    # Known city normalizations
    normalizations = {
        'Espoo': 'Espoo',
        'Helsinki': 'Helsinki',
        'Tampere': 'Tampere',
        'Turku': 'Turku',
        'Oulu': 'Oulu',
        'Jyväskylä': 'Jyväskylä',
        'Kuopio': 'Kuopio',
        'Lahti': 'Lahti',
        'Pori': 'Pori',
        'Vaasa': 'Vaasa',
        'Seinäjoki': 'Seinäjoki',
        'Lappeenranta': 'Lappeenranta',
        'Hämeenlinna': 'Hämeenlinna',
        'Kemi': 'Kemi',
        'Rovaniemi': 'Rovaniemi',
        'Kouvola': 'Kouvola',
        'Hyvinkää': 'Hyvinkää',
        'Raisio': 'Raisio',
        'Rauma': 'Rauma',
        'Uusikaupunki': 'Uusikaupunki',
        'Lohja': 'Lohja',
        'Porvoo': 'Porvoo',
        'Kajaani': 'Kajaani',
        'Kotka': 'Kotka',
        'Hamina': 'Hamina',
    }
    
    if location in normalizations:
        return normalizations[location]
    
    # If we don't recognize it, keep original (but title-cased)
    return location if location else None

def get_location_variants():
    """Get all current location variants from database"""
    conn = sqlite3.connect('duunitori_pipeline.db')
    c = conn.cursor()
    
    c.execute("""
    SELECT DISTINCT location
    FROM raw_postings
    WHERE extraction_status = 'done' 
    AND location IS NOT NULL 
    AND location NOT IN ('', 'Pending')
    ORDER BY location
    """)
    
    variants = [row[0] for row in c.fetchall()]
    conn.close()
    return variants

def analyze_locations():
    """Analyze current location coverage"""
    conn = sqlite3.connect('duunitori_pipeline.db')
    c = conn.cursor()
    
    # Count by location (before normalization)
    c.execute("""
    SELECT location, COUNT(*) as count
    FROM raw_postings
    WHERE extraction_status = 'done' 
    AND location IS NOT NULL 
    AND location NOT IN ('', 'Pending')
    GROUP BY location
    ORDER BY count DESC
    """)
    
    location_counts = {}
    for location, count in c.fetchall():
        location_counts[location] = count
    
    conn.close()
    return location_counts

def normalize_locations_in_db():
    """Apply normalization to database"""
    conn = sqlite3.connect('duunitori_pipeline.db')
    c = conn.cursor()
    
    # Get all unique locations
    c.execute("""
    SELECT DISTINCT location
    FROM raw_postings
    WHERE extraction_status = 'done' 
    AND location IS NOT NULL 
    AND location NOT IN ('', 'Pending')
    """)
    
    locations = [row[0] for row in c.fetchall()]
    
    print("=" * 70)
    print("LOCATION NORMALIZATION")
    print("=" * 70)
    print(f"Found {len(locations)} unique location values\n")
    
    # Build normalization map
    norm_map = {}
    for loc in sorted(locations):
        normalized = normalize_location(loc)
        if normalized and normalized != loc:
            norm_map[loc] = normalized
            print(f"  '{loc}' → '{normalized}'")
    
    if norm_map:
        print(f"\nApplying {len(norm_map)} normalizations...")
        for old_loc, new_loc in norm_map.items():
            c.execute("""
            UPDATE raw_postings 
            SET location = ? 
            WHERE location = ?
            """, (new_loc, old_loc))
        
        conn.commit()
        print("✓ Normalization complete!")
    else:
        print("No normalizations needed.")
    
    conn.close()

def report_location_distribution():
    """Report final location distribution"""
    conn = sqlite3.connect('duunitori_pipeline.db')
    c = conn.cursor()
    
    c.execute("""
    SELECT location, COUNT(*) as count
    FROM raw_postings
    WHERE extraction_status = 'done' 
    AND location IS NOT NULL 
    AND location NOT IN ('', 'Pending')
    GROUP BY location
    ORDER BY count DESC
    """)
    
    print("\n" + "=" * 70)
    print("FINAL LOCATION DISTRIBUTION")
    print("=" * 70)
    
    total = 0
    for location, count in c.fetchall():
        percentage = count  # Will calculate below
        total += count
        print(f"  {location:.<30} {count:>4} jobs")
    
    print("-" * 70)
    print(f"  {'TOTAL':.<30} {total:>4} jobs")
    
    conn.close()

if __name__ == '__main__':
    print("Analyzing location variants...")
    variants = get_location_variants()
    print(f"Found {len(variants)} unique location values\n")
    
    before = analyze_locations()
    
    normalize_locations_in_db()
    report_location_distribution()
