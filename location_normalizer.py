"""
Location Normalization Module
Standardizes Finnish job location strings to primary city names.

Handles:
- Case normalization (HELSINKI → Helsinki)
- Country suffix removal (Helsinki, Finland → Helsinki)
- Multi-city extraction (Helsinki, Tampere → Helsinki)
- Alternative city names (Helsingfors → Helsinki)
- Invalid/non-Finnish locations
"""

import re
from typing import Optional

# Known Finnish cities and regions (comprehensive list)
FINNISH_CITIES = {
    'Helsinki', 'Espoo', 'Tampere', 'Turku', 'Vantaa', 'Oulu', 'Kuopio',
    'Jyväskylä', 'Lahti', 'Pori', 'Kouvola', 'Joensuu', 'Lappeenranta',
    'Hämeenlinna', 'Vaasa', 'Seinäjoki', 'Kajaani', 'Roenne', 'Rovaniemi',
    'Kerava', 'Järvenpää', 'Riihimäki', 'Mikkeli', 'Rauma', 'Kaarina',
    'Raisio', 'Naantali', 'Lohja', 'Hyvinkää', 'Tuusula', 'Kauniainen',
    'Espoonlahti', 'Espoonlahden', 'Lieto', 'Piikkiö', 'Teuva', 'Ulvila',
    'Kankaanpää', 'Paimio', 'Turku (Pansio)', 'Kangasala', 'Kemi', 'Oulu',
    'Keuruu', 'Varkaus', 'Iisalmi', 'Metsämaa', 'Urjala', 'Ähtäri',
}

# Alternative names mapping (alternative → official)
CITY_ALIASES = {
    'Helsingfors': 'Helsinki',
    'Åbo': 'Turku',
    'Uleåborg': 'Oulu',
    'Vapo': 'Vaasa',
    'Björneborg': 'Pori',
}

# Non-Finnish cities to exclude (lowercase)
NON_FINNISH_CITIES = {
    'sofia', 'katowice', 'fuengirola', 'prague', 'warsaw', 'tallinn',
    'riga', 'vilnius', 'budapest', 'krakow', 'oslo', 'stockholm',
}


def normalize_location(location: str) -> str:
    """
    Normalize a location string to a single Finnish city name.
    
    Args:
        location: Raw location string from job posting
        
    Returns:
        Normalized city name or 'Unknown' if unable to extract
        
    Examples:
        normalize_location("HELSINKI") → "Helsinki"
        normalize_location("Helsinki, Finland") → "Helsinki"
        normalize_location("Helsinki, Tampere, Oulu") → "Helsinki"
        normalize_location("Sofia") → "Unknown"
    """
    
    if not location or not isinstance(location, str):
        return 'Unknown'
    
    location = location.strip()
    if not location:
        return 'Unknown'
    
    # Remove common suffixes
    location = re.sub(r',?\s*Finland\s*$', '', location, flags=re.IGNORECASE)
    location = re.sub(r',?\s*ja\s*Kajaani\.?\s*$', '', location, flags=re.IGNORECASE)  # "Tampere ja Kajaani."
    location = location.strip()
    
    # Remove street addresses (anything with numbers and special characters suggesting address)
    # Pattern: "Konepajankatu 1 00510 Helsinki" → extract "Helsinki"
    if re.search(r'\d{5}|\d+\s+\w+\s+(Street|Str|katu|tie)', location, re.IGNORECASE):
        # Try to extract last word that looks like a city
        words = re.findall(r'[A-ZÄÖÅa-zäöå]+', location)
        if words:
            for word in reversed(words):
                if word.lower() in [c.lower() for c in FINNISH_CITIES] or word in CITY_ALIASES:
                    location = word
                    break
    
    # Split on comma and take first city
    cities = [c.strip() for c in location.split(',')]
    primary_city = cities[0]
    
    # Check if it's a known alias
    if primary_city in CITY_ALIASES:
        return CITY_ALIASES[primary_city]
    
    # Title case and check against Finnish cities
    normalized = primary_city.title()
    
    # Exact match in Finnish cities
    for city in FINNISH_CITIES:
        if normalized.lower() == city.lower():
            return city  # Return official capitalization
    
    # Check if it's a non-Finnish city
    if normalized.lower() in NON_FINNISH_CITIES:
        return 'Unknown'
    
    # If we have multiple cities in the string and first didn't match,
    # try to find any Finnish city in the list
    for city_candidate in cities:
        city_normalized = city_candidate.title().strip()
        for city in FINNISH_CITIES:
            if city_normalized.lower() == city.lower():
                return city
    
    # Last resort: if first word looks like it could be a Finnish city name
    # (contains ä, ö, å or is in our whitelist), accept it
    if any(c in primary_city for c in 'äöåÄÖÅ'):
        return primary_city.title()
    
    # Can't determine - mark as unknown
    return 'Unknown'


def normalize_all_locations(db_path: str = 'duunitori_pipeline.db') -> None:
    """
    Normalize all locations in the database in-place.
    
    Args:
        db_path: Path to SQLite database
    """
    import sqlite3
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all unique raw locations
    cursor.execute("SELECT DISTINCT location FROM raw_postings WHERE location IS NOT NULL")
    locations = cursor.fetchall()
    
    print(f"\n{'=' * 80}")
    print(f"LOCATION NORMALIZATION PROCESS")
    print(f"{'=' * 80}\n")
    
    normalization_map = {}
    
    for (location,) in locations:
        normalized = normalize_location(location)
        normalization_map[location] = normalized
    
    # Show normalization results
    unique_normalized = set(normalization_map.values())
    print(f"📊 NORMALIZATION SUMMARY:")
    print(f"  Raw location variants:    {len(locations)}")
    print(f"  Normalized to:            {len(unique_normalized)} unique cities")
    print(f"\n📋 NORMALIZATION MAPPING (showing changes):\n")
    
    changes = 0
    for original, normalized in sorted(normalization_map.items()):
        if original != normalized:
            print(f"  '{original}' → '{normalized}'")
            changes += 1
    
    print(f"\nTotal locations to update: {changes}")
    
    # Apply normalization to database
    print(f"\n🔄 Updating database...")
    for original, normalized in normalization_map.items():
        cursor.execute(
            "UPDATE raw_postings SET location = ? WHERE location = ?",
            (normalized, original)
        )
    
    conn.commit()
    
    # Verify
    cursor.execute("SELECT DISTINCT location FROM raw_postings WHERE location != 'Unknown' ORDER BY location")
    final_locations = cursor.fetchall()
    
    print(f"\n✅ COMPLETE!")
    print(f"  Final unique locations: {len(final_locations)}")
    print(f"\n📍 Final normalized locations:")
    
    cursor.execute("""
        SELECT location, COUNT(*) as count
        FROM raw_postings
        WHERE location != 'Unknown'
        GROUP BY location
        ORDER BY count DESC
    """)
    
    for loc, count in cursor.fetchall():
        print(f"    {loc:<30} : {count:>3} jobs")
    
    # Check for unknown
    cursor.execute("SELECT COUNT(*) FROM raw_postings WHERE location = 'Unknown'")
    unknown_count = cursor.fetchone()[0]
    if unknown_count > 0:
        print(f"\n    {'Unknown':<30} : {unknown_count:>3} jobs")
    
    conn.close()


if __name__ == '__main__':
    # Run normalization on database
    normalize_all_locations()
