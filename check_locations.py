#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('duunitori_pipeline.db')
cursor = conn.cursor()

print("=" * 80)
print("LOCATION DATA QUALITY")
print("=" * 80)

cursor.execute("""
SELECT 
    COUNT(*) as total,
    SUM(CASE WHEN location IS NULL THEN 1 ELSE 0 END) as null_count,
    SUM(CASE WHEN location = '' THEN 1 ELSE 0 END) as empty_count,
    SUM(CASE WHEN location = 'Pending' THEN 1 ELSE 0 END) as pending_count
FROM raw_postings
WHERE extraction_status = 'done'
""")

total, null_cnt, empty_cnt, pending_cnt = cursor.fetchone()
valid = total - (null_cnt or 0) - (empty_cnt or 0) - (pending_cnt or 0)

print(f"\nExtracted records: {total}")
print(f"  ✓ Valid locations: {valid} ({100*valid/total:.1f}%)")
print(f"  ✗ NULL/Empty/Pending: {total-valid} ({100*(total-valid)/total:.1f}%)")

print("\n" + "=" * 80)
print("TOP 15 LOCATIONS")
print("=" * 80)

cursor.execute("""
SELECT location, COUNT(*) as count
FROM raw_postings
WHERE extraction_status = 'done' AND location NOT IN ('', 'Pending') AND location IS NOT NULL
GROUP BY location
ORDER BY count DESC
LIMIT 15
""")

for i, (location, count) in enumerate(cursor.fetchall(), 1):
    pct = 100 * count / valid
    print(f"{i:2d}. {location:25s} {count:4d} jobs ({pct:5.1f}%)")

conn.close()
