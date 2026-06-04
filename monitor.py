#!/usr/bin/env python3
import sqlite3
import time
import sys

def monitor_pipeline():
    db_file = 'duunitori_pipeline.db'
    
    while True:
        try:
            conn = sqlite3.connect(db_file)
            c = conn.cursor()
            
            # Get counts by status
            c.execute("SELECT extraction_status, COUNT(*) FROM raw_postings GROUP BY extraction_status")
            statuses = dict(c.fetchall())
            
            c.execute("SELECT COUNT(*) FROM structured_insights")
            structured = c.fetchone()[0]
            
            pending = statuses.get('pending', 0)
            done = statuses.get('done', 0)
            failed = statuses.get('failed', 0)
            total = pending + done + failed
            
            # Get latest log entries
            c.execute("""
                SELECT extraction_status, COUNT(*) 
                FROM raw_postings 
                GROUP BY extraction_status 
                ORDER BY COUNT(*) DESC
            """)
            
            conn.close()
            
            print(f"\n{'='*70}")
            print(f"Pipeline Status: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*70}")
            print(f"Raw Postings:")
            print(f"  Total:        {total:5d}")
            print(f"  Pending:      {pending:5d} (waiting for extraction)")
            print(f"  Done:         {done:5d} (extracted)")
            print(f"  Failed:       {failed:5d}")
            print(f"\nStructured Insights: {structured:5d} (actually extracted with LLM)")
            print(f"Coverage:           {100*structured/max(done,1):.1f}% of done records")
            
            # Check if still running
            try:
                with open('pipeline.log', 'r') as f:
                    lines = f.readlines()
                    if lines:
                        latest = lines[-1]
                        if 'Analytics' in latest or 'completed' in latest:
                            print(f"\n✓ Pipeline appears to be completing...")
                            break
            except:
                pass
            
            time.sleep(10)
        
        except FileNotFoundError:
            print("Database not created yet, waiting...")
            time.sleep(5)
        except KeyboardInterrupt:
            print("\nMonitoring stopped.")
            break
        except Exception as e:
            print(f"Monitor error: {e}")
            time.sleep(5)

if __name__ == '__main__':
    monitor_pipeline()
