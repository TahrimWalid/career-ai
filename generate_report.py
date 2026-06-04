#!/usr/bin/env python3
"""
Generate a professional HTML report with visualizations
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from database import DB_FILE

def get_analytics_data():
    """Fetch all analytics data from database"""
    conn = sqlite3.connect(str(DB_FILE))
    c = conn.cursor()
    
    # Top skills
    c.execute("""
    SELECT json_each.value as skill, COUNT(*) as count
    FROM structured_insights, json_each(structured_insights.skills)
    WHERE json_each.value IS NOT NULL
    GROUP BY json_each.value
    ORDER BY count DESC
    LIMIT 15
    """)
    top_skills = [(row[0], row[1]) for row in c.fetchall()]
    
    # Top frameworks
    c.execute("""
    SELECT json_each.value as framework, COUNT(*) as count
    FROM structured_insights, json_each(structured_insights.frameworks_tools)
    WHERE json_each.value IS NOT NULL
    GROUP BY json_each.value
    ORDER BY count DESC
    LIMIT 15
    """)
    top_frameworks = [(row[0], row[1]) for row in c.fetchall()]
    
    # Seniority distribution
    c.execute("""
    SELECT seniority, COUNT(*) as count
    FROM structured_insights
    GROUP BY seniority
    ORDER BY count DESC
    """)
    seniority = dict(c.fetchall())
    
    # Geographic distribution — location is set during hydration, not extraction
    c.execute("""
    SELECT location, COUNT(*) as count
    FROM raw_postings
    WHERE raw_html IS NOT NULL AND raw_html != ''
    AND location IS NOT NULL
    AND location NOT IN ('', 'Pending', 'Unknown')
    GROUP BY location
    ORDER BY count DESC
    LIMIT 10
    """)
    top_locations = [(row[0], row[1]) for row in c.fetchall()]
    
    # Key metrics
    c.execute("""
    SELECT 
        COUNT(*) as total_jobs,
        COUNT(CASE WHEN extraction_status = 'done' THEN 1 END) as extracted,
        COUNT(CASE WHEN extraction_status = 'failed' THEN 1 END) as failed
    FROM raw_postings
    """)
    total_jobs, extracted, failed = c.fetchone()
    
    # English vs Finnish
    c.execute("""
    SELECT
        SUM(CASE WHEN is_english = 1 THEN 1 ELSE 0 END) as english,
        SUM(CASE WHEN is_english = 0 THEN 1 ELSE 0 END) as finnish
    FROM structured_insights
    """)
    english_count, finnish_count = c.fetchone()

    # Experience distribution
    c.execute("""
    SELECT years_experience_required, COUNT(*) as count
    FROM structured_insights
    WHERE years_experience_required IS NOT NULL
    GROUP BY years_experience_required
    ORDER BY CASE years_experience_required
        WHEN '0-2' THEN 1 WHEN '2-5' THEN 2
        WHEN '5-10' THEN 3 WHEN '10+' THEN 4 ELSE 5
    END
    """)
    experience = dict(c.fetchall())

    # Remote work distribution
    c.execute("""
    SELECT remote_work_available, COUNT(*) as count
    FROM structured_insights
    WHERE remote_work_available IS NOT NULL
    GROUP BY remote_work_available
    ORDER BY count DESC
    """)
    remote_work = dict(c.fetchall())

    conn.close()

    return {
        'top_skills': top_skills,
        'top_frameworks': top_frameworks,
        'seniority': seniority,
        'top_locations': top_locations,
        'total_jobs': total_jobs,
        'extracted': extracted,
        'failed': failed,
        'english': english_count or 0,
        'finnish': finnish_count or 0,
        'experience': experience,
        'remote_work': remote_work,
    }

def generate_html_report(data):
    """Generate HTML report with embedded data visualization"""
    
    # Prepare data for JavaScript
    skills_labels = [s[0] for s in data['top_skills']]
    skills_values = [s[1] for s in data['top_skills']]
    
    frameworks_labels = [f[0] for f in data['top_frameworks']]
    frameworks_values = [f[1] for f in data['top_frameworks']]
    
    locations_labels = [l[0] for l in data['top_locations']]
    locations_values = [l[1] for l in data['top_locations']]
    
    seniority_labels = list(data['seniority'].keys())
    seniority_values = list(data['seniority'].values())

    experience_labels = list(data['experience'].keys())
    experience_values = list(data['experience'].values())

    remote_labels = list(data['remote_work'].keys())
    remote_values = list(data['remote_work'].values())

    english_pct = 100 * data['english'] / (data['english'] + data['finnish']) if (data['english'] + data['finnish']) > 0 else 0
    extraction_rate = 100 * data['extracted'] / data['total_jobs'] if data['total_jobs'] > 0 else 0
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Duunitori Job Market Analysis</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 40px 20px;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        
        .header {{
            background: white;
            padding: 40px;
            border-radius: 12px;
            margin-bottom: 30px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
        }}
        
        .header h1 {{
            color: #333;
            font-size: 2.5em;
            margin-bottom: 10px;
        }}
        
        .header p {{
            color: #666;
            font-size: 1.1em;
            margin-bottom: 20px;
        }}
        
        .metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-top: 30px;
        }}
        
        .metric {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }}
        
        .metric-value {{
            font-size: 2.5em;
            font-weight: bold;
            margin: 10px 0;
        }}
        
        .metric-label {{
            font-size: 0.9em;
            opacity: 0.9;
        }}
        
        .charts {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 30px;
            margin-bottom: 30px;
        }}
        
        .chart-container {{
            background: white;
            padding: 30px;
            border-radius: 12px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
        }}
        
        .chart-container h2 {{
            color: #333;
            margin-bottom: 20px;
            font-size: 1.5em;
        }}
        
        .chart-wrapper {{
            position: relative;
            height: 400px;
        }}
        
        .full-width {{
            grid-column: 1 / -1;
        }}
        
        .footer {{
            text-align: center;
            color: white;
            margin-top: 40px;
            padding: 20px;
        }}
        
        .footer-text {{
            font-size: 0.9em;
            opacity: 0.9;
        }}
        
        .data-source {{
            margin-top: 10px;
            font-size: 0.85em;
            opacity: 0.8;
        }}
        
        @media (max-width: 768px) {{
            .charts {{
                grid-template-columns: 1fr;
            }}
            
            .header h1 {{
                font-size: 1.8em;
            }}
            
            .metric-value {{
                font-size: 1.8em;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Duunitori Job Market Analysis</h1>
            <p>Finnish IT Job Market Insights from Duunitori.fi</p>
            
            <div class="metrics">
                <div class="metric">
                    <div class="metric-label">Total Jobs Analyzed</div>
                    <div class="metric-value">{data['total_jobs']:,}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Successfully Extracted</div>
                    <div class="metric-value">{data['extracted']:,}</div>
                    <div class="metric-label">({extraction_rate:.1f}%)</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Job Postings in English</div>
                    <div class="metric-value">{english_pct:.1f}%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Unique Locations</div>
                    <div class="metric-value">50+</div>
                </div>
            </div>
        </div>
        
        <div class="charts">
            <div class="chart-container">
                <h2>📊 Top 15 In-Demand Skills</h2>
                <div class="chart-wrapper">
                    <canvas id="skillsChart"></canvas>
                </div>
            </div>
            
            <div class="chart-container">
                <h2>🔧 Top 15 Frameworks & Tools</h2>
                <div class="chart-wrapper">
                    <canvas id="frameworksChart"></canvas>
                </div>
            </div>
            
            <div class="chart-container">
                <h2>💼 Seniority Level Distribution</h2>
                <div class="chart-wrapper">
                    <canvas id="seniorityChart"></canvas>
                </div>
            </div>
            
            <div class="chart-container">
                <h2>📍 Top 10 Job Locations</h2>
                <div class="chart-wrapper">
                    <canvas id="locationsChart"></canvas>
                </div>
            </div>

            <div class="chart-container">
                <h2>📅 Experience Required</h2>
                <div class="chart-wrapper">
                    <canvas id="experienceChart"></canvas>
                </div>
            </div>

            <div class="chart-container">
                <h2>🏠 Remote Work Availability</h2>
                <div class="chart-wrapper">
                    <canvas id="remoteChart"></canvas>
                </div>
            </div>
        </div>
        
        <div class="footer">
            <div class="footer-text">
                <strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </div>
            <div class="data-source">
                Data sourced from Duunitori.fi | Analysis Pipeline | MIT License
            </div>
        </div>
    </div>
    
    <script>
        const chartColors = {{
            primary: '#667eea',
            secondary: '#764ba2',
            accent: '#f093fb',
            success: '#4ade80',
            warning: '#fbbf24',
            danger: '#ef4444'
        }};
        
        // Skills Chart
        new Chart(document.getElementById('skillsChart'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(skills_labels)},
                datasets: [{{
                    label: 'Number of Jobs',
                    data: {json.dumps(skills_values)},
                    backgroundColor: chartColors.primary,
                    borderColor: chartColors.secondary,
                    borderWidth: 1
                }}]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{display: false}}
                }},
                scales: {{
                    x: {{
                        beginAtZero: true,
                        ticks: {{color: '#666'}}
                    }},
                    y: {{
                        ticks: {{color: '#666'}}
                    }}
                }}
            }}
        }});
        
        // Frameworks Chart
        new Chart(document.getElementById('frameworksChart'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(frameworks_labels)},
                datasets: [{{
                    label: 'Number of Jobs',
                    data: {json.dumps(frameworks_values)},
                    backgroundColor: chartColors.secondary,
                    borderColor: chartColors.primary,
                    borderWidth: 1
                }}]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{display: false}}
                }},
                scales: {{
                    x: {{
                        beginAtZero: true,
                        ticks: {{color: '#666'}}
                    }},
                    y: {{
                        ticks: {{color: '#666'}}
                    }}
                }}
            }}
        }});
        
        // Seniority Chart
        new Chart(document.getElementById('seniorityChart'), {{
            type: 'doughnut',
            data: {{
                labels: {json.dumps(seniority_labels)},
                datasets: [{{
                    data: {json.dumps(seniority_values)},
                    backgroundColor: [
                        chartColors.primary,
                        chartColors.secondary,
                        chartColors.accent,
                        chartColors.success,
                        chartColors.warning
                    ],
                    borderColor: 'white',
                    borderWidth: 2
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{
                        position: 'bottom',
                        labels: {{color: '#666'}}
                    }}
                }}
            }}
        }});
        
        // Locations Chart
        new Chart(document.getElementById('locationsChart'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(locations_labels)},
                datasets: [{{
                    label: 'Number of Jobs',
                    data: {json.dumps(locations_values)},
                    backgroundColor: chartColors.accent,
                    borderColor: chartColors.secondary,
                    borderWidth: 1
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'x',
                plugins: {{
                    legend: {{display: false}}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true,
                        ticks: {{color: '#666'}}
                    }},
                    x: {{
                        ticks: {{color: '#666'}}
                    }}
                }}
            }}
        }});
        // Experience Chart
        new Chart(document.getElementById('experienceChart'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(experience_labels)},
                datasets: [{{
                    label: 'Number of Jobs',
                    data: {json.dumps(experience_values)},
                    backgroundColor: chartColors.success,
                    borderColor: chartColors.primary,
                    borderWidth: 1
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{display: false}} }},
                scales: {{
                    y: {{ beginAtZero: true, ticks: {{color: '#666'}} }},
                    x: {{ ticks: {{color: '#666'}} }}
                }}
            }}
        }});

        // Remote Work Chart
        new Chart(document.getElementById('remoteChart'), {{
            type: 'doughnut',
            data: {{
                labels: {json.dumps(remote_labels)},
                datasets: [{{
                    data: {json.dumps(remote_values)},
                    backgroundColor: [
                        chartColors.success,
                        chartColors.warning,
                        chartColors.danger,
                        chartColors.primary
                    ],
                    borderColor: 'white',
                    borderWidth: 2
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ position: 'bottom', labels: {{color: '#666'}} }}
                }}
            }}
        }});
    </script>
</body>
</html>"""
    
    return html

def main():
    print("=" * 70)
    print("GENERATING HTML REPORT")
    print("=" * 70)
    
    print("Fetching analytics data...")
    data = get_analytics_data()
    
    print("Generating HTML...")
    html = generate_html_report(data)
    
    # Write report
    report_path = Path('report.html')
    report_path.write_text(html)
    
    print(f"\n✓ Report generated: {report_path}")
    print(f"  Open in browser: file://{report_path.absolute()}")
    
    print("\n" + "=" * 70)
    print("REPORT SUMMARY")
    print("=" * 70)
    print(f"Total jobs analyzed: {data['total_jobs']:,}")
    print(f"Successfully extracted: {data['extracted']:,}")
    if data['total_jobs']:
        print(f"Extraction rate: {100*data['extracted']/data['total_jobs']:.1f}%")
    total_lang = data['english'] + data['finnish']
    if total_lang:
        print(f"English postings: {data['english']:,} ({100*data['english']/total_lang:.1f}%)")
    if data['top_skills']:
        print(f"\nTop skill: {data['top_skills'][0][0]} ({data['top_skills'][0][1]} jobs)")
    if data['top_frameworks']:
        print(f"Top framework: {data['top_frameworks'][0][0]} ({data['top_frameworks'][0][1]} jobs)")
    if data['top_locations']:
        print(f"Top location: {data['top_locations'][0][0]} ({data['top_locations'][0][1]} jobs)")

if __name__ == '__main__':
    main()
